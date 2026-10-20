"""$0 cross-vendor jury: ask Claude, Codex (OpenAI) and a free Nous model the same multiple-choice
question, then majority-vote. Replaces a paid decision model (JEV) for gates between agent steps.

Costs nothing extra: Claude runs on your Claude plan, Codex on your ChatGPT plan, Hermes on a free
Nous model. Each juror gets no tools and must answer with JSON {"choice", "confidence", "reason"}.

Usage:
    python3 jury.py --question "Which branch to merge?" --options A,B,tie --state-file report.txt
    some_command | python3 jury.py --question "Is this plan ready for review?" --options yes,no

Prints each vote and a verdict line: DECIDE <option>, or ASK A HUMAN when the jurors disagree with
no majority, the majority picks a "human" option (tie/escalate), or average confidence < 0.7.
Exit code 0 on DECIDE, 2 on ASK A HUMAN.
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MIN_CONFIDENCE = 0.7
HUMAN_OPTIONS = {"tie", "escalate", "human", "ask"}
HERMES_MODEL = "poolside/laguna-s-2.1:free"


def schema(options: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "choice": {"type": "string", "enum": options},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reason": {"type": "string"},
        },
        "required": ["choice", "confidence", "reason"],
        "additionalProperties": False,
    }


def prompt(question: str, options: list[str], state: str) -> str:
    return (
        "You are one juror on a panel. Do not use tools; judge only from the material below.\n"
        f"Question: {question}\nAllowed choices: {', '.join(options)}\n"
        'Reply with only JSON: {"choice": <one allowed choice>, "confidence": <0..1>, "reason": <one sentence>}\n\n'
        f"Material:\n{state}"
    )


def parse(text: str, options: list[str]) -> dict:
    match = re.search(r"\{.*\}", text, re.S)
    vote = json.loads(match.group(0))
    vote["choice"] = str(vote.get("choice"))  # some models answer 7 instead of "7"
    if vote["choice"] not in options:
        raise ValueError(f"choice {vote.get('choice')!r} not in {options}")
    vote["confidence"] = float(vote.get("confidence", 0))
    return vote


def ask_claude(p: str, options: list[str]) -> dict:
    out = subprocess.run(
        ["claude", "-p", "--model", "haiku", "--tools", "", "--output-format", "json",
         "--json-schema", json.dumps(schema(options))],
        input=p, capture_output=True, text=True, timeout=300, check=True).stdout
    result = json.loads(out)
    if isinstance(result.get("structured_output"), dict):
        return parse(json.dumps(result["structured_output"]), options)
    return parse(result.get("result", ""), options)


def ask_codex(p: str, options: list[str]) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        schema_file, answer_file = Path(tmp, "schema.json"), Path(tmp, "answer.txt")
        schema_file.write_text(json.dumps(schema(options)))
        subprocess.run(
            ["codex", "exec", "-s", "read-only", "--skip-git-repo-check", "--ephemeral",
             "--output-schema", str(schema_file), "-o", str(answer_file), "-"],
            input=p, cwd=tmp, capture_output=True, text=True, timeout=300, check=True)
        return parse(answer_file.read_text(), options)


def ask_hermes(p: str, options: list[str]) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        out = subprocess.run(
            ["hermes", "chat", "-Q", "--provider", "nous", "-m", HERMES_MODEL, "--max-turns", "3",
             "--query-file", "-"],
            input=p, cwd=tmp, capture_output=True, text=True, timeout=300, check=True).stdout
    return parse(out, options)


JURORS = {"claude (Anthropic)": ask_claude, "codex (OpenAI)": ask_codex, "hermes (Nous, free)": ask_hermes}


def run(question: str, options: list[str], state: str) -> tuple[str, list[tuple[str, dict | str]]]:
    p = prompt(question, options, state)
    with ThreadPoolExecutor(len(JURORS)) as pool:
        futures = {name: pool.submit(fn, p, options) for name, fn in JURORS.items()}
    votes = []
    for name, future in futures.items():
        try:
            votes.append((name, future.result()))
        except Exception as error:  # a juror that fails abstains
            votes.append((name, f"abstained: {type(error).__name__}: {str(error)[:120]}"))

    cast = [v for _, v in votes if isinstance(v, dict)]
    if len(cast) < 2:
        return "ASK A HUMAN: fewer than 2 jurors answered", votes
    choice, count = Counter(v["choice"] for v in cast).most_common(1)[0]
    if count <= len(cast) / 2:
        return "ASK A HUMAN: no majority", votes
    confidence = sum(v["confidence"] for v in cast if v["choice"] == choice) / count
    if choice.lower() in HUMAN_OPTIONS:
        return f"ASK A HUMAN: majority chose {choice}", votes
    if confidence < MIN_CONFIDENCE:
        return f"ASK A HUMAN: {choice} won but confidence {confidence:.2f} < {MIN_CONFIDENCE}", votes
    return f"DECIDE {choice} ({count}/{len(cast)} votes, confidence {confidence:.2f})", votes


def report(verdict: str, votes: list[tuple[str, dict | str]]) -> int:
    for name, v in votes:
        if isinstance(v, dict):
            print(f"{name:20} {v['choice']:8} conf {v['confidence']:.2f}  {v.get('reason', '')[:110]}")
        else:
            print(f"{name:20} {v}")
    print(verdict)
    return 0 if verdict.startswith("DECIDE") else 2


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--question", required=True)
    p.add_argument("--options", required=True, help="comma-separated, e.g. A,B,tie")
    p.add_argument("--state-file", help="material to judge (default: stdin)")
    args = p.parse_args()
    state = Path(args.state_file).read_text() if args.state_file else sys.stdin.read()
    return report(*run(args.question, args.options.split(","), state))


if __name__ == "__main__":
    sys.exit(main())
