# Tests

Unit tests for the HEIDI ingestion/backfill scripts, plus template- and
source-level checks for the robustness and hygiene items in `docs/BACKLOG.md`.

```bash
pip install -r requirements-dev.txt
pytest
```

## How to read the results

Tests come in two flavours:

- **Plain tests** lock in behaviour that works today (characterization /
  regression coverage). These must stay green.
- **`xfail(strict=True)` tests** encode behaviour the backlog says we *want* but
  that is not implemented yet (retry/backoff, `FailedEntryCount` handling,
  PutEvents batching, the 256 KB guard, DLQs, and the code-hygiene cleanups).
  They currently fail, so pytest records them as **xfail** and CI stays green.

When you implement one of those gaps, its test starts passing. Because the
marker is `strict=True`, an unexpected pass (**XPASS**) fails the run — that is
the signal to delete the `xfail` marker (and turn the test into a normal guard)
and tick the item off the backlog.

So `xpassed` in the summary means "a backlog item got fixed — update the test."

## Why the scripts are exec'd under mocks

`src/Setup/utils/HealthEventBackFill*.py` are CLI tools that call `input()` and
build boto3 clients at import, and the single-account one runs `backfill()` on
import with no `__main__` guard. `conftest.load_script()` execs each module with
`input()` and `boto3.client` patched so the functions can be tested in isolation.
(The missing guard is itself one of the hygiene items under test.)
