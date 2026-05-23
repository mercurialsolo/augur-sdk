# Augur SDK — developer docs

Augur is a debugger for **screenshot-grounded computer-use agents** (CUAs).
This SDK is the only piece you need on the CUA side: one context manager,
one env var, and traces stream to your Augur workspace. Same model as
Sentry — instrument once, debug forever.

## Map

| If you want to…                                | Read this                                                |
|------------------------------------------------|----------------------------------------------------------|
| **Send your first trace in 5 minutes**         | [getting-started.md](./getting-started.md)               |
| Understand what a "DSN" is                     | [concepts/dsn.md](./concepts/dsn.md)                     |
| Understand what gets captured per mode         | [concepts/capture-modes.md](./concepts/capture-modes.md) |
| Understand the on-disk bundle layout           | [concepts/bundle-layout.md](./concepts/bundle-layout.md) |
| Understand the redaction defaults              | [concepts/redaction.md](./concepts/redaction.md)         |
| Run the diagnostic rules engine                | [concepts/diagnostics.md](./concepts/diagnostics.md)     |
| **Integrate with a generic Python CUA**        | [integrations/python.md](./integrations/python.md)       |
| Integrate with a Playwright runner             | [integrations/playwright.md](./integrations/playwright.md) |
| Integrate with Mantis                          | [integrations/mantis.md](./integrations/mantis.md)       |
| Hand a bundle to a coding agent (Claude/Cursor) | [coding-agent-quickstart.md](./coding-agent-quickstart.md) |
| See every public API symbol                    | [reference/api.md](./reference/api.md)                   |
| See the HTTP API a coding agent can call       | [reference/http-api.md](./reference/http-api.md)         |
| Implement an adapter for a new framework       | [reference/adapter-authoring.md](./reference/adapter-authoring.md) |
| Know the normative contract this SDK ships     | [spec.md](./spec.md)                                     |
| Track what changed across releases             | [changelog.md](./changelog.md)                           |

## The integration in one screen

```bash
pip install augur-sdk
export AUGUR_DSN='https://augur.example/api/v1?token=<key>&tenant=<slug>'
```

```python
from augur_sdk import CaptureMode, DebugSession

with DebugSession(
    run_id="run_abc",
    client_name="myagent",
    capture_mode=CaptureMode.SCREENSHOTS,
    out_dir="/var/log/augur/run_abc",
) as session:
    pre  = session.attach_observation(step_index=0, kind="pre",  png_bytes=...)
    post = session.attach_observation(step_index=0, kind="post", png_bytes=...)
    session.record_step({
        "step_id": "run_abc/step/0000",
        "step_index": 0,
        "step_type": "click",
        "status": "succeeded",
        "started_at": "...",
        "observation_pre": pre,
        "observation_post": post,
        "action":    {"type": "click", "params": {"x": 100, "y": 200},
                      "coordinate_space": "viewport_css_px",
                      "dispatch_backend": "playwright"},
        "grounding": {"provider": "myagent", "provenance": "screenshot"},
        "verdict":   {"status": "passed"},
    })
```

That's it. Skip to [getting-started.md](./getting-started.md) for the
full 5-minute path, including how to get a DSN.
