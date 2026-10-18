"""Immutable domain snapshots; these are not agent-writable API schemas."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import (
    AgentActionStatus,
    AgentRunStatus,
    EscalationStatus,
    OrderStatus,
    PaymentStatus,
    VerificationSource,
)

Identifier = Annotated[str, Field(strict=True, min_length=1)]
MinorUnits = Annotated[int, Field(strict=True, ge=0, le=9223372036854775807)]
Quantity = Annotated[int, Field(strict=True, ge=0, le=2147483647)]
PositiveQuantity = Annotated[int, Field(strict=True, gt=0, le=2147483647)]


class Snapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Customer(Snapshot):
    id: Identifier
    name: Identifier
    phone: Identifier
    preferred_language: Identifier = "English/Pidgin"


class Product(Snapshot):
    id: Identifier
    name: Identifier
    unit: Identifier = "carton"
    available_quantity: Quantity


class OrderItem(Snapshot):
    product_id: Identifier
    quantity: PositiveQuantity
    unit_price_minor: MinorUnits
    reserved_quantity: Quantity = 0

    @model_validator(mode="after")
    def validate_reservation(self) -> "OrderItem":
        if self.reserved_quantity not in (0, self.quantity):
            raise ValueError("Reservation must cover the entire order line")
        return self


class Order(Snapshot):
    id: Identifier
    customer_id: Identifier
    status: OrderStatus = OrderStatus.CREATED
    total_minor: MinorUnits
    currency: Literal["NGN"] = "NGN"
    items: tuple[OrderItem, ...] = Field(min_length=1)
    verified_payment_id: Identifier | None = None

    @model_validator(mode="after")
    def validate_items(self) -> "Order":
        if len({item.product_id for item in self.items}) != len(self.items):
            raise ValueError("An order may contain each product only once")
        if (
            sum(item.quantity * item.unit_price_minor for item in self.items)
            != self.total_minor
        ):
            raise ValueError("Order total must equal the sum of its lines")
        return self


class Payment(Snapshot):
    id: Identifier
    customer_id: Identifier
    order_id: Identifier | None
    amount_minor: MinorUnits
    currency: Literal["NGN"] = "NGN"
    status: PaymentStatus
    provider: Identifier
    reference: Identifier
    verified_at: datetime | None = None
    verification_source: VerificationSource | None = None

    @model_validator(mode="after")
    def validate_verification(self) -> "Payment":
        if (self.verified_at is None) != (self.verification_source is None):
            raise ValueError("Verification time and source must be supplied together")
        if self.verified_at is not None:
            if self.verified_at.utcoffset() is None:
                raise ValueError("Verification time must include a timezone")
            if self.status != PaymentStatus.SUCCESS:
                raise ValueError(
                    "Only successful payments may carry verification evidence"
                )
        return self


class AgentRun(Snapshot):
    id: Identifier
    customer_id: Identifier | None = None
    status: AgentRunStatus = AgentRunStatus.RUNNING


class AgentAction(Snapshot):
    id: Identifier
    run_id: Identifier
    tool: Identifier
    status: AgentActionStatus = AgentActionStatus.STARTED
    idempotency_key: Identifier


class Escalation(Snapshot):
    id: Identifier
    run_id: Identifier
    order_id: Identifier | None = None
    reason: Identifier
    details: Identifier
    status: EscalationStatus = EscalationStatus.OPEN
