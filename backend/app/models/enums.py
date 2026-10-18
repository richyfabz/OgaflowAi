from enum import Enum


class OrderStatus(str, Enum):
    CREATED = "CREATED"
    AWAITING_PAYMENT = "AWAITING_PAYMENT"
    PAYMENT_VERIFIED = "PAYMENT_VERIFIED"
    STOCK_RESERVED = "STOCK_RESERVED"
    CONFIRMED = "CONFIRMED"
    FULFILMENT = "FULFILMENT"
    ESCALATED = "ESCALATED"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class EscalationStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class AgentRunStatus(str, Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ESCALATED = "ESCALATED"
    FAILED = "FAILED"


class AgentActionStatus(str, Enum):
    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class VerificationSource(str, Enum):
    DEMO = "DEMO"
    PROVIDER = "PROVIDER"
