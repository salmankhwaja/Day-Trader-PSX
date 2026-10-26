# Working on Day-Trader-PSX

## Rules for every change

1. **Every commit updates README.md to match.** New or changed commands go in the cheat sheet,
   new settings in Settings, new scripts in Repo layout, new tabs in the dashboard tables, and the
   table of contents stays in sync. A commit that changes behaviour without the README is not
   done.
2. **Run the tests before committing:** `python3 -m unittest discover tests` (and
   `python3 -m unittest discover -s us-day-trader/tests` for the US pack). `TestDocs` fails if
   a script in `psx-mufap/scripts/` or a setting in `profiles.VARIABLES` / `DEFAULT_CONFIG` is
   missing from README.md.
3. **Check README links:** every `](#anchor)` must match a heading (GitHub slug rules).
4. Keep `psx-mufap/SKILL.md` in step too, when the way Claude should use a tool changes.

## Conventions

- Standard-library Python 3.8+ only; no dependencies.
- Every buy/sell variable lives in `psx-mufap/scripts/profiles.py` (four risk styles); code reads it
  from the config, never a hard-coded number.
- Market data and users' ledgers never go in the repo; tests use synthetic prices and trimmed page
  samples in `tests/fixtures/`.
- Nothing in `psx-mufap/` may place a real order. Suggestions are labelled as rule-based, not
  investment advice.
- `us-day-trader/` is Jake Schincariol's day-trader-skill (MIT), a git subtree kept **unchanged**:
  don't edit it here; update with `git subtree pull --prefix us-day-trader
  https://github.com/Jakeschincariol/day-trader-skill.git main --squash`, then run its tests
  (`python3 -m unittest discover -s us-day-trader/tests`) and update the README section.
- README voice: plain, friendly, a little humour, never at the expense of a safety note.
