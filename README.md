# chival-verify

Mutation-tested, execution-verified regression checks for bug fixes — no LLM judge, no network calls, no opinion to disagree with.

```
$ pip install chival-verify
$ chival doctor
[OK] sandbox executed a test and returned a deterministic reward.
Chival is ready. Try it now (no files needed): chival grade --example
```

## Why

Most "AI code eval" tools grade a fix by asking another model whether it looks right. That's circular: an LLM judging LLM output inherits every bias and blind spot of the judge itself. `chival-verify` never does this. Every verdict comes from four deterministic gates, run against real code:

| Gate | What it checks |
|---|---|
| 1. Fix passes | The candidate fix must make the real test suite pass. |
| 2. Bug fails | The original buggy version must fail that same suite — proving the test actually detects the bug. |
| 3. Behavioral diff | Fix and bug must differ in real, observable execution behavior, not just in source text (rejects cosmetic-only "fixes"). |
| 4. Mutation-gated | Mutation testing rejects test suites too weak to mean anything. |

If all four pass, the fix is certified. If any fail, you get told exactly which gate rejected it and why.

## Two things you can do with it

**Grade a submission against a test file, right now, offline:**

```bash
chival grade -s solution.py -t test_solution.py
# or, zero setup:
chival grade --example
```

**Certify your own bug fix as a permanent regression check:**

```bash
chival certify --bug bug.py --fix fix.py --tests test_it.py \
    --category security --subtype access_control
```

This runs the exact same four gates and, if it passes, saves a certificate to `.chival/suite/` — plain JSON, committable to git like any other test fixture. Check your suite's coverage and get a suggestion for what to certify next:

```bash
chival suite stats
```

## What this actually catches

`bug.py` / `fix.py` are the broken and fixed versions of the same function. `test_it.py` imports from `solution` and is run against each version in turn — pass on the fix, fail on the bug, or the certification is rejected. See `examples/` for three real, runnable illustrations (an off-by-one bug, a stale-cache read, and a missing ownership check).

## Does this need Docker?

No — a local sandbox backend runs `pytest` in a subprocess and works anywhere Python does. Docker adds isolation, not correctness, and is optional (`--sandbox docker`, image build instructions in [Dockerfile.sandbox](Dockerfile.sandbox)).

## CI

`chival-verify`'s own gates return real exit codes — 0 on certified/verified, 1 on rejected. Drop `chival certify` or `chival grade` straight into a required PR check. A worked example lives in `.github/workflows/ci.yml` in this repo — copy it into your own project's `.github/workflows/` and point it at your own bug/fix/test files.

## This is part of Chival

`chival-verify` is the exact engine behind [Chival](https://chival.ai) — regression testing for code-generation models. Connect a real model, get pass-rate history across bug categories, and diff two runs to catch the moment a fine-tune, merge, or provider swap made it quietly worse. Everything in this repo works standalone; the platform is there if you want live model connections and history on top of it.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Issues and PRs welcome — this maintainer reads every one within 48 hours.

## License

Apache-2.0 — see [LICENSE](LICENSE).
