"""HTTPX compatibility harness for the restricted boundary, not a live Bimpe client.

The runtime supplies a retained ticket. A future platform binding must prove how
it obtains that ticket without exposing runtime identity to model arguments.
"""

import json

import httpx
from pydantic import SecretStr, ValidationError

from app.agent.policies import MAX_HTTP_ATTEMPTS
from app.agent.session_context import BoundaryError, Invocation
from app.schemas.agent_integration import Envelope, validate_data


class ToolTransport:
    def __init__(self, client: httpx.Client, token: SecretStr):
        # Client is operator-owned. Never accept an origin or URL from model output.
        self.client = client
        self.token = token

    def invoke(self, ticket: Invocation) -> Envelope:
        for attempt in range(MAX_HTTP_ATTEMPTS):
            try:
                response = self.client.post(
                    "/agent/tools/" + ticket.tool,
                    json=json.loads(ticket.arguments_json),
                    headers={
                        "Authorization": "Bearer " + self.token.get_secret_value(),
                        "X-OgaFlow-Invocation": ticket.handle,
                    },
                    timeout=10.0,
                    follow_redirects=False,
                )
            except httpx.TransportError:
                if attempt + 1 == MAX_HTTP_ATTEMPTS:
                    raise BoundaryError("TOOL_TRANSPORT_UNAVAILABLE", 503) from None
                continue
            # Only the explicit transient backend code or an upstream 503/504 retries.
            # Invalid structured output (502) is a stop, never an invitation to guess.
            if response.status_code in {503, 504} and attempt + 1 < MAX_HTTP_ATTEMPTS:
                continue
            if response.status_code != 200:
                raise BoundaryError("TOOL_HTTP_FAILURE", response.status_code)
            try:
                result = Envelope.model_validate_json(response.content)
                validate_data(ticket.tool, result)
            except (ValidationError, ValueError, KeyError, TypeError):
                raise BoundaryError("INVALID_TOOL_RESULT", 502) from None
            return result
        raise BoundaryError("TOOL_TRANSPORT_UNAVAILABLE", 503)
