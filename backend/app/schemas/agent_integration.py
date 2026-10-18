"""Strict envelopes at the adapter boundary; domain models remain unchanged."""

import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.domain import Order
from app.models.enums import OrderStatus, PaymentStatus
from app.schemas.operations import Token


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class NoArguments(StrictModel):
    pass


class OrderArguments(StrictModel):
    order_id: Token


class Result(StrictModel):
    run_id: Token
    action_id: Token
    status: Literal["SUCCEEDED", "FAILED"]
    data: dict[str, Any]
    reason_code: Token | None
    human_review_required: bool
    replayed: bool

    @model_validator(mode="after")
    def consistent_status(self):
        if self.status == "SUCCEEDED" and (
            self.reason_code is not None or self.human_review_required
        ):
            raise ValueError("Inconsistent lookup success")
        if self.status == "FAILED" and (
            self.reason_code is None or not self.human_review_required
        ):
            raise ValueError("Inconsistent lookup failure")
        return self


class Envelope(Result):
    next_action_allowed: bool

    @model_validator(mode="after")
    def safe_continuation(self):
        if self.next_action_allowed and (
            self.status != "SUCCEEDED" or self.human_review_required
        ):
            raise ValueError("Unsafe continuation")
        return self


class CustomerData(StrictModel):
    customer_id: Token
    name: Annotated[str, Field(min_length=1)]
    preferred_language: Annotated[str, Field(min_length=1)]


class OrderSummary(StrictModel):
    id: Token
    status: OrderStatus
    total_minor: Annotated[int, Field(ge=0)]
    currency: Literal["NGN"]


class OrdersData(StrictModel):
    orders: Annotated[list[OrderSummary], Field(min_length=1, max_length=1)]


class OrderData(StrictModel):
    order: Order


class PaymentSummary(StrictModel):
    id: Token
    order_id: Token | None
    amount_minor: Annotated[int, Field(ge=0)]
    currency: Literal["NGN"]
    status: PaymentStatus


class PaymentsData(StrictModel):
    payments: list[PaymentSummary]


class FailureData(StrictModel):
    escalation_id: Token


DATA_MODELS = {
    "identify_customer": CustomerData,
    "get_open_orders": OrdersData,
    "get_order": OrderData,
    "find_payments": PaymentsData,
}


def validate_data(tool: str, result: Result):
    model = FailureData if result.status == "FAILED" else DATA_MODELS[tool]
    # JSON mode accepts wire enum strings/arrays while enforcing strict scalar types.
    return model.model_validate_json(json.dumps(result.data), strict=True)
