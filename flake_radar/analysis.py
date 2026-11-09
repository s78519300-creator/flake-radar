"""Parse Playwright JSON reports and analyse test stability across CI runs."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

ANSI = re.compile(r"\x1b\[[0-9;]*m")
STATUS = {"expected": "pass", "unexpected": "fail", "flaky": "flaky", "skipped": "skip"}

ROOT_CAUSES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("auth/session", re.compile(r"\b(401|403)\b|unauthori[sz]ed|forbidden|session expired|storageState", re.I), "Reuse a saved storageState and create the session in a setup project."),
    ("iframe", re.compile(r"frame was detached|frameLocator|iframe", re.I), "Target the frame with frameLocator and wait for content inside it."),
    ("stale element", re.compile(r"detached from (the )?DOM|element is not attached|not stable", re.I), "Use a locator instead of a stored handle, and let actions re-resolve it."),
    ("ambiguous locator", re.compile(r"strict mode violation", re.I), "Tighten the locator with getByRole or getByTestId."),
    ("network/backend", re.compile(r"net::ERR_|ECONNRESET|ECONNREFUSED|socket hang up|\b50[234]\b", re.I), "Mock unstable dependencies, or check backend health before the test."),
    ("navigation", re.compile(r"page\.goto|navigation|waitForURL", re.I), "Wait for the expected URL or a visible landmark, not for load events."),
    ("timing", re.compile(r"timeout|timed out|toBeVisible|waiting for", re.I), "Use web-first assertions and wait on the app state that matters."),
    ("assertion", re.compile(r"expect\(|toEqual|toHaveText|Expected", re.I), "Check for shared state and test-order dependence."),
)
UNKNOWN_FIX = "Open the failing trace and compare it with a passing run."


@dataclass
class RunInfo:
    name: str
    started: str
    commit: str | None


@dataclass
class TestHistory:
    test_id: str
    title: str
    outcomes: list[str | None]
    errors: list[str] = field(default_factory=list)
    retry_waste_ms: int = 0
    classification: str = "stable"
    instability: float = 0.0
    root_cause: str | None = None
    fix: str | None = None
    quarantine: bool = False

    @property
    def executed(self) -> list[str]:
        return [outcome for outcome in self.outcomes if outcome not in (None, "skip")]


def _walk(suite: dict[str, Any], path: tuple[str, ...]) -> Iterator[tuple[tuple[str, ...], dict]]:
    title = suite.get("title", "")
    here = path + (title,) if title and title != suite.get("file") else path
    for spec in suite.get("specs", []):
        yield here, spec
    for child in suite.get("suites", []):
        yield from _walk(child, here)


def _result_error(result: dict[str, Any]) -> str | None:
    error = result.get("error") or next(iter(result.get("errors") or []), None)
    if not error:
        return None
    return ANSI.sub("", error.get("message") or error.get("value") or "")


def _commit(report: dict[str, Any]) -> str | None:
    metadata = report.get("config", {}).get("metadata", {})
    git = metadata.get("gitCommit") or {}
    return metadata.get("commit") or git.get("hash")


def load_reports(folder: str | Path) -> list[dict]:
    reports = []
    for path in sorted(Path(folder).glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name}: not valid JSON ({exc.msg})") from exc
        if "suites" not in data:
            raise ValueError(f"{path.name}: not a Playwright JSON report (no 'suites')")
        data["_name"] = path.stem
        reports.append(data)
    reports.sort(key=lambda report: (report.get("stats", {}).get("startTime", ""), report["_name"]))
    return reports


def collect(reports: list[dict]) -> tuple[list[RunInfo], dict[str, TestHistory]]:
    runs = [RunInfo(report["_name"], report.get("stats", {}).get("startTime", ""), _commit(report)) for report in reports]
    histories: dict[str, TestHistory] = {}
    for index, report in enumerate(reports):
        for suite in report["suites"]:
            for path, spec in _walk(suite, ()):
                for test in spec.get("tests", []):
                    project = test.get("projectName") or "default"
                    title = " › ".join((*path, spec["title"]))
                    test_id = f"{spec.get('file', '?')} › {title} [{project}]"
                    history = histories.setdefault(test_id, TestHistory(test_id, spec["title"], [None] * len(reports)))
                    outcome = STATUS.get(test.get("status"), "fail")
                    history.outcomes[index] = outcome
                    for result in test.get("results", []):
                        if result.get("status") in {"passed", "skipped"}:
                            continue
                        if message := _result_error(result):
                            history.errors.append(message)
                        if outcome == "flaky":
                            history.retry_waste_ms += int(result.get("duration") or 0)
    return runs, histories


def classify_cause(errors: list[str]) -> tuple[str | None, str | None]:
    if not errors:
        return None, None
    counts: Counter[str] = Counter()
    for error in errors:
        counts[next((name for name, pattern, _ in ROOT_CAUSES if pattern.search(error)), "unknown")] += 1
    top = counts.most_common(1)[0][0]
    return top, next((fix for name, _, fix in ROOT_CAUSES if name == top), UNKNOWN_FIX)


def _same_commit_conflict(history: TestHistory, runs: list[RunInfo]) -> bool:
    seen: dict[str, set[str]] = {}
    for run, outcome in zip(runs, history.outcomes):
        if run.commit and outcome in {"pass", "fail"}:
            seen.setdefault(run.commit, set()).add(outcome)
    return any(len(outcomes) == 2 for outcomes in seen.values())


def analyze(reports: list[dict], threshold: float = 0.15, min_runs: int = 5, broken_after: int = 3) -> dict:
    """Separate flaky tests, which need stabilising, from broken tests, which need fixing."""
    runs, histories = collect(reports)
    for history in histories.values():
        executed = history.executed
        if not executed:
            history.classification = "skipped"
            continue
        recovered = sum(1 for now, after in zip(executed, executed[1:]) if now == "fail" and after in {"pass", "flaky"})
        flaky_runs = executed.count("flaky")
        history.instability = (flaky_runs + recovered) / len(executed)
        tail = executed[-broken_after:]
        if len(tail) == broken_after and all(outcome == "fail" for outcome in tail):
            history.classification = "broken"
        elif flaky_runs or recovered or _same_commit_conflict(history, runs):
            history.classification = "flaky"
        if history.classification != "stable":
            history.root_cause, history.fix = classify_cause(history.errors)
        history.quarantine = history.classification == "flaky" and history.instability >= threshold and len(executed) >= min_runs

    ordered = sorted(histories.values(), key=lambda item: ({"broken": 0, "flaky": 1}.get(item.classification, 2), -item.instability, item.test_id))
    return {"runs": runs, "tests": ordered}


def quarantine_payload(analysis: dict) -> dict:
    tests = [test for test in analysis["tests"] if test.quarantine]
    return {
        "count": len(tests),
        "tests": [{"id": test.test_id, "instability": round(test.instability, 3), "root_cause": test.root_cause, "fix": test.fix} for test in tests],
        "grep_invert": "|".join(sorted({re.escape(test.title) for test in tests})),
    }
