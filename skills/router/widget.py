"""HTML for the /router widgets, printed to stdout for Claude's show_widget tool.

    python3 widget.py form [--cwd DIR] [--task TEXT]   # the form /router opens
    python3 widget.py card [--why TEXT ...]            # the answer card for the last route-log.jsonl entry

Uses only the host's CSS variables, so both widgets follow light and dark mode.
"""
import argparse
import html
import json
import os
import subprocess
from pathlib import Path

LOG = Path.home() / "jev" / "route-log.jsonl"

# Plain names for the ORCHESTRATION.md rows.
ROW_TITLES = {
    1: "One agent, steps in order",
    2: "Scout agents search for you",
    3: "A lead agent with helpers",
    4: "An agent team that talks",
    5: "Parallel worktrees, one per ticket",
    6: "Two attempts, then a judge",
    7: "Claude plans, Codex reviews",
    8: "Codex reviews the finished diff",
    9: "Codex rescues a stuck fix",
    10: "Hermes, the open-source agent",
    11: "Agents inside your product",
}

STYLE = """<style>
.pane{background:var(--surface-2);border:0.5px solid var(--border);border-radius:12px;padding:1.25rem 1.25rem 1rem}
.lbl{font-size:13px;color:var(--text-secondary);margin:0 0 6px;display:block}
.chip{display:inline-flex;align-items:center;gap:6px;font-size:13px;padding:6px 12px;border:0.5px solid var(--border-strong);border-radius:var(--radius);cursor:pointer;color:var(--text-primary);background:transparent}
.chip.on{border:1.5px solid var(--border-accent);background:var(--bg-accent);color:var(--text-accent)}
.seg{display:inline-flex;border:0.5px solid var(--border-strong);border-radius:var(--radius);overflow:hidden}
.seg span{font-size:13px;padding:6px 12px;display:inline-flex;align-items:center;gap:6px}
.seg .on{background:var(--bg-accent);color:var(--text-accent)}
.go{background:var(--fill-accent);color:var(--on-accent);border:none;padding:0 18px;height:38px;border-radius:var(--radius);font-size:14px;cursor:pointer}
.step{font-size:12px;padding:4px 10px;border-radius:var(--radius);display:inline-flex;align-items:center;gap:5px}
.stat{background:var(--surface-1);border-radius:var(--radius);padding:10px 12px}
.stat p{margin:0}
</style>"""

HEADER = """<div style="display:flex;align-items:center;gap:10px;margin-bottom:1.1rem">
<div style="width:34px;height:34px;border-radius:var(--radius);background:var(--bg-accent);color:var(--text-accent);display:flex;align-items:center;justify-content:center"><i class="ti ti-route" style="font-size:19px" aria-hidden="true"></i></div>
<div style="flex:1"><p style="margin:0;font-size:15px;font-weight:500">Task router</p><p style="margin:0;font-size:13px;color:var(--text-secondary)">Picks the setup, models and effort for you</p></div>
<span style="font-size:12px;padding:4px 10px;border-radius:var(--radius);background:var(--bg-success);color:var(--text-success)">$0</span>
</div>"""


def tilde(path: str) -> str:
    home = str(Path.home())
    return "~" + path[len(home):] if path.startswith(home) else path


def is_repo(path: str) -> bool:
    return subprocess.run(["git", "-C", path, "rev-parse", "--is-inside-work-tree"],
                          capture_output=True).returncode == 0


def recent_repos(cwd: str | None) -> list[str]:
    """The current repo first, then repos from the log, newest first; at most four."""
    repos = []
    if cwd and is_repo(cwd):
        top = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True).stdout.strip()
        repos.append(top or cwd)
    if LOG.exists():
        for line in reversed(LOG.read_text().splitlines()):
            repo = json.loads(line).get("repo")
            if repo and repo not in repos and os.path.isdir(repo):
                repos.append(repo)
    return repos[:4]


def form(cwd: str | None, task: str) -> str:
    repos = recent_repos(cwd)
    chips = "".join(
        f'<button class="chip{" on" if i == 0 else ""}" data-p="{html.escape(tilde(r))}" onclick="pick(this)">'
        f'<i class="ti ti-folder" aria-hidden="true"></i>{html.escape(Path(r).name)}</button>'
        for i, r in enumerate(repos))
    chips += ('<button class="chip" data-p="" onclick="pick(this)">'
              '<i class="ti ti-plus" aria-hidden="true"></i>Other folder</button>')
    first = html.escape(tilde(repos[0])) if repos else ""
    return f"""<h2 class="sr-only">Task router form: describe a task, pick a project, and find the best setup.</h2>
{STYLE}
<div class="pane">
{HEADER}
<label class="lbl" for="task">What do you want done?</label>
<textarea id="task" rows="3" style="width:100%;box-sizing:border-box;resize:vertical;font-size:14px" placeholder="Add a CSV export command for the reports page" oninput="clr()">{html.escape(task)}</textarea>
<div style="margin-top:12px">
<span class="lbl">Project</span>
<div style="display:flex;gap:8px;flex-wrap:wrap" id="repos">{chips}</div>
<p id="path" style="font-size:12px;color:var(--text-muted);margin:6px 0 0;font-family:var(--font-mono)">{first}</p>
<input id="other" type="text" placeholder="~/projects/my-app" style="width:100%;box-sizing:border-box;margin-top:6px;font-family:var(--font-mono);font-size:13px" oninput="clr()" hidden>
</div>
<div style="display:flex;gap:24px;flex-wrap:wrap;margin-top:14px">
<div><span class="lbl">Who decides</span>
<div class="seg"><span class="on"><i class="ti ti-users" aria-hidden="true"></i>Free jury</span><span style="color:var(--text-muted)" title="Paid, turned off"><i class="ti ti-lock" aria-hidden="true"></i>JEV, paid</span></div></div>
<div><span class="lbl">Shortcut</span>
<label style="display:flex;align-items:center;gap:8px;font-size:13px;height:32px"><input id="rules" type="checkbox" checked> Decide easy tasks instantly</label></div>
</div>
<p id="err" style="font-size:13px;color:var(--text-danger);margin:10px 0 0"></p>
<div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-top:0.6rem;padding-top:1rem;border-top:0.5px solid var(--border)">
<button class="go" onclick="go()">Find the best setup ↗</button>
<p style="margin:0;font-size:12px;color:var(--text-muted)">1 second to 3 minutes. Your project isn't changed.</p>
</div>
</div>
<script>
function clr(){{document.getElementById('err').textContent='';}}
function pick(b){{document.querySelectorAll('#repos .chip').forEach(c=>c.classList.remove('on'));b.classList.add('on');
const o=!b.dataset.p;document.getElementById('other').hidden=!o;document.getElementById('path').textContent=b.dataset.p;clr();}}
function go(){{const t=document.getElementById('task').value.trim();const b=document.querySelector('#repos .chip.on');
const p=b.dataset.p||document.getElementById('other').value.trim();const e=document.getElementById('err');
if(!t){{e.textContent='Describe the task first';return;}}if(!p){{e.textContent='Enter the project folder';return;}}
sendPrompt('Route this task in '+p+': '+t+(document.getElementById('rules').checked?'':' (always ask the jury)'));}}
</script>"""


def step(icon: str, text: str, tone: str) -> str:
    colors = {"done": "background:var(--bg-success);color:var(--text-success)",
              "warn": "background:var(--bg-warning);color:var(--text-warning)",
              "off": "background:var(--surface-1);color:var(--text-secondary)"}[tone]
    return f'<span class="step" style="{colors}"><i class="ti ti-{icon}" aria-hidden="true"></i>{text}</span>'


def stages(entry: dict, decided: str) -> str:
    rules = entry.get("rules") or ""
    out = [step("check", "Rules decided", "done") if decided == "rules"
           else step("bolt", "Rules: skipped" if rules.startswith("skipped") else "Rules: no clear match", "off")]
    if decided != "rules":
        judge = "JEV" if entry.get("judge") == "jev" else "Jury"
        if decided in ("jury", "jev"):
            out.append(step("check", f"{judge} decided", "done"))
        else:
            out.append(step("users", f"{judge}: unsure" if isinstance(entry.get(entry.get("judge", "jury")), dict) else f"{judge}: no answer", "warn"))
            if decided == "scout":
                out.append(step("check", "Scout decided", "done"))
            else:
                out.append(step("search", "Scout: unsure" if isinstance(entry.get("scout"), dict) else "Scout: no answer", "warn"))
                out.append(step("hand-stop", "You choose", "warn"))
    arrow = '<i class="ti ti-chevron-right" style="color:var(--text-muted);font-size:14px" aria-hidden="true"></i>'
    return arrow.join(out)


def took(seconds) -> str:
    s = round(float(seconds or 0))
    return f"{s // 60} min {s % 60} s" if s >= 60 else f"{max(s, 1)} s"


def card(why: list[str]) -> str:
    entry = json.loads(LOG.read_text().splitlines()[-1])
    r = entry["result"]
    decided = r.get("decided_by", "")
    row = r.get("pattern_row")
    title = ROW_TITLES.get(row, r.get("pattern", "")) if decided != "human" else f"Not sure. Best guess: {ROW_TITLES.get(row, r.get('pattern', '')).lower()}"
    efforts = r.get("effort", {})
    stats = "".join(
        f'<div class="stat"><p style="font-size:12px;color:var(--text-secondary)">{html.escape(role.capitalize())}</p>'
        f'<p style="font-size:16px;font-weight:500">{html.escape(model.capitalize())}, {html.escape(efforts.get(role, "medium"))}</p></div>'
        for role, model in r.get("models", {}).items())
    conf = round(float(r.get("confidence") or 0) * 100)
    stats += (f'<div class="stat"><p style="font-size:12px;color:var(--text-secondary)">Confidence</p>'
              f'<p style="font-size:16px;font-weight:500">{conf}%</p><div style="height:4px;background:var(--border);border-radius:2px;margin-top:6px">'
              f'<div style="width:{conf}%;height:4px;background:var(--fill-accent);border-radius:2px"></div></div></div>'
              f'<div class="stat"><p style="font-size:12px;color:var(--text-secondary)">Took</p>'
              f'<p style="font-size:16px;font-weight:500">{took(entry.get("seconds"))}</p></div>')
    why_html = "".join(f"<li>{html.escape(w)}</li>" for w in why) or "".join(
        f"<li>{html.escape(w)}</li>" for w in r.get("reasons", [])[:3])
    task = entry.get("task", "")
    js_task = json.dumps(task)
    start = ("Start it ↗", f"sendPrompt('Start the row {row} setup for: '+{js_task})")
    if decided == "human":
        start = ("Use this setup ↗", f"sendPrompt('Use the row {row} setup for: '+{js_task})")
    return f"""<h2 class="sr-only">Task router answer: {html.escape(title)}.</h2>
{STYLE}
<div class="pane">
<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:14px">{stages(entry, decided)}</div>
<p style="margin:0;font-size:13px;color:var(--text-secondary)">{html.escape(task)} <span style="color:var(--text-muted);font-family:var(--font-mono);font-size:12px">· {html.escape(tilde(entry.get("repo", "")))}</span></p>
<p style="margin:2px 0 12px;font-size:20px;font-weight:500">{html.escape(title)}</p>
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px">{stats}</div>
<p style="font-size:13px;color:var(--text-secondary);margin:14px 0 4px">Why</p>
<ul style="margin:0;padding-left:18px;font-size:14px;line-height:1.7">{why_html}</ul>
<div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:1rem;padding-top:1rem;border-top:0.5px solid var(--border)">
<button class="go" onclick="{html.escape(start[1])}">{start[0]}</button>
<button onclick="{html.escape(f"sendPrompt('Show me the other setups I could pick for: '+{js_task})")}">Pick another setup ↗</button>
<button onclick="{html.escape(f"sendPrompt('Show the votes behind the router answer for: '+{js_task})")}">See the votes ↗</button>
</div>
</div>"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("form")
    f.add_argument("--cwd")
    f.add_argument("--task", default="")
    c = sub.add_parser("card")
    c.add_argument("--why", action="append", default=[])
    args = ap.parse_args()
    print(form(args.cwd, args.task) if args.cmd == "form" else card(args.why))


if __name__ == "__main__":
    main()
