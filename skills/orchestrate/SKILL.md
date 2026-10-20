---
name: orchestrate
description: Use when the user types "/orchestrate", or asks which orchestration pattern, how to split a task across agents, or whether to use subagents, an agent team, worktrees, Claude Squad, or a Codex review for a task. Picks one of the three patterns (lead + subagents, parallel worktrees, vendor handoff) or plain single agent, and prints the exact command and a filled starter prompt. Recommends only; starts nothing until the user says go.
---

# Orchestrate: pick a pattern per task

The full table lives in `~/jev/ORCHESTRATION.md`. Read it if the rules below don't settle the task.

For an autonomous run with no human, `python3 ~/jev/route.py <repo> "<task>"` picks the row, the model per role and the effort per role on its own and prints JSON (exit 2 means ASK A HUMAN). Suggest it when the user wants routing without being asked each time.

## Decide (first match wins)

1. The task is one bug in 1–2 files, a sequence of dependent steps, or small → **single agent**. Say so plainly; extra agents only add cost here.
2. The task is mostly reading: a big search, "where is X used", digesting a long log → **Pattern 1, scout subagent** (haiku, read-only).
3. One task splits into parts that touch different files and don't need to talk to each other → **Pattern 1, lead + subagents** (fixer on sonnet, scout for searches).
4. The parts must discuss or challenge each other (research from several angles, competing bug hypotheses, multi-lens review) → **Pattern 1, agent team** via `claude-team`, inside `tmux` for split panes. Note that it costs roughly one session per teammate.
5. Several independent tickets, or the user wants two attempts at the same fix → **Pattern 2, worktrees**: `claude --worktree <name>` per terminal, or `cs` (Claude Squad). For two attempts, end with the judge ($0 jury by default).
6. A risky plan (migration, auth, data, payments, deletes) → **Pattern 3**: Claude writes PLAN.md, then `/codex:adversarial-review`, at most 3 rounds.
7. A finished diff before merge → **Pattern 3**: `/codex:review --base main --wait`.
8. Claude has failed twice on the same problem → **Pattern 3**: `/codex:rescue`, only inside a worktree because it edits code.

9. The user wants an open-source agent, a non-Claude/non-OpenAI model, or a third reviewer → **Hermes** (`hermes`, Nous Research). It fits any pattern: as lead (`hermes`, which spawns its own subagents), per worktree (`hermes -w`, or `cs -p hermes`), or as reviewer (`hermes chat -Q -q "Review git diff main...HEAD. Read only, do not edit. List issues with severity."`). Its review is not read-only unless the prompt says so; prefer a worktree.

10. One fix the user wants Codex to write and Claude to plan and review, gated before it counts as done → **Claw loop**: `~/jev/claw/loop.sh <repo> "<task>" "<test command>"` (Claude scout → Codex coder → Claude reviewer → tests + jury gate).

If two rules fit, pick the cheaper one and mention the other in one line.

## Answer format (at most 15 lines)

```
Pattern: <single agent | 1 subagents | 1 agent team | 2 worktrees | 3 vendor handoff>
Why: <one line tied to the task>
Run: <exact commands, one per line>
Prompt:
<the starter prompt below, filled with the task's real file names>
Watch out: <one line: file overlap, cost, or permissions>
```

## Starter prompts

Lead + subagents:
> Split this task into subtasks that touch different files. Use the scout agent for searches and the fixer agent for edits. Each subagent returns at most 10 lines: files changed, test result, open questions. Don't edit files yourself until every subagent reports.

Per worktree (one per terminal, each naming different files):
> You are in worktree <name>. Fix <failing test>. Change only <file>. Run the full suite, commit, print git diff --stat main. Do not merge or push.

Plan + Codex review:
> Write the plan to PLAN.md: files, steps, tests, rollback. Then run /codex:adversarial-review on it. Apply only objections you can confirm in the code, list rejected ones with a reason, stop after 3 rounds.

Judge for two attempts at the same fix (`claude --worktree fix-a` creates the branch `worktree-fix-a`). It uses the $0 jury by default; `--judge jev` (via `~/jev/.venv/bin/python`) is the optional paid JEV:
```
python3 ~/jev/judge.py <repo> worktree-<a> worktree-<b>
```
`ASK A HUMAN` means a tie or confidence below 0.7: show the user both diffs and let them choose.

## Rules

- Don't start agents, worktrees, teams or reviews until the user says go.
- Never suggest skip-permissions with `claude-team`; teammates inherit the lead's mode.
- Every parallel agent's prompt names its own files, and no two agents share a file.
