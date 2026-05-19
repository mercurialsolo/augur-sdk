"""Rules engine."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from functools import cached_property
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Protocol

from augur_sdk.models import DiagnosticEvidence, DiagnosticFinding


class BundleContext:
    """Read-only view of a bundle for rule evaluation.

    The context lazily loads files and caches them — rules can be cheap to
    write because they don't need to worry about which file to open or whether
    it exists.
    """

    def __init__(self, bundle_dir: Path | str) -> None:
        self.bundle_dir = Path(bundle_dir)

    @cached_property
    def manifest(self) -> dict[str, Any]:
        return _read_json(self.bundle_dir / "manifest.json")

    @cached_property
    def trace(self) -> dict[str, Any]:
        return _read_json(self.bundle_dir / "trace.json")

    @cached_property
    def session(self) -> dict[str, Any]:
        session: dict[str, Any] = self.trace.get("session", {})
        return session

    @cached_property
    def steps(self) -> list[dict[str, Any]]:
        steps: list[dict[str, Any]] = self.trace.get("steps", [])
        return sorted(steps, key=lambda s: s.get("step_index", 0))

    @cached_property
    def declared_missing(self) -> set[str]:
        return set(self.manifest.get("missing", []) or [])

    def events_for_step(self, step_index: int) -> list[dict[str, Any]]:
        path = self.bundle_dir / "events" / f"{step_index:04d}.jsonl"
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                out.append(json.loads(line))
        return out

    def all_events(self) -> Iterator[dict[str, Any]]:
        events_dir = self.bundle_dir / "events"
        if not events_dir.exists():
            return iter(())
        return (
            event
            for path in sorted(events_dir.glob("*.jsonl"))
            for event in _read_jsonl(path)
        )

    def log_text(self, name: str = "runner.log") -> str | None:
        path = self.bundle_dir / "logs" / name
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8", errors="replace")

    def log_paths(self) -> list[str]:
        logs_dir = self.bundle_dir / "logs"
        if not logs_dir.exists():
            return []
        return sorted(
            f"logs/{p.name}" for p in logs_dir.iterdir() if p.is_file()
        )


@dataclass
class RuleResult:
    """Output of a single rule evaluation: zero or more findings."""

    findings: list[DiagnosticFinding] = field(default_factory=list)

    def emit(
        self,
        *,
        rule_id: str,
        severity: str,
        summary: str,
        evidence: Iterable[DiagnosticEvidence],
        step_index: int | None = None,
        recommendation: str | None = None,
    ) -> None:
        finding: DiagnosticFinding = {
            "rule_id": rule_id,
            "severity": severity,  # type: ignore[typeddict-item]
            "summary": summary,
            "evidence": list(evidence),
        }
        if step_index is not None:
            finding["step_index"] = step_index
        if recommendation is not None:
            finding["recommendation"] = recommendation
        self.findings.append(finding)


class Rule(Protocol):
    """A rule is a callable that takes a context and emits findings."""

    rule_id: str
    severity: str

    def __call__(self, ctx: BundleContext, result: RuleResult) -> None: ...


# --- helper decorator for declaring rules ---


def rule(
    rule_id: str, *, severity: str = "medium"
) -> Callable[[Callable[[BundleContext, RuleResult], None]], Rule]:
    """Decorator: turn a function into a Rule by attaching id + severity."""

    def wrap(fn: Callable[[BundleContext, RuleResult], None]) -> Rule:
        fn.rule_id = rule_id  # type: ignore[attr-defined]
        fn.severity = severity  # type: ignore[attr-defined]
        return fn  # type: ignore[return-value]

    return wrap


# --- engine ---


class RulesEngine:
    def __init__(self, rules: Iterable[Rule]) -> None:
        self._rules = list(rules)

    @property
    def rules(self) -> list[Rule]:
        return list(self._rules)

    def evaluate(self, bundle_dir: Path | str) -> list[DiagnosticFinding]:
        ctx = BundleContext(bundle_dir)
        out: list[DiagnosticFinding] = []
        for r in self._rules:
            result = RuleResult()
            r(ctx, result)
            out.extend(result.findings)
        return out


# --- pack discovery ---


def load_pack(name: str) -> list[Rule]:
    """Load a rule pack by name.

    Built-in packs: `cua`. Adapter-registered packs (via entry-point group
    `augur.rule_packs`) shadow built-ins if they share a name.
    """
    # Adapter-registered packs first; let them override built-ins.
    for ep in entry_points(group="augur.rule_packs"):
        if ep.name == name:
            loaded = ep.load()
            return _coerce_rule_pack(loaded)
    if name == "cua":
        from augur_sdk.diagnostics.packs.cua import CUA_RULES

        return list(CUA_RULES)
    raise LookupError(f"unknown rule pack: {name!r}")


def _coerce_rule_pack(obj: Any) -> list[Rule]:
    rules = obj() if callable(obj) else obj
    if not isinstance(rules, list):
        raise TypeError("rule pack must be a list of Rule callables")
    return rules


# --- internals ---


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
    return data


def _read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)
