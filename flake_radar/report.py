"""Render a self-contained HTML stability dashboard."""

from __future__ import annotations

from collections import Counter
from html import escape

STYLE = """
:root{--bg:#120d1f;--panel:#1d1630;--line:#382c55;--text:#f4f0ff;--muted:#a99dc6;--pass:#34d399;--flaky:#fbbf24;--fail:#f43f5e;--skip:#4b3f68;--accent:#f472b6}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(900px 450px at 75% -10%,#831843 0,transparent 60%),var(--bg);color:var(--text);font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1120px;margin:auto;padding:40px 20px 64px}.eyebrow{color:var(--accent);font-weight:800;font-size:13px;letter-spacing:.14em;text-transform:uppercase}h1{font-size:40px;line-height:1.1;margin:6px 0 8px}h2{font-size:20px;margin:30px 0 12px}.sub{color:var(--muted);margin:0 0 26px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}.card,.box{background:var(--panel);border:1px solid var(--line);border-radius:14px}.card{padding:18px}.card b{display:block;font-size:34px;line-height:1.1}.card span{color:var(--muted);font-size:13px}.box{padding:16px;overflow-x:auto}
.row{display:grid;grid-template-columns:minmax(230px,330px) 1fr 58px;gap:12px;align-items:center;min-width:760px;padding:4px 0}.name{font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.cells{display:flex;gap:3px}.cell{width:17px;height:17px;border-radius:4px;background:var(--skip)}.pass{background:var(--pass)}.flaky{background:var(--flaky)}.fail{background:var(--fail)}.rate{font:700 13px ui-monospace,monospace;text-align:right}
.legend{display:flex;gap:16px;color:var(--muted);font-size:13px;margin-top:12px;flex-wrap:wrap}.legend span{display:flex;gap:6px;align-items:center}.legend i{width:12px;height:12px;border-radius:3px;display:block}
.fix{padding:12px 0;border-top:1px solid var(--line)}.fix:first-child{border:0}.pill{font:700 11px ui-monospace,monospace;padding:2px 8px;border-radius:99px;background:#472d5f;margin-right:7px}.pill.broken{background:#7f1d3f}.small{color:var(--muted);font-size:13px}
.bar{display:grid;grid-template-columns:140px 1fr 30px;gap:10px;align-items:center;margin:7px 0;font-size:13px}.t{height:9px;background:var(--bg);border-radius:9px}.f{display:block;height:9px;border-radius:9px;background:linear-gradient(90deg,var(--flaky),var(--accent))}code{font:12px ui-monospace,monospace;overflow-wrap:anywhere;color:#fbcfe8}@media(max-width:640px){h1{font-size:31px}}
"""


def _row(test) -> str:
    cells = "".join(f'<span class="cell {outcome or ""}" title="{outcome or "not run"}"></span>' for outcome in test.outcomes)
    return f'<div class="row"><div class="name" title="{escape(test.test_id, quote=True)}">{escape(test.title)}</div><div class="cells">{cells}</div><div class="rate">{test.instability * 100:.0f}%</div></div>'


def render_html(analysis: dict, payload: dict, title: str = "Flake Radar") -> str:
    tests = analysis["tests"]
    flaky = [test for test in tests if test.classification == "flaky"]
    broken = [test for test in tests if test.classification == "broken"]
    wasted = sum(test.retry_waste_ms for test in tests) / 60000
    causes = Counter(test.root_cause or "unknown" for test in [*flaky, *broken])
    widest = max(causes.values(), default=1)
    cause_bars = "".join(
        f'<div class="bar"><span>{escape(name)}</span><span class="t"><span class="f" style="width:{count / widest * 100:.0f}%"></span></span><b>{count}</b></div>'
        for name, count in causes.most_common()
    ) or '<div class="small">No unstable tests found.</div>'
    actions = "".join(
        f'<div class="fix"><span class="pill {test.classification}">{test.classification.upper()}</span><b>{escape(test.title)}</b>'
        f'<div class="small">{escape(test.root_cause or "unknown")} · {escape(test.fix or "")}</div></div>'
        for test in [*broken, *flaky]
    ) or '<div class="small">Nothing to do.</div>'
    grep = f'<p class="small">Quarantine command:</p><code>npx playwright test --grep-invert "{escape(payload["grep_invert"])}"</code>' if payload["grep_invert"] else ""
    return (
        f'<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title><style>{STYLE}</style><main>'
        f'<div class="eyebrow">Test stability dashboard</div><h1>{escape(title)}</h1><p class="sub">{len(tests)} tests across {len(analysis["runs"])} CI runs, oldest to newest.</p>'
        f'<section class="cards"><div class="card"><b>{len(flaky)}</b><span>flaky tests</span></div><div class="card"><b>{len(broken)}</b><span>broken tests</span></div>'
        f'<div class="card"><b>{payload["count"]}</b><span>recommended for quarantine</span></div><div class="card"><b>{wasted:.1f}m</b><span>lost to failed retry attempts</span></div></section>'
        f'<h2>Stability heatmap</h2><div class="box">{"".join(_row(test) for test in tests)}<div class="legend"><span><i class="pass"></i>passed</span><span><i class="flaky"></i>passed on retry</span><span><i class="fail"></i>failed</span><span><i style="background:var(--skip)"></i>skipped or not run</span></div></div>'
        f'<h2>Likely root causes</h2><div class="box">{cause_bars}</div><h2>What to do next</h2><div class="box">{actions}{grep}</div></main></html>'
    )
