"""Canonical reward / score-component vocabulary — augur-sdk#41.

`step.verdict.score_components` is an open dict on the schema side
(``additionalProperties: true``) so producers MAY add domain-specific
keys. But to keep cross-producer RL training from drowning in
per-adapter naming maps, the canonical keys are pinned by
``augur-schema 0.4.0`` and exposed here as constants.

Producers SHOULD use these constants when their signal matches the
documented semantic. Consumers MUST tolerate extra keys.

Semantics (all values are numbers in [0, 1] unless noted):

- ``PROGRESS``           — fraction of the task completed at this step.
  Use the per-step delta for shaping (raw progress rewards sitting in
  an already-good state).
- ``ACTION_QUALITY``     — step-local: was the chosen action sensible
  given this observation, independent of trajectory context.
- ``PROCESS_QUALITY``    — trajectory-aware: how well does this step
  fit the overall plan, avoid unnecessary navigation / backtracking.
- ``SAFETY_RISK``        — 0 = safe, 1 = catastrophic. Pair with
  ``side_effect.reversibility`` for committed actions.
- ``LOOPINESS``          — state-repetition penalty (1 = identical
  observation to a prior step). Derive from
  ``observation.hashes.phash_64`` + ``env_fingerprint.dom_hash``
  adjacency.
- ``VERIFIER_CONFIDENCE``— how confident the verifier was in this
  step's verdict.
- ``GROUNDING_ACCURACY`` — did the agent's grounded action target
  what its ``intent`` named.

Usage::

    from augur_sdk import ScoreComponents

    session.set_score(
        step_index=4,
        score=0.82,
        components={
            ScoreComponents.PROGRESS: 0.25,
            ScoreComponents.ACTION_QUALITY: 0.9,
            ScoreComponents.SAFETY_RISK: 0.0,
        },
    )
"""

from __future__ import annotations


class ScoreComponents:
    """Canonical keys for ``verdict.score_components``. Names match
    the documented semantics in ``augur-schema 0.4.0``'s
    ``step_trace.schema.json``. Producers MAY add custom keys
    alongside these; consumers MUST tolerate them."""

    PROGRESS = "progress"
    ACTION_QUALITY = "action_quality"
    PROCESS_QUALITY = "process_quality"
    SAFETY_RISK = "safety_risk"
    LOOPINESS = "loopiness"
    VERIFIER_CONFIDENCE = "verifier_confidence"
    GROUNDING_ACCURACY = "grounding_accuracy"


CANONICAL_SCORE_COMPONENTS: frozenset[str] = frozenset(
    {
        ScoreComponents.PROGRESS,
        ScoreComponents.ACTION_QUALITY,
        ScoreComponents.PROCESS_QUALITY,
        ScoreComponents.SAFETY_RISK,
        ScoreComponents.LOOPINESS,
        ScoreComponents.VERIFIER_CONFIDENCE,
        ScoreComponents.GROUNDING_ACCURACY,
    }
)


__all__ = ["CANONICAL_SCORE_COMPONENTS", "ScoreComponents"]
