# Capture modes

Capture mode is the cost/coverage dial. Pick a low setting for always-on
fleet observability; promote individual runs to a higher setting when
you need to debug.

## The modes

| Mode          | What it captures                                                 | Bytes per step | Cost  |
|---------------|------------------------------------------------------------------|----------------|-------|
| `off`         | Manifest envelope only                                            | 0              | none  |
| `metadata`    | + run/step ids, status, action type, failure class                | ~0.5 KB        | tiny  |
| `trace`       | + decisions, verifier output, recovery, grounding summary         | ~3 KB          | low   |
| `screenshots` | + pre/post PNGs + coordinate overlays                             | ~800 KB        | med   |
| `video`       | + video / MJPEG references                                        | reference only | med   |
| `model_io`    | + prompts, model responses, redacted secrets                      | ~30 KB         | med   |
| `dispatch`    | + input dispatch details, retries, post-action state checks       | ~5 KB          | low   |
| `replay`      | + observation/task/context state for replay fixtures              | ~50 KB         | med   |
| `full`        | All above, subject to redaction + retention                       | ~1 MB          | high  |

Modes are **ordered** in code (`CaptureMode.SCREENSHOTS > CaptureMode.TRACE`),
so adapters that want to check "is screenshot capture active?" can:

```python
if session.capture_mode >= CaptureMode.SCREENSHOTS:
    take_pre_screenshot()
```

## Where to set it

In order of precedence:

```python
# 1. Explicit argument — wins
DebugSession(capture_mode=CaptureMode.FULL, ...)

# 2. AUGUR_CAPTURE_MODE env var — covers an entire fleet
# export AUGUR_CAPTURE_MODE=screenshots

# 3. Default — off
```

## Recommended deployments

- **Always-on fleet observability**: `metadata` or `trace`. Free disk + bandwidth.
- **Staging / canary**: `screenshots`. Useful overlays for grounding bugs.
- **Active debugging**: `full`. Tag the run, rotate retention after a week.
- **Sensitive workflows** (PCI, PII): set redaction + drop to `metadata`
  unless the operator explicitly opts in.

## Capture mode does NOT control redaction

A `full` capture is still redacted by the active `RedactionPolicy`. The
mode controls **what** is captured; the policy controls **how** it is
written. See [redaction.md](./redaction.md).
