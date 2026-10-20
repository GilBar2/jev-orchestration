"""Claw Orchestrator verifier step: the $0 jury (stand-in for JEV) votes on the change in the cwd.

Claw runs this as a `command` check in the tree the agent just worked in. It collects the change
since HEAD (tracked diff + untracked files), asks jury.py "accept this change?", and exits:
  0  jury decided "yes"            -> check passes
  1  jury decided "no"             -> check fails, Claw's repair loop runs
  2  ASK A HUMAN (tie, low conf.)  -> check fails, a human must look (clawo verify <runId>)
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jury  # noqa: E402

MAX_CHARS = 60_000


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout


def change_set() -> str:
    parts = [git("diff", "HEAD")]
    for name in git("ls-files", "--others", "--exclude-standard").splitlines():
        try:
            parts.append(f"--- new file: {name}\n{Path(name).read_text()[:5000]}")
        except (OSError, UnicodeDecodeError):
            parts.append(f"--- new file: {name} (unreadable)")
    return "\n".join(p for p in parts if p.strip())[:MAX_CHARS]


def main() -> int:
    change = change_set()
    if not change:
        print("ASK A HUMAN: the run changed nothing")
        return 2
    verdict, votes = jury.run(
        "Should this code change be accepted as a correct, safe fix? Answer escalate if you cannot tell.",
        ["yes", "no", "escalate"], change)
    code = jury.report(verdict, votes)
    if code == 0 and not verdict.startswith("DECIDE yes"):
        return 1
    return code


if __name__ == "__main__":
    sys.exit(main())
