"""
Real, end-to-end tests for the chival-verify CLI. No mocking of the
verification pipeline -- every test here runs the actual sandbox (local
pytest subprocess), since the entire point of this package is that grading
is real execution, not a stub.
"""

from __future__ import annotations

import json

from chival_verify import cli


def _run(argv):
    return cli.main(argv)


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


_FIX_CODE = "def add(a, b):\n    return a + b\n"
_BUG_CODE = "def add(a, b):\n    return a - b\n"
_TEST_CODE = (
    "from solution import add\n\n"
    "def test_add():\n    assert add(2, 3) == 5\n\n"
    "def test_zero():\n    assert add(0, 0) == 0\n"
)


def test_bare_invocation_prints_help_and_exits_zero(capsys):
    code = _run([])
    out = capsys.readouterr().out
    assert code == 0
    assert "usage: chival" in out


def test_doctor_runs_a_real_smoke_evaluation(capsys):
    code = _run(["doctor", "--sandbox", "local"])
    out = capsys.readouterr().out
    assert code == 0
    assert "[OK]" in out


def test_grade_example_is_zero_setup_and_verified(capsys):
    code = _run(["grade", "--example", "--sandbox", "local"])
    out = capsys.readouterr().out
    assert code == 0
    payload = json.loads(out.split("\n\n", 1)[1].split("\n\nThat's")[0])
    assert payload["verified"] is True
    assert payload["metrics"]["tests_total"] == 2
    assert isinstance(payload["metrics"]["tests_total"], int)


def test_certify_a_real_bug_fix_pair_succeeds(tmp_path, capsys):
    bug = _write(tmp_path, "bug.py", _BUG_CODE)
    fix = _write(tmp_path, "fix.py", _FIX_CODE)
    tests = _write(tmp_path, "test_it.py", _TEST_CODE)
    suite_dir = str(tmp_path / "suite")

    code = _run([
        "certify", "--bug", bug, "--fix", fix, "--tests", tests,
        "--category", "backend", "--subtype", "off_by_one",
        "--suite-dir", suite_dir, "--sandbox", "local",
    ])
    out = capsys.readouterr().out
    assert code == 0
    assert "CERTIFIED" in out


def test_certify_rejects_a_fix_that_does_not_pass(tmp_path, capsys):
    bug = _write(tmp_path, "bug.py", _BUG_CODE)
    broken_fix = _write(tmp_path, "fix.py", _BUG_CODE)  # "fix" is still broken
    tests = _write(tmp_path, "test_it.py", _TEST_CODE)
    suite_dir = str(tmp_path / "suite")

    code = _run([
        "certify", "--bug", bug, "--fix", broken_fix, "--tests", tests,
        "--category", "backend", "--subtype", "off_by_one",
        "--suite-dir", suite_dir, "--sandbox", "local",
    ])
    out = capsys.readouterr().out
    assert code == 1
    assert "NOT CERTIFIED" in out


def test_suite_stats_after_certifying_shows_coverage(tmp_path, capsys):
    bug = _write(tmp_path, "bug.py", _BUG_CODE)
    fix = _write(tmp_path, "fix.py", _FIX_CODE)
    tests = _write(tmp_path, "test_it.py", _TEST_CODE)
    suite_dir = str(tmp_path / "suite")

    _run([
        "certify", "--bug", bug, "--fix", fix, "--tests", tests,
        "--category", "backend", "--subtype", "off_by_one",
        "--suite-dir", suite_dir, "--sandbox", "local",
    ])
    capsys.readouterr()

    code = _run(["suite", "stats", "--suite-dir", suite_dir])
    out = capsys.readouterr().out
    assert code == 0
    assert "1 certified task(s)" in out
