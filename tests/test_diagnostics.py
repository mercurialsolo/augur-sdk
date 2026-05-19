"""Diagnostic rules engine tests (issue #19)."""

from __future__ import annotations

import pytest

from augur_sdk.diagnostics import CUA_RULES, load_pack


def test_load_pack_cua() -> None:
    rules = load_pack("cua")
    assert len(rules) >= 10
    assert {r.rule_id for r in rules} == {r.rule_id for r in CUA_RULES}


def test_load_pack_unknown_raises() -> None:
    with pytest.raises(LookupError):
        load_pack("nonexistent")
