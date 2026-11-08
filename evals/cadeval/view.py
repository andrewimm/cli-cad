"""Self-contained HTML viewer for eval runs: renders, checks, metrics, feedback and scripts per attempt.

    python -m cadeval view ../eval-runs/hc-baseline ../eval-runs/hc-v4 --out viewer.html
"""

from __future__ import annotations

import base64
import html
import io
import json
from collections import Counter, defaultdict
from pathlib import Path

from .report import collect, summarize
from .tasks import EVALS, load_task

VIEW_ORDER = ["iso", "front", "top", "right", "iso_back", "iso_bottom"]


def _sheet(render_paths: list[str], tile=(350, 262), quality=74) -> str | None:
    """3x2 JPEG contact sheet of the grader's renders, as a data URI."""
    from PIL import Image, ImageDraw

    by_view = {}
    for p in render_paths:
        name = Path(p).stem
        for v in VIEW_ORDER:
            if name.endswith("_" + v):
                by_view[v] = p
    views = [v for v in VIEW_ORDER if v in by_view and Path(by_view[v]).exists()]
    if not views:
        return None
    cols, rows = 3, (len(views) + 2) // 3
    sheet = Image.new("RGB", (cols * tile[0], rows * tile[1]), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    for i, v in enumerate(views):
        im = Image.open(by_view[v]).convert("RGB")
        im.thumbnail(tile, Image.Resampling.LANCZOS)
        x, y = (i % cols) * tile[0], (i // cols) * tile[1]
        sheet.paste(im, (x + (tile[0] - im.width) // 2, y + (tile[1] - im.height) // 2))
        d.rectangle((x, y, x + tile[0] - 1, y + tile[1] - 1), outline=(214, 218, 224))
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=quality, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _check_detail(c: dict) -> str:
    """One-line explanation of a failed check."""
    t = c["type"]
    if c.get("error"):
        return c["error"]
    if t == "min_thickness":
        parts = []
        for n, v in (c.get("actual") or {}).items():
            th = (v.get("thinnest") or [{}])[0]
            parts.append(f"{n}: {v.get('value')} mm (thinnest {th.get('thickness')} at {th.get('point')})")
        return f"needs ≥ {c['expected']['min']} mm — " + "; ".join(parts)
    if t == "holes":
        bits = []
        if c.get("missing"):
            bits.append(f"missing at {c['missing']}")
        if c.get("blocked"):
            bits.append(f"screw access blocked at {[b['position'] for b in c['blocked']]}")
        return "; ".join(bits) or f"found {len(c.get('found', []))} matching holes"
    if t in ("points_inside", "points_outside"):
        return "; ".join(f"{f['point']} is {f['state']}" for f in c.get("failures", [])[:4])
    if t == "keepout":
        return "; ".join(f"{h['part']} enters {h['zone']} ({h['volume']} mm³)" for h in c.get("intrusions", [])[:4])
    if t in ("param_rebuild", "param_sweep"):
        fs = c.get("failures", [])
        return "; ".join(f"{f.get('overrides')}: {f.get('type', 'build')} failed" for f in fs[:4])
    if t == "file":
        return f"exists={c.get('exists')}, chars={c.get('chars')}, missing mentions {c.get('missing_mentions')}"
    if "actual" in c and "expected" in c:
        return f"actual {json.dumps(c['actual'], default=str)[:160]} vs expected {json.dumps(c['expected'], default=str)[:160]}"
    return json.dumps({k: v for k, v in c.items() if k not in ("type", "ok")}, default=str)[:240]


def _esc(s) -> str:
    return html.escape(str(s), quote=True)


def build(run_dirs: list[Path], out: Path, title: str = "Eval Run Viewer") -> Path:
    runs = []
    for rd in run_dirs:
        rd = Path(rd)
        meta = json.loads((rd / "run.json").read_text()) if (rd / "run.json").exists() else {}
        runs.append({"dir": rd, "label": meta.get("label") or rd.name, "git": meta.get("git", "?"),
                     "rows": collect(rd), "summary": summarize(rd)})
    tasks = sorted({r["task"] for run in runs for r in run["rows"]})
    task_meta = {}
    for t in tasks:
        p = EVALS / "tasks" / f"{t}.toml"
        task_meta[t] = load_task(p) if p.exists() else None

    # ---------------------------------------------------------------- summary
    sum_rows = []
    for run in runs:
        o = run["summary"]["overall"]
        sum_rows.append(
            f"<tr><th scope='row'><span class='run-tag'>{_esc(run['label'])}</span> <span class='mono dim'>{_esc(run['git'])}</span></th>"
            f"<td class='num'>{o['attempts']}</td>"
            f"<td class='num'><b>{round((o['pass_rate'] or 0) * 100)}%</b></td>"
            f"<td class='num'>{o['overclaimed']}</td>"
            f"<td class='num'>{o['mean_cad_calls']}</td><td class='num'>{o['mean_turns']}</td>"
            f"<td class='num'>${o['total_cost_usd']}</td></tr>")
    grid_head = "".join(f"<th scope='col'>{_esc(run['label'])}</th>" for run in runs)
    grid_rows = []
    for t in tasks:
        tm = task_meta[t]
        split = tm.split if tm else ""
        cells = []
        for run in runs:
            rs = [r for r in run["rows"] if r["task"] == t]
            if not rs:
                cells.append("<td class='cell none'>—</td>")
                continue
            k = sum(1 for r in rs if r["grade"]["passed"])
            cls = "all" if k == len(rs) else ("none-pass" if k == 0 else "some")
            cells.append(f"<td class='cell {cls}'><a href='#task-{_esc(t)}'>{k}/{len(rs)}</a></td>")
        grid_rows.append(f"<tr><th scope='row'><a href='#task-{_esc(t)}'>{_esc(t)}</a>"
                         f"{' <span class=chip-split>held out</span>' if split == 'heldout' else ''}</th>{''.join(cells)}</tr>")

    # ---------------------------------------------------------------- attempts
    sections = []
    for t in tasks:
        tm = task_meta[t]
        cards = []
        for run in runs:
            for r in sorted((r for r in run["rows"] if r["task"] == t), key=lambda r: r["attempt"]):
                g, m, fb = r["grade"], r["metrics"], r["feedback"] or {}
                passed = g["passed"]
                claimed = fb.get("success")
                ws = run["dir"] / t / r["attempt"] / "workspace"
                img = _sheet(g.get("renders", []))
                vis = ((r.get("visual") or {}).get("verdict") or {}).get("overall_match")
                checks_html = []
                for c in g.get("checks", []):
                    label = c["type"] + (f" · {c['part']}" if c.get("part") else "")
                    note = f"<span class='dim'> — {_esc(c['note'])}</span>" if c.get("note") else ""
                    if c["ok"]:
                        checks_html.append(f"<li class='ok'><span class='mark' aria-hidden='true'>✓</span>{_esc(label)}{note}</li>")
                    else:
                        checks_html.append(f"<li class='bad'><span class='mark' aria-hidden='true'>✗</span>{_esc(label)}{note}"
                                           f"<div class='detail mono'>{_esc(_check_detail(c))}</div></li>")
                if not g.get("built"):
                    err = g.get("error") or {}
                    checks_html.append(f"<li class='bad'><span class='mark'>✗</span>build failed<div class='detail mono'>"
                                       f"{_esc(err.get('code'))}: {_esc(err.get('message'))}</div></li>")
                cmds = Counter(m.get("cad_commands") or {})
                cmd_html = " ".join(f"<span class='cmd'>{_esc(k)}<b>{v}</b></span>" for k, v in cmds.most_common())
                issues = fb.get("issues") or []
                issues_html = "".join(
                    f"<li><span class='sev sev-{_esc(i.get('severity', 'low'))}'>{_esc(i.get('severity', ''))}</span> "
                    f"<span class='dim'>{_esc(i.get('category', ''))}</span> {_esc(i.get('description', ''))}</li>" for i in issues)
                script = ""
                try:
                    import tomllib

                    entry = tomllib.loads((ws / "cad.toml").read_text()).get("project", {}).get("entry", "model.py") \
                        if (ws / "cad.toml").exists() else "model.py"
                    script = (ws / entry).read_text()
                except Exception:
                    pass
                status = "pass" if passed else "fail"
                claim = ""
                if claimed is not None:
                    claim = ("<span class='claim over'>claimed success</span>" if claimed and not passed
                             else "<span class='claim'>claimed success</span>" if claimed else "<span class='claim'>reported failure</span>")
                cards.append(f"""
<article class="card {status}" data-run="{_esc(run['label'])}" data-status="{status}">
  <header class="card-head">
    <span class="status {status}">{'PASS' if passed else 'FAIL'}</span>
    <span class="run-tag">{_esc(run['label'])}</span>
    <span class="mono dim">{_esc(r['attempt'])}</span>
    {claim}
  </header>
  {f'<button class="shot" type="button" data-src="{img}" aria-label="Enlarge renders of {_esc(t)} {_esc(run["label"])} {_esc(r["attempt"])}"><img src="{img}" alt="Grader renders: iso, front, top, right, iso back, iso bottom" loading="lazy"></button>' if img else '<div class="noshot">no renders</div>'}
  <dl class="metrics">
    <div><dt>cad calls</dt><dd>{m.get('cad_calls', '—')}</dd></div>
    <div><dt>builds</dt><dd>{m.get('builds', '—')}<span class="dim"> ({m.get('failed_builds', 0)} failed)</span></dd></div>
    <div><dt>turns</dt><dd>{m.get('turns', '—')}</dd></div>
    <div><dt>cost</dt><dd>${round(m.get('cost_usd') or 0, 3)}</dd></div>
    <div><dt>vision</dt><dd>{vis if vis is not None else '—'}<span class="dim">/5</span></dd></div>
  </dl>
  <div class="cmds">{cmd_html}</div>
  <details {'open' if not passed else ''}><summary>Checks <span class="dim">{sum(1 for c in g.get('checks', []) if c['ok'])}/{len(g.get('checks', []))}</span></summary><ul class="checks">{''.join(checks_html)}</ul></details>
  <details><summary>Agent feedback <span class="dim">{len(issues)} issue(s)</span></summary><ul class="issues">{issues_html or '<li class="dim">none</li>'}</ul></details>
  <details><summary>Model script</summary><pre class="code">{_esc(script) or 'not found'}</pre></details>
</article>""")
        brief = _esc(tm.prompt) if tm else ""
        sections.append(f"""
<section class="task" id="task-{_esc(t)}">
  <div class="task-head">
    <h2>{_esc(t)}</h2>
    <span class="dim">{_esc(tm.title if tm else '')}</span>
    {'<span class="chip-split">held out</span>' if tm and tm.split == 'heldout' else ''}
  </div>
  <details class="brief"><summary>Design brief given to the agent</summary><pre class="brief-text">{brief}</pre></details>
  <div class="cards">{''.join(cards)}</div>
</section>""")

    run_buttons = "".join(f"<label><input type='checkbox' class='run-filter' value='{_esc(run['label'])}' checked> {_esc(run['label'])}</label>"
                          for run in runs)
    page = TEMPLATE.replace("{{TITLE}}", _esc(title)).replace("{{SUMMARY}}", "".join(sum_rows)) \
        .replace("{{GRID_HEAD}}", grid_head).replace("{{GRID}}", "".join(grid_rows)) \
        .replace("{{RUN_FILTERS}}", run_buttons).replace("{{SECTIONS}}", "".join(sections)) \
        .replace("{{RUN_COUNT}}", str(len(runs))).replace("{{ATTEMPTS}}", str(sum(len(r["rows"]) for r in runs)))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)
    return out


TEMPLATE = r"""<title>{{TITLE}}</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Layout: summary first (runs table + task x run grid), then one band per task with a responsive grid of attempt cards. */
:root {
  --paper: #f4f6f8;
  --surface: #ffffff;
  --ink: #18212b;
  --muted: #5d6b7a;
  --line: #d6dce3;
  --steel: #3f6b98;
  --pass: #2f7d4f;
  --pass-bg: #e3f2e8;
  --fail: #b3382e;
  --fail-bg: #fbe7e4;
  --warn: #9a6a12;
  --warn-bg: #fbf0d9;
  --code-bg: #eef1f5;
  --display: "Archivo", "Helvetica Neue", Arial, sans-serif;
  --body: "IBM Plex Sans", "Helvetica Neue", Arial, sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --paper: #12171d; --surface: #1a2129; --ink: #e4e9ef; --muted: #93a1b0; --line: #2c3743;
    --steel: #8fb4dd; --pass: #6cc792; --pass-bg: #18301f; --fail: #f08a7f; --fail-bg: #3a1f1c;
    --warn: #e2b55c; --warn-bg: #352a14; --code-bg: #141a20;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --paper: #12171d; --surface: #1a2129; --ink: #e4e9ef; --muted: #93a1b0; --line: #2c3743;
  --steel: #8fb4dd; --pass: #6cc792; --pass-bg: #18301f; --fail: #f08a7f; --fail-bg: #3a1f1c;
  --warn: #e2b55c; --warn-bg: #352a14; --code-bg: #141a20;
}
* { box-sizing: border-box; }
body {
  background: var(--paper); color: var(--ink); font: 15px/1.5 var(--body);
  padding-block: 28px 64px;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px));
}
.wrap { max-width: 1320px; margin: 0 auto; display: grid; gap: 36px; }
h1, h2 { font-family: var(--display); letter-spacing: 0.01em; text-wrap: balance; margin: 0; }
h1 { font-size: 30px; }
h2 { font-size: 21px; }
.lede { color: var(--muted); max-width: 72ch; margin: 6px 0 0; }
.mono { font-family: var(--mono); font-size: 12.5px; }
.dim { color: var(--muted); }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.eyebrow { font: 600 11px/1 var(--body); text-transform: uppercase; letter-spacing: 0.09em; color: var(--muted); margin: 0 0 10px; }
.summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 460px), 1fr)); gap: 28px; align-items: start; }
.table-scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
th, td { padding: 7px 10px; border-bottom: 1px solid var(--line); text-align: left; white-space: nowrap; }
thead th { font: 600 11px/1.2 var(--body); text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); }
.cell { text-align: center; font-family: var(--mono); }
.cell a { color: inherit; text-decoration: none; display: block; }
.cell.all { background: var(--pass-bg); color: var(--pass); }
.cell.some { background: var(--warn-bg); color: var(--warn); }
.cell.none-pass { background: var(--fail-bg); color: var(--fail); font-weight: 600; }
.cell.none { color: var(--muted); }
th a { color: var(--ink); text-decoration: none; }
th a:hover, .cell a:hover { text-decoration: underline; }
.run-tag { font: 500 12px/1 var(--mono); background: var(--code-bg); border: 1px solid var(--line); border-radius: 4px; padding: 3px 6px; }
.chip-split { font: 600 10px/1 var(--body); text-transform: uppercase; letter-spacing: 0.08em; color: var(--steel); border: 1px solid currentColor; border-radius: 99px; padding: 3px 7px; vertical-align: middle; }
.filters { display: flex; flex-wrap: wrap; gap: 8px 18px; align-items: center; padding: 12px 14px; background: var(--surface); border: 1px solid var(--line); border-radius: 8px; position: sticky; top: env(safe-area-inset-top, 0px); z-index: 5; }
.filters label { display: inline-flex; gap: 6px; align-items: center; cursor: pointer; }
.filters input:focus-visible, button:focus-visible, summary:focus-visible { outline: 2px solid var(--steel); outline-offset: 2px; }
.task { display: grid; gap: 12px; scroll-margin-top: 80px; }
.task-head { display: flex; flex-wrap: wrap; gap: 10px; align-items: baseline; border-bottom: 2px solid var(--ink); padding-bottom: 6px; }
.brief summary, details summary { cursor: pointer; color: var(--muted); font-size: 13.5px; }
.brief-text { white-space: pre-wrap; font: 13.5px/1.55 var(--body); max-width: 90ch; background: var(--surface); border: 1px solid var(--line); border-radius: 6px; padding: 12px 14px; margin: 8px 0 0; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 380px), 1fr)); gap: 16px; align-items: start; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 12px; display: grid; gap: 10px; border-top: 4px solid var(--pass); }
.card.fail { border-top-color: var(--fail); }
.card-head { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.status { font: 700 12px/1 var(--display); letter-spacing: 0.08em; padding: 4px 7px; border-radius: 4px; }
.status.pass { background: var(--pass-bg); color: var(--pass); }
.status.fail { background: var(--fail-bg); color: var(--fail); }
.claim { font-size: 12px; color: var(--muted); margin-left: auto; }
.claim.over { color: var(--fail); font-weight: 600; }
.claim.over::before { content: "⚠ "; }
.shot { padding: 0; border: 1px solid var(--line); border-radius: 4px; background: #fff; cursor: zoom-in; display: block; width: 100%; }
.shot img { display: block; width: 100%; height: auto; border-radius: 3px; }
.noshot { color: var(--muted); font-size: 13px; padding: 30px; text-align: center; border: 1px dashed var(--line); border-radius: 4px; }
.metrics { display: grid; grid-template-columns: repeat(5, 1fr); gap: 4px; margin: 0; }
.metrics div { display: grid; gap: 1px; }
.metrics dt { font: 600 10px/1.2 var(--body); text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); }
.metrics dd { margin: 0; font: 500 14px/1.3 var(--mono); font-variant-numeric: tabular-nums; }
.cmds { display: flex; flex-wrap: wrap; gap: 5px; }
.cmd { font: 12px/1 var(--mono); background: var(--code-bg); border-radius: 3px; padding: 3px 5px; display: inline-flex; gap: 4px; }
.cmd b { color: var(--steel); font-weight: 500; }
.checks, .issues { list-style: none; margin: 8px 0 0; padding: 0; display: grid; gap: 4px; font-size: 13.5px; }
.checks li { padding-left: 20px; position: relative; }
.checks .mark { position: absolute; left: 2px; font-weight: 700; }
.checks .ok .mark { color: var(--pass); }
.checks .bad { color: var(--fail); }
.checks .bad .mark { color: var(--fail); }
.detail { color: var(--ink); background: var(--fail-bg); border-radius: 3px; padding: 4px 6px; margin-top: 3px; overflow-wrap: anywhere; }
.issues li { line-height: 1.45; }
.sev { font: 600 10px/1 var(--body); text-transform: uppercase; letter-spacing: 0.06em; padding: 2px 5px; border-radius: 3px; background: var(--code-bg); }
.sev-medium { background: var(--warn-bg); color: var(--warn); }
.sev-high { background: var(--fail-bg); color: var(--fail); }
.code { background: var(--code-bg); border-radius: 4px; padding: 10px; font: 12px/1.5 var(--mono); overflow-x: auto; max-height: 420px; margin: 8px 0 0; }
dialog { border: none; border-radius: 8px; padding: 0; max-width: min(1100px, 96vw); background: var(--surface); }
dialog::backdrop { background: rgba(10, 14, 18, 0.72); }
dialog img { display: block; width: 100%; height: auto; }
dialog button { position: absolute; top: 8px; right: 8px; font: 600 13px var(--body); background: var(--surface); color: var(--ink); border: 1px solid var(--line); border-radius: 4px; padding: 5px 9px; cursor: pointer; }
.hidden-by-filter { display: none; }
@media (max-width: 520px) { .metrics { grid-template-columns: repeat(3, 1fr); } }
@media (prefers-reduced-motion: no-preference) { html { scroll-behavior: smooth; } }
</style>

<div class="wrap">
  <header>
    <p class="eyebrow">cadeval · independent-agent runs</p>
    <h1>{{TITLE}}</h1>
    <p class="lede">{{ATTEMPTS}} attempts across {{RUN_COUNT}} runs. Each card shows what the agent built (the grader's own renders of the rebuilt model), whether it passed the hidden checks, what it claimed, how much work it took, and its feedback. Click a render to enlarge it.</p>
  </header>

  <div class="summary">
    <div>
      <p class="eyebrow">Runs</p>
      <div class="table-scroll"><table>
        <thead><tr><th scope="col">run</th><th scope="col" class="num">attempts</th><th scope="col" class="num">pass</th><th scope="col" class="num">over-claimed</th><th scope="col" class="num">cad calls</th><th scope="col" class="num">turns</th><th scope="col" class="num">cost</th></tr></thead>
        <tbody>{{SUMMARY}}</tbody>
      </table></div>
    </div>
    <div>
      <p class="eyebrow">Passed attempts per task</p>
      <div class="table-scroll"><table>
        <thead><tr><th scope="col">task</th>{{GRID_HEAD}}</tr></thead>
        <tbody>{{GRID}}</tbody>
      </table></div>
    </div>
  </div>

  <div class="filters" role="group" aria-label="Filter attempts">
    <span class="eyebrow" style="margin:0">Show</span>
    {{RUN_FILTERS}}
    <label><input type="checkbox" id="only-fail"> failures only</label>
  </div>

  {{SECTIONS}}
</div>

<dialog id="zoom"><button type="button" id="zoom-close">Close</button><img id="zoom-img" alt="Enlarged renders"></dialog>

<script>
(function () {
  var dlg = document.getElementById("zoom"), img = document.getElementById("zoom-img");
  document.querySelectorAll(".shot").forEach(function (b) {
    b.addEventListener("click", function () { img.src = b.dataset.src; dlg.showModal(); });
  });
  document.getElementById("zoom-close").addEventListener("click", function () { dlg.close(); });
  dlg.addEventListener("click", function (e) { if (e.target === dlg) dlg.close(); });
  function apply() {
    var runs = Array.prototype.filter.call(document.querySelectorAll(".run-filter"), function (c) { return c.checked; })
      .map(function (c) { return c.value; });
    var onlyFail = document.getElementById("only-fail").checked;
    document.querySelectorAll(".card").forEach(function (c) {
      var show = runs.indexOf(c.dataset.run) >= 0 && (!onlyFail || c.dataset.status === "fail");
      c.classList.toggle("hidden-by-filter", !show);
    });
    document.querySelectorAll(".task").forEach(function (t) {
      t.classList.toggle("hidden-by-filter", !t.querySelector(".card:not(.hidden-by-filter)"));
    });
  }
  document.querySelectorAll(".run-filter, #only-fail").forEach(function (c) { c.addEventListener("change", apply); });
})();
</script>
"""
