from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

Token = Annotated[
    str, Field(strict=True, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
]


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartRun(Request):
    phone: Annotated[str, Field(strict=True, min_length=1, max_length=40)]
    idempotency_key: Token


class RunCommand(Request):
    run_id: Token
    idempotency_key: Token


class OrderCommand(RunCommand):
    order_id: Token


class PaymentCommand(RunCommand):
    payment_id: Token


class EscalationCommand(RunCommand):
    order_id: Token | None = None


class ActionView(BaseModel):
    id: str
    tool: str
    status: str
    failure_code: str | None
    started_at: datetime
    finished_at: datetime | None


class RunView(BaseModel):
    id: str
    customer_id: str | None
    status: str
    started_at: datetime
    finished_at: datetime | None
    actions: list[ActionView]
