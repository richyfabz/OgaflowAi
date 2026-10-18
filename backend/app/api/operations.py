from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.core.config import get_settings
from app.core.database import Database
from app.core.integration_security import restrict_legacy_routes
from app.models.results import ToolResult
from app.repositories.unit_of_work import UnitOfWork
from app.schemas.operations import (
    EscalationCommand,
    OrderCommand,
    PaymentCommand,
    RunCommand,
    RunView,
    StartRun,
)
from app.services.operations import OperationsService
from app.services.verification import StoredDemoVerifier

router = APIRouter(dependencies=[Depends(restrict_legacy_routes)])


def get_service() -> OperationsService:
    settings = get_settings()
    if settings.database_url is None or not settings.database_url.get_secret_value():
        raise HTTPException(status_code=503, detail={"code": "DATABASE_NOT_CONFIGURED"})
    return OperationsService(
        UnitOfWork(Database(settings.database_url.get_secret_value())),
        allow_demo=settings.demo_mode,
        verifier=StoredDemoVerifier() if settings.demo_mode else None,
    )


Service = Annotated[OperationsService, Depends(get_service)]


@router.post("/runs", response_model=ToolResult)
def start_run(body: StartRun, service: Service):
    return service.start_run(body.phone, body.idempotency_key)


@router.get("/runs/{run_id}", response_model=RunView)
def get_run(run_id: str, service: Service):
    return service.get_run(run_id)


@router.post("/tools/get_open_orders", response_model=ToolResult)
def get_open_orders(body: RunCommand, service: Service):
    return service.get_open_orders(body.run_id, body.idempotency_key)


@router.post("/tools/get_order", response_model=ToolResult)
def get_order(body: OrderCommand, service: Service):
    return service.get_order(body.run_id, body.idempotency_key, body.order_id)


@router.post("/tools/find_payments", response_model=ToolResult)
def find_payments(body: RunCommand, service: Service):
    return service.find_payments(body.run_id, body.idempotency_key)


@router.post("/tools/verify_payment", response_model=ToolResult)
def verify_payment(body: PaymentCommand, service: Service):
    return service.verify_payment(body.run_id, body.idempotency_key, body.payment_id)


@router.post("/tools/match_payment", response_model=ToolResult)
def match_payment_route(body: OrderCommand, service: Service):
    return service.match_payment(body.run_id, body.idempotency_key, body.order_id)


@router.post("/tools/check_inventory", response_model=ToolResult)
def check_inventory(body: OrderCommand, service: Service):
    return service.check_inventory(body.run_id, body.idempotency_key, body.order_id)


@router.post("/tools/reserve_inventory", response_model=ToolResult)
def reserve_inventory(body: OrderCommand, service: Service):
    return service.reserve_inventory(body.run_id, body.idempotency_key, body.order_id)


@router.post("/tools/confirm_order", response_model=ToolResult)
def confirm_order(body: OrderCommand, service: Service):
    return service.confirm_order(body.run_id, body.idempotency_key, body.order_id)


@router.post("/tools/create_escalation", response_model=ToolResult)
def create_escalation(body: EscalationCommand, service: Service):
    return service.create_escalation(body.run_id, body.idempotency_key, body.order_id)
