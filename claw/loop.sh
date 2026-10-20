#!/bin/zsh
# Claude plans -> Codex codes -> Claude reviews -> tests + $0 jury gate -> done (or ASK A HUMAN).
# Usage: ~/jev/claw/loop.sh <repo> "<task>" [test command]
#   ~/jev/claw/loop.sh ~/jev/orch-lab "Fix the bug in src/money.py" "python3 -m unittest"
set -e
repo=$1 task=$2 tests=$3
[[ -z $repo || -z $task ]] && { sed -n 2,4p $0; exit 64; }
contract=$(mktemp -t jury-contract).json  # fill in this folder's path, so the repo works on any machine
sed "s|__CLAW_DIR__|${0:A:h}|g" ${0:A:h}/jury-contract.json > $contract
args=(--cwd $repo --scouts claude --engine codex --reviewers claude
      --contract $contract --wait)
[[ -n $tests ]] && args+=(--check $tests)
exec clawo solve $task $args
