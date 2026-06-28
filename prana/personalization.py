"""
Per-user indoor-offset personalization via Bayesian normal-normal updates.

Pure functions, no I/O, no framework imports — so it is trivially testable and
cheap to run on a lightweight backend.

Motivation
----------
The RDS population model produces a *prior* estimate of a household's indoor
temperature offset from onboarding answers (AC, fan, roof, floor, occupants).
That prior does not generalise well across cities (see the cross-site null
result), so instead of trying to predict it better, we let each user's real
WhatsApp sleep check-ins correct it over time.

Each check-in is treated as a single noisy observation of the household's TRUE
indoor offset. A conjugate normal-normal update combines the onboarding prior
with the accumulated observations so that:
  - with few check-ins, the personalised offset stays near the onboarding prior
    (we don't overreact to one night);
  - with many check-ins, it shrinks toward the user's observed reality;
  - we always carry an uncertainty that narrows as evidence accumulates.

Caveat: the observation magnitudes in `infer_offset_observation` (how far over
or under the recovery threshold a given sleep-quality label implies) are
prototype assumptions, not empirically fitted. They affect how fast
personalisation moves, not its direction, and the update is robust to them.
"""
from __future__ import annotations

from dataclasses import dataclass


# Observation standard deviation (degC of inferred offset). A single check-in is
# a fuzzy signal, so we keep it wide; larger = slower, more conservative
# personalisation.
CHECKIN_OBS_SD = 3.0

# Floor on the prior SD so an over-confident onboarding guess can still be moved
# by real evidence.
MIN_PRIOR_SD = 1.0

# How far past the recovery threshold each sleep-quality class implies the
# user's effective indoor temperature sat (degC). Prototype assumptions.
_OVER_THRESHOLD = 2.0
_UNDER_THRESHOLD = 2.0

_POOR_LABELS = {"poor", "too_hot", "cooling_unavailable", "bad"}
_GOOD_LABELS = {"good", "comfortable", "cool_enough"}
_MODERATE_LABELS = {"moderate", "warm", "warm_manageable", "ok"}


@dataclass
class OffsetPosterior:
    """Personalised indoor-offset estimate after Bayesian updating."""
    mean: float       # personalised indoor offset estimate (degC)
    sd: float         # uncertainty on that estimate (degC)
    n_checkins: int   # number of observations folded in


def infer_offset_observation(outdoor_temp: float, threshold: float,
                             sleep_quality: str) -> float | None:
    """
    Convert one check-in into a single noisy observation of the user's indoor
    offset, in degC.

    effective_indoor = outdoor_temp + offset, and `threshold` is the recovery
    threshold. The reported sleep quality tells us where the effective indoor
    temperature sat relative to that threshold, which implies the offset:

      - poor / too hot   -> effective indoor was clearly ABOVE threshold
      - good / comfortable -> effective indoor was clearly BELOW threshold
      - moderate / warm  -> effective indoor sat NEAR the threshold

    Args:
        outdoor_temp: outdoor nighttime temperature for that check-in (degC).
        threshold: recovery threshold the offset is measured against (degC).
        sleep_quality: free-text/structured label from the check-in.

    Returns:
        The observed offset (degC), or None if the label is unrecognised.
    """
    boundary = threshold - outdoor_temp  # offset that puts indoor exactly at threshold
    q = str(sleep_quality).lower().strip()
    if q in _POOR_LABELS:
        return boundary + _OVER_THRESHOLD
    if q in _GOOD_LABELS:
        return boundary - _UNDER_THRESHOLD
    if q in _MODERATE_LABELS:
        return boundary
    return None


def update_posterior(prior_mean: float, prior_sd: float,
                     observations: list[float]) -> OffsetPosterior:
    """
    Normal-normal conjugate update of the indoor offset.

    Args:
        prior_mean: onboarding offset estimate (degC).
        prior_sd: uncertainty on the onboarding estimate (degC), e.g. the RDS
                  band half-width.
        observations: inferred offset observations (degC) from check-ins.

    Returns:
        OffsetPosterior. With no observations, returns the prior unchanged.
    """
    prior_sd = max(prior_sd, MIN_PRIOR_SD)
    prior_prec = 1.0 / (prior_sd ** 2)
    obs_prec = 1.0 / (CHECKIN_OBS_SD ** 2)

    n = len(observations)
    if n == 0:
        return OffsetPosterior(mean=round(prior_mean, 3), sd=round(prior_sd, 3),
                               n_checkins=0)

    post_prec = prior_prec + n * obs_prec
    post_mean = (prior_prec * prior_mean + obs_prec * sum(observations)) / post_prec
    post_sd = (1.0 / post_prec) ** 0.5
    return OffsetPosterior(mean=round(post_mean, 3), sd=round(post_sd, 3),
                           n_checkins=n)


def personalize_offset(prior_mean: float, prior_sd: float, checkins: list[dict],
                       threshold: float) -> OffsetPosterior:
    """
    Convenience pipeline: turn raw check-ins into a personalised offset.

    Args:
        prior_mean/prior_sd: onboarding prior.
        checkins: list of dicts, each with 'outdoor_temp' and 'sleep_quality'.
                  Entries that cannot be interpreted are skipped.
        threshold: recovery threshold for the offset scale.

    Returns:
        OffsetPosterior reflecting all usable check-ins.
    """
    observations = []
    for c in checkins:
        outdoor = c.get("outdoor_temp")
        quality = c.get("sleep_quality")
        if outdoor is None or quality is None:
            continue
        obs = infer_offset_observation(outdoor, threshold, quality)
        if obs is not None:
            observations.append(obs)
    return update_posterior(prior_mean, prior_sd, observations)
