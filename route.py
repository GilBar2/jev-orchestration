"""Task router: pick the orchestration pattern, the model per role and the effort per role for a coding task.

Usage:
    python3 ~/jev/route.py <repo> "<task>"
    python3 ~/jev/route.py <repo> "<task>" --judge jev   # paid JEV instead (needs TYPESAFE_API_KEY)

Stage 1 collects repo facts without any LLM (likely touched files from task keywords, git grep and
git log -S, their size, whether they import each other, the tests covering them, repo size, risk
flags). If the facts are clear-cut (rule_route: risk flag → row 7, one item in 1-2 files → row 1,
separate items on separate files → row 5), the rules decide with no LLM; --no-rules skips this.
Otherwise it asks three multiple-choice questions about them (pattern row of ORCHESTRATION.md, main
model, effort). The default judge is the $0 jury in jury.py (Claude + Codex + a free Nous model,
majority vote per question); --judge jev sends them to JEV's system_one instead. If every
confidence is >= 0.7, that answer stands.
Stage 2, when any stage-1 confidence is below 0.7 (or the judge fails): the read-only scout agent (Haiku,
~/.claude/agents/scout.md) explores the repo and answers the same three questions. If only its
effort answer is below 0.7, effort defaults to medium (logged). Otherwise, below 0.7 means ASK A HUMAN.

Read-only: only git grep, git log and git ls-files run in the target repo, and the scout runs with
no edit tools and an allow-list of read-only shell commands.

Prints the decision as JSON on stdout (pattern_row, pattern, models, effort, confidence, decided_by,
reasons) and a trace plus the verdict line on stderr. Appends every decision to ~/jev/route-log.jsonl.
Exit code 0 when routed, 2 on ASK A HUMAN.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENV_PYTHON = HERE / ".venv" / "bin" / "python"
RULES_FILE = HERE / "ORCHESTRATION.md"
LOG_FILE = HERE / "route-log.jsonl"
SCOUT_FILE = Path.home() / ".claude" / "agents" / "scout.md"

MIN_CONFIDENCE = 0.7
DEFAULT_EFFORT = "medium"  # used when only the effort answer is below MIN_CONFIDENCE
GIT_ENV = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}

QUESTIONS = ("pattern", "models", "effort")
MODELS = {
    "haiku": "Claude Haiku, cheapest: only read-only work (search, where-is-X-used, digesting a log) "
             "or a one-line edit that the task spells out exactly.",
    "sonnet": "Claude Sonnet, the default: any ordinary code change, bug or feature in 1-5 files with no "
              "risk flags, including each ticket of a multi-ticket job.",
    "opus": "Claude Opus, most expensive: risk flags (auth, payments, migrations, data, secrets), a new "
            "subsystem, a refactor across more than 5 coupled files, or leading an agent team.",
    "codex": "OpenAI Codex: only when the task asks for Codex or a non-Claude implementer, or the task is a "
             "finished diff to review or Claude being stuck (the row then assigns Codex itself).",
    "hermes": "Hermes Agent: only when the task asks for Hermes, an open-source agent or a third opinion.",
}
MODELS_QUESTION = ("Which model should do the main work: the single agent, the lead, the implementer or "
                   "the planner? Apply the first description that matches the task and the repo facts.")
EFFORT = {
    "low": "The task names the exact change and where it goes, at most 2 files, and no risk flags.",
    "medium": "The default: the cause or design must be worked out, but in 1-5 files with no risk flags.",
    "high": "Any risk flag, a new subsystem, more than 5 files, or files that import each other.",
}
EFFORT_QUESTION = ("How much reasoning effort should the main model spend? Apply the first description that "
                   "matches the task and the repo facts.")

# Roles per ORCHESTRATION.md row: role -> (model rule, effort rule). "main" takes the routed model or
# effort; "claude" keeps a Claude model (Claude-only tools); "planner" keeps Sonnet or Opus;
# "other" picks a second vendor so the two attempts differ. Row 6's judge is jury.py, not a model.
ROLES = {
    1: {"agent": ("main", "main")},
    2: {"lead": ("claude", "main"), "scout": ("haiku", "low")},
    3: {"lead": ("claude", "main"), "scout": ("haiku", "low"), "fixer": ("sonnet", "main")},
    4: {"lead": ("claude", "main"), "teammates": ("sonnet", "main")},
    5: {"worker": ("main", "main")},
    6: {"worker_a": ("main", "main"), "worker_b": ("other", "main")},
    7: {"planner": ("planner", "main"), "reviewer": ("codex", "main")},
    8: {"reviewer": ("codex", "main")},
    9: {"rescuer": ("codex", "main")},
    10: {"lead": ("hermes", "main")},
    11: {"agent": ("main", "main")},
}

STOP = set("""
about above after again all also and any are because been before being below between both but can
cannot change changes code correct correctly currently does doing done each else every feature file
files first fix fixed fixes fixing from function functions handle have here instead into issue issues
item items its just make makes more most must need needs new not only other please really same should
some still such than that the their them then there these they this those ticket tickets two three
under until update use used uses using want when where which while will with without work works would
wrong your separate independent risky change task tasks bug bugs error errors test tests add adds
return returns true false null none check checks give gives call calls called getting gets
""".split())
NOISE_PATH = re.compile(r"\.(md|markdown|rst|txt|adoc)$|(^|/)(docs?/|LICENSE|CHANGELOG)|"
                        r"(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|Cargo\.lock|go\.sum)$")
TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|specs?)/|(^|/)test_[^/]+$|_test\.\w+$|\.(test|spec)\.\w+$")
IMPORT_LINE = re.compile(r"^\s*(from\s+\S+\s+import|import\s|export\s.*\sfrom\s|#include|use\s)|require\(")
DEF_LINE = "(def|class|function|func|fn|interface|struct|type)[[:space:]]+[[:alnum:]_]*{}"
RISKS = {
    "auth": r"\b(auth\w*|login|logout|sign[- ]?in|password\w*|passwd|sessions?|oauth|jwt|tokens?|"
            r"credentials?|permissions?|rbac|acl|sso|2fa|mfa)\b",
    "payments": r"\b(payments?|billing|invoices?|stripe|paypal|checkout|refunds?|charges?|charged|"
                r"subscriptions?|credit card)\b",
    "migrations": r"\b(migrations?|migrate|alembic|schema change|alter table|add column|drop column|"
                  r"flyway|liquibase)\b",
    "data": r"\b(drop table|truncate|backfill|pii|gdpr|personal data|user data|production data|"
            r"data loss|purge|wipe|delete all)\b",
    "secrets": r"\b(secrets?|api[_ ]keys?|private keys?)\b|\.env\b",
}


def git(repo: str, *args: str) -> str:
    out = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, env=GIT_ENV,
                         timeout=60)
    return out.stdout if out.returncode in (0, 1) else ""


def read_text(repo: str, path: str, limit: int = 1_000_000) -> str:
    p = Path(repo, path)
    try:
        if p.stat().st_size > limit:
            return ""
        data = p.read_bytes()
    except OSError:
        return ""
    return "" if b"\0" in data[:8000] else data.decode("utf-8", "replace")


def keywords(text: str) -> list[str]:
    found = []
    for raw in re.findall(r"[A-Za-z_][\w./-]*", text):
        token = raw.strip("./-")
        strong = "_" in token or "/" in token or re.search(r"[a-z][A-Z]|\.\w{1,4}$", token)
        if strong or (len(token) >= 4 and token.lower() not in STOP):
            word = token if strong else token.lower()
            if word not in found:
                found.append(word)
    return found[:12]


def task_items(task: str) -> list[str]:
    marker = r"(?:^|\s)\(?\d{1,2}[.)]\s+|\n\s*[-*•]\s+"
    parts = [p.strip(" ;,.\n") for p in re.split(marker, task)]
    if len(re.findall(marker, task)) >= 2:
        return [p for p in parts[1:] if len(p) > 8]
    refs = re.findall(r"#\d+|\b[A-Z]{2,}-\d+\b", task)
    return refs if len(refs) >= 2 else [task]


def rank_files(repo: str, tracked: list[str], words: list[str]) -> tuple[Counter, Counter, dict]:
    score, hits, history = Counter(), Counter(), {}
    tracked_set = set(tracked)
    for w in words:
        lw = w.lower()
        for f in tracked:
            if lw in f.lower():
                score[f] += 3
        for line in git(repo, "grep", "-I", "-i", "-c", "-F", "-e", w).splitlines():
            f, _, n = line.rpartition(":")
            if f in tracked_set:
                score[f] += 1
                hits[f] += int(n)
        for f in git(repo, "grep", "-I", "-i", "-l", "-E", "-e", DEF_LINE.format(re.escape(w))).splitlines():
            if f in tracked_set:
                score[f] += 2
        if "/" not in w:
            touched = [f for f in git(repo, "log", "-S", w, "--format=", "--name-only", "-n", "20",
                                      "--no-merges").splitlines() if f in tracked_set]
            if touched:
                history[w] = sorted(set(touched))
                for f in set(touched):
                    score[f] += 1
    return score, hits, history


def pick(score: Counter) -> list[str]:
    ranked = [f for f, s in score.most_common() if s >= 2]
    return ranked[:8] or [f for f, s in score.most_common(3) if s >= 1]


def module_name(path: str) -> str:
    p = Path(path)
    return p.parent.name if p.stem in ("__init__", "index", "mod", "main") and p.parent.name else p.stem


def imports_of(repo: str, path: str) -> str:
    return "\n".join(line for line in read_text(repo, path).splitlines() if IMPORT_LINE.search(line))


def groups(files: list[str], edges: set[tuple[str, str]]) -> int:
    parent = {f: f for f in files}

    def root(f: str) -> str:
        while parent[f] != f:
            f = parent[f]
        return f

    for a, b in edges:
        parent[root(a)] = root(b)
    return len({root(f) for f in files})


def collect(repo: str, task: str) -> dict:
    tracked = git(repo, "ls-files").splitlines()
    code = [f for f in tracked if not NOISE_PATH.search(f)]
    task_risks = [name for name, pattern in RISKS.items() if re.search(pattern, task, re.I)]
    total_lines, langs, risk_code = 0, Counter(), Counter()
    for f in tracked[:30000]:
        text = read_text(repo, f)
        if text:
            total_lines += text.count("\n")
            langs[Path(f).suffix or Path(f).name] += 1
            if not NOISE_PATH.search(f):
                risk_code.update(name for name in task_risks if re.search(RISKS[name], f + "\n" + text, re.I))

    words = keywords(task)
    score, hits, history = rank_files(repo, code, words)
    candidates = pick(score)
    sources = [f for f in candidates if not TEST_PATH.search(f)]
    tests = [f for f in candidates if TEST_PATH.search(f)]

    imports = {f: imports_of(repo, f) for f in sources}
    edges = {(a, b) for a in sources for b in sources
             if a != b and re.search(rf"\b{re.escape(module_name(b))}\b", imports[a])}
    covering = set(tests)
    for t in (f for f in tracked if TEST_PATH.search(f)):
        t_imports = imports_of(repo, t)
        if any(re.search(rf"\b{re.escape(module_name(s))}\b", t_imports) or module_name(s) in Path(t).stem
               for s in sources):
            covering.add(t)

    named = [w for w in words if "_" in w or re.search(r"[a-z][A-Z]", w)]
    defined = sorted({w for w in named for f in sources
                      if re.search(rf"\b(def|class|function|func|fn|interface|struct|type)\s+{re.escape(w)}\b", read_text(repo, f))})

    items = task_items(task)
    item_files = []
    if 2 <= len(items) <= 6:
        for item in items:
            s, _, _ = rank_files(repo, code, keywords(item))
            item_files.append([f for f in pick(s) if not TEST_PATH.search(f)][:3])
    overlap = sorted({f for i, a in enumerate(item_files) for b in item_files[i + 1:] for f in set(a) & set(b)})

    risks = {}
    for name, pattern in RISKS.items():
        where = [f"task text; {risk_code[name]} code files in the repo match"] if name in task_risks else []
        where += [f for f in sources if re.search(pattern, f, re.I)]
        if name != "data":
            where += [f"{f} (content)" for f in sources if f not in where and re.search(pattern, read_text(repo, f), re.I)]
        if where:
            risks[name] = where[:4]

    return {
        "repo": str(Path(repo).resolve()),
        "tracked_files": len(tracked),
        "total_lines": total_lines,
        "languages": dict(langs.most_common(4)),
        "keywords": words,
        "task_items": len(items),
        "item_files": item_files,
        "item_overlap": overlap,
        "files": [{"path": f, "score": score[f], "lines": read_text(repo, f).count("\n"), "keyword_lines": hits[f]}
                  for f in sources],
        "files_lines": sum(read_text(repo, f).count("\n") for f in sources),
        "imports": sorted(f"{a} -> {b}" for a, b in edges),
        "groups": groups(sources, edges) if sources else 0,
        "tests": sorted(covering),
        "history": history,
        "risks": risks,
        "named_definitions": defined,
    }


def summarize(facts: dict) -> str:
    langs = ", ".join(f"{k} {v}" for k, v in facts["languages"].items())
    lines = [f"Repo size: {facts['tracked_files']} tracked files, {facts['total_lines']} lines ({langs})."]
    if facts["files"]:
        listed = ", ".join(f"{f['path']} ({f['lines']} lines)" for f in facts["files"])
        lines.append(f"Likely touched files: {len(facts['files'])}, {facts['files_lines']} lines in all: {listed}.")
    else:
        lines.append("Likely touched files: none matched the task keywords (new code, or a vague task).")
    if len(facts["files"]) > 1:
        coupling = "; ".join(facts["imports"]) or "none of them import each other"
        lines.append(f"Coupling: {coupling}. Independent groups: {facts['groups']}.")
    lines.append(f"Tests covering them: {', '.join(facts['tests']) or 'none found'}.")
    if facts["task_items"] > 1:
        split = " | ".join(", ".join(fs) or "no files" for fs in facts["item_files"])
        shared = ", ".join(facts["item_overlap"]) or "none"
        lines.append(f"The task lists {facts['task_items']} separate items. Files per item: {split}. "
                     f"Files shared between items: {shared}.")
    else:
        lines.append("The task is a single item.")
    if facts["history"]:
        lines.append("Git history (log -S): " + "; ".join(f"{w} in {', '.join(fs[:3])}" for w, fs in facts["history"].items()) + ".")
    risks = "; ".join(f"{k} ({', '.join(v)})" for k, v in facts["risks"].items())
    lines.append(f"Risk flags: {risks or 'none'}.")
    return "\n".join(lines)


def load_rules() -> tuple[str, dict[int, dict]]:
    text = RULES_FILE.read_text()
    rows = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 5 and cells[0].isdigit():
            clean = [re.sub(r"\*\*|`", "", c) for c in cells]
            rows[int(cells[0])] = {"task": clean[1], "pattern": clean[2], "tool": clean[3]}
    if set(rows) != set(ROLES):
        raise SystemExit(f"{RULES_FILE} rows {sorted(rows)} no longer match ROLES {sorted(ROLES)}; update route.py")
    guide = [line for line in text.splitlines()
             if line.startswith(("Choose per task", "Use a router", "Use one agent"))]
    return " ".join(guide), rows


RULE_CONFIDENCE = 1.0  # a rule either matches or the task goes to the jury
NOT_CLEAR_CUT = re.compile(
    r"\b(review\w*|diff|merge|stuck|tried|rescue|codex|hermes|open[- ]source|third opinion|where is|"
    r"find all|usages?|logs?|investigat\w*|research\w*|hypothes\w*|compar\w*|two attempts|approaches|"
    r"team\w*|langgraph|crewai|agent framework|refactor\w*|redesign\w*|architect\w*|design)\b", re.I)


def rule_route(task: str, facts: dict) -> tuple[dict | None, str]:
    """Route with no LLM when the repo facts make the row obvious; otherwise say why the jury is needed."""
    def answers(row: int, model: str, effort: str, why: str) -> tuple[dict, str]:
        pick = {"pattern": str(row), "models": model, "effort": effort}
        return {q: {"choice": c, "confidence": RULE_CONFIDENCE} for q, c in pick.items()} | {"reasons": [why]}, why

    if m := NOT_CLEAR_CUT.search(task):
        return None, f"not clear-cut: the task mentions '{m.group(0)}'"
    files = [f["path"] for f in facts["files"]]
    if facts["risks"]:
        why = f"rule risky: risk flags {', '.join(facts['risks'])} → row 7, opus plans, codex reviews, high effort"
        return answers(7, "opus", "high", why)
    if not files:
        return None, "not clear-cut: no files matched the task"
    if facts["task_items"] == 1 and len(files) <= 2:
        named = facts["named_definitions"]
        effort = "low" if named and len(files) == 1 else "medium"
        why = (f"rule one-bug: 1 item, {len(files)} file(s) ({', '.join(files)}), no risk flags → row 1, sonnet, {effort}"
               + (f" (task names {', '.join(named)})" if effort == "low" else ""))
        return answers(1, "sonnet", effort, why)
    item_files = facts["item_files"]
    if facts["task_items"] >= 2 and item_files and all(item_files) and not facts["item_overlap"]:
        why = (f"rule tickets: {facts['task_items']} items on separate files, none shared, no risk flags "
               f"→ row 5, sonnet, medium")
        return answers(5, "sonnet", "medium", why)
    return None, (f"not clear-cut: {facts['task_items']} item(s), {len(files)} files, "
                  f"shared files: {', '.join(facts['item_overlap']) or 'none'}")


def tally(verdict: str, votes: list[tuple[str, dict | str]]) -> dict:
    cast = [v for _, v in votes if isinstance(v, dict)]
    if not cast:
        raise RuntimeError(verdict)
    shares = Counter(v["choice"] for v in cast)
    choice, count = shares.most_common(1)[0]
    # Same rule as jury.run: 2+ votes and a strict majority, then the winners' average confidence; else 0.
    majority = len(cast) >= 2 and count > len(cast) / 2
    confidence = sum(v["confidence"] for v in cast if v["choice"] == choice) / count if majority else 0.0
    return {"choice": choice, "confidence": round(confidence, 3),
            "probabilities": {k: round(n / len(cast), 3) for k, n in shares.items()},
            "votes": {name: v if isinstance(v, str) else f"{v['choice']} {v['confidence']:.2f}: {v.get('reason', '')}"
                      for name, v in votes}}


def ask_jury(state: str, guide: str, rows: dict[int, dict]) -> dict:
    import jury

    questions = {
        "pattern": (f"Which orchestration row fits this task? {guide}\n" + "\n".join(
            f"{n}: When: {r['task']}. Pattern: {r['pattern']}. Tool: {r['tool']}." for n, r in rows.items()),
            [str(n) for n in rows]),
        "models": (MODELS_QUESTION + "\n" + "\n".join(f"{k}: {v}" for k, v in MODELS.items()), list(MODELS)),
        "effort": (EFFORT_QUESTION + "\n" + "\n".join(f"{k}: {v}" for k, v in EFFORT.items()), list(EFFORT)),
    }
    with ThreadPoolExecutor(len(questions)) as pool:
        futures = {q: pool.submit(jury.run, text, options, state) for q, (text, options) in questions.items()}
    return {q: tally(*f.result()) for q, f in futures.items()}


def ask_jev(state: str, guide: str, rows: dict[int, dict]) -> dict:
    from typesafe_sdk import Choice, TypeSafeClient

    questions = {
        "pattern": Choice(
            instructions=f"Which orchestration row fits this task? {guide}",
            criteria={str(n): f"When: {r['task']}. Pattern: {r['pattern']}. Tool: {r['tool']}." for n, r in rows.items()}),
        "models": Choice(instructions=MODELS_QUESTION, criteria=MODELS),
        "effort": Choice(instructions=EFFORT_QUESTION, criteria=EFFORT),
    }
    with TypeSafeClient(model="jev-latest") as jev:
        r = jev.system_one(state=state, questions=questions, timeout=60)
    return {q: {"choice": a.choice, "confidence": a.confidence,
                "probabilities": {k: round(v, 3) for k, v in a.probabilities.items()}}
            for q, a in r.choices.items()}


def scout_agent() -> dict:
    _, front, body = SCOUT_FILE.read_text().split("---", 2)
    meta = dict(re.findall(r"^(\w+):\s*(.*)$", front, re.M))
    return {"scout": {"description": meta["description"], "prompt": body.strip(), "model": meta["model"],
                      "tools": [t.strip() for t in meta["tools"].split(",")]}}


def scout_schema(rows: dict[int, dict]) -> dict:
    def answer(options: list[str]) -> dict:
        return {"type": "object", "additionalProperties": False, "required": ["choice", "confidence"],
                "properties": {"choice": {"type": "string", "enum": options},
                               "confidence": {"type": "number", "minimum": 0, "maximum": 1}}}

    return {"type": "object", "additionalProperties": False,
            "required": ["pattern", "models", "effort", "reasons"],
            "properties": {"pattern": answer([str(n) for n in rows]), "models": answer(list(MODELS)),
                           "effort": answer(list(EFFORT)),
                           "reasons": {"type": "array", "items": {"type": "string"}, "maxItems": 4}}}


def ask_scout(repo: str, state: str, guide: str, rows: dict[int, dict], first: dict | None) -> dict:
    table = "\n".join(f"{n}. When: {r['task']}. Pattern: {r['pattern']}. Tool: {r['tool']}." for n, r in rows.items())
    unsure = ""
    if first:
        unsure = "\nA first, cheaper pass was unsure (check these against the code):\n" + "\n".join(
            f"- {q}: " + ", ".join(f"{k} {v:.2f}" for k, v in sorted(a["probabilities"].items(), key=lambda kv: -kv[1])[:3])
            for q, a in first.items())
    prompt = (
        "Route this coding task. Do not edit, create or delete anything, and do not run tests. Look at the "
        "repo only as far as you need to confirm or correct the facts below, then answer three questions.\n\n"
        f"{state}\n{unsure}\n\n"
        f"Question 1, pattern: which row fits? {guide}\n{table}\n\n"
        f"Question 2, models: {MODELS_QUESTION}\n" + "\n".join(f"- {k}: {v}" for k, v in MODELS.items()) + "\n\n"
        f"Question 3, effort: {EFFORT_QUESTION}\n" + "\n".join(f"- {k}: {v}" for k, v in EFFORT.items()) + "\n\n"
        "For each answer give a confidence from 0 to 1: your probability that the answer is what these rules "
        "give for this task and repo, not a matter of taste. Instead of the usual 10-line report, reply with only "
        'JSON: {"pattern": {"choice": "<row number>", "confidence": 0.0}, "models": {"choice": "<model>", '
        '"confidence": 0.0}, "effort": {"choice": "<level>", "confidence": 0.0}, "reasons": ["<path:line evidence>"]}'
    )
    read_only = ["Read", "Grep", "Glob", *(f"Bash({c}:*)" for c in
                 ("git log", "git grep", "git show", "git ls-files", "git blame", "ls", "cat", "head", "wc"))]
    with tempfile.TemporaryDirectory() as tmp:
        agents = Path(tmp, "agents.json")
        agents.write_text(json.dumps(scout_agent()))
        out = subprocess.run(
            ["claude", "-p", "--agents", str(agents), "--agent", "scout", "--model", "haiku", "--restricted",
             "--tools", "Read,Grep,Glob,Bash", "--permission-mode", "dontAsk",
             "--allowedTools", ",".join(read_only), "--no-session-persistence", "--output-format", "json",
             "--json-schema", json.dumps(scout_schema(rows))],
            input=prompt, cwd=repo, capture_output=True, text=True, timeout=600, check=True,
            env=GIT_ENV).stdout
    result = json.loads(out)
    answer = result.get("structured_output")
    if not isinstance(answer, dict):
        answer = json.loads(re.search(r"\{.*\}", result.get("result", ""), re.S).group(0))
    for q, options in (("pattern", [str(n) for n in rows]), ("models", list(MODELS)), ("effort", list(EFFORT))):
        a = answer[q]
        if str(a.get("choice")) not in options:
            raise ValueError(f"scout {q} choice {a.get('choice')!r} not in {options}")
        answer[q] = {"choice": str(a["choice"]), "confidence": float(a.get("confidence", 0))}
    answer["denied"] = len(result.get("permission_denials") or [])
    return answer


def route(answers: dict, rows: dict[int, dict]) -> dict:
    row = int(answers["pattern"]["choice"])
    main, level = answers["models"]["choice"], answers["effort"]["choice"]
    claude = {"haiku", "sonnet", "opus"}
    rules = {"main": main, "claude": main if main in claude else "sonnet",
             "planner": main if main in ("sonnet", "opus") else "opus",
             "other": "codex" if main in claude else "sonnet"}
    roles = ROLES[row]
    return {
        "pattern_row": row,
        "pattern": rows[row]["pattern"],
        "models": {role: rules.get(m, m) for role, (m, _) in roles.items()},
        "effort": {role: level if e == "main" else e for role, (_, e) in roles.items()},
        "confidence": round(min(answers[q]["confidence"] for q in QUESTIONS if "defaulted_from" not in answers[q]), 3),
    }


def confident(answers: dict | None) -> bool:
    return bool(answers) and min(answers[q]["confidence"] for q in QUESTIONS) >= MIN_CONFIDENCE


def default_effort(answers: dict | None) -> dict | None:
    """Pattern and model pass but effort is unsure: use the default effort instead of asking a person."""
    if not answers or min(answers[q]["confidence"] for q in ("pattern", "models")) < MIN_CONFIDENCE:
        return None
    e = answers["effort"]
    return {**answers, "effort": {"choice": DEFAULT_EFFORT, "confidence": e["confidence"], "defaulted_from": e["choice"]}}


def describe(source: str, answers: dict) -> str:
    return f"{source}: " + ", ".join(f"{q} {answers[q]['choice']} ({answers[q]['confidence']:.2f})"
                                     for q in QUESTIONS)


def staged(repo: str, state: str, guide: str, rows: dict[int, dict], judge: str, log: dict) -> tuple:
    """The LLM stages: the jury (or JEV), then the scout."""
    first = scout = verdict = None
    try:
        first = log[judge] = (ask_jury if judge == "jury" else ask_jev)(state, guide, rows)
        print(describe(judge, first), file=sys.stderr)
    except Exception as error:  # judge down (or no JEV key): the scout decides
        log[judge] = f"failed: {type(error).__name__}: {str(error)[:200]}"
        print(f"{judge} {log[judge]}", file=sys.stderr)

    if confident(first):
        answers, decided_by = first, judge
    else:
        try:
            scout = log["scout"] = ask_scout(repo, state, guide, rows, first)
            print(describe("scout", scout), file=sys.stderr)
        except Exception as error:  # a scout that fails leaves the call to a person
            log["scout"] = f"failed: {type(error).__name__}: {str(error)[:200]}"
            print(f"scout {log['scout']}", file=sys.stderr)
        if confident(scout):
            answers, decided_by = scout, "scout"
        elif fallback := default_effort(scout or first):
            answers, decided_by = fallback, "scout" if scout else judge
            e = fallback["effort"]
            log["effort_defaulted"] = (f"effort defaulted to {DEFAULT_EFFORT}: {decided_by} said "
                                       f"{e['defaulted_from']} at {e['confidence']:.2f} < {MIN_CONFIDENCE}")
        else:
            answers, decided_by = scout or first, "human"
            verdict = f"ASK A HUMAN: {f'the {judge} and the scout failed' if not answers else f'confidence below {MIN_CONFIDENCE}'}"
    return answers, decided_by, verdict, first, scout


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("repo")
    p.add_argument("task")
    p.add_argument("--judge", choices=["jury", "jev"], default="jury")
    p.add_argument("--no-rules", action="store_true", help="skip the rules stage (to compare against the jury)")
    args = p.parse_args()

    if args.judge == "jev":
        if VENV_PYTHON.exists() and Path(sys.prefix).resolve() != VENV_PYTHON.parent.parent.resolve():
            os.execv(VENV_PYTHON, [str(VENV_PYTHON), __file__, *sys.argv[1:]])  # JEV lives in ~/jev/.venv
        from dotenv import load_dotenv

        load_dotenv(HERE / ".env")  # TYPESAFE_API_KEY
    judge = args.judge
    started = time.time()
    repo = git(args.repo, "rev-parse", "--show-toplevel").strip()
    if not repo:
        raise SystemExit(f"{args.repo} is not a git repository")
    guide, rows = load_rules()
    facts = collect(repo, args.task)
    summary = summarize(facts)
    state = f"Task: {args.task}\n\nRepo facts, collected by a script without an LLM:\n{summary}"
    print(summary, file=sys.stderr)

    log = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "repo": repo, "task": args.task, "facts": facts,
           "summary": summary, "judge": judge, judge: None, "scout": None}
    first = scout = verdict = None
    rule, log["rules"] = (None, "skipped (--no-rules)") if args.no_rules else rule_route(args.task, facts)
    print(f"rules: {log['rules']}", file=sys.stderr)
    if rule:
        answers, decided_by = rule, "rules"
    else:
        answers, decided_by, verdict, first, scout = staged(repo, state, guide, rows, judge, log)

    result = route(answers, rows) if answers else {"pattern_row": None, "pattern": None, "models": {},
                                                   "effort": {}, "confidence": 0.0}
    reasons = [verdict] if verdict else []
    if answers:
        r = rows[result["pattern_row"]]
        reasons.append(f"Row {result['pattern_row']} ({r['task']}): {r['tool']}")
    reasons += rule["reasons"] if rule else []
    reasons += [log["effort_defaulted"]] if log.get("effort_defaulted") else []
    reasons += [describe(name, a) for name, a in ((judge, first), ("scout", scout)) if a]
    reasons += scout.get("reasons", []) if scout else []
    result.update(decided_by=decided_by, reasons=reasons)

    code = 2 if verdict else 0
    log.update(result=result, exit_code=code, seconds=round(time.time() - started, 1))
    with LOG_FILE.open("a") as f:
        f.write(json.dumps(log, ensure_ascii=False) + "\n")

    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(verdict or f"ROUTE row {result['pattern_row']}: {result['pattern']} ({decided_by}, "
                     f"confidence {result['confidence']:.2f})", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
