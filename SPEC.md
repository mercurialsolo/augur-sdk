# augur-sdk — normative spec

**Status:** Draft, v0.1.
**Audience:** Implementers of the Augur SDK and anyone integrating a
CUA with it.
**Purpose:** Pin down the contract the SDK exposes — public surface,
behavioural guarantees, and version boundaries — so coding agents,
framework owners, and downstream tools can rely on it without reading
the source.

This document uses RFC-2119 keywords (`MUST`, `SHOULD`, `MAY`).

The umbrella product spec (architecture, the full debugger surface,
non-goals) is maintained alongside the hosted Augur service and is not
publicly mirrored. This file is the **SDK-only slice** — the contract
the public client exposes.

---

## 1. What the SDK is

A Python library that an authoring CUA imports to:

1. **Capture** a per-run trace at a configurable level of detail.
2. **Redact** sensitive material before it lands on disk or hits the network.
3. **Bundle** captured records onto disk in a path-stable, schema-validated
   layout.
4. **Stream** captured records to an Augur server (Sentry-style DSN),
   when configured. Streaming is observe-only on top of (1)–(3) — the
   local bundle is the canonical artefact; the network sink is an
   optimisation.

The SDK does **NOT**:

- Provide a UI (that's the Augur viewer, upstream).
- Provide a CLI (that's `augur-cli`, upstream).
- Make decisions for the CUA. The SDK never reads back from the server
  during a run to influence the agent's behaviour. (See §6.)

## 2. CUA contract preservation

The SDK MUST NOT promote DOM-derived coordinates to runtime inputs. Per
the umbrella spec §4, **runtime action selection is screenshot-grounded.**
Adapters MAY emit DOM/CDP records as `provenance: "dom"` for diagnostic
evidence, but the SDK will not interpret them as the agent's real
target. The diagnostic-rules engine (`augur_sdk.diagnostics`) flags any
rule that treats a non-`screenshot` provenance as a runtime input.

## 3. Public surface (the supported API)

These are the symbols the SDK considers public. Stable across patch
versions; **may break** across minor versions while pre-1.0; **strictly
additive** across minors post-1.0.

### Top-level (`augur_sdk`)

```python
from augur_sdk import (
    DebugSession,
    CaptureMode, resolve_capture_mode,
    DefaultRedactionPolicy, RedactionPolicy, DEFAULT_POLICY_ID,
    LocalFSStore, S3Store, Store,
    Adapter,
    SUPPORTED_SCHEMA_RANGE, __version__,
)
```

### Models (`augur_sdk.models`)

Every record type the SDK accepts or produces is a `TypedDict`:

- `DebugSession`, `StepTrace`, `Observation`, `DecisionEvent`,
  `ReplayFixture`, `DiagnosticFinding`, `BundleManifest`, `BundleTrace`.

Enum types are `Literal`s — implementers can use them at the boundary
without runtime imports.

### Diagnostics (`augur_sdk.diagnostics`)

- `BundleContext`, `Rule`, `RuleResult`, `RulesEngine`
- `load_pack(name: str) -> list[Rule]`
- `rule(rule_id: str, *, severity: str = "medium")` decorator
- `CUA_RULES` — the generic rule pack

### Streaming (`augur_sdk.streaming`)

- `DSN` — parser
- `StreamingSink` — best-effort POSTs

Anything not listed here is **private**. Names starting with `_` are
private regardless.

## 4. Behavioural guarantees

The SDK MUST behave as follows. These are the only invariants downstream
consumers may rely on.

### 4.1 Bundle writes are atomic per file

Every file in a bundle is written via `<file>.tmp` + `os.replace`. A
reader observing the bundle mid-run never sees a partial file.

### 4.2 The bundle is always written

If `capture_mode != "off"`, the bundle is written to `out_dir` even when:
- Streaming is disabled.
- The network is unreachable.
- The DSN's `api_key` is rejected.
- The Augur server returns 4xx/5xx.

The bundle is the source of truth; streaming is observe-only.

### 4.3 Streaming failures are never fatal

The SDK MUST NOT raise on network errors. The streaming sink runs on
background threads and logs failures at DEBUG; never WARN or higher.
This means an instrumented CUA cannot be made to crash by toggling a
firewall rule.

### 4.4 Heartbeat cadence

When `dsn` is configured and a session is open, the SDK MUST heartbeat
the server at intervals of **15 seconds ± 1 s**. Operators set the
server's heartbeat window via `AUGUR_HEARTBEAT_WINDOW_S` (default 60 s).

### 4.5 No reads from the server during a run

The SDK MUST NOT issue HTTP `GET` against the Augur server while a
session is open. Live attach (Phase 4) introduces SSE/WS reads in a
viewer-side path; the SDK side stays write-only.

### 4.6 Redaction runs before bytes leave the SDK

Both local bundle writes and streaming POSTs run through the active
`RedactionPolicy` before serialization. There is no opt-out path.

### 4.7 Schema validation on close

`session.close()` MUST validate every record against the canonical
schemas under `augur_sdk._schema/json/`. Validation failure raises;
this is the one place the SDK is allowed to be loud (the alternative
is to ship a broken bundle).

### 4.8 Path stability

Every file in a bundle is at a path predictable from the step index
(or constant for top-level files). See [docs/concepts/bundle-layout.md].

### 4.9 No side-effecting imports

`import augur_sdk` MUST NOT open files, sockets, or threads. The first
side effect happens inside `DebugSession.__enter__`.

### 4.10 Thread safety

`DebugSession.record_step`, `record_event`, and `attach_observation`
MUST be safe to call from multiple threads on the same session. The SDK
uses an internal `threading.Lock` around the `EventRecorder`.

## 5. Version policy

- The SDK follows semver per `MAJOR.MINOR.PATCH`.
- Pre-1.0: minors MAY break public surface but MUST ship a migration
  note in `CHANGELOG.md`.
- Post-1.0: minors are strictly additive; only majors break.
- `__version__` and `SUPPORTED_SCHEMA_RANGE` are introspectable at runtime.
- The bundled JSON Schemas under `augur_sdk._schema/json/` track the
  upstream schemas at the version pinned in `SUPPORTED_SCHEMA_RANGE`.

## 6. Non-goals (don't ask the SDK for these)

The SDK does not:

- Render the UI (use the Augur viewer, upstream).
- Provide a CLI (use `augur-cli`, upstream).
- Implement an HTTP server (use `augur-server`, upstream).
- Manage tenants, users, or DSNs (those are operator concerns; mint
  DSNs via `augur admin dsn-issue` upstream).
- Run a coding agent (use Claude Code / Cursor; this SDK produces the
  bundle they read).
- Schedule, retry, or replay runs (those are framework concerns).
- Validate adapter code (see the contract test suite upstream).

## 7. Status

- **Schema version**: `0.1`
- **SDK version**: `0.1.0`
- **Supported Python**: 3.11, 3.12, 3.13
- **Runtime deps**: `jsonschema`, `referencing`, `urllib3`

Anything beyond `0.1.x` may break this spec; check `CHANGELOG.md`.
