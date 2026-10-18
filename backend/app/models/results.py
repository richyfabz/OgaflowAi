from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    run_id: str
    action_id: str = ""
    status: Literal["SUCCEEDED", "FAILED"]
    data: dict[str, Any] = Field(default_factory=dict)
    reason_code: str | None = None
    human_review_required: bool = False
    replayed: bool = False
