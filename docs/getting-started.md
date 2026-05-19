# Getting started

Send your first Augur trace in **5 minutes**.

## 0. Prerequisites

- Python ≥ 3.11
- A computer-use agent (CUA) you can edit, even minimally
- Either:
  - Access to an Augur server (someone runs `augur serve`), **or**
  - A local checkout — bundles still write to disk

If you don't have an Augur server yet, see
[Run an Augur server](https://github.com/mercurialsolo/augur/blob/main/docs/server.md)
upstream. You can finish this guide without one (local-only mode).

## 1. Install

```bash
pip install augur-sdk
# or
uv pip install augur-sdk
```

Verify:

```bash
python -c "from augur_sdk import DebugSession; print(DebugSession.__doc__)"
```

## 2. Get a DSN (Sentry-style credential)

Ask an Augur admin to mint one for your workspace:

```bash
augur admin dsn-issue --tenant <your-tenant> --label <name-for-this-client>
```

The admin will paste back something like:

```text
export AUGUR_DSN='https://augur.your-org.com/api/v1?token=…&tenant=ops-prod'
```

That's the **only secret** the SDK needs. Bcrypt-hashed server-side; if
it leaks, the admin rotates it via `augur admin dsn-issue` again. See
[concepts/dsn.md](./concepts/dsn.md) for the full lifecycle.

> Skipping the server? You can do this guide **without** a DSN. The SDK
> writes the bundle to `out_dir` either way; streaming is observe-only on
> top.

## 3. Wrap your CUA loop

Find the place where your agent runs a step (`for action in plan:`, an
`@step` decorator, whatever) and wrap the whole run in a `DebugSession`.

```python
import os
from augur_sdk import CaptureMode, DebugSession

with DebugSession(
    run_id=run_id,                              # whatever you call this run
    client_name="myagent",
    client_version="2.3.0",
    capture_mode=CaptureMode.SCREENSHOTS,       # see concepts/capture-modes.md
    out_dir=f"/var/log/augur/{run_id}",         # local bundle root
    tags={"env": "staging", "user_id": "abc"},  # arbitrary key/value
) as session:
    for i, step in enumerate(my_cua.run()):
        pre  = session.attach_observation(step_index=i, kind="pre",  png_bytes=step.pre_png)
        post = session.attach_observation(step_index=i, kind="post", png_bytes=step.post_png)
        session.record_step({
            "step_id":          f"{run_id}/step/{i:04d}",
            "step_index":       i,
            "step_type":        step.action_type,       # "click" / "type" / "navigate" / …
            "intent":           step.intent,            # human-readable
            "status":           "succeeded" if step.ok else "failed",
            "started_at":       step.started_at,        # ISO-8601 UTC
            "observation_pre":  pre,
            "observation_post": post,
            "action": {
                "type":              step.action_type,
                "params":            {"x": step.x, "y": step.y},
                "coordinate_space":  "viewport_css_px",
                "dispatch_backend":  "playwright",
            },
            "grounding": {
                "provider":   "myagent",
                "provenance": "screenshot",   # MUST be 'screenshot' for CUA semantics
            },
            "verdict": {"status": "passed" if step.ok else "failed"},
        })

        # Optional but valuable — surface the brain's decisions:
        session.record_event({
            "ts":         step.ts,
            "step_index": i,
            "layer":      "model",
            "kind":       "decision",
            "summary":    f"chose {step.action_type} at ({step.x},{step.y})",
        })
```

That's the whole integration.

## 4. Run a session + see the bundle

Run your CUA once. Then:

```bash
ls /var/log/augur/<run_id>/
# → manifest.json, trace.json, AGENT.md, steps/, events/, screenshots/, schema/
```

If `AUGUR_DSN` was set, the run also appears in your Augur workspace at
`/<tenant>/` with the connection-status badge turning green while the
session is open.

## 5. Make sense of a failure

When a run fails:

```bash
# Locally
augur summarize  /var/log/augur/<run_id>
augur diagnose   /var/log/augur/<run_id> --rules cua
augur agent-prompt /var/log/augur/<run_id>   # markdown you can paste into Claude / Cursor

# Or in the viewer
augur view /var/log/augur/<run_id>
```

For coding-agent workflows specifically, see
[coding-agent-quickstart.md](./coding-agent-quickstart.md).

## Next steps

- [concepts/capture-modes.md](./concepts/capture-modes.md) — pick the
  right cost/value tradeoff for production vs debugging.
- [concepts/redaction.md](./concepts/redaction.md) — what the default
  policy scrubs; how to ship a stricter one.
- [integrations/playwright.md](./integrations/playwright.md) — drop-in
  patterns for Playwright runners.
- [integrations/mantis.md](./integrations/mantis.md) — if you're using Mantis.
- [reference/api.md](./reference/api.md) — every public symbol.
