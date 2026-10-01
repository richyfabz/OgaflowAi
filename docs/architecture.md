# OgaFlow Architecture

## Status

Canonical architecture specification.

Architectural changes require explicit review before implementation.

## Core Workflow

Customer request
→ identify customer
→ retrieve order
→ verify payment
→ verify inventory
→ reserve inventory
→ confirm order
→ notify customer

Unsafe or ambiguous conditions
→ human escalation
