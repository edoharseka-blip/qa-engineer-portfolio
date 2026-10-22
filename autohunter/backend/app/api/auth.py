"""Простая защита панели: пароль из окружения → подписанный токен с TTL (HMAC-SHA256, без внешних зависимостей)."""
import base64
import hashlib
import hmac
import json
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def create_token(secret: str, ttl_hours: int, now: float | None = None) -> str:
    payload = _b64(json.dumps({"exp": (time.time() if now is None else now) + ttl_hours * 3600}).encode())
    sig = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def verify_token(secret: str, token: str, now: float | None = None) -> bool:
    try:
        payload, sig = token.split(".", 1)
        good = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good):
            return False
        return json.loads(_unb64(payload))["exp"] > (time.time() if now is None else now)
    except Exception:  # noqa: BLE001
        return False


class SlidingWindow:
    """Ограничитель частоты по ключу (IP)."""
    def __init__(self, limit: int, window: float = 60.0):
        self.limit, self.window = limit, window
        self.hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        q = self.hits[key]
        while q and q[0] <= now - self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True


def require_auth(request: Request) -> None:
    st = request.app.state
    header = request.headers.get("authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else request.query_params.get("token", "")
    if not token or not verify_token(st.settings.auth_secret, token):
        raise HTTPException(status_code=401, detail="Требуется авторизация")
