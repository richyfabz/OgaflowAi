"""Fail-closed local compatibility boundary; no database privileges in its token."""

from hmac import compare_digest
from typing import Annotated

from fastapi import Header, HTTPException

from app.core.config import get_settings


def require_tool_token(authorization: Annotated[str | None, Header()] = None):
    settings = get_settings()
    if not settings.agent_boundary_enabled:
        raise HTTPException(404, detail={"code": "AGENT_BOUNDARY_DISABLED"})
    token = settings.tool_token
    if token is None or not token.get_secret_value().strip():
        raise HTTPException(503, detail={"code": "TOOL_AUTH_NOT_CONFIGURED"})
    expected = ("Bearer " + token.get_secret_value()).encode()
    if authorization is None or not compare_digest(authorization.encode(), expected):
        raise HTTPException(401, detail={"code": "TOOL_AUTH_REQUIRED"})


def restrict_legacy_routes():
    # A valid callback credential must not bypass the restricted tool allowlist.
    if get_settings().agent_boundary_enabled:
        raise HTTPException(403, detail={"code": "LEGACY_API_DISABLED"})
