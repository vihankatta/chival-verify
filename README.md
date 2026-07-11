![CI](https://github.com/vihankatta/chival-verify/actions/workflows/ci.yml/badge.svg)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

# chival-verify

Mutation-tested, execution-verified regression checks for bug fixes — no LLM judge, no network calls, no opinion to disagree with.

```
$ pip install git+https://github.com/vihankatta/chival-verify.git
$ chival doctor
[OK] sandbox executed a test and returned a deterministic reward.
Chival is ready. Try it now (no files needed): chival grade --example
```

> Not on PyPI yet — `pip install chival-verify` alone will not work until it is. The `git+https://` install above is the real, working path today. See [Installation](#installation).

## Why

Most "AI code eval" tools grade a fix by asking another model whether it looks right. That's circular: an LLM judging LLM output inherits every bias and blind spot of the judge itself. `chival-verify` never does this. Every verdict comes from four deterministic gates, run against real code:

| Gate | What it checks |
|---|---|
| 1. Fix passes | The candidate fix must make the real test suite pass. |
| 2. Bug fails | The original buggy version must fail that same suite — proving the test actually detects the bug. |
| 3. Behavioral diff | Fix and bug must differ in real, observable execution behavior, not just in source text (rejects cosmetic-only "fixes"). |
| 4. Mutation-gated | Mutation testing rejects test suites too weak to mean anything. |

If all four pass, the fix is certified. If any fail, you get told exactly which gate rejected it and why.

## Installation

```bash
pip install git+https://github.com/vihankatta/chival-verify.git
```

This installs a real `chival` command on your PATH, backed by Python 3.10+. No API key, no account, no network calls required to use it — the install itself needs network access (to fetch from GitHub), but nothing after that does.

Prefer to inspect the code first? Clone and install locally:

```bash
git clone https://github.com/vihankatta/chival-verify.git
cd chival-verify
pip install -e .
```

To uninstall: `pip uninstall chival-verify`.

## 30-second quickstart

```bash
chival doctor              # confirms your environment can run the sandbox -- offline
chival grade --example     # grades a built-in example -- zero files needed
```

Both commands run fully offline. No files, no API key, no model. If `chival doctor` prints `[OK]`, everything else in this README will work on your machine.

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

### Example output

Real output, captured from an actual run — not a mockup:

```
$ chival certify --bug bug.py --fix fix.py --tests test_it.py --category security --subtype access_control
certifying 'security/access_control regression' (security/access_control)...
  gate 1  fix passes the real test suite             PASS
  gate 2  fix and bug differ in real behavior         PASS
  gate 3  bug is genuinely caught (1/2 tests kill it)      PASS
  gate 4  test suite isn't trivially weak              PASS

CERTIFIED  (score 62/100)
  saved: .chival/suite/4cc7739869b6b408.json

your local suite now has 1 certified task(s) across 1 category: security=1
```

## What this actually catches

`bug.py` / `fix.py` are the broken and fixed versions of the same function. `test_it.py` imports from `solution` and is run against each version in turn — pass on the fix, fail on the bug, or the certification is rejected. See `examples/` for three real, runnable illustrations (an off-by-one bug, a stale-cache read, and a missing ownership check).

## Common use cases

- **Before you trust a fix.** You (or an AI coding agent) wrote a bug fix. `chival grade` tells you, deterministically, whether it actually works — not whether it looks plausible.
- **Building a personal or team regression suite.** Every real bug you've hit becomes a `chival certify` call. Six months in, you have a suite of real regressions specific to your own codebase, not generic examples.
- **Gating CI on regressions.** `chival certify`/`chival grade` return real exit codes. Wire either into a required PR check and a regression fails the build instead of shipping quietly. See [CI](#ci) below.
- **Evaluating AI-generated code without an LLM judge.** If you're grading model output and don't want a second model's opinion deciding correctness, this is the alternative: real execution, real tests.

## Does this need Docker?

No — a local sandbox backend runs `pytest` in a subprocess and works anywhere Python does. Docker adds isolation, not correctness, and is optional (`--sandbox docker`, image build instructions in [Dockerfile.sandbox](Dockerfile.sandbox)).

## CI

`chival-verify`'s own gates return real exit codes — 0 on certified/verified, 1 on rejected. Drop `chival certify` or `chival grade` straight into a required PR check. A worked example lives in `.github/workflows/ci.yml` in this repo — copy it into your own project's `.github/workflows/` and point it at your own bug/fix/test files.

## FAQ

**Is this an LLM judging another LLM?**
No. Every grading decision comes from executing code against real tests — pass or fail, nothing in between that's an opinion.

**Does it need Docker?**
No, see [above](#does-this-need-docker).

**Is it actually deterministic?**
Yes, in both sandbox backends. Same submission, same scenario, same verdict — every time, on any machine.

**Is this published on PyPI?**
Not yet. Install directly from GitHub (see [Installation](#installation)) until it is. This README will be updated the day it lands on PyPI, not before.

**What's the certification score (0-100)?**
It reflects mutation-kill strength and test thoroughness for that *one* task — how robustly the bug was caught and how clean the test suite is. It is not a general code-quality score.

**Can I use my own categories, not the built-in ones?**
Yes. `--category`/`--subtype` accept any string. `chival suite stats` tracks coverage against six starter categories (api, async_concurrency, backend, database, performance, security) but anything you certify outside them still counts and still shows up.

**Why Python only?**
Because that's what's built and tested today. See [Roadmap](#roadmap).

## Troubleshooting

**`chival: command not found` after install**
Your Python scripts directory probably isn't on PATH. Confirm the install worked with `pip show chival-verify`, then either add your Python `Scripts`/`bin` directory to PATH, or run it as `python -m chival_verify.cli` instead.

**`pip install chival-verify` fails with "No matching distribution found"**
Expected right now — this package isn't on PyPI yet. Use `pip install git+https://github.com/vihankatta/chival-verify.git` instead.

**`chival doctor` reports `[FAIL]` on both backends**
This means even the local `pytest` subprocess sandbox couldn't run. Confirm `pytest` is actually importable in the same Python environment `chival` is installed in (`python -m pytest --version`). If that also fails, the environment itself is broken, not `chival-verify`.

**A certification I expect to pass is rejected**
Read the specific gate it failed — the message names one of the four gates and why (see the [gates table](#why)). The most common one is Gate 3 (`bug is genuinely caught`): if your bug and fix produce the *same* output for the specific inputs your tests use, the test suite never actually distinguished them. Pick input values where the two behaviors genuinely diverge.

**Docker sandbox fails with a message about missing pytest**
The image you pointed `CHIVAL_IMAGE` at doesn't have pytest installed and the sandbox has no network access to install it. Build the provided image first: `docker build -f Dockerfile.sandbox -t chival-verify-sandbox .`

## Roadmap

Ideas under consideration, not commitments — each ships only if real usage justifies it:

- Publish to PyPI (the actual next step, tracked honestly as not-yet-done above).
- Community-contributed example task packs.
- Language support beyond Python (would need its own sandboxed test-runner adapter).
- Pluggable oracle backends (e.g. property-based test generation via Hypothesis).

## This is part of Chival

`chival-verify` is the exact engine behind [Chival](https://chival.ai) — regression testing for code-generation models. If you outgrow what a local CLI can do, that's what the platform is for:

- **Need regression history across many runs, not just one diff?** Chival keeps every run and diffs any two automatically.
- **Need to grade a live model connection, not a file you already have?** Chival connects to OpenAI-compatible and Anthropic endpoints and runs the same four gates against real model output.
- **Need this wired into a team's CI without hand-rolling the plumbing?** That's the platform's job.

Everything in this repo works standalone, forever — the platform is an upgrade path, not a requirement.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Issues and PRs welcome — this maintainer reads every one within 48 hours.

## Security

See [SECURITY.md](SECURITY.md) for how to report a vulnerability.

## Code of conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

Apache-2.0 — see [LICENSE](LICENSE).
