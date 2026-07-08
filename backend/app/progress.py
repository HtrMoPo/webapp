"""In-memory publish-progress tracking, polled by the frontend while a
publish request is in flight.

Deliberately not SSE/WebSocket: those need extra reverse-proxy configuration
(disabling response buffering, longer read timeouts, upgrade headers) to work
reliably in front of a generic nginx/whatever setup. Polling a plain JSON
endpoint every second works unmodified behind any proxy.

In-memory only: fine as long as this app runs as a single process (our
Dockerfile's default `uvicorn` command, no multi-worker setup). If that ever
changes, this needs to move to something shared (DB row, Redis, etc).
"""

import time

_progress: dict[int, dict] = {}
_TTL_SECONDS = 300


def set_progress(version_id: int, step: str, detail: str = "") -> None:
    _progress[version_id] = {"step": step, "detail": detail, "updated_at": time.time()}


def get_progress(version_id: int) -> dict:
    entry = _progress.get(version_id)
    if not entry or time.time() - entry["updated_at"] > _TTL_SECONDS:
        return {"step": "idle", "detail": ""}
    return {"step": entry["step"], "detail": entry["detail"]}


def clear_progress(version_id: int) -> None:
    _progress.pop(version_id, None)
