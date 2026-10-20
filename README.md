# jev-orchestration

A small toolkit for routing coding tasks between Claude Code, Codex and Hermes, with $0 decision gates and no human in the loop unless the gates are unsure.

- **`route.py`**: given a repo and a task, picks the orchestration pattern, the model for each role and the effort for each role.
- **`jury.py`**: a $0 cross-vendor jury. Claude, Codex and a free Hermes model answer a multiple-choice question, then a majority vote decides.
- **`judge.py`**: two branches attempt the same fix. It tests each one and the jury picks which to merge.
- **`claw/loop.sh`**: Claude plans, Codex codes, Claude reviews, then the tests and the jury gate decide whether the change is done.
- **`ORCHESTRATION.md`**: the pattern table that everything reads as its source of truth.

Every gate uses the same rule: confidence below 0.7 means `ASK A HUMAN` and exit code 2.

## How the router decides

```text
task + repo
   │
   ▼
1. Repo facts, no LLM (git grep, git log -S, imports, tests, risk words)
   │
   ▼
2. $0 jury votes on 3 questions ──── every confidence ≥ 0.7 ──► route (decided_by: jury)
   │ any below 0.7, or the jury fails
   ▼
3. Read-only Haiku scout explores the repo, answers the same 3 ──► ≥ 0.7 ──► route (decided_by: scout)
   │ only effort below 0.7                    │ pattern or model below 0.7
   ▼                                          ▼
effort = medium, logged                    ASK A HUMAN, exit 2
```

1. **Repo facts.** With no LLM, the script collects:
   - likely touched files (task keywords, `git grep`, `git log -S`, function names) and their line counts
   - whether those files import each other
   - the tests that cover them
   - the repo's size
   - whether the task lists separate items, and whether those items share files
   - risk flags: auth, payments, migrations, data, secrets
2. **Three questions.** The jury answers each one:
   - which row of `ORCHESTRATION.md` fits (1–11)
   - which model does the main work (haiku, sonnet, opus, codex, hermes)
   - which effort (low, medium, high)

   Each question needs at least 2 votes and a strict majority. Its confidence is the average confidence of the winning voters.
3. **Roles.** Each row maps to roles. For example, row 7 means Claude plans and Codex reviews, and row 3 means a lead with a Haiku scout and a Sonnet fixer. The answers fill in a model and an effort for each role.
4. **Fallback.** If the jury is unsure, the scout agent (`agents/scout.md`) gets the same facts plus read-only tools: no edit tools and an allow-list of read-only shell commands.
5. **Log.** Every decision, with all votes and reasons, goes to `route-log.jsonl` for later tuning.

The router never edits the target repo or switches its branches.

Optional paid judge: `--judge jev` sends the three questions to TypeSafe's JEV (`system_one`) instead of the jury. It needs credits and `TYPESAFE_API_KEY` in `.env`.

### Usage

```bash
python3 ~/jev/route.py ~/code/my-app "Fix the 100/400 leap-year rule in is_leap_year"
```

```json
{
  "pattern_row": 1,
  "pattern": "None: one agent",
  "models": {"agent": "sonnet"},
  "effort": {"agent": "low"},
  "confidence": 0.92,
  "decided_by": "jury",
  "reasons": ["Row 1 (One bug, 1–2 files, steps in order): claude", "jury: pattern 1 (0.97), ..."]
}
```

The JSON goes to stdout, and a trace plus the verdict line go to stderr. Exit code 0 means routed, 2 means ASK A HUMAN. A run takes about 25–35 seconds.

Results on the practice repo:

| Task | Route |
|---|---|
| One-file bug | row 1 one agent, sonnet, low |
| Two independent tickets | row 5 worktrees, sonnet, low |
| Password login + session tokens | row 7 vendor handoff, opus plans + codex reviews, high |

## Repo layout

| Path | What it is | Installed to |
|---|---|---|
| `route.py`, `jury.py`, `judge.py` | router, jury, merge judge | `~/jev/` |
| `ORCHESTRATION.md` | pattern table, starter prompts, safety and cost rules | `~/jev/` |
| `claw/` | Claw Orchestrator loop, jury gate, contract | `~/jev/claw/` |
| `agents/scout.md`, `agents/fixer.md` | Claude Code subagents | `~/.claude/agents/` |
| `skills/orchestrate/SKILL.md` | `/orchestrate` skill (recommends a pattern) | `~/.claude/skills/orchestrate/` |
| `practice/orch-lab/` | practice repo with two planted bugs | `~/jev/orch-lab/` (as its own git repo) |
| `zed/agent-servers.example.json` | Zed chat panel for Claw | merge into `~/.config/zed/settings.json` |
| `requirements-jev.txt`, `.env.example` | only for the optional JEV judge | `~/jev/.venv`, `~/jev/.env` |

## Install on another machine with an AI agent

These steps are for macOS with Homebrew and Node (nvm is fine). Open Claude Code in any folder and paste this prompt:

```text
Set up the jev-orchestration toolkit on this Mac from https://github.com/GilBar2/jev-orchestration.
Work through the steps in order, run every command yourself, and stop to ask me only for sign-ins.

1. Clone the repo to ~/jev (if ~/jev exists, stop and ask me first).
2. Install the tools, skipping any that `command -v` already finds:
   npm install -g @anthropic-ai/claude-code @openai/codex @enderfga/claw-orchestrator
   brew install tmux claude-squad hermes-agent
3. Sign-ins (ask me to complete each one in the browser): `codex login` (ChatGPT plan),
   `hermes setup` (choose the Nous provider and a free model). Claude Code is already signed in.
4. Codex plugin for Claude Code:
   claude plugin marketplace add openai/codex-plugin-cc
   claude plugin install codex@openai-codex
5. Copy agents/scout.md and agents/fixer.md to ~/.claude/agents/, and
   skills/orchestrate/SKILL.md to ~/.claude/skills/orchestrate/SKILL.md (ask before overwriting).
6. Add this line to ~/.zprofile unless it is already there:
   alias claude-team='CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 claude --teammate-mode auto'
7. Practice repo: copy practice/orch-lab to ~/jev/orch-lab, then inside it run
   git init -b main && git add . && git commit -m "Initial orch-lab practice repo".
8. Check the free Hermes model in ~/jev/jury.py (HERMES_MODEL). If `hermes` cannot use it,
   pick another free Nous model and update that constant.
9. Optional, only if I say so: Zed (brew install --cask zed) with zed/agent-servers.example.json
   merged into ~/.config/zed/settings.json, filling in the real path of clawo. Also optional: the
   paid JEV judge (python3 -m venv ~/jev/.venv, ~/jev/.venv/bin/pip install -r requirements-jev.txt,
   cp .env.example .env, and I add the key).
10. Verify, and show me each result:
    - python3 ~/jev/jury.py --question "Is 2 + 2 = 4?" --options yes,no <<< "arithmetic"  → DECIDE yes
    - python3 ~/jev/route.py ~/jev/orch-lab "is_leap_year returns True for 1900. Fix the 100/400 rule."
      → row 1, decided_by jury, exit 0
    - git -C ~/jev/orch-lab status --short → empty (the router is read-only)
```

### What each piece needs

| Piece | Needs | Cost |
|---|---|---|
| jury | `claude` (Claude plan), `codex` (ChatGPT plan), `hermes` with a free Nous model | $0 extra; a missing juror abstains, and 2 votes are enough |
| scout fallback | `claude` with Haiku | Claude plan |
| `judge.py` | git, your test command, the jury | $0 extra |
| `claw/loop.sh` | `clawo`, `claude`, `codex`, the jury | Claude and ChatGPT plans (Claw's cost column shows the API-equivalent price) |
| `--judge jev` | TypeSafe credits and API key | paid |

### Keep in sync

`route.py` reads the table rows from `ORCHESTRATION.md`. If you add or remove a row, update `ROLES` in `route.py`. The router stops with an error until they match.
