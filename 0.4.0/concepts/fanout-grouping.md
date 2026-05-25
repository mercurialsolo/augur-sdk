# Fanout grouping

When a producer fans out work across multiple sessions — Phase-1 collectors,
Phase-2 workers, sub-agent siblings — the viewer should render those
sessions **grouped under a parent row**, not as flat siblings in the
runs-list. This page pins the contract producers and viewers hold each
other to so the grouping is unambiguous.

## The contract

> When a producer emits multiple `DebugSession` payloads (each with its
> own `run_id`) that share the same `branch_context.parent_run_id`,
> those sessions are **siblings of one logical orchestrator**. Viewers
> SHOULD group them under a parent row in any runs-list rendering —
> using either an explicit parent session at `parent_run_id` (when one
> exists) or a synthetic parent aggregated from the children otherwise.

The contract covers both the **replay-branch** case (siblings produced
by [`branch_from(...)`](../reference/api.md#debugsessionbranch_from)
with different `mutated_axis` mutations on the same parent) and the
**fanout** case (independent worker sessions spawned by an
orchestrator). Both reach the platform through the same shape — a
`branch_context.parent_run_id` carried on each step — and both deserve
the same grouping treatment.

The load-bearing field is `branch_context.parent_run_id`. Other fields
(`branch_point_step_index`, `mutated_axis`, `mutation`, `branch_id`)
remain meaningful in the replay-branch case; for genuinely independent
fanout siblings, producers typically pick `mutated_axis="action"` to
satisfy the schema and use `branch_id` to disambiguate the sibling.

## Producer side — orchestrator session helper

For the fanout case where the producer **has** aggregate metadata worth
attaching (phase counts, fanout strategy, total budget), open a
parent-only session via
[`DebugSession.open_orchestrator(...)`](../reference/api.md#debugsessionopen_orchestrator).
It carries the aggregate tags and costs but records no steps of its
own:

```python
from augur_sdk import DebugSession

# Open the parent row up front, before spawning workers.
with DebugSession.open_orchestrator(
    run_id="fanout-20b9a4786aa3-4e136449",
    client_name="myproducer",
    out_dir="parent-bundle/",
    session_name="boattrader-fanout (4 workers)",
    tenant_id="acme",
    tags={
        "phase1_workers": "4",
        "phase2_workers": "4",
        "fanout_pattern": "phase1_collect_phase2_extract",
    },
) as parent:
    # Spawn N child sessions; each carries branch_context.parent_run_id
    # pointing at this orchestrator's run_id.
    children = spawn_workers(parent_run_id=parent.run_id)
    for child in children:
        ...

    # Roll the children's costs up onto the parent — surfaces in the
    # viewer's runs-list COST column on the parent row.
    parent.set_costs(total_usd=sum(c.cost for c in children))
```

The session is marked internally with the
`augur.session_type=orchestrator` tag (exported as
`augur_sdk.ORCHESTRATOR_TAG_KEY` / `_VALUE`) so the server / viewer can
render it differently — aggregate stats only, no step list.
`record_step`, `record_step_iteration`, and `attach_observation` all
raise `RuntimeError` to make the contract explicit at the SDK boundary;
`set_costs`, `add_tag`, `set_live_endpoints`, `finalize_outcome` and the
other session-level helpers work normally.

## Producer side — children

Each child session points at the orchestrator via `branch_context`:

```python
with DebugSession(
    run_id=f"{parent.run_id}:phase2_w{i}",
    client_name="myproducer",
    out_dir=f"child-{i}-bundle/",
    branch_context={
        "parent_run_id": parent.run_id,
        "branch_point_step_index": 0,  # fanout siblings diverge at the start
        "mutated_axis": "action",       # closest match for independent work
        "branch_id": f"{parent.run_id}:phase2_w{i}",
    },
) as child:
    child.record_step(...)
```

A lightweight slice (without the `mutation` payload) propagates to every
step automatically, so the server can group by `parent_run_id` without
joining steps back to the session record.

## Viewer side — synthetic parent fallback

If the producer doesn't use `open_orchestrator(...)`, the server is
expected to **synthesize a parent row** from the children's shared
`branch_context.parent_run_id`. The orchestrator helper is purely the
producer-side ergonomic for attaching aggregate metadata the server
can't derive from the children alone (phase counts, fanout strategy,
total budget).

Either way — explicit parent or synthetic — the runs-list shows one
parent row with N child rows underneath. Consumers and producers
contract on the `branch_context.parent_run_id` link; the orchestrator
helper just makes the aggregate-metadata case ergonomic.

## When to use which

| Scenario | Open an orchestrator session? |
|----------|------------------------------|
| Fanout with no aggregate metadata (children carry everything) | No — let the viewer synthesize the parent row. |
| Fanout with aggregate tags / costs / phase counts | Yes — `open_orchestrator(...)`. |
| Replay branches via `branch_from(...)` | No — the parent run already exists as a real session. |

## Related

- [`DebugSession.open_orchestrator(...)` API
  reference](../reference/api.md#debugsessionopen_orchestrator)
- [`branch_from(...)` API reference](../reference/api.md#debugsessionbranch_from)
  — the replay-branch sibling case
- `augur#138` — runs-list grouping by `branch_context.parent_run_id`
  with synthetic parent rows (server side)
