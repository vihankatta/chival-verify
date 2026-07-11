# v0.1.0

First public release. Everything here is code that already exists and already works inside Chival -- this is the same engine, extracted, not a rewrite.

## What's included

- The four-gate verifier: fix passes, bug fails, behavioral diff, mutation-gated. No LLM judge anywhere in the path.
- `chival doctor` -- environment check plus a real offline smoke evaluation.
- `chival grade` -- grade a submission against a test file, or `--example` for a zero-setup demo.
- `chival certify` -- certify your own bug/fix/tests trio through the same four gates, save it to a local, git-committable regression suite.
- `chival suite list / stats / export` -- inspect your suite's coverage, get a next-recommended-category suggestion, bundle for optional sharing.
- Two sandbox backends: a local `pytest` subprocess (default, no Docker required) and an isolated Docker backend.
- Three verified example tasks in `examples/`.
- CI that re-certifies every example on every push.

## What's not included (by design)

- No model connections, no live benchmark runs, no hosted platform. That's the Chival platform, not this repo -- see [chival.ai](https://chival.ai) if you want that on top of this.
- No LLM-judge grading path, ever. This is the one line that will never move.

## Known limits, stated plainly

- Python only, via `pytest`. Other languages are a real roadmap idea, not a promise.
- The certification score (0-100) reflects mutation-kill strength and test thoroughness for a *single* task -- it is not a claim about overall code quality.
