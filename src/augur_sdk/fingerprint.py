"""Trajectory fingerprinting (#19).

Computes a deterministic, hand-crafted fingerprint over the action /
failure / target sequence of a run so the platform's failure-mode
clustering pipeline has a cheap discriminator that doesn't require an
embedding model.

Plug-in surface
---------------
The default algorithm is ``cua_v1``. A producer can swap in a learned
embedding by exposing an entry point under the
``augur_sdk.fingerprints`` group whose value is a
``Callable[[list[StepTrace]], str]``. The fingerprint string lands on
``manifest.trajectory_fingerprint`` and is opaque to consumers — they
treat it as a black-box key for near-hash comparisons. Two runs with
identical action/failure/target sequences MUST produce identical
fingerprints; two runs with one differing axis produce different but
similar fingerprints (small Hamming distance on the n-gram set).

The algorithm is documented in
``docs/concepts/trajectory-fingerprint.md``.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from importlib.metadata import entry_points
from typing import Any

DEFAULT_ALGORITHM = "cua_v1"

_WHITESPACE = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _normalize_target(label: str) -> str:
    """Normalise a grounding target label so trivial wording differences
    don't move the fingerprint. Lowercase, collapse whitespace, strip
    non-alphanumerics so 'Login button' and 'login-button' collide."""
    out = label.lower()
    out = _WHITESPACE.sub(" ", out).strip()
    out = _NON_ALNUM.sub("", out)
    return out


def _step_tuple(step: dict[str, Any]) -> tuple[str, str, str]:
    action = step.get("action") or {}
    action_type = (
        action.get("type", "") if isinstance(action, dict) else ""
    ) or ""
    failure_class = step.get("failure_class")
    verdict = step.get("verdict") or {}
    verdict_status = (
        verdict.get("status", "") if isinstance(verdict, dict) else ""
    ) or ""
    # Prefer failure_class when it's set (more specific), fall back to
    # verdict.status so the fingerprint still reflects success/failure
    # shape for runs that never failed.
    failure_or_verdict = failure_class or verdict_status or ""
    grounding = step.get("grounding") or {}
    target_label = (
        grounding.get("target_label", "") if isinstance(grounding, dict) else ""
    ) or ""
    return action_type, failure_or_verdict, _normalize_target(target_label)


def _ngrams(tokens: list[str], n: int) -> list[str]:
    """Window n-grams. Pad with a sentinel so short trajectories still
    produce stable grams."""
    if not tokens:
        return []
    if len(tokens) < n:
        return ["|".join(tokens)]
    return ["|".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


def cua_v1(steps: list[dict[str, Any]]) -> str:
    """Default fingerprint algorithm.

    Hash the concatenation of (action.type, failure_or_verdict,
    normalized_target_label) for each step in order, sprinkled with
    bigrams for near-hash comparisons. The output is a single 64-char
    hex digest — short enough to fit on a dashboard row, long enough
    that accidental collisions across cohorts are negligible.
    """
    tuples = [_step_tuple(s) for s in steps]
    seq_tokens: list[str] = []
    for action, fc_or_verdict, target in tuples:
        seq_tokens.append(f"{action}:{fc_or_verdict}:{target}")

    # Linear hash over the ordered step sequence — sensitive to order
    # so two runs with the same steps in different order get different
    # fingerprints.
    linear = hashlib.sha256("\n".join(seq_tokens).encode("utf-8")).hexdigest()

    # Bigram hash — sensitive to *local* sequence differences. We sort
    # the bigram set before hashing so a one-step swap moves only the
    # bigrams adjacent to the swap, not the whole digest.
    bigrams = sorted(set(_ngrams(seq_tokens, 2)))
    bigram_digest = hashlib.sha256(
        "\n".join(bigrams).encode("utf-8")
    ).hexdigest()

    # Combine the two halves so the resulting digest mixes whole-run
    # sensitivity with bigram-locality sensitivity.
    return f"cua_v1:{linear[:32]}{bigram_digest[:32]}"


_BUILTIN: dict[str, Callable[[list[dict[str, Any]]], str]] = {
    "cua_v1": cua_v1,
}


def resolve_algorithm(
    name: str | None = None,
) -> Callable[[list[dict[str, Any]]], str]:
    """Return the fingerprint function for ``name``.

    Lookup order: built-ins → entry points under
    ``augur_sdk.fingerprints``. Unknown names raise ``ValueError`` so
    a typo in a producer's config doesn't silently fall back to
    ``cua_v1``.
    """
    name = name or DEFAULT_ALGORITHM
    if name in _BUILTIN:
        return _BUILTIN[name]
    # SDK requires py3.11+, so the keyword form of entry_points is always
    # available — no need for the py3.9 select-via-dict fallback.
    eps = entry_points(group="augur_sdk.fingerprints")
    for ep in eps:
        if ep.name == name:
            fn = ep.load()
            if not callable(fn):
                raise ValueError(
                    f"augur_sdk.fingerprints entry point {name!r} is not callable"
                )
            return fn  # type: ignore[no-any-return]
    raise ValueError(f"unknown trajectory_fingerprint algorithm: {name!r}")


def compute_trajectory_fingerprint(
    steps: list[dict[str, Any]],
    *,
    algorithm: str | None = None,
) -> str:
    """Public entry point used by the bundle writer."""
    fn = resolve_algorithm(algorithm)
    return fn(steps)


__all__ = [
    "DEFAULT_ALGORITHM",
    "compute_trajectory_fingerprint",
    "cua_v1",
    "resolve_algorithm",
]
