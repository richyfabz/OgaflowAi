"""Prepare seed SQL for a fresh demo database without executing destructive SQL."""

from pathlib import Path

from seed_demo import render_seed


def write_reset_artifact(destination: Path) -> None:
    """Write a new artifact exclusively, preserving any existing local file."""
    header = (
        "-- DEMO RESET PREPARATION ONLY: use a fresh, isolated schema/database.\n"
        "-- Apply schema.sql first. This file does not clear existing state.\n"
        "-- Reusing an occupied fixture namespace fails and rolls back.\n"
    )
    with destination.open("x", encoding="utf-8") as output:
        output.write(header + render_seed())


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, required=True, help="New local SQL artifact path"
    )
    args = parser.parse_args()
    write_reset_artifact(args.output)
    print(f"Prepared {args.output}; no database contacted or cleared.")
