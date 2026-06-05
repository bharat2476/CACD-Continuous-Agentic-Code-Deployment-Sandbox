#!/usr/bin/env python3
"""
Simulated canary deployment for CA/CD stage-to-prod pipeline.

Models progressive traffic shift: 5% → 25% → 50% → 100% with health gates between steps.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone


STAGES = [
    {"percent": 5, "label": "canary-5", "sleep_seconds": 2},
    {"percent": 25, "label": "canary-25", "sleep_seconds": 2},
    {"percent": 50, "label": "canary-50", "sleep_seconds": 2},
    {"percent": 100, "label": "full-production", "sleep_seconds": 1},
]


def log_event(event: str, payload: dict) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **payload,
    }
    print(json.dumps(record))


def route_traffic(percent: int, label: str) -> None:
    log_event(
        "traffic_route",
        {
            "action": "shift_traffic",
            "canary_label": label,
            "stable_weight_percent": 100 - percent,
            "canary_weight_percent": percent,
            "message": f"Routing {percent}% of traffic to new revision ({label})",
        },
    )


def check_canary_health(percent: int, force_fail: bool) -> bool:
    if force_fail and percent >= 25:
        log_event(
            "health_check",
            {
                "status": "failed",
                "canary_percent": percent,
                "error_rate": 0.12,
                "p99_latency_ms": 890,
            },
        )
        return False
    log_event(
        "health_check",
        {
            "status": "passed",
            "canary_percent": percent,
            "error_rate": 0.001,
            "p99_latency_ms": 120,
        },
    )
    return True


def run_canary(environment: str, version: str, force_fail: bool = False) -> int:
    log_event("deploy_start", {"environment": environment, "version": version})

    for stage in STAGES:
        route_traffic(stage["percent"], stage["label"])
        time.sleep(stage["sleep_seconds"])
        if not check_canary_health(stage["percent"], force_fail):
            log_event(
                "deploy_aborted",
                {
                    "environment": environment,
                    "version": version,
                    "failed_at_percent": stage["percent"],
                    "reason": "post-deploy health check failed",
                },
            )
            return 1

    log_event("deploy_complete", {"environment": environment, "version": version, "traffic": "100%"})
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulated canary deployment")
    parser.add_argument("--environment", default="production")
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--force-fail",
        action="store_true",
        help="Simulate health check failure after 25 percent canary (for rollback testing)",
    )
    args = parser.parse_args()
    sys.exit(run_canary(args.environment, args.version, args.force_fail))


if __name__ == "__main__":
    main()
