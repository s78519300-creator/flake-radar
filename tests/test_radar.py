import json
from pathlib import Path

import pytest

from flake_radar.analysis import analyze, classify_cause, load_reports, quarantine_payload
from flake_radar.cli import main
from flake_radar.report import render_html

ROOT = Path(__file__).resolve().parents[1]
ERROR = "Timeout waiting for toBeVisible"


def report(status_map, name="r", commit=None, start="2026-01-01"):
    specs = []
    for title, status in status_map.items():
        results = [{"status": "failed", "duration": 1000, "error": {"message": ERROR}}] if status in {"unexpected", "flaky"} else []
        results.append({"status": "passed", "duration": 500})
        specs.append({"title": title, "file": "a.spec.ts", "tests": [{"projectName": "chromium", "status": status, "results": results}]})
    return {"_name": name, "config": {"metadata": {"commit": commit}}, "stats": {"startTime": start}, "suites": [{"title": "a.spec.ts", "file": "a.spec.ts", "specs": specs}]}


def history(*statuses, commits=None):
    commits = commits or [None] * len(statuses)
    reports = [report({"t": status}, f"r{index}", commits[index], f"2026-01-{index + 1:02d}") for index, status in enumerate(statuses)]
    return analyze(reports)["tests"][0]


def test_retry_pass_is_flaky():
    assert history("expected", "flaky", "expected").classification == "flaky"


def test_fail_then_pass_is_flaky():
    assert history("expected", "unexpected", "expected").classification == "flaky"


def test_consistent_recent_failure_is_broken_not_flaky():
    test = history("expected", "unexpected", "unexpected", "unexpected")
    assert test.classification == "broken" and not test.quarantine


def test_same_commit_pass_and_fail_is_flaky():
    assert history("unexpected", "expected", commits=["abc", "abc"]).classification == "flaky"


def test_all_passing_is_stable():
    test = history("expected", "expected", "expected")
    assert test.classification == "stable" and test.instability == 0


def test_all_skipped_is_not_counted_as_stable():
    assert history("skipped", "skipped").classification == "skipped"


def test_quarantine_needs_enough_runs():
    assert not history("flaky", "expected", "flaky").quarantine
    assert history("flaky", "expected", "flaky", "expected", "expected", "expected").quarantine


def test_quarantine_respects_threshold():
    statuses = ["flaky", *["expected"] * 19]
    assert not history(*statuses).quarantine


def test_retry_waste_counts_only_failed_attempts():
    assert history("flaky").retry_waste_ms == 1000


def test_test_missing_from_a_run_stays_aligned():
    reports = [report({"a": "expected"}, "r1", start="2026-01-01"), report({"a": "expected", "b": "expected"}, "r2", start="2026-01-02")]
    tests = {test.title: test for test in analyze(reports)["tests"]}
    assert tests["b"].outcomes == [None, "pass"]


@pytest.mark.parametrize(
    "message, cause",
    [
        ("strict mode violation: resolved to 2", "ambiguous locator"),
        ("frame was detached", "iframe"),
        ("Error: 401 Unauthorized", "auth/session"),
        ("net::ERR_CONNECTION_RESET", "network/backend"),
        ("element is not attached to the DOM", "stale element"),
        ("Timeout 5000ms exceeded", "timing"),
        ("something new", "unknown"),
    ],
)
def test_root_cause_classification(message, cause):
    assert classify_cause([message])[0] == cause


def test_most_common_cause_wins():
    assert classify_cause(["Timeout", "Timeout", "strict mode violation"])[0] == "timing"


def test_nested_suites_and_ansi_errors_are_parsed():
    data = {
        "_name": "r", "stats": {},
        "suites": [{"title": "a.ts", "file": "a.ts", "suites": [{"title": "group", "specs": [{"title": "t", "file": "a.ts", "tests": [
            {"projectName": "firefox", "status": "flaky", "results": [{"status": "failed", "duration": 1, "errors": [{"message": "\x1b[31mTimeout\x1b[0m"}]}]}
        ]}]}]}],
    }
    test = analyze([data])["tests"][0]
    assert test.test_id == "a.ts › group › t [firefox]" and test.errors == ["Timeout"]


def test_grep_pattern_escapes_regex_characters():
    tests = analyze([report({"costs $5 (net)": "flaky"}, f"r{i}", start=f"2026-01-{i + 1:02d}") for i in range(5)])
    assert quarantine_payload(tests)["grep_invert"] == r"costs\ \$5\ \(net\)"


def test_html_is_escaped():
    result = analyze([report({"<img src=x>": "flaky"})])
    assert "<img src=x>" not in render_html(result, quarantine_payload(result))


def test_invalid_report_is_rejected(tmp_path):
    (tmp_path / "x.json").write_text("{}")
    with pytest.raises(ValueError, match="not a Playwright"):
        load_reports(tmp_path)


def test_sample_data_end_to_end(tmp_path):
    html, quarantine = tmp_path / "r.html", tmp_path / "q.json"
    assert main([str(ROOT / "examples/reports"), "--html", str(html), "--quarantine", str(quarantine)]) == 0
    assert html.exists() and json.loads(quarantine.read_text())["count"] >= 3
    assert main([str(ROOT / "examples/reports"), "--fail-on-flaky"]) == 1


def test_empty_folder_returns_2(tmp_path):
    assert main([str(tmp_path)]) == 2
