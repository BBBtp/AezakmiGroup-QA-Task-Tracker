from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from aiohttp import web

from bot.codex_channel import claim_job, create_job, upload_telemetry
from bot.db.session import init_db
from bot.office_data import list_runs, run_events


class Request:
    def __init__(self, app, *, user=123, worker=False, payload=None, job_id=None, issue_key="FRONT-187"):
        self.app = app
        self.user = {"id": user}
        self.headers = {"Authorization": "Bearer test-worker-secret"} if worker else {}
        self.payload = payload
        self.content_length = 1000
        self.match_info = {"job_id": job_id, "issue_key": issue_key, "run_id": job_id}
        self.query = {"source": "relay", "after": "0"}

    def get(self, key):
        return self.user if key == "miniapp_user" else None

    async def json(self):
        return self.payload


class CodexRelayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = {
            "session_factory": init_db(f"sqlite:///{Path(self.temp.name) / 'jobs.db'}"),
            "settings": SimpleNamespace(codex_allowed_user_ids=(123,), codex_worker_token="test-worker-secret"),
            "office_reader": None,
        }

    def tearDown(self):
        self.temp.cleanup()

    async def test_mac_relay_is_idempotent_and_is_visible_to_office(self):
        run_id = str(uuid.uuid4())
        await create_job(Request(self.app, payload={"id": run_id, "issue_key": "FRONT-187"}))
        claimed = json.loads((await claim_job(Request(self.app, worker=True))).text)["job"]
        now = datetime.now(timezone.utc).isoformat()
        manifest = {"schemaVersion": 1, "runId": run_id, "issueKey": "FRONT-187",
                    "startedAt": now, "eventCount": 1, "status": "completed", "telemetry": "published"}
        event = {"schemaVersion": 1, "eventId": "agev_" + "a" * 32, "runId": run_id,
                 "issueKey": "FRONT-187", "seq": 1, "source": "wrapper", "kind": "run.finished",
                 "observedAt": now, "occurredAt": now,
                 "detail": {"reason": "completed", "private_text": "never-forward"}}
        payload = {"claim_token": claimed["claim_token"], "manifest": manifest, "events": [event]}
        request = Request(self.app, worker=True, payload=payload, job_id=run_id)
        self.assertEqual((await upload_telemetry(request)).status, 200)
        self.assertEqual((await upload_telemetry(request)).status, 200)

        runs = json.loads((await list_runs(Request(self.app))).text)
        self.assertEqual(runs["source"], "relay")
        self.assertEqual(runs["runs"][0]["runId"], run_id)
        page = json.loads((await run_events(Request(self.app, job_id=run_id))).text)
        self.assertEqual(page["nextSeq"], 1)
        self.assertNotIn("never-forward", json.dumps(page))

        changed = dict(event, detail={"reason": "changed"})
        with self.assertRaises(web.HTTPConflict):
            await upload_telemetry(Request(self.app, worker=True,
                payload={"claim_token": claimed["claim_token"], "manifest": manifest, "events": [changed]}, job_id=run_id))
