from __future__ import annotations

import gzip
import hashlib
import io
import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from aiohttp import web

from bot.office_data import Reader, _event, _manifest, list_runs, run_events


class FakeS3:
    def __init__(self, objects):
        self.objects = objects

    def list_objects_v2(self, **args):
        keys = [key for key in self.objects if key.startswith(args["Prefix"])]
        if args.get("Delimiter"):
            prefixes = {args["Prefix"] + key[len(args["Prefix"]):].split("/", 1)[0] + "/"
                        for key in keys if "/" in key[len(args["Prefix"]):]}
            return {"CommonPrefixes": [{"Prefix": prefix} for prefix in sorted(prefixes)]}
        return {"Contents": [{"Key": key} for key in keys]}

    def get_object(self, **args):
        body = self.objects[args["Key"]]
        return {"ContentLength": len(body), "Body": io.BytesIO(body)}


class Request:
    def __init__(self, reader, *, issue="FRONT-187", run="b97b9f9c-30b0-4680-bcf3-e19102fde93b", user=123):
        self.app = {"office_reader": reader,
                    "settings": SimpleNamespace(codex_allowed_user_ids=(123,))}
        self.user = {"id": user}
        self.query = {"source": "minio", "after": "0"}
        self.match_info = {"issue_key": issue, "run_id": run}

    def get(self, key):
        return self.user if key == "miniapp_user" else None


class OfficeDataTests(unittest.IsolatedAsyncioTestCase):
    async def test_published_manifest_and_verified_event_page(self):
        run_id = "b97b9f9c-30b0-4680-bcf3-e19102fde93b"
        prefix = f"factory/agent-runs/v1/front-187/{run_id}/"
        now = datetime.now(timezone.utc).isoformat()
        event = {"schemaVersion": 1, "eventId": "agev_" + "a" * 32,
                 "runId": run_id, "issueKey": "FRONT-187", "seq": 1,
                 "source": "wrapper", "kind": "run.started", "observedAt": now,
                 "occurredAt": now, "detail": {"sandbox": "read-only", "secret": "must-not-leak"}}
        segment = gzip.compress((json.dumps(event) + "\n").encode())
        manifest = {"schemaVersion": 1, "runId": run_id, "issueKey": "FRONT-187",
                    "startedAt": now, "status": "completed", "eventCount": 1,
                    "segments": [{"key": "segments/000001.ndjson.gz", "firstSeq": 1, "lastSeq": 1,
                                  "digest": "sha256:" + hashlib.sha256(segment).hexdigest()}]}
        reader = Reader(FakeS3({prefix + "manifest.json": json.dumps(manifest).encode(),
                                prefix + "segments/000001.ndjson.gz": segment}), "test")
        runs = json.loads((await list_runs(Request(reader))).text)["runs"]
        self.assertEqual(runs[0]["runId"], run_id)
        page = json.loads((await run_events(Request(reader))).text)
        self.assertEqual(page["nextSeq"], 1)
        self.assertFalse(page["hasMore"])
        self.assertNotIn("must-not-leak", json.dumps(page))

        broken = Reader(FakeS3({prefix + "manifest.json": json.dumps(manifest).encode(),
                                prefix + "segments/000001.ndjson.gz": b"broken"}), "test")
        with self.assertRaises(web.HTTPServiceUnavailable):
            await run_events(Request(broken))

    async def test_office_data_requires_telegram_allowlist(self):
        with self.assertRaises(web.HTTPForbidden):
            await list_runs(Request(Reader(FakeS3({}), "test"), user=999))

    def test_rejects_untrusted_manifest_fields(self):
        now = datetime.now(timezone.utc).isoformat()
        manifest = {"schemaVersion": 1, "runId": "b97b9f9c-30b0-4680-bcf3-e19102fde93b",
                    "issueKey": "FRONT-187", "startedAt": now, "status": "completed",
                    "eventCount": 0, "branch": "codex/secret-token"}
        self.assertIsNone(_manifest(manifest)["branch"])
