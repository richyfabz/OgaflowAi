"""Disabled by default. Only trusted local runtime code can issue invocation handles."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException

from app.agent.session_context import BoundaryError, SessionRegistry
from app.api.operations import Service
from app.core.integration_security import require_tool_token
from app.schemas.agent_integration import Envelope

router = APIRouter(prefix="/agent", dependencies=[Depends(require_tool_token)])
registry = SessionRegistry()


def get_registry() -> SessionRegistry:
    return registry


@router.post("/tools/{tool}", response_model=Envelope)
def invoke(
    tool: str,
    arguments: dict[str, Any],
    service: Service,
    contexts: Annotated[SessionRegistry, Depends(get_registry)],
    x_ogaflow_invocation: Annotated[str, Header(min_length=1, max_length=128)],
):
    try:
        return contexts.execute(x_ogaflow_invocation, tool, arguments, service)
    except BoundaryError as error:
        raise HTTPException(error.status, detail={"code": error.code}) from None
