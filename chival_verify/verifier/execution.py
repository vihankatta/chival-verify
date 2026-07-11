"""
Shared sandbox-execution primitive.

Both the certifier (`verifier/runner.py`, differential verification) and the
grader (`core/grader.py`, single-submission evaluation) need to run code+tests in
the sandbox and parse the deterministic result. That primitive lives here so the
two share it — the grader is an adapter over the SAME execution, never a second
verifier.

Pure execution + parsing. No certification policy, no scoring, no LLM.
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from chival_verify.verifier.sandbox import JUNIT_FILE, Sandbox

_PASSED = re.compile(r"(\d+) passed")
_FAILED = re.compile(r"(\d+) failed")
_ERRORS = re.compile(r"(\d+) errors?")
_FAILURES_HDR = re.compile(r"^=+ FAILURES =+", re.MULTILINE)


def _count(pattern: re.Pattern, text: str) -> int:
    m = pattern.search(text)
    return int(m.group(1)) if m else 0


def parse_junit(xml_text: str) -> dict[str, str]:
    """Map test name -> 'passed' | 'failed' | 'skipped' from a JUnit XML report."""
    results: dict[str, str] = {}
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return results
    for tc in root.iter("testcase"):
        name = tc.get("name")
        if not name:
            continue
        status = "passed"
        for child in tc:
            tag = child.tag.split("}")[-1]
            if tag in ("failure", "error"):
                status = "failed"
                break
            if tag == "skipped":
                status = "skipped"
                break
        results[name] = status
    return results


def failures_only(output: str, limit: int = 4000) -> str:
    """Extract the real pytest FAILURES section (actual values + traceback)."""
    m = _FAILURES_HDR.search(output)
    if not m:
        return output.strip()[-limit:]
    return output[m.start():].strip()[:limit]


@dataclass
class ExecutionResult:
    passed: int
    failed: int            # failures + errors
    timed_out: bool
    suite_ok: bool         # ran clean: rc==0, >0 passed, 0 failed/errors
    runtime: float
    backend: str
    per_test: dict[str, str]  # test name -> status (empty if junit unavailable)
    output: str = ""          # combined stdout+stderr


def parse(sandbox_result, runtime: float) -> ExecutionResult:
    """Turn a raw SandboxResult into parsed, deterministic execution metrics."""
    output = f"{sandbox_result.stdout}\n{sandbox_result.stderr}"
    per_test = parse_junit(sandbox_result.artifacts.get(JUNIT_FILE, ""))
    if per_test:
        passed = sum(1 for s in per_test.values() if s == "passed")
        failed = sum(1 for s in per_test.values() if s == "failed")
    else:  # fall back to summary parsing if junit didn't make it out
        passed = _count(_PASSED, output)
        failed = _count(_FAILED, output) + _count(_ERRORS, output)
    suite_ok = (
        not sandbox_result.timed_out
        and sandbox_result.returncode == 0
        and passed > 0
        and failed == 0
    )
    return ExecutionResult(passed, failed, sandbox_result.timed_out, suite_ok,
                           runtime, sandbox_result.backend, per_test, output)


def run_tests(sandbox: Sandbox, code: str, tests: str, timeout: float) -> ExecutionResult:
    """Write solution.py + test_solution.py, run pytest in the sandbox, parse."""
    files = {"solution.py": code, "test_solution.py": tests}
    start = time.perf_counter()
    res = sandbox.run(files, timeout=timeout)
    return parse(res, time.perf_counter() - start)
