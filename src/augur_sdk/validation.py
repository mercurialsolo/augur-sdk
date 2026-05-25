"""Bundle validation.

Used by `augur validate` and by the SDK's self-test on close. Validates
every record in a bundle against the canonical JSON Schemas.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from augur_schema import SCHEMA_VERSION, validator_for
from jsonschema import ValidationError


@dataclass
class ValidationIssue:
    where: str
    message: str
    path: str

    def render(self) -> str:
        return f"{self.where}: {self.message} (at {self.path or '<root>'})"


def _issues_from_validator(
    validator: Any, instance: Any, where: str
) -> Iterator[ValidationIssue]:
    for err in validator.iter_errors(instance):
        path = "/".join(str(p) for p in err.absolute_path) or "<root>"
        yield ValidationIssue(where=where, message=err.message, path=path)


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate_bundle(bundle_dir: str | Path) -> list[ValidationIssue]:
    """Validate every JSON record in `bundle_dir` against its schema.

    Returns a list of issues. Empty list = bundle is valid.
    """
    root = Path(bundle_dir)
    issues: list[ValidationIssue] = []

    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        return [ValidationIssue("manifest.json", "missing", "")]

    try:
        manifest = _read_json(manifest_path)
    except json.JSONDecodeError as e:
        return [ValidationIssue("manifest.json", f"invalid JSON: {e}", "")]

    issues.extend(
        _issues_from_validator(validator_for("manifest"), manifest, "manifest.json")
    )

    # schema_version range check
    declared = manifest.get("schema_version")
    if isinstance(declared, str) and not declared.startswith(SCHEMA_VERSION):
        issues.append(
            ValidationIssue(
                "manifest.json",
                f"schema_version {declared!r} outside supported range {SCHEMA_VERSION!r}",
                "schema_version",
            )
        )

    # trace.json
    trace_path = root / "trace.json"
    if not trace_path.exists():
        issues.append(ValidationIssue("trace.json", "missing", ""))
    else:
        try:
            trace = _read_json(trace_path)
        except json.JSONDecodeError as e:
            issues.append(ValidationIssue("trace.json", f"invalid JSON: {e}", ""))
            trace = None
        if trace is not None:
            issues.extend(
                _issues_from_validator(validator_for("trace"), trace, "trace.json")
            )

    # per-step files. Walks both layouts: flat `steps/<NNNN>.json` for
    # single-emission steps and nested `steps/<NNNN>/<short_id>.json`
    # for canonical steps with iterations (augur-sdk#30).
    steps_dir = root / "steps"
    if steps_dir.exists():
        step_validator = validator_for("step_trace")
        for step_file in sorted(steps_dir.rglob("*.json")):
            rel = step_file.relative_to(root).as_posix()
            try:
                step = _read_json(step_file)
            except json.JSONDecodeError as e:
                issues.append(
                    ValidationIssue(rel, f"invalid JSON: {e}", "")
                )
                continue
            issues.extend(
                _issues_from_validator(step_validator, step, rel)
            )

    # events JSONL
    events_dir = root / "events"
    if events_dir.exists():
        event_validator = validator_for("decision_event")
        for events_file in sorted(events_dir.glob("*.jsonl")):
            with events_file.open(encoding="utf-8") as f:
                for lineno, line in enumerate(f, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError as e:
                        issues.append(
                            ValidationIssue(
                                f"events/{events_file.name}",
                                f"invalid JSON on line {lineno}: {e}",
                                "",
                            )
                        )
                        continue
                    try:
                        event_validator.validate(event)
                    except ValidationError as err:
                        path = (
                            "/".join(str(p) for p in err.absolute_path) or "<root>"
                        )
                        issues.append(
                            ValidationIssue(
                                f"events/{events_file.name}",
                                f"line {lineno}: {err.message}",
                                path,
                            )
                        )

    # diagnostics
    diagnostics_dir = root / "diagnostics"
    if diagnostics_dir.exists():
        finding_validator = validator_for("diagnostic_finding")
        findings_file = diagnostics_dir / "findings.json"
        if findings_file.exists():
            try:
                findings = _read_json(findings_file)
            except json.JSONDecodeError as e:
                issues.append(
                    ValidationIssue("diagnostics/findings.json", f"invalid JSON: {e}", "")
                )
                findings = []
            if not isinstance(findings, list):
                issues.append(
                    ValidationIssue(
                        "diagnostics/findings.json",
                        "expected a JSON array of findings",
                        "",
                    )
                )
            else:
                for i, finding in enumerate(findings):
                    issues.extend(
                        _issues_from_validator(
                            finding_validator,
                            finding,
                            f"diagnostics/findings.json[{i}]",
                        )
                    )

    # path-stability check: every "screenshots/" reference in steps should
    # either exist on disk or be listed in manifest.missing.
    declared_missing = set(manifest.get("missing", []) or [])
    if steps_dir.exists():
        for step_file in sorted(steps_dir.rglob("*.json")):
            rel = step_file.relative_to(root).as_posix()
            try:
                step = _read_json(step_file)
            except json.JSONDecodeError:
                continue
            for key in ("observation_pre", "observation_post"):
                ref = step.get(key)
                if not isinstance(ref, str) or not ref.startswith("screenshots/"):
                    continue
                if (root / ref).exists():
                    continue
                if ref in declared_missing:
                    continue
                issues.append(
                    ValidationIssue(
                        rel,
                        f"references {ref} which is neither on disk nor listed in manifest.missing",
                        key,
                    )
                )

    return issues


__all__ = ["ValidationIssue", "validate_bundle"]
