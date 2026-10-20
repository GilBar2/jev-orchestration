# Orchestration cheat sheet

Choose per task. Work down the table and stop at the first row that fits. Most tasks stop at row 1.
To have Claude choose for you, type `/orchestrate <task>` in any Claude Code session.
To choose with no human in the loop (pattern, model per role, effort per role), run `route.py` (see Automatic router below).

## Task → pattern → tool

| # | Task | Pattern | Tool | Start with |
|---|------|---------|------|------------|
| 1 | One bug, 1–2 files, steps in order | None: one agent | `claude` | Just ask |
| 2 | Big search, "where is X used", digest a long log | 1. Subagents | `claude` + **scout** (haiku, read-only) | `Use the scout agent to …` |
| 3 | One task that splits cleanly by file | 1. Lead + subagents | `claude` + **fixer** (sonnet) / **scout** | Prompt A |
| 4 | Parts must talk: research, competing hypotheses, review from several angles | 1. Agent team | `claude-team` (run inside `tmux` for split panes) | `Spawn 3 teammates: …` |
| 5 | Several independent tickets | 2. Worktrees | `claude --worktree <name>` per terminal, or `cs` (Claude Squad) | Prompt B, once per worktree |
| 6 | Two attempts at the same fix | 2. Worktrees + judge | Two worktrees, then `judge.py` | Prompt B ×2, then the judge |
| 7 | Risky plan: migration, auth, data, payments | 3. Vendor handoff | Claude plans, Codex reviews read-only | Prompt C |
| 8 | Finished diff, before merge | 3. Vendor handoff | `/codex:review --base main --wait` | That command |
| 9 | Claude is stuck after 2 tries | 3. Vendor handoff | `/codex:rescue` (**edits code**, so run it in a worktree) | `/codex:rescue <what's failing>` |
| 10 | Want an open-source agent, a non-Claude model, or a third opinion | 1, 2 or 3 with **Hermes** | `hermes` (Nous Research, MIT) | Lead: `hermes` (spawns its own subagents). Worktree: `hermes -w` or `cs -p hermes`. Review: `hermes chat -Q -q "Review git diff main...HEAD. Read only, do not edit. List issues with severity."` |
| 11 | Agents inside your own product | Not installed | LangGraph, Microsoft Agent Framework, CrewAI | `pip install langgraph` etc. |

Use a router (several agents) when the work splits cleanly, difficulty varies between parts, or you want an audit trail.
Use one agent for sequential steps, shared files, deep shared context, or small tasks.

## Starter prompts

**A. Lead agent (row 3)**

```text
Split this task into subtasks that touch different files. Use the scout agent
for searches and the fixer agent for edits. Each subagent returns at most
10 lines: files changed, test result, open questions. Don't edit files
yourself until every subagent reports.
```

**B. One agent per worktree (rows 5–6)**

```text
You are in worktree <name>. Fix the failing test in <tests/test_x.py>.
Change only <src/x.py>. Run the full suite, commit, print
git diff --stat main. Do not merge or push.
```

**C. Plan, then Codex review (row 7)**

```text
Write the plan to PLAN.md: files, steps, tests, rollback. Then run
/codex:adversarial-review on it. Apply only objections you can confirm
in the code, list rejected ones with a reason, stop after 3 rounds.
```

## The judge (row 6)

```bash
python3 ~/jev/judge.py <repo> <branchA> <branchB>
```

It tests each branch in a temp copy and sends the results and diffs to the $0 jury (`jury.py`: Claude + Codex + a free Hermes model, majority vote). Paid JEV is optional: add `--judge jev` and run it with `~/jev/.venv/bin/python` (needs `TYPESAFE_API_KEY`). It prints `MERGE A`, `MERGE B`, or `ASK A HUMAN` (a tie, neither branch passes, or confidence below 0.7).
Options: `--base main`, `--test-cmd "npm test"`. If other unrelated tests already fail on main, scope `--test-cmd` to the tests for the fix (for example `python3 -m unittest tests.test_dates`), or the judge returns ASK A HUMAN because neither branch passes. `claude --worktree fix-a` creates the branch `worktree-fix-a`, so pass that name.

## Automatic router

```bash
python3 ~/jev/route.py <repo> "<task>"
```

Picks a row of the table above, the model for each role (haiku, sonnet, opus, codex, hermes) and the effort per role (low, medium, high). It never edits the repo or switches branches.

1. A script collects repo facts with no LLM: likely touched files (task keywords, `git grep`, `git log -S`, function names), their size, whether they import each other, the tests that cover them, repo size, and risk flags (auth, payments, migrations, data, secrets).
2. Rules, no LLM: if the facts make the answer obvious, the router decides right away. Any risk flag → row 7; 1 item in 1–2 files → row 1; several items on separate files → row 5. Tasks about review, search, logs, research, teams, Codex, Hermes, refactors or design go on to the jury. `--no-rules` skips this stage.
3. Otherwise the $0 jury (`jury.py`: Claude + Codex + a free Hermes model) votes on three questions from the task and those facts: pattern row, main model, effort. Each question needs a majority of at least 2 votes, and its confidence is the winners' average. If every confidence is at least 0.7, the jury's answer stands. Paid JEV is optional: add `--judge jev` (needs credits and `TYPESAFE_API_KEY` in `~/jev/.env`).
4. If the jury is unsure, the read-only scout (Haiku) checks the repo and answers the same three questions. If only its effort answer is below 0.7, effort defaults to medium and the log records it. Any other answer below 0.7 gives `ASK A HUMAN` with exit code 2.

Output: JSON `{pattern_row, pattern, models, effort, confidence, decided_by, reasons}` on stdout (`decided_by` is `rules`, `jury`, `jev`, `scout` or `human`). Rules take about 1 second, the jury 25–35 seconds. Exit code 0 when routed, 2 on ASK A HUMAN. Every decision is appended to `~/jev/route-log.jsonl` for tuning.
The table rows are read from this file, so `route.py` stays in sync with it. If you add or remove a row, also update `ROLES` in `route.py` (it stops with an error until you do).

## Claw loop: Claude plans → Codex codes → Claude reviews → jury gate

```bash
~/jev/claw/loop.sh <repo> "<task>" ["<test command>"]
```

Runs `clawo solve` with Claude as scout, Codex as implementer and Claude as reviewer, then the contract in `~/jev/claw/jury-contract.json`: the tests (if given), a diff policy, and `claw/jury_gate.py`. The gate passes only when the jury decides `yes`. A `no` fails the check and Claw runs one repair round. `ASK A HUMAN` fails it and waits for you: open the run with `clawo verify <runId>` or the dashboard.
Dashboard: `clawo serve`, then `http://127.0.0.1:18796/dash?token=$(cat ~/.openclaw/server-token)` (cookie lasts 24 h).

## Safety checklist

- One worktree per agent, and each agent's prompt names its files.
- Default permission mode. Teammates inherit the lead's mode, so never run `claude-team` with skip-permissions.
- No shared secrets: list only what each worktree needs in `.worktreeinclude`.
- Merge one branch at a time and rerun the full tests after each merge.
- Reviewers stay read-only (`/codex:review`, `/codex:adversarial-review`). Use `/codex:rescue` only inside a worktree.

## Cost controls

- Each agent has its own billed context. An agent team costs roughly the single-session price multiplied by the number of teammates.
- Use scout (haiku) for searches. Cap review loops at 3 rounds. Shut down idle teammates (`Ask the <name> teammate to shut down`).
- Check usage with `/usage` (Claude) and `/codex:status` (Codex jobs).

## What's installed

| Tool | Pattern | Check |
|------|---------|-------|
| Claude Code, with subagents `scout` and `fixer` in `~/.claude/agents/` | 1, 2, 3 | `claude --version` |
| `claude-team` alias (agent teams on for that session only), in `~/.zprofile` | 1 | `type claude-team` |
| tmux | 1 (split panes), 2 (Claude Squad) | `tmux -V` |
| Claude Squad (`cs`); `cs -p codex` runs Codex instead | 2 | `cs version` |
| Codex CLI, signed in with ChatGPT | 3 | `codex login status` |
| Codex plugin for Claude Code (`/codex:*`) | 3 | `claude plugin list` |
| $0 jury (`~/jev/jury.py`), default judge | judge | `python3 ~/jev/jury.py --help` |
| Automatic router (`~/jev/route.py`): repo facts → $0 jury (or JEV) → scout fallback | all | `python3 ~/jev/route.py --help` |
| JEV (`typesafe-sdk`) in `~/jev/.venv`, optional and paid | judge | `judge.py --help` |
| Claw Orchestrator 7.12 (`clawo`), loop in `~/jev/claw/` | 1, 3 + judge | `clawo --version` |
| Hermes Agent 0.22.0 (`hermes`): open source, any provider, needs `hermes setup` first | 1, 2, 3 | `hermes --version` |

Hermes reviews are not read-only by default: say "do not edit" in the prompt, or run it in a worktree.

Install later if needed: `brew install --cask conductor` (Mac app for parallel worktrees), `brew install --cask emdash` (open-source app, supports 34 agents), `brew install --cask antigravity-cli` (`agy`, a third vendor).

Practice repo: `~/jev/orch-lab` (two planted bugs; see its README).
