"""Logical schemas only. Platform registration waits for compatibility evidence."""

from app.agent.policies import ENABLED_TOOLS
from app.schemas.agent_integration import NoArguments, OrderArguments

ARGUMENT_MODELS = {
    name: OrderArguments if name == "get_order" else NoArguments
    for name in ENABLED_TOOLS
}

TOOL_DEFINITIONS = [
    {"name": name, "parameters": ARGUMENT_MODELS[name].model_json_schema()}
    for name in sorted(ENABLED_TOOLS)
]
