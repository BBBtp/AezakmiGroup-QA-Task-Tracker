from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

from aiohttp import web

from bot.codex_channel import claim_job, complete_job, create_job, heartbeat_job, list_jobs
from bot.db.session import init_db


class Request:
    def __init__(self, app, *, payload=None, user_id=None, worker_token=None, job_id=None):
        self.app = app
        self.payload = payload
        self.headers = {"Authorization": f"Bearer {worker_token}"} if worker_token else {}
        self.match_info = {"job_id": job_id} if job_id else {}
        self.user = {"id": user_id} if user_id else None

    def get(self, key):
        return self.user if key == "miniapp_user" else None

    async def json(self):
        return self.payload


class CodexChannelTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        db = Path(self.temp.name) / "jobs.db"
        self.app = {
            "session_factory": init_db(f"sqlite:///{db}"),
            "settings": SimpleNamespace(codex_allowed_user_ids=(123,), codex_worker_token="test-worker-secret"),
        }

    def tearDown(self):
        self.temp.cleanup()

    async def test_idempotent_job_and_one_claim(self):
        job_id = str(uuid.uuid4())
        browser = Request(self.app, user_id=123, payload={"id": job_id, "issue_key": "FRONT-187"})
        first = await create_job(browser)
        second = await create_job(browser)
        self.assertEqual(first.status, 201)
        self.assertEqual(second.status, 200)
        self.assertEqual(json.loads(first.text)["job"]["id"], job_id)

        worker = Request(self.app, worker_token="test-worker-secret")
        claim = json.loads((await claim_job(worker)).text)["job"]
        self.assertEqual(claim["id"], job_id)
        self.assertIsNone(json.loads((await claim_job(worker)).text)["job"])

        await heartbeat_job(Request(self.app, worker_token="test-worker-secret", job_id=job_id,
                                    payload={"claim_token": claim["claim_token"]}))
        result = await complete_job(Request(self.app, worker_token="test-worker-secret", job_id=job_id,
                                            payload={"claim_token": claim["claim_token"], "status": "completed",
                                                     "telemetry": "published"}))
        self.assertEqual(json.loads(result.text)["job"]["status"], "completed")
        listing = json.loads((await list_jobs(Request(self.app, user_id=123))).text)
        self.assertEqual(listing["jobs"][0]["id"], job_id)
        self.assertNotIn("claim_token", result.text)

    async def test_access_and_claim_token_are_required(self):
        with self.assertRaises(web.HTTPForbidden):
            await list_jobs(Request(self.app, user_id=999))
        with self.assertRaises(web.HTTPUnauthorized):
            await claim_job(Request(self.app, worker_token="wrong"))
        with self.assertRaises(web.HTTPBadRequest):
            await create_job(Request(self.app, user_id=123, payload={"id": str(uuid.uuid4()), "issue_key": "bad"}))

        job_id = str(uuid.uuid4())
        await create_job(Request(self.app, user_id=123, payload={"id": job_id, "issue_key": "FRONT-187"}))
        await claim_job(Request(self.app, worker_token="test-worker-secret"))
        with self.assertRaises(web.HTTPConflict):
            await complete_job(Request(self.app, worker_token="test-worker-secret", job_id=job_id,
                                            payload={"claim_token": "wrong", "status": "completed",
                                                     "telemetry": "published"}))
