## What this does

<!-- One or two sentences. -->

## Checklist

- [ ] All seven test gates pass: `for t in tests/test_*.py; do python3 "$t" || break; done`
- [ ] No new dependencies (stdlib only)
- [ ] No network egress introduced
- [ ] Sources stay read-only; any test fixtures are fictional (555 numbers, `.example` domains)
