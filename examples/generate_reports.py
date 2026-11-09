"""Generate the synthetic Playwright JSON reports used by the demo.

The data is fictional and seeded, so running this again gives identical files.
"""

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

RUNS = 26
# (file, title, chance of flaking, chance of a hard failure, error message)
TESTS = [
    ("checkout.spec.ts", "applies discount code", 0.34, 0.08, "Timeout 5000ms exceeded while waiting for locator('#total') toBeVisible"),
    ("checkout.spec.ts", "completes payment in iframe", 0.27, 0.04, "frame was detached while resolving frameLocator('#card')"),
    ("login.spec.ts", "keeps session after reload", 0.22, 0.04, "Request failed with 401 Unauthorized: session expired"),
    ("search.spec.ts", "shows result count", 0.19, 0.0, "strict mode violation: getByText('Results') resolved to 2 elements"),
    ("orders.spec.ts", "loads order history", 0.15, 0.04, "page.request failed: 503 Service Unavailable"),
    ("profile.spec.ts", "uploads avatar", 0.08, 0.0, "element is not attached to the DOM"),
    ("login.spec.ts", "logs in with valid user", 0, 0, ""),
    ("login.spec.ts", "rejects bad password", 0, 0, ""),
    ("search.spec.ts", "filters by category", 0, 0, ""),
    ("orders.spec.ts", "downloads invoice", 0, 0, ""),
    ("profile.spec.ts", "updates display name", 0, 0, ""),
]
BROKEN_FILE, BROKEN_TITLE = "cart.spec.ts", "removes last item"
BROKEN_ERROR = "expect(received).toEqual(expected): Expected 0, received 1"


def attempt(status, duration, message=""):
    result = {"status": status, "duration": duration, "retry": 0}
    if message:
        result["error"] = {"message": message}
    return result


def spec(file, title, status, results):
    return {"title": title, "file": file, "tests": [{"projectName": "chromium", "status": status, "results": results}]}


def main() -> None:
    rng = random.Random(20261110)
    target = Path(__file__).with_name("reports")
    target.mkdir(exist_ok=True)
    start = datetime(2026, 10, 1, 6, 30, tzinfo=timezone.utc)
    for run in range(RUNS):
        by_file = {}
        for file, title, flake, fail, message in TESTS:
            roll = rng.random()
            duration = rng.randint(900, 4200)
            if roll < fail:
                entry = spec(file, title, "unexpected", [attempt("failed", duration, message), attempt("failed", duration, message)])
            elif roll < fail + flake:
                entry = spec(file, title, "flaky", [attempt("failed", duration, message), attempt("passed", duration)])
            else:
                entry = spec(file, title, "expected", [attempt("passed", duration)])
            by_file.setdefault(file, []).append(entry)
        if run >= RUNS - 4:
            broken = spec(BROKEN_FILE, BROKEN_TITLE, "unexpected", [attempt("failed", 1500, BROKEN_ERROR)])
        else:
            broken = spec(BROKEN_FILE, BROKEN_TITLE, "expected", [attempt("passed", 1500)])
        by_file.setdefault(BROKEN_FILE, []).append(broken)
        report = {
            "config": {"metadata": {"commit": f"{run // 2:07x}"}},
            "stats": {"startTime": (start + timedelta(days=run)).isoformat()},
            "suites": [{"title": file, "file": file, "specs": specs, "suites": []} for file, specs in by_file.items()],
        }
        (target / f"run-{run + 1:02d}.json").write_text(json.dumps(report), encoding="utf-8")


if __name__ == "__main__":
    main()
