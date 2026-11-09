"""Command-line interface: ``flake-radar reports/ --html radar.html``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .analysis import analyze, load_reports, quarantine_payload
from .report import render_html


def main(argv: list[str] | None = None) -> int:
    """Return 0 if healthy, 1 if --fail-on-flaky found problems, 2 on bad input."""
    parser = argparse.ArgumentParser(prog="flake-radar", description="Find and explain flaky Playwright tests.")
    parser.add_argument("reports", type=Path, help="folder of Playwright JSON reports, one per CI run")
    parser.add_argument("--html", type=Path)
    parser.add_argument("--quarantine", type=Path, help="write the quarantine list as JSON")
    parser.add_argument("--threshold", type=float, default=0.15, help="instability needed for quarantine")
    parser.add_argument("--min-runs", type=int, default=5, help="runs needed before quarantine")
    parser.add_argument("--fail-on-flaky", action="store_true")
    args = parser.parse_args(argv)

    try:
        reports = load_reports(args.reports)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not reports:
        print(f"error: no JSON reports in {args.reports}", file=sys.stderr)
        return 2

    result = analyze(reports, args.threshold, args.min_runs)
    payload = quarantine_payload(result)
    unstable = [test for test in result["tests"] if test.classification in {"flaky", "broken"}]
    print(f"{len(result['tests'])} tests, {len(result['runs'])} runs, {len(unstable)} unstable, {payload['count']} to quarantine")
    for test in unstable:
        print(f"{test.classification:<7} {test.instability * 100:>3.0f}%  {test.root_cause or 'unknown':<18} {test.test_id}")
    if args.html:
        args.html.write_text(render_html(result, payload), encoding="utf-8")
    if args.quarantine:
        args.quarantine.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 1 if args.fail_on_flaky and unstable else 0


if __name__ == "__main__":
    raise SystemExit(main())
