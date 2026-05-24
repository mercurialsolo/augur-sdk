# Coding-agent quickstart

How to hand an Augur bundle to a coding agent (Claude Code, Cursor,
Aider, Sweep) and get back a high-signal patch.

## The 30-second flow

```bash
# 1. Run diagnostics on the bundle
augur diagnose /path/to/bundle --rules cua

# 2. Emit a prompt template the agent can consume
augur agent-prompt /path/to/bundle

# 3. Paste into your coding agent. It can also read the bundle from disk
#    or via your Augur server's /api/v1/runs/{id}/* endpoints.
```

## What's in the bundle for the agent

Every Augur bundle ships with **two things specifically for coding
agents**:

### 1. `AGENT.md` — first-read index

Lives at the root of the bundle. Markdown. Tells the agent:

- What kind of artifact this is (`bundle_format: augur-bundle`)
- Where to read first (`steps/<first-failed>.json`, the events JSONL,
  the diagnostics file)
- The failure-class summary
- The CUA contract reminder (don't promote DOM coordinates to runtime
  inputs)

### 2. `schema/` — vendored JSON Schemas

The 12 canonical record schemas live inside the bundle so the agent
doesn't need a network round-trip to validate anything it's about to
cite or generate.

## Recommended agent system prompt

```text
You are debugging a screenshot-grounded computer-use agent. The bundle
at $BUNDLE_PATH contains the exact artifacts for one failing run.

Constraints:
- Bundle paths are stable. Read directly with read_file:
    manifest.json, trace.json, steps/<NNNN>.json, events/<NNNN>.jsonl,
    diagnostics/findings.json, schema/*.schema.json
- Runtime action selection is screenshot-grounded. If grounding.provenance
  is "dom" or "diagnostic", that coordinate is evidence, not a runtime
  input. Flag any code that treats it as the latter.
- Cite evidence as `<rule_id> @ <bundle-relative path>` so reviewers can
  verify in O(1).
- Schemas at schema/*.schema.json are the source of truth for record shapes.

Workflow:
1. Read AGENT.md inside the bundle for layout.
2. Read manifest.json for sniff (schema_version, capture_mode, missing[]).
3. Read diagnostics/findings.json if present — severity-sorted findings.
4. For the first high/critical finding, follow evidence[].ref paths.
5. Propose a minimal code change. Cite by `<rule_id> @ <path>`.
6. Do not weaken grounding on unambiguous pages to fix one ambiguous case.
```

## `augur agent-prompt` — the generator

Emits a tight markdown prompt with the deterministic paths the agent
should read first:

```bash
$ augur agent-prompt /tmp/cua-bundle
# Augur evidence package — `run_demo_1779228909`

You are debugging a screenshot-grounded computer-use agent. The bundle below
contains the **exact artifacts** (no narrative) for one failing run.

- **Bundle**: `/tmp/cua-bundle`
- **Client**: `myagent v0.1.0`
- **Schema**: `0.1`
- **Capture mode**: `screenshots`
- **Status**: `halted`
- **Steps**: 3
- **Failure classes**: `no_state_change` ×1

## First failure

- **Step**: `0002` — Click the submit button
- **Failure class**: `no_state_change`

## Suggested first reads
1. `manifest.json`
2. `AGENT.md`
3. `steps/0002.json`
4. `events/0002.jsonl`

## Your task ...
```

Use `--json` for a structured payload the agent can consume
programmatically.

## When the agent connects via the Augur server

If your CUA streams to an Augur server, the agent can use the HTTP API
instead of a local path:

```text
GET /api/v1/runs                                       # list runs in this tenant
GET /api/v1/runs/{run_id}/manifest.json
GET /api/v1/runs/{run_id}/trace.json
GET /api/v1/runs/{run_id}/steps/{NNNN}.json
GET /api/v1/runs/{run_id}/events/{NNNN}.jsonl
GET /api/v1/runs/{run_id}/screenshots/{NNNN}_post.png
GET /api/v1/runs/{run_id}/diagnostics/findings.json
```

All require a session cookie or — if you wire it up — an admin bearer
token. The OpenAPI spec lives at `/api/v1/openapi.json` (Swagger UI at
`/api/v1/docs`).

## Cite-by-evidence

The thing that makes coding-agent output trustworthy is **citation**.
Tell the agent (in its prompt) to format every recommendation as:

```
<rule_id> @ <bundle-relative path>[#L<line>]
```

For example:

```text
cua.no_state_change @ steps/0002.json
cua.verifier_disagrees @ events/0011.jsonl#L3
mantis.wrong_target @ logs/runner.log#L4226-L4280
```

A human (or another agent) can verify any claim in O(1).

## Why JSON, not plain text?

The SDK writes JSON / JSONL for record types and PNG for images. JSON
is **text** (UTF-8, line-readable, diff-able, grep-able) — same as `.txt`
for an agent's purposes, but with structure the agent can reason about
without re-parsing free-form prose. Plain `.txt` would push parsing onto
the agent and make citations unstable.
