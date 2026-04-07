"""Request / response logging middleware with user identity tracking."""

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("audit")


class AuditLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000

        # Extract user identity from Authorization header if present
        user = "-"
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            try:
                from jose import jwt
                from app.config import settings
                payload = jwt.decode(
                    auth_header[7:],
                    settings.secret_key,
                    algorithms=[settings.jwt_algorithm],
                )
                user = payload.get("sub", "-")
            except Exception:
                pass

        logger.info(
            "%s %s %s %.0fms user=%s",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            user,
        )
        return response
