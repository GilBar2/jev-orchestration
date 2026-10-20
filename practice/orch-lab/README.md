# orch-lab

Practice repo for the three orchestration patterns in `../ORCHESTRATION.md`.

Two planted bugs, in separate files so two agents never touch the same file:

- `src/dates.py`: `is_leap_year` ignores the 100/400 rule (`tests/test_dates.py` fails)
- `src/money.py`: `format_cents` drops the leading zero (`tests/test_money.py` fails)

Run the tests:

```bash
python3 -m unittest
```

To reset after practising, remove the worktrees with `git worktree remove <path>`, delete their branches, and run `git checkout -- src`.
