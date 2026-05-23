# Trajectory fingerprint

Every bundle ships a `trajectory_fingerprint` on `manifest.json`. It is a
short, deterministic, opaque string that the platform's failure-mode
clustering pipeline uses as a cheap discriminator — a hand-crafted
stand-in for a learned trajectory embedding.

```
"trajectory_fingerprint": "cua_v1:6cf...e2a8d8...b1c4"
```

## Properties

The fingerprint is:

- **deterministic** — two runs with identical step sequences produce
  identical fingerprints, across SDK versions and machines.
- **order-sensitive** — swapping two steps changes the fingerprint.
- **locally near-similar** — runs that differ in one step share most of
  their bigram digest, so a Hamming-style proximity check on the server
  side picks up close cousins.
- **opaque** — consumers MUST NOT parse the body. The `cua_v1:` prefix
  is reserved for algorithm versioning.

## Default algorithm: `cua_v1`

For each step in order, the algorithm computes a token of the form
`<action.type>:<failure_class|verdict.status>:<normalized_target_label>`
where the target label is lowercased and stripped of whitespace and
non-alphanumerics so `Login button` and `login-button` collide.

The fingerprint body is:

- `sha256(linear)[:32]` — hash over the ordered concatenation of step
  tokens.
- `+`
- `sha256(sorted_bigrams)[:32]` — hash over the sorted set of bigrams
  of step tokens.

The linear half is sensitive to whole-run shape; the bigram half is
sensitive to local edits. Concatenating gives a 64-char body that
mixes both.

## Plugging in a learned embedding

Adapters can swap the algorithm without changing the SDK API by
registering an entry point under the `augur_sdk.fingerprints` group:

```toml
# pyproject.toml
[project.entry-points."augur_sdk.fingerprints"]
my_embedding_v1 = "my_pkg.fingerprint:embed_trajectory"
```

The callable takes the list of `StepTrace` dicts and returns a
single string. The SDK picks the algorithm at bundle-write time;
see `augur_sdk.fingerprint.resolve_algorithm()`.

## Edge cases

- Empty trajectories (zero steps) do NOT emit a fingerprint — the
  field is absent from the manifest, not the empty string.
- Steps without an `action.type`, `failure_class`, `verdict.status`,
  or `grounding.target_label` contribute empty tokens — the algorithm
  is robust to partial step records.
