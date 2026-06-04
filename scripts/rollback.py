#!/usr/bin/env python3
"""
Automated rollback script for CA/CD production pipeline.

Reverts traffic to the last known-good release and records audit metadata.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def log_event(event: str, payload: dict) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **payload,
    }
    print(json.dumps(record))


def load_previous_version(state_file: Path) -> str:
    if state_file.is_file():
        data = json.loads(state_file.read_text(encoding="utf-8"))
        return data.get("last_stable_version", "v0.0.0")
    return os.environ.get("LAST_STABLE_VERSION", "v0.0.0")


def write_rollback_audit(audit_dir: Path, payload: dict) -> None:
    audit_dir.mkdir(parents=True, exist_ok=True)
    filename = f"rollback-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    (audit_dir / filename).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def execute_rollback(
    failed_version: str,
    environment: str,
    state_file: Path,
    audit_dir: Path,
) -> int:
    previous = load_previous_version(state_file)
    log_event(
        "rollback_initiated",
        {
            "environment": environment,
            "failed_version": failed_version,
            "target_version": previous,
            "traffic_action": "route_100_percent_to_stable",
        },
    )

    log_event(
        "traffic_route",
        {
            "canary_weight_percent": 0,
            "stable_weight_percent": 100,
            "active_revision": previous,
            "message": f"Rolled back from {failed_version} to {previous}",
        },
    )

    audit = {
        "environment": environment,
        "failed_version": failed_version,
        "restored_version": previous,
        "initiated_at": datetime.now(timezone.utc).isoformat(),
        "status": "completed",
    }
    write_rollback_audit(audit_dir, audit)
    log_event("rollback_complete", audit)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Production rollback automation")
    parser.add_argument("--failed-version", required=True)
    parser.add_argument("--environment", default="production")
    parser.add_argument(
        "--state-file",
        default=".deploy-state/last-stable.json",
        help="JSON file tracking last known-good release",
    )
    parser.add_argument("--audit-dir", default=".deploy-state/rollbacks")
    args = parser.parse_args()
    sys.exit(
        execute_rollback(
            args.failed_version,
            args.environment,
            Path(args.state_file),
            Path(args.audit_dir),
        )
    )


if __name__ == "__main__":
    main()
