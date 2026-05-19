# augur-sdk

[![PyPI](https://img.shields.io/pypi/v/augur-sdk.svg)](https://pypi.org/project/augur-sdk/)
[![Python](https://img.shields.io/pypi/pyversions/augur-sdk.svg)](https://pypi.org/project/augur-sdk/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache_2.0-blue.svg)](LICENSE)

Instrument any **screenshot-grounded computer-use agent** (CUA) with one
context manager. Streams traces to an [Augur](https://github.com/mercurialsolo/augur)
server (Sentry-style DSN) AND writes a path-stable bundle to disk —
both work, both at once, no extra glue.

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
        "step_id":          "run_abc/step/0000",
        "step_index":       0,
        "step_type":        "click",
        "intent":           "Click the login button",
        "status":           "succeeded",
        "started_at":       "2026-05-19T00:00:00Z",
        "observation_pre":  pre,
        "observation_post": post,
        "action":   {"type": "click", "params": {"x": 100, "y": 200},
                     "coordinate_space": "viewport_css_px",
                     "dispatch_backend": "playwright"},
        "grounding": {"provider": "myagent", "provenance": "screenshot"},
        "verdict":   {"status": "passed"},
    })
```

Set `AUGUR_DSN=…` and the same code streams to your Augur server. No code
change required to switch between local-only and hosted modes.

## Install

### From PyPI (when published)

```bash
pip install augur-sdk
# or
uv pip install augur-sdk
```

### From source (today)

```bash
git clone https://github.com/mercurialsolo/augur-sdk.git
cd augur-sdk
pip install -e .
# or
uv pip install -e .
```

### Requirements

- Python ≥ 3.11
- `jsonschema`, `referencing`, `urllib3` (installed automatically)

The SDK is **zero-monorepo**: JSON Schemas are vendored inside the package
(`augur_sdk._schema`), so `import augur_sdk` doesn't require any sibling
Augur packages. The Augur server, viewer, and CLI live in the main
[`mercurialsolo/augur`](https://github.com/mercurialsolo/augur) repo — you
only need this package on the **client side** (your CUA runtime).

## Quickstart — three modes

### 1. Local-only (no server)

The default. Bundles are written under `out_dir/`. Use `augur view <dir>`
from the main Augur repo to render them in the viewer, or hand the path
to a coding agent.

```python
from augur_sdk import CaptureMode, DebugSession

with DebugSession(
    run_id="run_abc",
    client_name="myagent",
    out_dir="/var/log/augur/run_abc",
    capture_mode=CaptureMode.SCREENSHOTS,
) as session:
    ...
```

### 2. Stream to an Augur server (Sentry-style)

Set one env var; nothing else changes.

```bash
export AUGUR_DSN='https://augur.example/api/v1?token=<api_key>&tenant=<tenant_slug>'
```

The SDK heart-beats every 15 s while a session is open so the server's
connection-status indicator stays green. Each step + screenshot + event
streams over HTTPS with `Authorization: Bearer <api_key>`. The local
bundle is still written; streaming is observe-only on top.

Or pass the DSN directly:

```python
DebugSession(dsn="https://augur.example/api/v1?token=...&tenant=...", ...)
```

Get a DSN by asking an Augur admin to run:

```bash
augur admin dsn-issue --tenant <your-tenant> --label <client-name>
```

### 3. Adapter pattern (existing CUA exports)

Already have a trace exporter (Mantis-style)? Write a small adapter that
maps your shape to Augur records. See the upstream
[adapter authoring guide](https://github.com/mercurialsolo/augur/blob/main/docs/adapter-authoring.md).

## What gets written

Every bundle is path-stable — no discovery needed:

```text
out_dir/
  manifest.json           # envelope: schema_version, bundle_format, paths, signatures
  trace.json              # session + ordered steps[]
  AGENT.md                # coding-agent-friendly index (first-read hints, layout)
  steps/0000.json         # one StepTrace per file
  events/0000.jsonl       # decision events per step (planner / grounding / verifier / recovery)
  screenshots/0000_pre.png
  screenshots/0000_post.png
  diagnostics/findings.json   # if `augur diagnose` has been run
  schema/*.schema.json    # canonical record schemas (vendored for offline validation)
```

The same bundle drives the viewer, the CLI, and any coding agent. See
[`docs/bundle-layout.md`](https://github.com/mercurialsolo/augur/blob/main/docs/bundle-layout.md)
upstream for the full normative spec.

## Capture modes

The `capture_mode` arg controls how much the SDK writes:

| Mode          | What it captures                                                | Cost |
|---------------|-----------------------------------------------------------------|------|
| `off`         | Manifest envelope only                                          | none |
| `metadata`    | + run/step ids, status, action type, failure class              | tiny |
| `trace`       | + decisions, verifier output, recovery, grounding summary       | low  |
| `screenshots` | + pre/post PNGs + coordinate overlays                           | med  |
| `video`       | + video / MJPEG references                                      | med  |
| `model_io`    | + prompts, model responses, redacted secrets                    | med  |
| `dispatch`    | + input dispatch details, retries, post-action state checks     | low  |
| `replay`      | + observation/task/context state for replay fixtures            | med  |
| `full`        | All above, subject to redaction + retention                     | high |

Set via `capture_mode=CaptureMode.FULL` or `AUGUR_CAPTURE_MODE=full`.

## Redaction

`default-pii-v1` ships in the box and is applied to every bundle:

- Drops `Authorization`, `Cookie`, `Set-Cookie`, `X-API-Key` headers entirely.
- Masks `token`, `api_key`, `ssn`, `credit_card`, `cvv` keys.
- Regex-scrubs bearer tokens, AWS keys, JWTs, password=… patterns out of strings.
- Honors `sensitive=True` on a step: pre/post screenshots are dropped.

Subclass `augur_sdk.RedactionPolicy` for tighter rules:

```python
from augur_sdk import DebugSession, RedactionPolicy

class StrictPolicy(RedactionPolicy):
    id = "strict-v1"
    drop_keys = RedactionPolicy.drop_keys | frozenset({"customer_email"})

DebugSession(redaction_policy=StrictPolicy(), ...)
```

## Diagnostics

Augur ships a generic CUA rules pack you can run against any bundle:

```python
from augur_sdk.diagnostics import RulesEngine, load_pack

engine = RulesEngine(load_pack("cua"))
findings = engine.evaluate("/path/to/bundle")
for f in findings:
    print(f["severity"], f["rule_id"], f["summary"])
```

Adapter-specific packs (e.g. `mantis`) are registered via the
`augur.rule_packs` entry-point group; install the corresponding adapter
package alongside this SDK and they appear automatically in
`load_pack(...)`.

## CUA contract — what the SDK enforces

Per Augur's design invariant: **runtime action selection MUST remain
screenshot-grounded**. The SDK doesn't enforce this at write time, but
the diagnostic-rules engine and the viewer both flag DOM-derived
coordinates that show up in `grounding.provenance != "screenshot"` and
get used as runtime inputs. Tag DOM probes as `provenance: dom` so they
stay visible as **diagnostic** evidence without being mistaken for the
agent's real target.

## Develop

```bash
git clone https://github.com/mercurialsolo/augur-sdk.git
cd augur-sdk
uv sync                 # creates .venv and installs dev deps
uv run pytest           # tests
uv run ruff check .     # lint
uv run mypy -p augur_sdk  # types
```

## Publish to PyPI

The package is set up to publish via standard tooling. To cut a release:

```bash
# 1. Bump version in src/augur_sdk/_version.py and pyproject.toml
# 2. Update CHANGELOG.md
# 3. Build sdist + wheel
uv build
# 4. Upload (requires PYPI_API_TOKEN)
uv publish
# or:
pip install twine
twine upload dist/*
```

To enable **automated** publish on git tag:

1. Add `PYPI_API_TOKEN` to your GitHub repo secrets.
2. Push a tag matching `v*` (e.g. `v0.1.0`).
3. The workflow in `.github/workflows/release.yml` builds + publishes.

```bash
git tag v0.1.0 -m "Initial release"
git push origin v0.1.0
```

## Where Augur lives

This is the **client-side SDK only**. The Augur server, viewer, CLI,
diagnostic rule packs, and Mantis adapter live in the umbrella repo:

- **Main Augur repo**: https://github.com/mercurialsolo/augur
- **Issues, schemas, docs**: same repo, `docs/` and the GitHub issue tracker
- **Mantis adapter**: `packages/adapters/mantis/` upstream

The SDK is the only piece your CUA runtime actually needs. The rest is
operator-side.

## License

Apache 2.0 — see [LICENSE](LICENSE).
