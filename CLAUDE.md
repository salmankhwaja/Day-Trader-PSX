# Working on Day-Trader-PSX

## Rules for every change

1. **Every commit updates the docs to match.** `README.md` is the short front door (what to ask,
   your data, setup for Claude, Gemini, ChatGPT, computer and phone): keep it short and add a line
   there only for something a new user should see. `docs/REFERENCE.md` is the full manual: new or
   changed commands go in its cheat sheet, new settings in Settings, new scripts in Repo layout,
   and its table of contents stays in sync. A commit that changes behaviour without the docs is
   not done.
2. **Run the tests before committing:** `python3 -m unittest discover tests`. `TestDocs` fails if
   a script in `psx-mufap/scripts/` or a setting in `profiles.VARIABLES` / `DEFAULT_CONFIG` is
   missing from README.md and docs/REFERENCE.md.
3. **Check links in both files:** every `](#anchor)` and `](file#anchor)` must match a heading (GitHub slug rules).
4. Keep `psx-mufap/SKILL.md` in step too, when the way Claude should use a tool changes.

## Conventions

- Standard-library Python 3.8+ only; no dependencies.
- Every buy/sell variable lives in `psx-mufap/scripts/profiles.py` (four risk styles); code reads it
  from the config, never a hard-coded number.
- Market data and users' ledgers never go in the repo; tests use synthetic prices and trimmed page
  samples in `tests/fixtures/`.
- Nothing may place a real order (PSX retail apps have no order API; tickets are typed by the user). Suggestions are labelled as rule-based, not
  investment advice.
- This repo is PSX-only. The 11 desk skills (`psx-scanner/` … `psx-insiders/`) carry copies of the
  code: edit `psx-mufap/scripts/` only, then run `python3 tools/sync_skills.py`, which also rebuilds `zips/` (the tests fail if
  a copy or a zip is stale). A new desk tool goes in `tools/sync_skills.py` SKILLS and gets its SKILL.md.
- README voice: plain, friendly, a little humour, never at the expense of a safety note.
