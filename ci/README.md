# GitHub Actions workflows (not enabled yet)

`tests.yml` runs the test suite on Python 3.8 and 3.12 on every push. `release.yml` publishes
`psx-mufap.zip` (the file people add to Claude as a skill) whenever a `v*` tag is pushed.

To enable them, move both files into `.github/workflows/`, either on GitHub (open the file,
copy it, then *Add file → Create new file* named `.github/workflows/tests.yml`) or locally:

```bash
mkdir -p .github/workflows && git mv ci/*.yml .github/workflows/ && git commit -m "Enable CI" && git push
```
