"""
The Scenario — the task contract (the missing object between tests and Experience).

In the hierarchy (World -> Scenario -> Experience -> Trajectory -> Outcome ->
Export), a Scenario is the addressable, ownable *task*: what an agent must
achieve, the interface it must satisfy, the tests that grade it (public and/or
held), and the success criteria. It is what makes the product primitive

    agent submission + Scenario -> deterministic Outcome

real: previously "the task" was smeared across a pytest file and an implicit
import contract. A Scenario names it, gives it identity, and lets a customer
bring their own task.

Domain-neutral by construction. `from_example` derives a Scenario from existing
generated `CodingExample`s — no new generators, no generation change.

Held tests matter: grading against *held* tests (not the ones an agent could
see) is what turns reward from "passed the visible tests" into a capability
signal that can't be trivially gamed.
"""

from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass, field

DOMAIN_SOFTWARE_ENGINEERING = "software_engineering"
DEFAULT_ENTRYPOINT = "solution"  # the module name a submission is mounted as


def _symbols(code: str) -> tuple[str, ...]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return ()
    return tuple(
        n.name for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    )


def _fingerprint(parts) -> str:
    return hashlib.sha256("\x1f".join(p or "" for p in parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SuccessCriteria:
    """How an Outcome's verdict is decided from a run. Deterministic."""

    kind: str = "all_pass"      # "all_pass" | "pass_rate"
    threshold: float = 1.0      # used when kind == "pass_rate"

    def evaluate(self, pass_rate: float, suite_ok: bool) -> bool:
        if self.kind == "pass_rate":
            return pass_rate >= self.threshold
        return bool(suite_ok)   # all_pass: clean run, every test green

    def to_dict(self) -> dict:
        return {"kind": self.kind, "threshold": self.threshold}


@dataclass(frozen=True)
class Scenario:
    """A deterministic, domain-neutral task contract."""

    id: str
    fingerprint: str
    domain: str
    category: str
    subtype: str
    difficulty: str
    # Task contract: what interface the submission must satisfy.
    entrypoint: str                       # module the submission is mounted as
    required_symbols: tuple[str, ...]
    # Grading tests.
    public_tests: str                     # visible to the agent (may be empty)
    held_tests: str | None = None         # hidden grading tests (preferred)
    success: SuccessCriteria = field(default_factory=SuccessCriteria)
    # Ownership / provenance.
    source: str = "custom"
    visibility: str = "internal"          # internal | public | private
    provenance: dict = field(default_factory=dict)

    @property
    def grading_tests(self) -> str:
        """The authoritative tests used to grade: held if present, else public."""
        return self.held_tests if self.held_tests else self.public_tests

    @property
    def has_held_tests(self) -> bool:
        return bool(self.held_tests)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "fingerprint": self.fingerprint,
            "domain": self.domain,
            "category": self.category,
            "subtype": self.subtype,
            "difficulty": self.difficulty,
            "entrypoint": self.entrypoint,
            "required_symbols": list(self.required_symbols),
            "has_public_tests": bool(self.public_tests),
            "has_held_tests": self.has_held_tests,
            "success": self.success.to_dict(),
            "source": self.source,
            "visibility": self.visibility,
            "provenance": dict(self.provenance),
        }

    # ------------------------------------------------------------------ #
    @classmethod
    def build(
        cls,
        *,
        public_tests: str = "",
        held_tests: str | None = None,
        success: SuccessCriteria | None = None,
        domain: str = DOMAIN_SOFTWARE_ENGINEERING,
        category: str = "general",
        subtype: str = "general",
        difficulty: str = "medium",
        entrypoint: str = DEFAULT_ENTRYPOINT,
        required_symbols=(),
        source: str = "custom",
        visibility: str = "internal",
        provenance: dict | None = None,
    ) -> "Scenario":
        symbols = tuple(required_symbols)
        success = success or SuccessCriteria()
        # Content address over GRADING-DETERMINING fields only: entrypoint,
        # interface, both test suites, and success criteria. Labels (domain/
        # category/difficulty/visibility) intentionally do NOT change the
        # fingerprint — they don't change the evaluation target.
        fp = _fingerprint([
            entrypoint,
            ",".join(sorted(symbols)),
            public_tests,
            held_tests or "",
            success.kind,
            repr(success.threshold),
        ])
        return cls(
            id="scn_" + fp[:12],
            fingerprint=fp,
            domain=domain, category=category, subtype=subtype, difficulty=difficulty,
            entrypoint=entrypoint, required_symbols=symbols,
            public_tests=public_tests, held_tests=held_tests,
            success=success,
            source=source, visibility=visibility, provenance=provenance or {},
        )

    # ------------------------------------------------------------------ #
    # Full-fidelity (de)serialization for the registry (includes test bodies,
    # unlike to_dict() which is the metadata-only view).
    # ------------------------------------------------------------------ #
    def to_payload(self) -> dict:
        return {
            "id": self.id, "fingerprint": self.fingerprint, "domain": self.domain,
            "category": self.category, "subtype": self.subtype, "difficulty": self.difficulty,
            "entrypoint": self.entrypoint, "required_symbols": list(self.required_symbols),
            "public_tests": self.public_tests, "held_tests": self.held_tests,
            "success": self.success.to_dict(), "source": self.source,
            "visibility": self.visibility, "provenance": dict(self.provenance),
        }

    @classmethod
    def from_payload(cls, d: dict) -> "Scenario":
        return cls(
            id=d["id"], fingerprint=d["fingerprint"], domain=d["domain"],
            category=d["category"], subtype=d["subtype"], difficulty=d["difficulty"],
            entrypoint=d["entrypoint"], required_symbols=tuple(d["required_symbols"]),
            public_tests=d["public_tests"], held_tests=d.get("held_tests"),
            success=SuccessCriteria(**d["success"]), source=d["source"],
            visibility=d["visibility"], provenance=dict(d.get("provenance", {})),
        )

    @classmethod
    def from_example(cls, example, *, domain: str = DOMAIN_SOFTWARE_ENGINEERING) -> "Scenario":
        """Derive a Scenario from an existing CodingExample (no generation change).

        The example's test suite becomes the *held* grading tests (the agent does
        not get to see them); the contract is 'all grading tests pass'.
        """
        return cls.build(
            public_tests="",
            held_tests=example.tests,
            success=SuccessCriteria("all_pass"),
            domain=domain,
            category=getattr(example, "category", "general"),
            subtype=getattr(example, "subtype", "general"),
            difficulty=getattr(example, "difficulty", "medium"),
            required_symbols=_symbols(example.solution_code),
            source="generated",
            visibility="internal",
            provenance={"derived_from": "CodingExample", "title": example.title},
        )
