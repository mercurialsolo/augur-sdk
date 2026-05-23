# Redaction

CUA traces are sensitive — screenshots contain credentials, customer
data, business records. The SDK applies a **redaction policy** to every
bundle before it lands on disk or hits the network.

## Default: `default-pii-v1`

Ships in the box; applies to every bundle unless you override.

### What gets dropped (removed entirely, not masked)

These keys never make it into the bundle:

| Key                  | Why                                    |
|----------------------|----------------------------------------|
| `Authorization`      | HTTP auth header                       |
| `Cookie` / `Set-Cookie` | HTTP cookies                         |
| `X-API-Key`          | Common API-key header                  |
| `password` / `passwd` / `pwd` | Cleartext passwords           |
| `secret`             | Generic secret keys                    |

### What gets masked (key kept; value replaced with `***REDACTED:mask***`)

| Key            | Why                                |
|----------------|------------------------------------|
| `token`        | Generic tokens                     |
| `api_key` / `apiKey` | API keys at any depth        |
| `ssn`          | US social security numbers         |
| `credit_card` / `card_number` | PAN              |
| `cvv`          | Card verification value            |

### What gets regex-scrubbed in string values

Matches replaced inline with `***REDACTED:<kind>***`:

| Kind                | Pattern                                                       |
|---------------------|---------------------------------------------------------------|
| `bearer`            | `(?i)bearer\s+[A-Za-z0-9._\-]+`                              |
| `api_key`           | `(?i)(api[_-]?key\|x-api-key)\s*[:=]\s*[A-Za-z0-9._\-]+`     |
| `aws_key`           | `AKIA[0-9A-Z]{16}`                                            |
| `cookie_header`     | `(?i)cookie\s*:\s*[^\r\n]+`                                  |
| `set_cookie`        | `(?i)set-cookie\s*:\s*[^\r\n]+`                              |
| `email`             | `[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}`                    |
| `password_kv`       | `(?i)(password\|passwd\|pwd)\s*[:=]\s*\S+`                   |
| `jwt`               | `eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+`       |

## Step-level sensitivity

Adapters can mark a step as `sensitive=True`. When set:

- Pre/post screenshots are **dropped**, not just masked.
- Their paths land in `manifest.missing[]` so consumers know they were
  intentionally absent.
- Model I/O for that step is dropped.
- Decision-event `detail` payloads for that step are dropped (the
  `summary` survives so the trajectory is still legible).

## Customising

For tighter rules, subclass `RedactionPolicy`:

```python
from augur_sdk import DebugSession, RedactionPolicy

class StrictPolicy(RedactionPolicy):
    id = "staffai-strict-v1"
    drop_keys = RedactionPolicy.drop_keys | frozenset({"customer_email", "ip_address"})
    mask_keys = RedactionPolicy.mask_keys | frozenset({"order_id"})

with DebugSession(redaction_policy=StrictPolicy(), ...) as s:
    ...
```

Add a one-off scrubber without subclassing:

```python
policy = DefaultRedactionPolicy()
policy.add_redactor(lambda s: re.sub(r"acct_\w+", "***REDACTED:acct***", s))
policy.add_dropper(lambda key, value: key == "internal_id")
```

## What the bundle records

Every bundle's `manifest.json` carries:

```json
{
  "redaction": {
    "policy_id": "default-pii-v1",
    "applied": true
  }
}
```

so a consumer can decide whether to trust the bundle for export, replay,
or hand-off to a coding agent.

## Not redacted (read carefully)

The SDK does **not**:

- Pixel-mask regions of screenshots automatically. If a screenshot
  contains a credit card, the bytes still contain it. Mark the step
  `sensitive=True` to drop the screenshot, or supply your own
  region-mask in the adapter before calling `attach_observation`.
- Inspect binary artefacts (videos, model weights). Those go in via
  reference URLs only; treat the storage upstream of Augur as
  trust-equivalent to your CUA's host.
- Encrypt anything at rest. That's a deployment concern; encrypt the
  bundle directory like you would `/var/log`.
