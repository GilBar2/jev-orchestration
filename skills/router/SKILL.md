---
name: router
description: Use when the user types "/router" (with or without a task after it), or sends a message starting "Route this task in" (sent by the router widget's button), or asks to route, classify or pick the orchestration setup for a coding task. Opens the task router widget, runs ~/jev/route.py, and shows the answer as a card with the setup, models, effort and reasons. Recommends only; starts nothing until the user clicks Start it or says go.
---

# Router: a widget for picking the setup for a task

The user does not use terminals or command syntax. Everything happens in two widgets made by `widget.py` (next to this file), shown with the `show_widget` visualize tool. Load the visualize `read_me` (module `interactive`) once per conversation before the first `show_widget` call, silently.

## 1. `/router` → show the form

1. Run `python3 ~/.claude/skills/router/widget.py form --cwd "$PWD"`. If the user typed a task after `/router`, add `--task "<that text>"` so the box is filled in.
2. Pass the printed HTML unchanged to `show_widget` (title `task_router_form`).
3. Say one short line, such as "Describe the task, pick the project, then press Find the best setup." Stop and wait.

The form's button sends a message like `Route this task in ~/jev/orch-lab: Add a CSV export command` and may end with `(always ask the jury)`.

## 2. "Route this task in …" → run the router

1. Expand `~` in the path. If it is not a git repo, say so in one line and show the form again.
2. Run `python3 ~/jev/route.py <path> "<task>"`, adding `--no-rules` if the message ends with `(always ask the jury)`. Never pass `--judge jev`: it is paid and parked until the user says go on it by name.
3. Rules-only answers take about a second; the jury and scout can take 3 minutes, so run it in the background and say one line while it runs ("Routing, this can take up to 3 minutes").
4. Exit code 0 is routed, 2 is ASK A HUMAN. Both are written to `~/jev/route-log.jsonl`, which the card reads.

## 3. Show the answer card

1. From the JSON `reasons`, write three short plain-language reasons: no row numbers, file counts only if they help, no confidence math. Example: "No reports or export code exists yet, so this is new code."
2. Run `python3 ~/.claude/skills/router/widget.py card --why "<reason 1>" --why "<reason 2>" --why "<reason 3>"` and pass the HTML unchanged to `show_widget` (title `task_router_answer`).
3. Say nothing more than one line, then stop and wait.

## 4. The card's buttons

- **Start it** (`Start the row N setup for: …`) or **Use this setup**: start that ORCHESTRATION.md row's setup for the task in that repo, using the models and effort from the card. Follow the row's "Start with" column in `~/jev/ORCHESTRATION.md`.
- **Pick another setup**: list the rows that could fit as a short numbered list; when the user picks one, treat it like Start it.
- **See the votes**: show the jury and scout votes from the last `route-log.jsonl` entry as a short numbered list.

Routing itself never edits the repo. Run every command through Bash.
