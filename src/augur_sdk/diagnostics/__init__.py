"""Diagnostic rules engine (issue #19, spec §15).

A rule inspects a bundle and emits zero-or-more `DiagnosticFinding` records.
Rules MUST cite evidence references (step / event / screenshot / log paths)
so a viewer or coding agent can pinpoint the source.

Rule packs are groups of rules registered under entry-point group
`augur.rule_packs`. The default `cua` pack ships with the SDK; adapters
register their own (e.g. `mantis`).
"""

from augur_sdk.diagnostics.engine import (
    BundleContext,
    Rule,
    RuleResult,
    RulesEngine,
    load_pack,
    rule,
)
from augur_sdk.diagnostics.packs.cua import CUA_RULES

__all__ = [
    "BundleContext",
    "CUA_RULES",
    "Rule",
    "RuleResult",
    "RulesEngine",
    "load_pack",
    "rule",
]
