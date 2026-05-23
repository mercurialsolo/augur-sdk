# Generic Python CUA

Pattern for any Python CUA where you control the per-step loop.

## The whole integration

```python
import os, time
from augur_sdk import CaptureMode, DebugSession

run_id = f"run_{int(time.time())}"

with DebugSession(
    run_id=run_id,
    client_name="myagent",
    client_version="2.3.0",
    client_git_sha=os.environ.get("GIT_SHA", ""),
    capture_mode=CaptureMode.SCREENSHOTS,
    out_dir=f"/var/log/augur/{run_id}",
    tags={"env": "prod", "task_id": task.id},
) as session:

    for i, step in enumerate(my_cua.run()):
        # 1. Stage screenshots (no-op when capture_mode < screenshots)
        pre  = session.attach_observation(step_index=i, kind="pre",  png_bytes=step.pre_png)
        post = session.attach_observation(step_index=i, kind="post", png_bytes=step.post_png)

        # 2. Record the step
        session.record_step({
            "step_id":          f"{run_id}/step/{i:04d}",
            "step_index":       i,
            "step_type":        step.action_type,
            "intent":           step.intent,
            "status":           "succeeded" if step.ok else "failed",
            "failure_class":    step.failure_class,    # optional
            "started_at":       step.started_at,       # ISO-8601 UTC
            "ended_at":         step.ended_at,
            "duration_ms":      step.duration_ms,
            "observation_pre":  pre,
            "observation_post": post,
            "action": {
                "type":              step.action_type,
                "params":            step.action_params,
                "coordinate_space":  "viewport_css_px",
                "dispatch_backend":  "playwright",
            },
            "grounding": {
                "provider":      step.grounding.provider,
                "target_label":  step.grounding.label,
                "coordinates":   {"x": step.grounding.x, "y": step.grounding.y},
                "confidence":    step.grounding.confidence,
                "evidence":      step.grounding.evidence_text,
                "provenance":    "screenshot",   # ALWAYS for CUA contract
            },
            "verdict": {
                "status":  step.verdict,
                "reason":  step.verdict_reason,
            },
        })

        # 3. Optionally surface decision events
        for ev in step.decision_events:
            session.record_event({
                "ts":         ev.ts,
                "step_index": i,
                "layer":      ev.layer,
                "kind":       ev.kind,
                "summary":    ev.summary,
                "detail":     ev.detail,
            })

    if cua_halted:
        session.set_status("halted")
```

## Common shapes

### Async loops

`DebugSession` is a regular (sync) context manager. If your CUA is
async, wrap the whole run in `asyncio.to_thread(...)` — the SDK does its
own thread-pool for outbound HTTP, so blocking-style writes are fine.

```python
async def run_async():
    def _run():
        with DebugSession(...) as s:
            ...
    await asyncio.to_thread(_run)
```

### Long-running runs with many steps

The bundle writer streams steps to disk as you record them. No memory
ceiling at thousands of steps; just be mindful of screenshot size if you
capture every pre + post (~1 MB each on a 1440×900 PNG).

### Late attach

If you only want to start capturing partway through:

```python
# Steps 0..4 are NOT captured.
with DebugSession(...) as session:
    # Tell the SDK steps 0..4 were intentionally skipped:
    for i in range(5):
        session.record_step({
            "step_id": f"{run_id}/step/{i:04d}",
            "step_index": i,
            "step_type": "verify",
            "status": "skipped",
            "started_at": "...",
            "observation_pre":  None,   # tells the bundle writer this is intentional
            "observation_post": None,
        })
    # Capture from step 5 onward.
```

The viewer renders skipped steps as `unavailable`, not `blank`.

### Streaming + local mode at once

When `AUGUR_DSN` is set, the SDK streams to the server **and** writes
locally. There's no separate "local-only" mode to toggle; turning
streaming on or off is a matter of whether the env var is set.

## What you don't need to do

- Don't generate `step_id` randomly — the convention is
  `<run_id>/step/<zero-padded-index>` and the validator checks it.
- Don't pre-serialize JSON yourself — pass dicts; the SDK calls
  `json.dumps` with sorted keys.
- Don't worry about atomic writes — the SDK uses `.tmp + os.replace` so
  a viewer reading the bundle mid-run never sees a half-step file.
- Don't worry about retrying on network failure — the streaming sink is
  best-effort and never raises.

## See also

- [Capture modes](../concepts/capture-modes.md) — pick a default for prod
- [Redaction](../concepts/redaction.md) — what's scrubbed before bytes hit disk
- [Reference / API](../reference/api.md) — every public symbol
