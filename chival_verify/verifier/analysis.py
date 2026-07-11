"""
Static analysis for verification quality and adversarial bug detection.

Two responsibilities, both pure-Python AST work (no execution, no deps):

  1. Test-quality analysis — detect meaningless assertions, duplicate tests,
     and trivially-weak suites. Complements the dynamic mutation check by
     judging the *tests themselves*, not just whether they pass/fail.

  2. Adversarial difference detection — decide whether `buggy_code` differs from
     `solution_code` in a way that could possibly change behavior. A "bug" that
     is only a rename, a reformat, a comment, or a docstring change is FAKE: no
     behavioral test could legitimately distinguish it, so it must be rejected
     even if a flaky test happens to fail.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# Test-quality analysis
# --------------------------------------------------------------------------- #


@dataclass
class TestQuality:
    n_tests: int
    n_meaningful: int
    n_meaningless: int
    n_duplicate: int
    trivial_names: set[str]          # tests with no behavior-exercising assertion
    duplicate_names: list[str]
    issues: list[str] = field(default_factory=list)

    @property
    def meaningful_tests(self) -> int:
        return self.n_meaningful

    def to_dict(self) -> dict:
        return {
            "n_tests": self.n_tests,
            "n_meaningful": self.n_meaningful,
            "n_meaningless": self.n_meaningless,
            "n_duplicate": self.n_duplicate,
            "issues": self.issues,
        }


_RAISES_LIKE = {"raises", "warns", "approx", "fail", "deprecated_call"}


def _is_meaningful_assert(node: ast.Assert) -> bool:
    """
    A meaningful assertion exercises code: it references a name or calls a
    function. `assert True`, `assert 1 == 1`, `assert 2` are NOT meaningful —
    their truth is independent of the code under test.
    """
    expr = node.test
    for sub in ast.walk(expr):
        if isinstance(sub, (ast.Call, ast.Name, ast.Attribute, ast.Subscript)):
            return True
    return False


def _uses_assertion_helper(fn: ast.FunctionDef) -> bool:
    """True if the test uses pytest.raises/approx/... or an assertX helper —
    these exercise behavior without a bare `assert` statement."""
    for n in ast.walk(fn):
        if isinstance(n, ast.Attribute) and n.attr in _RAISES_LIKE:
            return True
        if isinstance(n, ast.Call):
            f = n.func
            name = getattr(f, "attr", None) or getattr(f, "id", None)
            if name and name.startswith("assert"):
                return True
    return False


def _test_functions(tree: ast.AST) -> list[ast.FunctionDef]:
    return [
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name.startswith("test")
    ]


def _normalized_body(fn: ast.FunctionDef) -> str:
    """AST dump of a test body with any leading docstring removed (for dup detection)."""
    body = list(fn.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(
        getattr(body[0], "value", None), ast.Constant
    ) and isinstance(body[0].value.value, str):
        body = body[1:]
    return "||".join(ast.dump(stmt) for stmt in body)


def analyze_test_quality(tests_src: str) -> TestQuality:
    """Static quality judgment of a pytest module's test functions."""
    try:
        tree = ast.parse(tests_src)
    except SyntaxError:
        return TestQuality(0, 0, 0, 0, set(), [], ["tests do not parse"])

    fns = _test_functions(tree)
    trivial: set[str] = set()
    bodies: dict[str, str] = {}
    duplicate_names: list[str] = []
    issues: list[str] = []

    for fn in fns:
        asserts = [n for n in ast.walk(fn) if isinstance(n, ast.Assert)]
        # Trivial unless it has a meaningful assert OR uses pytest.raises/assertX.
        meaningful = any(_is_meaningful_assert(a) for a in asserts) or _uses_assertion_helper(fn)
        if not meaningful:
            trivial.add(fn.name)

        norm = _normalized_body(fn)
        if norm in bodies.values():
            duplicate_names.append(fn.name)
        bodies[fn.name] = norm

    n_tests = len(fns)
    n_meaningless = len(trivial)
    n_duplicate = len(duplicate_names)
    n_meaningful = n_tests - n_meaningless

    if n_meaningless:
        issues.append(f"{n_meaningless} test(s) with no meaningful assertion")
    if n_duplicate:
        issues.append(f"{n_duplicate} duplicate test(s): {', '.join(duplicate_names)}")
    if n_tests < 2:
        issues.append("fewer than 2 tests")

    return TestQuality(
        n_tests=n_tests,
        n_meaningful=n_meaningful,
        n_meaningless=n_meaningless,
        n_duplicate=n_duplicate,
        trivial_names=trivial,
        duplicate_names=duplicate_names,
        issues=issues,
    )


# --------------------------------------------------------------------------- #
# Adversarial difference detection
# --------------------------------------------------------------------------- #

REASON_IDENTICAL = "identical_ast"   # only formatting/comments/docstrings differ
REASON_RENAME = "rename_only"        # only consistent local-variable renames
REASON_NONE = "none"                 # a real structural/behavioral difference
REASON_UNPARSEABLE = "unparseable"


@dataclass
class AdversarialResult:
    is_fake: bool
    reason: str

    def to_dict(self) -> dict:
        return {"is_fake": self.is_fake, "reason": self.reason}


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(getattr(body[0], "value", None), ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:]
    return tree


def _bound_names(tree: ast.AST) -> set[str]:
    """Names that are locally bound (params + assignment targets) — safe to rename.
    Free names (builtins like max/min, called functions, globals) are left alone so
    that, e.g., `max(...)` vs `min(...)` is NOT treated as equivalent."""
    names: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.arg):
            names.add(n.arg)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            names.add(n.id)
    return names


class _AlphaCanon(ast.NodeTransformer):
    """Rename bound names to canonical placeholders by first appearance.

    Because AST field order visits a function's signature before its body,
    parameters are numbered in signature order. That makes a genuine operand
    swap (e.g. `a - b` vs `b - a` under the same signature) come out DIFFERENT,
    while a pure rename (`x + 1` vs `y + 1`) comes out identical.
    """

    def __init__(self, bound: set[str]):
        self.bound = bound
        self.map: dict[str, str] = {}
        self.counter = 0

    def _rename(self, name: str) -> str:
        if name not in self.bound:
            return name
        if name not in self.map:
            self.map[name] = f"__v{self.counter}__"
            self.counter += 1
        return self.map[name]

    def visit_arg(self, node: ast.arg) -> ast.arg:
        node.arg = self._rename(node.arg)
        return node

    def visit_Name(self, node: ast.Name) -> ast.Name:
        node.id = self._rename(node.id)
        return node


def _canonical_dump(src: str, alpha: bool) -> str:
    tree = _strip_docstrings(ast.parse(src))
    if alpha:
        tree = _AlphaCanon(_bound_names(tree)).visit(tree)
    return ast.dump(tree)


def behavioral_difference(solution_src: str, buggy_src: str) -> AdversarialResult:
    """
    Classify the difference between solution and buggy code.

    - identical_ast: same AST ignoring formatting/comments/docstrings -> FAKE
    - rename_only:   identical up to consistent local renames          -> FAKE
    - none:          a real structural difference exists               -> OK
    """
    try:
        if _canonical_dump(solution_src, alpha=False) == _canonical_dump(buggy_src, alpha=False):
            return AdversarialResult(True, REASON_IDENTICAL)
        if _canonical_dump(solution_src, alpha=True) == _canonical_dump(buggy_src, alpha=True):
            return AdversarialResult(True, REASON_RENAME)
    except SyntaxError:
        # If either side doesn't parse, leave the judgment to the dynamic run.
        return AdversarialResult(False, REASON_UNPARSEABLE)
    return AdversarialResult(False, REASON_NONE)
