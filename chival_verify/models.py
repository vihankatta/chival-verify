"""
The minimal shape a bug/fix/tests trio needs to be verified.

This is a deliberately small, standalone version of the same idea as
Chival's internal dataset-generation schema -- it carries only the fields
the four gates and `certify` actually read (title, buggy_code, solution_code,
tests, category, subtype, bug_type). No generation-pipeline fields, no LLM
client dependency: this package never talks to a model or the network.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CodingExample(BaseModel):
    """One example to verify: a buggy version, a fixed version, and the tests
    that should tell them apart."""

    title: str = Field(min_length=3, max_length=200)
    buggy_code: str = Field(min_length=1)
    solution_code: str = Field(min_length=1)
    tests: str = Field(min_length=1)
    category: str = "general"
    subtype: str = "general"
    bug_type: str = "general"
