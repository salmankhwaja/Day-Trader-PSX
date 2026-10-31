# GitHub Actions workflows (not enabled yet)

`feed.yml` is the website's price feed: it fetches PSX and MUFAP prices on a schedule (and when
you press *Run workflow*) and commits them, encrypted with the `PSX_DATA_KEY` secret, to `feed/`.
See [the website](../docs/REFERENCE.md#the-website-prices-by-github-action-holdings-in-your-browser).
It is already enabled, in `.github/workflows/feed.yml` (this folder keeps a copy); add the secret to
switch it on.

`tests.yml` runs the test suite on Python 3.8 and 3.12 on every push to `main` and on pull requests
(not for docs-only changes; a newer push cancels the older run). `release.yml` publishes
`psx-mufap.zip` (the file people add to Claude as a skill) whenever a `v*` tag is pushed.

To enable them, move the files into `.github/workflows/`, either on GitHub (open the file,
copy it, then *Add file → Create new file* named `.github/workflows/tests.yml`) or locally:

```bash
mkdir -p .github/workflows && git mv ci/*.yml .github/workflows/ && git commit -m "Enable CI" && git push
```

**What it costs.** Nothing: this repo is public, and GitHub Actions minutes on its standard
runners are free and uncapped for public repos. A test run takes about a minute per Python
version, and every job stops itself after 10 minutes, so nothing can hang. Nothing here is
scheduled, so nothing runs while you're away. (Were the repo ever private, the free plan's 2,000
minutes a month would still cover hundreds of pushes.)
