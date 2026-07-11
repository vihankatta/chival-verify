# Contributing to chival-verify

Thanks for looking. This is a small, focused tool, and it stays that way on purpose -- the bar for a change isn't "would this be neat" but "does this make the four gates more correct, or the CLI easier to use without adding a new concept."

## Before opening a PR

For anything beyond a typo or a small bug fix, open an issue first describing what you want to change and why. This saves you from writing a PR that doesn't get merged because it's out of scope -- the gates themselves (fix passes, bug fails, behavioral diff, mutation-gated) are the core of the project and changes there get the most scrutiny.

## What's genuinely welcome

- Bug reports with a minimal reproduction (a bug/fix/test trio that behaves unexpectedly is ideal -- it's literally the input format this tool already understands).
- Documentation fixes and clarity improvements.
- New illustrative examples in `examples/` (not your production code, just clean, small, real bug patterns).
- Support for sandboxes or environments beyond the two already shipped (local subprocess, Docker).

## What's out of scope for this repo

- Adding an LLM-judge or model-opinion-based scoring path. This is the one non-negotiable constraint: every verdict comes from executing code, never from asking a model what it thinks. If you want that, it belongs in a different tool.
- Anything that requires a network call by default. `chival doctor` and `chival grade` work fully offline; that stays true.

## Development setup

```bash
git clone https://github.com/chival-ai/chival-verify
cd chival-verify
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
python -m pytest
```

The full test suite must stay green. Add a regression test with every bug fix -- that's not just house style, it's the entire premise of the tool.

## Review

I read every issue and PR within 48 hours. This is a solo-maintained project today, so "within 48 hours" means exactly that, not "instantly" -- thanks for your patience if it takes a day or two.

## Code of conduct

Be direct, be kind, assume good faith. Technical disagreement is fine and expected; anything else isn't.
