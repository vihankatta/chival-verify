"""
Deterministic evaluation entrypoint — the in-process Reward API surface.

This is the capability that turns Chival from an internal dataset pipeline
into a callable evaluation primitive: given an arbitrary submission (an agent's
solution) and a scenario's tests, run it deterministically and return a neutral
`Outcome` (verifiable reward + structured evidence + provenance).

It is a thin ADAPTER, not a new verifier: it reuses the exact sandbox-execution
primitive the certifier uses (`verifier.execution.run_tests`). No generation, no
LLM judging, no certification policy — just deterministic execution -> Outcome.

Deferred by design (need product pull): HTTP/FastAPI, auth, billing, MCP,
multi-step runtime. This is the function-level surface those would wrap later.
"""

from __future__ import annotations

from chival_verify.evaluation import Outcome
from chival_verify.scenario import Scenario
from chival_verify.verifier.execution import run_tests
from chival_verify.verifier.sandbox import Sandbox, get_sandbox

# Default per-submission wall-clock budget for the sandbox run.
DEFAULT_TIMEOUT = 30.0


def _as_test_module(tests) -> str:
    """Accept the scenario tests as a pytest module string or a list of files."""
    if isinstance(tests, (list, tuple)):
        return "\n\n".join(str(t) for t in tests)
    return str(tests)


def grade_submission(
    submission: str,
    tests,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    sandbox: Sandbox | None = None,
) -> Outcome:
    """
    Grade one submission against a scenario's tests and return an Outcome.

    `submission` is the candidate solution saved as `solution.py`; `tests` is the
    pytest module (or list of modules) that imports from `solution`. The result
    is deterministic: identical inputs produce an identical Outcome.
    """
    sandbox = sandbox or get_sandbox()
    execution = run_tests(sandbox, submission, _as_test_module(tests), timeout)
    return Outcome.from_run(execution, timeout=timeout)


def grade(
    submission: str,
    scenario: Scenario,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    sandbox: Sandbox | None = None,
) -> Outcome:
    """
    Grade a submission against a Scenario — the product primitive.

    Runs the submission against the scenario's grading tests (held when present,
    so the reward reflects capability rather than passing visible tests) and
    applies the scenario's success criteria. Deterministic; reuses the same
    execution primitive as `grade_submission` and the certifier — no new logic.
    """
    sandbox = sandbox or get_sandbox()
    execution = run_tests(sandbox, submission, scenario.grading_tests, timeout)
    return Outcome.from_run(execution, timeout=timeout, scenario=scenario)


def grade_many(
    submissions: list[str],
    scenario: Scenario,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    sandbox: Sandbox | None = None,
) -> list[Outcome]:
    """
    Grade many candidate submissions against one Scenario — the RLVR batch shape.

    Order-preserving and deterministic; reuses a single sandbox. (Pure composition
    over `grade()`; no new grading logic.)
    """
    sandbox = sandbox or get_sandbox()
    return [grade(s, scenario, timeout=timeout, sandbox=sandbox) for s in submissions]
