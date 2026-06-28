"""Tests for the Bayesian per-user indoor-offset personalization layer."""

import unittest

from prana.personalization import (
    OffsetPosterior,
    infer_offset_observation,
    update_posterior,
    personalize_offset,
    MIN_PRIOR_SD,
)

THRESHOLD = 32.0


class TestObservationInference(unittest.TestCase):
    def test_poor_sleep_implies_offset_above_boundary(self):
        # Outdoor 30C: boundary offset = +2. "Too hot" should imply more than that.
        obs = infer_offset_observation(30.0, THRESHOLD, "poor")
        self.assertGreater(obs, THRESHOLD - 30.0)

    def test_good_sleep_implies_offset_below_boundary(self):
        # Outdoor 34C: boundary offset = -2. "Good" should imply less than that.
        obs = infer_offset_observation(34.0, THRESHOLD, "good")
        self.assertLess(obs, THRESHOLD - 34.0)

    def test_moderate_sleep_sits_at_boundary(self):
        obs = infer_offset_observation(31.0, THRESHOLD, "moderate")
        self.assertEqual(obs, THRESHOLD - 31.0)

    def test_unknown_label_returns_none(self):
        self.assertIsNone(infer_offset_observation(30.0, THRESHOLD, "spaceship"))


class TestPosteriorUpdate(unittest.TestCase):
    def setUp(self):
        self.prior_mean = 2.0   # onboarding: +2C (e.g. tin roof)
        self.prior_sd = 2.0

    def test_zero_checkins_returns_prior(self):
        p = update_posterior(self.prior_mean, self.prior_sd, [])
        self.assertEqual(p.mean, self.prior_mean)
        self.assertEqual(p.n_checkins, 0)

    def test_few_checkins_pull_partway(self):
        # Observations point at ~+6; with few, posterior should sit between.
        p = update_posterior(self.prior_mean, self.prior_sd, [6.0, 5.5, 6.5])
        self.assertGreater(p.mean, self.prior_mean)
        self.assertLess(p.mean, 6.0)

    def test_many_checkins_dominated_by_observations(self):
        p = update_posterior(self.prior_mean, self.prior_sd, [6.0] * 20)
        self.assertLess(abs(p.mean - 6.0), 0.5)

    def test_uncertainty_narrows_with_more_data(self):
        p3 = update_posterior(self.prior_mean, self.prior_sd, [6.0] * 3)
        p20 = update_posterior(self.prior_mean, self.prior_sd, [6.0] * 20)
        self.assertLess(p20.sd, p3.sd)
        self.assertLess(p3.sd, self.prior_sd)

    def test_offset_moves_monotonically_toward_observations(self):
        means = [
            update_posterior(self.prior_mean, self.prior_sd, [6.0] * k).mean
            for k in range(0, 11)
        ]
        for i in range(len(means) - 1):
            self.assertLessEqual(means[i], means[i + 1])

    def test_cool_observations_pull_offset_down(self):
        p = update_posterior(self.prior_mean, self.prior_sd, [-4.0] * 10)
        self.assertLess(p.mean, self.prior_mean)

    def test_overconfident_prior_sd_is_floored(self):
        # A near-zero prior SD must still be movable by evidence.
        p = update_posterior(2.0, 0.0001, [6.0] * 10)
        self.assertGreater(p.mean, 2.0)


class TestPersonalizePipeline(unittest.TestCase):
    def test_pipeline_skips_unusable_checkins(self):
        checkins = [
            {"outdoor_temp": 30.0, "sleep_quality": "poor"},
            {"outdoor_temp": None, "sleep_quality": "good"},      # skipped
            {"outdoor_temp": 33.0, "sleep_quality": "unknown??"}, # skipped
            {"outdoor_temp": 31.0, "sleep_quality": "moderate"},
        ]
        p = personalize_offset(2.0, 2.0, checkins, THRESHOLD)
        self.assertEqual(p.n_checkins, 2)  # only two usable

    def test_pipeline_no_usable_checkins_returns_prior(self):
        checkins = [{"outdoor_temp": None, "sleep_quality": None}]
        p = personalize_offset(2.0, 2.0, checkins, THRESHOLD)
        self.assertEqual(p.mean, 2.0)
        self.assertEqual(p.n_checkins, 0)

    def test_consistent_hot_reports_raise_offset(self):
        # User repeatedly reports poor sleep at a cool-ish outdoor temp ->
        # their home clearly runs hotter than onboarding assumed.
        checkins = [{"outdoor_temp": 29.0, "sleep_quality": "poor"} for _ in range(8)]
        p = personalize_offset(0.0, 2.0, checkins, THRESHOLD)
        self.assertGreater(p.mean, 0.0)


if __name__ == "__main__":
    unittest.main()
