# Changelog

All notable changes to `augur-sdk` are recorded here. Format roughly follows
[Keep a Changelog](https://keepachangelog.com/), with semver applied per
`docs/versioning.md` upstream (`MAJOR.MINOR.PATCH`; pre-1.0 minors may break).

## [Unreleased]

## [0.1.2] — 2026-05-19

### Fixed

- Heartbeat POST now sends a JSON body with `Content-Type:
  application/json`. Previously it used `urllib3`'s `fields=` kwarg,
  which produces `multipart/form-data` — the server parsed that as an
  empty JSON body and returned **HTTP 422 "client_id field required"**,
  silently breaking the connection-status badge against any server
  shipped after the JSON-only heartbeat parser landed.
- Added `tests/test_streaming_heartbeat.py` to pin the wire format so
  this can't regress.

## [0.1.1] — 2026-05-19

### Changed

- `StreamingSink` now fires one immediate `session_opened` heartbeat
  at construction time (i.e. on `DebugSession(dsn=…)`), so the
  workspace's connection list shows the client before the first step
  is recorded. The periodic 15 s heartbeat loop continues to start at
  `__enter__` as before.
- Heartbeat payload gains an optional `last_event` field used by the
  initial fire. Existing servers ignore unknown fields; no client or
  server upgrade required.

### Spec

- §4.4 now documents the initial-fire requirement.
- §4.9 now reflects that side effects begin at `DebugSession(...)`
  construction when `dsn` is configured, not at `__enter__`.

## [0.1.0] — 2026-05-19

Initial standalone release.

### Added

- `DebugSession` context manager — the only API a CUA needs to integrate.
- Capture modes (`off` / `metadata` / `trace` / `screenshots` / `model_io` / `dispatch` / `replay` / `full`) spec'd in `augur_sdk.CaptureMode`.
- Atomic local bundle writer with path-stable layout (`manifest.json`, `trace.json`, `steps/`, `events/`, `screenshots/`, `AGENT.md`, `schema/`).
- DSN-based streaming sink (Sentry-style). Set `AUGUR_DSN=…` or pass `dsn=` directly; per-step + per-screenshot POSTs with a 15 s heartbeat. Bundle on disk is always written even if the network is flapping.
- Vendored JSON Schemas (`augur_sdk._schema`) — zero monorepo dependency at install time.
- `RedactionPolicy` + shipped `default-pii-v1` policy: drops `Authorization` / `Cookie` / `Set-Cookie` / `X-API-Key`; masks `token` / `api_key` / `ssn` / `credit_card` / `cvv`; regex-scrubs bearer tokens, AWS keys, JWTs, and password=… patterns.
- Diagnostic rules engine + generic `cua` rule pack (10 rules). Adapter packs land via the `augur.rule_packs` entry-point group.
- Adapter base protocol (`augur_sdk.Adapter`) + contract for adapter authors.
- `LocalFSStore` (default) + `S3Store` stub for forward compatibility.
- `validate_bundle()` — schema-validates every record in a bundle against the vendored JSON Schemas.

### Compatibility

- Schema version: `0.1`.
- Python: ≥ 3.11.
- Compatible with the Augur server's `/api/v1/*` ingest endpoints at server version 0.1.x.
