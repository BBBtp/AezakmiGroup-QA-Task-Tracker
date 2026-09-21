from __future__ import annotations

import asyncio
import re
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout


class DoqaApiError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class DoqaClient:
    def __init__(
        self,
        base_url: str,
        api_token: str,
        *,
        space_id: int | None = None,
        space_ids: tuple[int, ...] | None = None,
        timeout_seconds: int = 60,
        attempts: int = 3,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_token = api_token
        configured_space_ids = space_ids or ((space_id,) if space_id is not None else ())
        self.space_ids = tuple(dict.fromkeys(configured_space_ids))
        if not self.space_ids:
            raise ValueError("At least one DoQA space ID must be configured")
        if any(configured_space_id <= 0 for configured_space_id in self.space_ids):
            raise ValueError("DoQA space IDs must be positive integers")
        self.space_id = self.space_ids[0]
        self.timeout_seconds = timeout_seconds
        self.attempts = max(1, attempts)

    async def get_full_report(self, run_id: int) -> dict[str, Any]:
        payload = await self._request_json(
            "GET",
            f"/api/runs/{run_id}/full-report",
            run_id=run_id,
        )
        report = payload.get("data", payload)
        if not isinstance(report, dict) or not report:
            raise DoqaApiError("DoQA вернул пустой полный отчёт")
        return report

    async def find_run_by_title_id(self, external_id: int) -> dict[str, Any]:
        responses = await asyncio.gather(
            *(self._find_runs_in_space(space_id, external_id) for space_id in self.space_ids),
            return_exceptions=True,
        )
        candidates: list[dict[str, Any]] = []
        errors: list[tuple[int, BaseException]] = []
        for space_id, response in zip(self.space_ids, responses, strict=True):
            if isinstance(response, BaseException):
                errors.append((space_id, response))
                continue
            for run in _find_matching_runs(response, external_id):
                candidate = dict(run)
                candidate["_space_id"] = space_id
                candidates.append(candidate)

        if not candidates:
            if errors:
                failed_spaces = ", ".join(str(space_id) for space_id, _ in errors)
                first_error = errors[0][1]
                if isinstance(first_error, DoqaApiError) and first_error.status in {401, 403}:
                    raise first_error
                raise DoqaApiError(
                    f"Не удалось проверить пространства DoQA: {failed_spaces}"
                ) from first_error
            spaces = ", ".join(str(space_id) for space_id in self.space_ids)
            raise DoqaApiError(
                f"Не найден прогон с ID {external_id} в пространствах {spaces}",
                status=404,
            )
        return max(
            candidates,
            key=lambda run: (str(run.get("createdAt") or ""), int(run.get("id") or 0)),
        )

    async def _find_runs_in_space(self, space_id: int, external_id: int) -> dict[str, Any]:
        return await self._request_json(
            "POST",
            "/api/runs/list",
            json={"spaceId": space_id, "search": str(external_id)},
        )

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        run_id: int | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self._api_token}",
            "Accept": "application/json",
        }
        last_error: Exception | None = None

        for attempt in range(1, self.attempts + 1):
            try:
                timeout = ClientTimeout(total=self.timeout_seconds)
                async with ClientSession(timeout=timeout, headers=headers) as session:
                    async with session.request(method, url, json=json) as response:
                        payload = await _read_json(response)
                        if response.status == 404:
                            message = f"Прогон #{run_id} не найден" if run_id else "Данные не найдены"
                            raise DoqaApiError(message, status=404)
                        if response.status in {401, 403}:
                            raise DoqaApiError("DoQA отклонил API-токен", status=response.status)
                        if response.status >= 500:
                            raise DoqaApiError(
                                f"DoQA временно недоступен: HTTP {response.status}",
                                status=response.status,
                            )
                        if response.status >= 400:
                            raise DoqaApiError(
                                _api_error_message(payload) or f"DoQA вернул HTTP {response.status}",
                                status=response.status,
                            )
                        if not isinstance(payload, dict):
                            raise DoqaApiError("DoQA вернул некорректный JSON")
                        return payload
            except DoqaApiError as exc:
                if exc.status is not None and exc.status < 500:
                    raise
                last_error = exc
            except (ClientError, TimeoutError, asyncio.TimeoutError) as exc:
                last_error = exc

            if attempt < self.attempts:
                await asyncio.sleep(0.5 * attempt)

        raise DoqaApiError("Не удалось получить отчёт из DoQA после нескольких попыток") from last_error


async def _read_json(response: Any) -> Any:
    try:
        return await response.json(content_type=None)
    except (ValueError, TypeError):
        return None


def _api_error_message(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return error["message"][:500]
    return None


def _find_matching_runs(payload: Any, external_id: int):
    pattern = re.compile(rf"(?<!\w)ID\s*[:#-]?\s*{external_id}(?!\d)", re.IGNORECASE)

    def walk(value: Any):
        if not isinstance(value, dict):
            return
        data = value.get("data")
        if isinstance(data, dict):
            title = str(data.get("name") or data.get("title") or "")
            if data.get("id") and not data.get("isFolder") and pattern.search(title):
                yield data
        for child in value.get("children") or ():
            yield from walk(child)
        if isinstance(data, dict) and ("data" in data or "children" in data):
            yield from walk(data)

    yield from walk(payload)
