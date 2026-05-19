# Mantis

[Mantis](https://github.com/mercurialsolo/mantis) is the reference
client-zero CUA — Holo3 + Claude over Xvfb + Chrome + xdotool. There are
two integration paths.

## Path A — Post-hoc ingest (zero Mantis code changes)

Best when Mantis is operated by someone else and you can only observe
its on-disk output.

### Step 1 — Enable Mantis's TraceExporter

Set on the Mantis runtime container:

```bash
MANTIS_TRACE_EXPORT_DIR=/workspace/mantis-data/traces
MANTIS_TRACE_INCLUDE_SCREENSHOTS=1
```

Mantis writes per-run:

```
$MANTIS_TRACE_EXPORT_DIR/<tenant>/<run_id>.json              # the trace
$MANTIS_TRACE_EXPORT_DIR/<tenant>/<run_id>_screens/<NNNN>.png # POST screenshots
$MANTIS_TRACE_EXPORT_DIR/<tenant>/<run_id>.reasoning.jsonl    # decision events
```

### Step 2 — Convert into an Augur bundle

On a host that can both reach the Mantis export dir and your Augur server:

```bash
# Install the umbrella tooling (CLI + Mantis adapter)
pip install augur-cli augur-adapter-mantis

# Per-run conversion (idempotent)
export AUGUR_DSN='https://augur.example/api/v1?token=…&tenant=<your-tenant>'

augur bundle --adapter mantis \
    $MANTIS_TRACE_EXPORT_DIR/<tenant>/<run_id>.json \
    --output /tmp/augur-bundles/<run_id>

augur validate /tmp/augur-bundles/<run_id>
augur diagnose /tmp/augur-bundles/<run_id> --rules mantis
```

The adapter converts the Mantis shape (epoch timestamps, POST-only
screenshots, `data` failure strings, reasoning event taxonomy) into the
Augur schema. With `AUGUR_DSN` set, the bundle also streams to your
workspace; without it, it's just on-disk.

Hook this into a cron, a Modal webhook, or a CI job — Mantis itself
needs nothing more than the env vars in step 1.

## Path B — Streaming directly from Mantis (recommended)

Best when you control the Mantis deployment. Two-line patch into the
Mantis runner gives you **live streaming + connection-status badge** as
the run executes.

### Step 1 — Install the SDK in Mantis's image

In Mantis's `pyproject.toml` (or equivalent):

```toml
dependencies = [
    ...,
    "augur-sdk>=0.1.0",
]
```

### Step 2 — Wrap the per-run loop

In `mantis_agent/gym/run_executor.py` (or wherever Mantis runs steps):

```python
import os, time
from datetime import datetime, UTC
from augur_sdk import CaptureMode, DebugSession

def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

def run_with_augur(runner) -> None:
    run_id = runner.run_key

    with DebugSession(
        run_id=run_id,
        client_name="mantis",
        client_version=os.environ.get("MANTIS_VERSION", ""),
        client_git_sha=os.environ.get("MANTIS_GIT_SHA", ""),
        capture_mode=CaptureMode.SCREENSHOTS,
        out_dir=f"/workspace/mantis-data/augur/{run_id}",
        tags={"tenant": runner.tenant_id, "session": runner.session_name},
    ) as augur:

        for step in runner.run():
            # POST screenshot is what Mantis always has (TraceExporter convention)
            post_path = augur.attach_observation(
                step_index=step.step_index, kind="post",
                png_bytes=step.screenshot_png,
            )

            augur.record_step({
                "step_id":         f"{run_id}/step/{step.step_index:04d}",
                "step_index":      step.step_index,
                "step_type":       step.last_action.action_type.value,
                "intent":          step.intent,
                "status":          "succeeded" if step.success else "failed",
                "started_at":      _iso(step.started_at),
                "duration_ms":     int(step.duration * 1000),
                "observation_pre":  None,        # Mantis doesn't capture pre
                "observation_post": post_path,
                "action": {
                    "type":             step.last_action.action_type.value,
                    "params":           dict(step.last_action.params or {}),
                    "coordinate_space": "viewport_css_px",
                    "dispatch_backend": "cdp",
                },
                "grounding": {"provider": "mantis", "provenance": "screenshot"},
                "verdict": {
                    "status": "passed" if step.success else "failed",
                    "reason": step.observed_outcome or step.data,
                },
            })

            # Optional: forward Mantis reasoning events
            for ev in step.reasoning_events:
                augur.record_event({
                    "ts":         ev.ts,
                    "step_index": step.step_index,
                    "layer":      _MANTIS_LAYER_MAP.get(ev.layer, "runner"),
                    "kind":       _MANTIS_KIND_MAP.get(ev.kind, "info"),
                    "summary":    ev.summary,
                    "detail":     ev.detail,
                })

        if runner.halted:
            augur.set_status("halted")


_MANTIS_LAYER_MAP = {
    "critic-frontier":   "verifier",
    "agentic-recovery":  "step_recovery",
    "som-click":         "grounding",
    "gate-decision":     "verifier",
}
_MANTIS_KIND_MAP = {
    "fire":     "decision",
    "skip":     "info",
    "decision": "decision",
    "result":   "observation",
}
```

### Step 3 — Configure the env

```bash
AUGUR_DSN='https://augur.example/api/v1?token=…&tenant=<your-tenant>'

# Optional — Mantis can keep writing its own TraceExporter alongside
MANTIS_TRACE_EXPORT_DIR=/workspace/mantis-data/traces
MANTIS_TRACE_INCLUDE_SCREENSHOTS=1
```

That's the whole integration. The SDK heartbeats every 15 s while a run
is open; the Augur workspace's connection-status badge turns green and
stays green for the run.

## Which path to pick

| If…                                                  | Use     |
|------------------------------------------------------|---------|
| You don't control the Mantis deployment              | Path A  |
| You want live streaming + connection badge           | Path B  |
| You want both an Augur bundle AND a Mantis trace dir | Either; they coexist |
| You want the diagnostic rule pack                    | Both — `augur diagnose --rules mantis` works on the resulting bundle |

## Failure-class taxonomy

Mantis's `failure_class.classify()` returns its own vocabulary
(`cf_challenge`, `nav_timeout`, `wrong_target`, `brain_loop_exhausted`,
…). The Mantis adapter canonicalises these against the Augur
failure-class taxonomy; the canonical vocabulary is fixed by the
vendored schema `src/augur_sdk/_schema/json/failure_class.schema.json`.
