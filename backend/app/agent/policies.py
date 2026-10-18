"""Deterministic limits, independent of the model's prompt."""

MAX_LOGICAL_CALLS = 12
MAX_HTTP_ATTEMPTS = 2
ENABLED_TOOLS = frozenset(
    {"identify_customer", "get_open_orders", "get_order", "find_payments"}
)
DISABLED_TOOLS = frozenset(
    {
        "verify_payment",
        "match_payment",
        "check_inventory",
        "reserve_inventory",
        "confirm_order",
        "create_escalation",
    }
)
