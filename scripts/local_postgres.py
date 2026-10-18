"""Start/stop an isolated project-local PostgreSQL cluster; no system service."""

import argparse
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / ".local/pgdata"
SOCKET = ROOT / ".local/pgsocket"
PORT = "55432"


def executable(name):
    local = ROOT / ".local/postgres/bin" / name
    value = str(local) if local.is_file() else shutil.which(name)
    if not value:
        raise SystemExit(f"{name} not found. Install PostgreSQL locally; see README.")
    return value


def run(*args):
    subprocess.run(args, check=True, env={**os.environ, "LC_ALL": "C"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop", "status"])
    args = parser.parse_args()
    SOCKET.mkdir(parents=True, exist_ok=True)
    SOCKET.chmod(0o700)
    if args.action == "start":
        if not (DATA / "PG_VERSION").exists():
            run(
                executable("initdb"),
                "-D",
                str(DATA),
                "-U",
                "ogaflow_local",
                "--auth=trust",
                "--no-locale",
                "--encoding=UTF8",
            )
        # Unix socket only, protected by its private directory. No TCP listener.
        run(
            executable("pg_ctl"),
            "-D",
            str(DATA),
            "-l",
            str(ROOT / ".local/postgres.log"),
            "-o",
            f"-k {SOCKET} -p {PORT} -h '' -c unix_socket_permissions=0700",
            "-w",
            "start",
        )
    else:
        run(
            executable("pg_ctl"),
            "-D",
            str(DATA),
            *(["-m", "fast", "-w"] if args.action == "stop" else []),
            args.action,
        )


if __name__ == "__main__":
    main()
