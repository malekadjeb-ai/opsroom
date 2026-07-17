# Contributing to opsroom

Thanks for helping. The bar here is simple: **zero dependencies, zero network egress, read-only on sources, fail-closed redaction.** PRs that hold that line get merged fast.

## Dev setup

There is nothing to install. Clone and run:

```
git clone https://github.com/malekadjeb-ai/opsroom && cd opsroom
python3 -m opsroom.cli demo        # a fully loaded console on fictional data
```

Python 3.11+ required. Stdlib only — if your change needs `pip install` anything, it will be declined.

## Test gates

Seven script-style gates. Every one must exit 0 before a PR:

```
for t in tests/test_*.py; do python3 "$t" || break; done
```

CI runs the same gates on ubuntu + macos across Python 3.11/3.12/3.13, then does a clean `pip install . && opsroom --help`. Green CI is required to merge.

## Writing a collector (the most-wanted contribution)

Each collector is one ~100-line file in `opsroom/collectors/` with a single entry point:

```python
def collect(con, dry_run: bool = False) -> None: ...
```

Use [`opsroom/collectors/codex.py`](opsroom/collectors/codex.py) as the template. The recipe:

1. **Read the agent's local logs** (e.g. `~/.gemini/...`), strictly read-only. Never write to, move, or lock source files.
2. **Emit events through `Emitter`** (`opsroom/collectors/__init__.py`) — it redacts *before* truncating and fails closed: if redaction errors, the event is dropped, never written. Do not insert into the DB directly.
3. **Use per-file watermarks** (`file_changed` / `record_file`) so re-syncs are incremental and idempotent.
4. **Attribute by path**: derive the venture from the session's working directory, same rule as the Claude/Codex collectors.
5. **Register it** in the import list in `opsroom/cli.py` and add a test gate `tests/test_<name>.py` that feeds a small synthetic log fixture (fictional data only — 555 numbers, `.example` domains) and asserts the emitted events.

Wanted: Gemini CLI, Cursor, Aider, OpenCode — see the open [`good first issue`](https://github.com/malekadjeb-ai/opsroom/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) list.

## Ground rules for any PR

- **No network egress.** The console HTML loads zero external resources; collectors never phone home.
- **No new dependencies.** Stdlib only, forever.
- **Fixtures are fictional.** Test data and screenshots use fake names, 555 phone numbers, and `.example` domains — never real logs.
- Keep the diff small and the module boundaries as they are: collectors collect, `state.py` derives, `dashboard.py` renders.

## Reporting bugs

Open an issue with your OS, Python version, the command you ran, and the output. If the bug involves your own logs, please reproduce it against `opsroom demo` data or a synthetic fixture — don't paste real session content.
