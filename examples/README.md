# Examples

Three real, runnable bug/fix/test trios, each independently verified through all four gates before being committed here (see the repo's CI, which re-certifies every example on every push -- if one of these ever stops passing, the build fails).

| Example | Category | What it catches |
|---|---|---|
| `off_by_one/` | Logic | A summation loop that drops the last term. |
| `stale_cache/` | Correctness | A cache invalidation method that silently does nothing. |
| `idor/` | Security | A document store with no ownership check -- the exact IDOR pattern behind a real class of production bugs. |

Try any of them:

```bash
chival certify --bug examples/idor/bug.py --fix examples/idor/fix.py \
    --tests examples/idor/test_it.py --category security --subtype access_control
```

Or grade just the fix on its own:

```bash
chival grade -s examples/idor/fix.py -t examples/idor/test_it.py
```
