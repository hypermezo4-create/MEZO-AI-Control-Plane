import asyncio
import logging
import secrets
import time
from collections import defaultdict, deque
from uuid import uuid4

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from mezo_control_plane.api.schemas import ErrorDetail, ErrorEnvelope

logger = logging.getLogger("mezo.api")


def error_response(request: Request, code: str, message: str, status_code: int) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    envelope = ErrorEnvelope(error=ErrorDetail(code=code, message=message, request_id=request_id))
    return JSONResponse(envelope.model_dump(), status_code=status_code)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied = request.headers.get("x-request-id", "")
        request.state.request_id = supplied[:128] if supplied else str(uuid4())
        response = await call_next(request)
        response.headers["x-request-id"] = request.state.request_id
        return response


class AuthenticationMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, api_key: str) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._api_key = api_key

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        exempt = {"/health/live", "/health/ready", "/v1/webhooks/github"}
        if request.url.path in exempt:
            return await call_next(request)
        provided = request.headers.get("x-api-key", "")
        if not self._api_key or not secrets.compare_digest(provided, self._api_key):
            logger.warning("request denied", extra={"request_id": request.state.request_id})
            return error_response(request, "authentication_failed", "Invalid API key", 401)
        return await call_next(request)


class BodyLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, maximum_bytes: int) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._maximum = maximum_bytes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self._maximum:
            return error_response(request, "body_too_large", "Request body exceeds limit", 413)
        body = await request.body()
        if len(body) > self._maximum:
            return error_response(request, "body_too_large", "Request body exceeds limit", 413)
        return await call_next(request)


class TimeoutMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, timeout_seconds: float) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._timeout = timeout_seconds

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        try:
            async with asyncio.timeout(self._timeout):
                return await call_next(request)
        except TimeoutError:
            return error_response(request, "request_timeout", "Request deadline exceeded", 504)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, limit: int, window_seconds: int) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._limit = limit
        self._window = window_seconds
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        identity = request.headers.get("x-api-key") or (
            request.client.host if request.client else "unknown"
        )
        now = time.monotonic()
        bucket = self._requests[identity]
        while bucket and bucket[0] <= now - self._window:
            bucket.popleft()
        if len(bucket) >= self._limit:
            response = error_response(request, "rate_limited", "Rate limit exceeded", 429)
            response.headers["retry-after"] = str(self._window)
            return response
        bucket.append(now)
        return await call_next(request)


class AuditLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            logger.info(
                "control write",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "request_id": request.state.request_id,
                },
            )
        return response
