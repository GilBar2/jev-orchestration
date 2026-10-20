"""Merge judge: two branches attempt the same fix, pick one to merge or hand it to a person.

Usage:
    python3 ~/jev/judge.py <repo> <branchA> <branchB> [--base main] [--test-cmd "python3 -m unittest"]
    ~/jev/.venv/bin/python ~/jev/judge.py ... --judge jev   # paid JEV instead (needs TYPESAFE_API_KEY)

Each branch is exported with `git archive` into a temp folder and tested there, so the repo's
working tree, branches and worktrees are never touched. The default judge is the $0 jury in
jury.py (Claude + Codex + a free Nous model, majority vote). Prints MERGE A, MERGE B or ASK A HUMAN
(tie, no majority, neither branch passes, or confidence below 0.7). Exit code 0 on MERGE, 2 otherwise.
"""

import argparse
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

import jury

MIN_CONFIDENCE = 0.7
CLEAN = ["Messy", "Acceptable", "Clean: minimal, readable, only the fix"]
MERGE_QUESTION = "Which branch to merge? Passing tests first, then smaller diff, then cleanliness."


def git(repo: str, *args: str) -> str:
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True).stdout


def check_branch(repo: str, base: str, branch: str, test_cmd: str) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        archive = subprocess.run(["git", "-C", repo, "archive", branch], capture_output=True, check=True).stdout
        subprocess.run(["tar", "-x", "-C", tmp], input=archive, check=True)
        tests = subprocess.run(shlex.split(test_cmd), cwd=tmp, capture_output=True, text=True, timeout=900)
    output = (tests.stdout + tests.stderr).strip().splitlines()
    return {
        "branch": branch,
        "passed": tests.returncode == 0,
        "test_tail": "\n".join(output[-12:]),
        "stat": git(repo, "diff", "--shortstat", f"{base}...{branch}").strip() or "no changes",
        "diff": git(repo, "diff", f"{base}...{branch}")[:4000],
    }


def section(label: str, b: dict) -> str:
    result = "PASSED" if b["passed"] else "FAILED"
    return (
        f"Branch {label} ({b['branch']}): tests {result}\n"
        f"Diff stat: {b['stat']}\n"
        f"Test output (last lines):\n{b['test_tail']}\n"
        f"Diff:\n{b['diff']}\n"
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("repo")
    p.add_argument("branch_a")
    p.add_argument("branch_b")
    p.add_argument("--base", default="main")
    p.add_argument("--test-cmd", default="python3 -m unittest")
    p.add_argument("--judge", choices=["jury", "jev"], default="jury")
    args = p.parse_args()

    a = check_branch(args.repo, args.base, args.branch_a, args.test_cmd)
    b = check_branch(args.repo, args.base, args.branch_b, args.test_cmd)
    for label, br in (("A", a), ("B", b)):
        print(f"{label} {br['branch']}: tests {'pass' if br['passed'] else 'FAIL'}, {br['stat']}")
    if not (a["passed"] or b["passed"]):
        print("ASK A HUMAN: neither branch passes its tests")
        return 2

    report = f"Two branches attempt the same fix against base {args.base}.\n\n" + section("A", a) + "\n" + section("B", b)
    if args.judge == "jury":
        verdict, votes = jury.run(MERGE_QUESTION, ["A", "B", "tie"], report)
        jury.report(verdict, votes)
        if not verdict.startswith("DECIDE"):
            return 2
        choice = verdict.split()[1]
        print(f"MERGE {choice}: {a['branch'] if choice == 'A' else b['branch']}")
        return 0

    from dotenv import load_dotenv
    from typesafe_sdk import Choice, Score, TypeSafeClient

    load_dotenv(Path(__file__).with_name(".env"))  # TYPESAFE_API_KEY
    with TypeSafeClient(model="jev-latest") as jev:
        r = jev.system_one(state=report, questions={
            "clean_a": Score(instructions="How clean is branch A?", criteria=CLEAN),
            "clean_b": Score(instructions="How clean is branch B?", criteria=CLEAN),
            "merge": Choice(
                instructions=MERGE_QUESTION,
                criteria={"A": "Merge A", "B": "Merge B", "tie": "A person decides"}),
        })

    for key in ("clean_a", "clean_b"):
        s = r.scores[key]
        print(f"{key}: {s.score:.2f} of {len(CLEAN) - 1} (confidence {s.confidence:.2f})")
    m = r.choices["merge"]
    odds = ", ".join(f"{k} {v:.2f}" for k, v in m.probabilities.items())
    print(f"merge: {m.choice} (confidence {m.confidence:.2f}; {odds})")

    if m.choice == "tie" or m.confidence < MIN_CONFIDENCE:
        print("ASK A HUMAN")
        return 2
    print(f"MERGE {m.choice}: {a['branch'] if m.choice == 'A' else b['branch']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
