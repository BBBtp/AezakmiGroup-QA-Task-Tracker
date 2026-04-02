from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

from aiohttp import web
from sqlalchemy import desc, select
from sqlalchemy.orm import joinedload, sessionmaker

import re
from urllib.parse import urlparse

from bot.db.models import Chat, Task, TaskEventType
from bot.live_updates import LiveUpdateBroadcaster
from bot.services.task_service import TaskService

REPO_ROOT = Path(__file__).resolve().parent.parent
MINIAPP_DIST = REPO_ROOT / "miniapp" / "dist"


def create_web_app(session_factory: sessionmaker, broadcaster: LiveUpdateBroadcaster) -> web.Application:
    app = web.Application()
    app["session_factory"] = session_factory
    app["broadcaster"] = broadcaster
    app.router.add_get("/", root_handler)
    app.router.add_get("/miniapp", miniapp_handler)
    app.router.add_get("/miniapp/{tail:.*}", miniapp_handler)
    app.router.add_get("/api/tasks", tasks_handler)
    app.router.add_get("/api/chats", chats_handler)
    app.router.add_get("/api/stream", events_handler)
    app.router.add_get("/api/tasks/{task_id:\\d+}", task_detail_handler)
    app.router.add_post("/api/tasks/{task_id:\\d+}/archive", archive_task_handler)
    app.router.add_post("/api/tasks/{task_id:\\d+}/restore", restore_task_handler)
    app.router.add_delete("/api/tasks/{task_id:\\d+}", delete_task_handler)
    return app


async def root_handler(request: web.Request) -> web.Response:
    raise web.HTTPFound("/miniapp")


async def miniapp_handler(request: web.Request) -> web.StreamResponse:
    if not MINIAPP_DIST.exists():
        return web.Response(
            text=(
                "Mini app is not built yet. Run `npm install && npm run build` in the `miniapp/` directory "
                "to generate static assets."
            ),
            content_type="text/plain",
            status=503,
        )

    tail = request.match_info.get("tail", "")
    target = (MINIAPP_DIST / tail).resolve() if tail else MINIAPP_DIST / "index.html"
    if tail and target.exists() and target.is_file() and str(target).startswith(str(MINIAPP_DIST)):
        return web.FileResponse(target)
    return web.FileResponse(MINIAPP_DIST / "index.html")


async def tasks_handler(request: web.Request) -> web.Response:
    session_factory: sessionmaker = request.app["session_factory"]
    archived = request.query.get("archived") == "1"
    with session_factory() as session:
        tasks = list(
            session.execute(
                select(Task)
                .options(joinedload(Task.assignee), joinedload(Task.events))
                .where(Task.is_archived.is_(archived))
                .order_by(desc(Task.created_at))
            )
            .unique()
            .scalars()
        )
        chat_ids = {task.source_chat_id for task in tasks}
        chats = (
            list(session.scalars(select(Chat).where(Chat.telegram_chat_id.in_(chat_ids))))
            if chat_ids
            else []
        )
        chat_map = {chat.telegram_chat_id: chat for chat in chats}

    payload = {"tasks": [serialize_task_summary(task, chat_map) for task in tasks]}
    return web.json_response(payload)


async def chats_handler(request: web.Request) -> web.Response:
    session_factory: sessionmaker = request.app["session_factory"]
    archived = request.query.get("archived") == "1"
    with session_factory() as session:
        chats = list(session.scalars(select(Chat).order_by(Chat.title, Chat.telegram_chat_id)))
        chat_ids = {chat.telegram_chat_id for chat in chats}
        task_chat_ids = set(session.scalars(select(Task.source_chat_id).where(Task.is_archived.is_(archived)).distinct()))
        missing_ids = sorted(task_chat_ids - chat_ids)
    payload = {
        "chats": [
            {
                "id": chat.telegram_chat_id,
                "title": chat.title,
                "username": chat.username,
            }
            for chat in chats
        ]
        + [{"id": chat_id, "title": None, "username": None} for chat_id in missing_ids]
    }
    return web.json_response(payload)


async def events_handler(request: web.Request) -> web.StreamResponse:
    broadcaster: LiveUpdateBroadcaster = request.app["broadcaster"]
    response = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
    await response.prepare(request)

    async with broadcaster.subscribe() as queue:
        await response.write(b": connected\n\n")
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=25)
                    message = f"data: {json.dumps(payload)}\n\n".encode("utf-8")
                except TimeoutError:
                    message = b": ping\n\n"
                await response.write(message)
                await response.drain()
        except (asyncio.CancelledError, ConnectionResetError):
            pass

    return response


async def task_detail_handler(request: web.Request) -> web.Response:
    session_factory: sessionmaker = request.app["session_factory"]
    task_id = int(request.match_info["task_id"])
    with session_factory() as session:
        task = (
            session.execute(
            select(Task)
            .options(joinedload(Task.assignee), joinedload(Task.events))
            .where(Task.id == task_id)
            )
            .unique()
            .scalar_one_or_none()
        )
        chat = session.scalar(select(Chat).where(Chat.telegram_chat_id == task.source_chat_id)) if task else None

    if task is None:
        raise web.HTTPNotFound(text="Task not found")

    payload = serialize_task_detail(task, chat)
    return web.json_response(payload)


async def archive_task_handler(request: web.Request) -> web.Response:
    return await mutate_task_archive_state(request, action="archive")


async def restore_task_handler(request: web.Request) -> web.Response:
    return await mutate_task_archive_state(request, action="restore")


async def delete_task_handler(request: web.Request) -> web.Response:
    session_factory: sessionmaker = request.app["session_factory"]
    broadcaster: LiveUpdateBroadcaster = request.app["broadcaster"]
    task_id = int(request.match_info["task_id"])
    service = TaskService()

    with session_factory() as session:
        result = service.delete_task_permanently(session, task_id)
        session.commit()

    await broadcaster.publish({"type": "task_deleted", "task_id": task_id})
    return web.json_response({"ok": result.action == "deleted", "message": result.message})


async def mutate_task_archive_state(request: web.Request, *, action: str) -> web.Response:
    session_factory: sessionmaker = request.app["session_factory"]
    broadcaster: LiveUpdateBroadcaster = request.app["broadcaster"]
    task_id = int(request.match_info["task_id"])
    service = TaskService()

    with session_factory() as session:
        if action == "archive":
            result = service.archive_task(session, task_id)
        else:
            result = service.restore_task(session, task_id)
        session.commit()

    await broadcaster.publish({"type": "task_changed", "task_id": task_id})
    return web.json_response({"ok": result.action in {"archived", "restored"}, "message": result.message})


def serialize_task_summary(task: Task, chat_map: dict[int, Chat] | None = None) -> dict[str, object | None]:
    latest_event = task.events[-1] if task.events else None
    chat = chat_map.get(task.source_chat_id) if chat_map else None
    report_url = find_report_url(task)
    return {
        "id": task.id,
        "task_key": task.task_key,
        "app_name": task.app_name,
        "title": task.title,
        "status": task.status.value,
        "assignee": TaskService.format_assignee(task.assignee) if task.assignee else None,
        "chat_id": task.source_chat_id,
        "chat_title": chat.title if chat else None,
        "chat_username": chat.username if chat else None,
        "report_url": report_url,
        "figma_url": task.figma_url,
        "github_url": task.github_url,
        "archive_url": task.archive_url,
        "branch_name": task.branch_name,
        "relevant_file_path": task.relevant_file_path,
        "relevant_line_number": task.relevant_line_number,
        "is_archived": task.is_archived,
        "archived_at": serialize_dt(task.archived_at),
        "created_at": serialize_dt(task.created_at),
        "completed_at": serialize_dt(task.completed_at),
        "last_activity_at": serialize_dt(latest_event.created_at if latest_event else task.created_at),
        "last_event_text": latest_event.message_text if latest_event else task.raw_text,
        "last_event_type": latest_event.event_type.value if latest_event else "created",
        "has_review": any(event.event_type.value == "review" for event in task.events),
    }


def serialize_task_detail(task: Task, chat: Chat | None) -> dict[str, object | None]:
    chat_map = {chat.telegram_chat_id: chat} if chat else None
    payload = serialize_task_summary(task, chat_map)
    payload["raw_text"] = task.raw_text
    payload["events"] = [
        {
            "id": event.id,
            "event_type": event.event_type.value,
            "message_text": event.message_text,
            "created_at": serialize_dt(event.created_at),
        }
        for event in task.events
    ]
    return payload


def serialize_dt(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value else None


URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)


def is_google_report_url(url: str) -> bool:
    hostname = urlparse(url).hostname or ""
    hostname = hostname.lower()
    return hostname in {"docs.google.com", "drive.google.com"}


def extract_first_url(text: str | None) -> str | None:
    if not text:
        return None
    match = URL_RE.search(text)
    return match.group(0) if match else None


def extract_first_google_report_url(text: str | None) -> str | None:
    if not text:
        return None
    for match in URL_RE.finditer(text):
        url = match.group(0)
        if is_google_report_url(url):
            return url
    return None


def find_report_url(task: Task) -> str | None:
    if not task.events:
        return None

    # Prefer explicit report events, newest first.
    for event in reversed(task.events):
        if event.event_type == TaskEventType.REPORT:
            url = extract_first_google_report_url(event.message_text)
            if url:
                return url

    # Fallback: messages that look like a report mention.
    for event in reversed(task.events):
        lowered = event.message_text.lower()
        if "отчет" in lowered or "отчёт" in lowered:
            url = extract_first_google_report_url(event.message_text)
            if url:
                return url

    return None
