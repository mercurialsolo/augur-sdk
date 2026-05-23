"""Bundle writer.

Serializes the in-memory recorder state into the path-stable layout defined in
`docs/bundle-layout.md`.

Every bundle also ships with:

- `AGENT.md`  — a tiny markdown index oriented at coding agents. First-read
  hints, suggested follow-up paths per finding type, and a summary of what's
  inside.
- `schema/*.schema.json` — copies of the canonical JSON Schemas from
  `augur_sdk._schema`, so an offline agent has the validator in-hand without a
  network round-trip.

Both are written automatically; producers don't need to opt in.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from augur_sdk._schema import SCHEMA_VERSION, list_schemas, load_schema
from augur_sdk.fingerprint import compute_trajectory_fingerprint
from augur_sdk.models import (
    BundleManifest,
    BundleTrace,
    DebugSession,
    DecisionEvent,
    StepTrace,
)
from augur_sdk.recorder import EventRecorder
from augur_sdk.redaction import RedactionPolicy
from augur_sdk.storage import Store


def _step_path(step_index: int) -> str:
    return f"steps/{step_index:04d}.json"


def _screenshot_path(step_index: int, kind: str) -> str:
    return f"screenshots/{step_index:04d}_{kind}.png"


def _events_path_for_step(step_index: int) -> str:
    return f"events/{step_index:04d}.jsonl"


def _events_path_unscoped() -> str:
    return "events/run.jsonl"


_PATH_MAP = {
    "steps": "steps/",
    "screenshots": "screenshots/",
    "crops": "crops/",
    "diffs": "diffs/",
    "events": "events/",
    "logs": "logs/",
    "replay": "replay/",
    "diagnostics": "diagnostics/",
    "modelio": "modelio/",
    "side_effects": "side_effects/",
    "preferences": "preferences/",
    "schema": "schema/",
    "agent": "AGENT.md",
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def write_bundle(
    *,
    store: Store,
    session: DebugSession,
    recorder: EventRecorder,
    policy: RedactionPolicy,
    include_signatures: bool = True,
) -> BundleManifest:
    """Write the bundle to `store` and return the manifest dict.

    The session's `schema_version` is forced to the schema package version so
    callers do not have to remember to set it. Steps and events are redacted
    via `policy` before serialization.
    """
    session = dict(session)  # type: ignore[assignment]
    session["schema_version"] = SCHEMA_VERSION

    steps_raw = recorder.all_steps()
    events_grouped = recorder.all_events_grouped()

    steps = [policy.apply(s) for s in steps_raw]
    redacted_events_grouped: dict[int | None, list[DecisionEvent]] = {
        k: [policy.apply(e) for e in v] for k, v in events_grouped.items()
    }

    # observation bytes — already-redacted by the SDK before staging, just write
    observation_bytes = recorder.staged_observations()
    signatures: dict[str, str] = {}

    # 1. screenshots
    for relpath, data in observation_bytes.items():
        with store.open_write_binary(relpath) as f:
            f.write(data)
        if include_signatures:
            signatures[relpath] = _sha256(data)

    # 1b. modelio records (#56 producer side, since 0.1.8)
    modelio_records = recorder.staged_modelio()
    for relpath, record in modelio_records.items():
        payload = _dumps(record)
        with store.open_write_text(relpath) as f:
            f.write(payload)
        if include_signatures:
            signatures[relpath] = _sha256(payload.encode("utf-8"))

    # 2. per-step JSON
    for step in steps:
        idx = step["step_index"]
        payload = _dumps(step)
        with store.open_write_text(_step_path(idx)) as f:
            f.write(payload)
        if include_signatures:
            signatures[_step_path(idx)] = _sha256(payload.encode("utf-8"))

    # 3. events JSONL — one file per step, plus an unscoped file for run-level
    for step_index, evs in redacted_events_grouped.items():
        if not evs:
            continue
        sorted_evs = sorted(
            evs,
            key=lambda e: (
                e.get("ts", ""),
                e.get("layer", ""),
                e.get("kind", ""),
                e.get("summary", ""),
            ),
        )
        relpath = (
            _events_path_for_step(step_index)
            if step_index is not None
            else _events_path_unscoped()
        )
        body_lines = [json.dumps(e, sort_keys=True, ensure_ascii=False) for e in sorted_evs]
        body = "\n".join(body_lines) + "\n"
        with store.open_write_text(relpath) as f:
            f.write(body)
        if include_signatures:
            signatures[relpath] = _sha256(body.encode("utf-8"))

    # 3b. eval_candidates.json — tagged regression-fixture candidates (#16).
    # Only emitted when at least one step was tagged; empty bundles get no file.
    eval_candidates = recorder.staged_eval_candidates()
    if eval_candidates:
        payload = _dumps({"candidates": eval_candidates})
        with store.open_write_text("eval_candidates.json") as f:
            f.write(payload)
        if include_signatures:
            signatures["eval_candidates.json"] = _sha256(payload.encode("utf-8"))

    # 3c. outcomes.json — coupled (verdict, cost, task_class) records (#18).
    outcomes = recorder.staged_outcomes()
    if outcomes:
        outcomes_payload = _dumps({"outcomes": outcomes})
        with store.open_write_text("outcomes.json") as f:
            f.write(outcomes_payload)
        if include_signatures:
            signatures["outcomes.json"] = _sha256(outcomes_payload.encode("utf-8"))

    # 3e. side_effects/ — irreversible-action ledger keyed by step + id (#11).
    side_effects = recorder.staged_side_effects()
    for record in side_effects:
        sid = record.get("side_effect_id", "unknown")
        step_idx = record.get("step_index", 0)
        relpath = f"side_effects/{int(step_idx):04d}-{sid}.json"
        payload = _dumps(record)
        with store.open_write_text(relpath) as f:
            f.write(payload)
        if include_signatures:
            signatures[relpath] = _sha256(payload.encode("utf-8"))

    # 3d. events/reasoning.jsonl — reasoning records (#14). One line per
    # record so streaming consumers can `tail -f` and so the file stays
    # append-only if a future SDK version writes incrementally.
    reasoning = recorder.staged_reasoning()
    if reasoning:
        reasoning_payload = (
            "\n".join(
                json.dumps(r, sort_keys=True, ensure_ascii=False) for r in reasoning
            )
            + "\n"
        )
        with store.open_write_text("events/reasoning.jsonl") as f:
            f.write(reasoning_payload)
        if include_signatures:
            signatures["events/reasoning.jsonl"] = _sha256(
                reasoning_payload.encode("utf-8")
            )

    # 4. trace.json (session + steps)
    trace: BundleTrace = {"session": session, "steps": steps}
    trace_payload = _dumps(trace)
    with store.open_write_text("trace.json") as f:
        f.write(trace_payload)
    if include_signatures:
        signatures["trace.json"] = _sha256(trace_payload.encode("utf-8"))

    # 5. manifest.json
    manifest: BundleManifest = {
        "schema_version": SCHEMA_VERSION,
        "bundle_format": "augur-bundle",
        "run_id": session["run_id"],
        "debug_session_id": session["debug_session_id"],
        "client": dict(session.get("client", {})),  # type: ignore[typeddict-item]
        "capture_mode": session["capture_mode"],
        "created_at": datetime.now(UTC).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        ),
        "redaction": {"policy_id": policy.id, "applied": True},
        "trace": "trace.json",
        "step_count": len(steps),
        "paths": _PATH_MAP,  # type: ignore[typeddict-item]
    }
    missing = _compute_missing(steps, observation_bytes)
    if missing:
        manifest["missing"] = missing
    session_costs = session.get("costs")
    if isinstance(session_costs, dict) and session_costs:
        manifest["costs"] = dict(session_costs)  # type: ignore[typeddict-unknown-key]
    # #19: trajectory fingerprint over the (action, failure_or_verdict,
    # target_label) sequence so the platform's failure-mode clustering
    # has a cheap discriminator. Only emitted for non-empty traces;
    # empty bundles get no fingerprint.
    if steps:
        manifest["trajectory_fingerprint"] = compute_trajectory_fingerprint(
            [dict(s) for s in steps]
        )

    # 6. AGENT.md — coding-agent-oriented index. We write this BEFORE adding
    # its signature to the manifest so the digest covers the rendered file.
    agent_md = _render_agent_md(session, steps, manifest)
    with store.open_write_text("AGENT.md") as f:
        f.write(agent_md)
    if include_signatures:
        signatures["AGENT.md"] = _sha256(agent_md.encode("utf-8"))

    # 7. schema/<name>.schema.json — bundled copies of the canonical schemas
    # so a coding agent can validate records without a network round-trip.
    for schema_relpath, payload in _bundled_schema_files():
        with store.open_write_text(schema_relpath) as f:
            f.write(payload)
        if include_signatures:
            signatures[schema_relpath] = _sha256(payload.encode("utf-8"))

    if include_signatures:
        manifest["signatures"] = signatures

    manifest_payload = _dumps(manifest)
    with store.open_write_text("manifest.json") as f:
        f.write(manifest_payload)

    return manifest


# ── AGENT.md + bundled schemas ───────────────────────────────────────────────


def _render_agent_md(
    session: DebugSession,
    steps: list[StepTrace],
    manifest: BundleManifest,
) -> str:
    """Tight markdown index aimed at coding agents.

    Deliberately short — agents are bandwidth-constrained on context, so we
    surface the deterministic paths, schema version, and the first failure's
    location rather than embedding any of the actual data.
    """
    run_id = session.get("run_id", "?")
    client = session.get("client", {}) or {}
    client_name = client.get("name", "?")
    capture = session.get("capture_mode", "?")
    status = session.get("status", "?")
    step_count = manifest.get("step_count", len(steps))

    first_failed = _first_failed_step(steps)
    failure_class_summary = _failure_class_summary(steps)

    lines: list[str] = [
        f"# Augur bundle — {run_id}",
        "",
        f"- **Bundle format**: `augur-bundle` (schema_version: `{manifest.get('schema_version', SCHEMA_VERSION)}`)",
        f"- **Client**: `{client_name}`"
        + (f" (version `{client.get('version')}`)" if client.get("version") else ""),
        f"- **Capture mode**: `{capture}`",
        f"- **Status**: `{status}`",
        f"- **Steps**: {step_count}",
    ]
    if first_failed is not None:
        idx = first_failed.get("step_index")
        intent = first_failed.get("intent", "")
        fc = first_failed.get("failure_class")
        lines.append(
            f"- **First failed step**: `{idx:04d}` — {intent}"
            + (f" (`{fc}`)" if fc else "")
        )
    if failure_class_summary:
        lines.append(f"- **Failure classes**: {failure_class_summary}")

    lines += [
        "",
        "## Layout",
        "",
        "Every path below is **stable**. Read directly — no discovery needed.",
        "",
        "| Path                                | Format | What it carries                              |",
        "|-------------------------------------|--------|----------------------------------------------|",
        "| `manifest.json`                     | JSON   | Bundle envelope (paths, signatures, missing) |",
        "| `trace.json`                        | JSON   | Session + ordered `steps[]`                  |",
        "| `steps/<NNNN>.json`                 | JSON   | One `StepTrace` per file                     |",
        "| `events/<NNNN>.jsonl`               | JSONL  | Decision events for a step                   |",
        "| `events/run.jsonl`                  | JSONL  | Run-level decision events (when present)     |",
        "| `screenshots/<NNNN>_pre.png` `_post.png` | PNG  | Pre/post observations (when captured)       |",
        "| `diagnostics/findings.json`         | JSON   | Diagnostic-rule findings with evidence refs  |",
        "| `logs/*.log`                        | text   | Adapter-supplied logs (when present)         |",
        "| `schema/*.schema.json`              | JSON   | Canonical record schemas — validate locally  |",
        "",
        "## Suggested first reads",
        "",
        "1. `manifest.json` — sniff `bundle_format` + `schema_version`; look for `missing[]`.",
    ]
    if first_failed is not None:
        idx = first_failed.get("step_index")
        lines.append(f"2. `steps/{int(idx or 0):04d}.json` — the first failed step.")
        lines.append(f"3. `events/{int(idx or 0):04d}.jsonl` — the decision trail for that step.")
        lines.append("4. `diagnostics/findings.json` — if present, look for findings whose `step_index` matches.")
    else:
        lines.append("2. `trace.json` — full session + steps in one file.")
        lines.append("3. `diagnostics/findings.json` — if present, severity-sorted findings.")

    lines += [
        "",
        "## Citing evidence",
        "",
        "Findings in `diagnostics/findings.json` carry `evidence[].ref` pointing at",
        "exact paths inside this bundle. Cite by `<rule_id> @ <path>` so the human",
        "(or another agent) can verify in O(1).",
        "",
        "## Failure-class taxonomy",
        "",
        "Generic CUA classes (no namespace) match generic rules. Adapter-specific",
        "classes are namespaced under `<adapter>.*` (e.g. `mantis.wrong_target`).",
        "Full table: `docs/failure-class-taxonomy.md` in the Augur source tree.",
        "",
        "## CUA contract",
        "",
        "Runtime action selection is **screenshot-grounded** (`grounding.provenance",
        "== 'screenshot'`). Coordinates tagged `dom` or `diagnostic` are evidence,",
        "not runtime inputs — flag any rule that treats them as the latter.",
        "",
    ]
    return "\n".join(lines)


def _first_failed_step(steps: list[StepTrace]) -> StepTrace | None:
    for s in steps:
        status = s.get("status")
        if status in ("failed", "halted", "halt"):
            return s
    return None


def _failure_class_summary(steps: list[StepTrace]) -> str:
    counts: dict[str, int] = {}
    for s in steps:
        fc = s.get("failure_class")
        if isinstance(fc, str) and fc:
            counts[fc] = counts.get(fc, 0) + 1
    if not counts:
        return ""
    items = sorted(counts.items(), key=lambda kv: -kv[1])
    return ", ".join(f"`{name}` ×{n}" for name, n in items)


def _bundled_schema_files() -> list[tuple[str, str]]:
    """Return (bundle-relative-path, JSON text) for every canonical schema."""
    out: list[tuple[str, str]] = []
    for name in list_schemas():
        schema = load_schema(name)
        # Strip the absolute $id so the bundled copy is self-contained; we
        # don't want consumers resolving against augur.dev.
        payload = json.dumps(schema, indent=2, sort_keys=True) + "\n"
        out.append((f"schema/{name}.schema.json", payload))
    return out


def _compute_missing(
    steps: list[StepTrace], observation_bytes: dict[str, bytes]
) -> list[str]:
    """Return bundle-relative paths the producer expected to exist but didn't.

    The contract (docs/bundle-layout.md): if a step references
    observation_pre/post with a non-null path that wasn't staged, list it
    here. Late attach scenarios set the field to None on the step itself —
    those are not reported in `missing` (they are not expected to be present).
    """
    missing: list[str] = []
    for step in steps:
        for key in ("observation_pre", "observation_post"):
            ref = step.get(key)
            if ref is None:
                continue
            if isinstance(ref, str) and ref.startswith("screenshots/") and ref not in observation_bytes:
                missing.append(ref)
    return sorted(set(missing))


__all__ = ["write_bundle"]
