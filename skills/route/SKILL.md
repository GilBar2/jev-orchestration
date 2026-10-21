---
name: route
description: Use when the user types "/route" followed by a task in plain words (for example "/route fix the CSV export bug"), or asks to route, classify or pick the orchestration setup for a coding task automatically. Runs ~/jev/route.py on the current repo (or a repo path the user gives) and reports the ORCHESTRATION.md row, the model per role and the effort per role. Recommends only; starts nothing until the user says go.
---

# Route: pick the setup for a task

`/route fix the CSV export bug` runs the jev router on the current working directory; everything after `/route` is the task, in plain words, with no brackets or quotes. The user can name another repo by adding `repo=~/myrepo` anywhere in the message. If there is no task text, ask for it in one short line.

## Run

1. Repo = the `repo=` path if given, else the current working directory. It must be a git repo; if not, say so and stop.
2. Run: `python3 ~/jev/route.py <repo> "<task>"`
3. stdout is the JSON decision; stderr is the trace and verdict line. Exit code 2 means ASK A HUMAN. A rules-only decision takes about a second; the jury or scout can take a few minutes, so run it in the background if it may exceed 2 minutes.
4. Pass `--no-rules` or `--judge jev` only if the user asks. `--judge jev` is paid and parked: do not use it unless the user says go.

## Report, then stop

Tell the user, as a short numbered list:

1. The row and pattern name, and who decided (`decided_by`: rules, jury or scout).
2. The model per role and the effort per role.
3. The one-line reason (`reasons`) and the lowest confidence.
4. If exit code 2: say ASK A HUMAN and show the reasons, so they can pick the row.

Then ask whether to start the setup, and wait. Routing never edits the repo, and neither does this skill: running the chosen pattern happens only on the user's go. The user cannot use a terminal, so run everything through Bash.
