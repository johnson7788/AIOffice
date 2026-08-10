"""Fixed-window rate limiter.

ponytail: in-process dict of (identity, window)->count. Per-replica, so behind a
multi-process/-replica deployment it under-counts — swap for a Redis INCR+EXPIRE
when you scale out. Identity = JWT sub (no verification, just bucketing) else
client IP. Health check is exempt.
"""
import time

import jwt
from fastapi import Request
from fastapi.responses import JSONResponse

from .settings import JWT_ALG, JWT_SECRET, RATE_LIMIT_MAX, RATE_LIMIT_WINDOW_SEC

# module-level so tests can dial it down: ratelimit.MAX = 3
MAX = RATE_LIMIT_MAX
WINDOW = RATE_LIMIT_WINDOW_SEC

_counts: dict[tuple[str, int], int] = {}


def _identity(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        try:
            payload = jwt.decode(auth[7:], JWT_SECRET, algorithms=[JWT_ALG])
            return f"u:{payload.get('sub')}"
        except jwt.PyJWTError:
            pass
    return f"ip:{request.client.host if request.client else 'unknown'}"


async def rate_limit(request: Request, call_next):
    if request.url.path == "/healthz":
        return await call_next(request)
    window = int(time.time()) // WINDOW
    key = (_identity(request), window)
    n = _counts.get(key, 0) + 1
    _counts[key] = n
    if len(_counts) > 10_000:  # cheap sweep of stale windows
        for k in [k for k in _counts if k[1] != window]:
            del _counts[k]
    if MAX and n > MAX:
        return JSONResponse(
            {"detail": "rate limit exceeded"},
            status_code=429,
            headers={"Retry-After": str(WINDOW)},
        )
    return await call_next(request)
