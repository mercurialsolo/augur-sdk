"""SDK version + supported schema range."""

__version__ = "0.3.0"

# Range of schema **content** versions this SDK can produce and read.
# Inclusive on both ends.
#
# This is the JSON Schema `$id` content version (e.g. the `0.1` in
# `https://augur.dev/schemas/0.1/step_trace.schema.json`), **not** the
# `augur-schema` PyPI package version. The two are intentionally
# decoupled — the dep ships additive field updates under the same
# content version until a structural break forces a bump. Today's
# `augur-schema 0.3.2` still ships content version `0.1` (additive
# fields like `step_iterations` slot in without changing the `$id`),
# so this range stays at `("0.1", "0.1")`. Bump only when the dep
# publishes schemas at a new content version. The authoritative
# runtime value is `augur_schema.SCHEMA_VERSION`.
SUPPORTED_SCHEMA_RANGE: tuple[str, str] = ("0.1", "0.1")
