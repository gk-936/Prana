"""Test Issue 5 fix: CCRI pollution unavailable handling"""

import unittest
from ccri_calculator import CCRICalculator


class TestIssue5PollutionUnavailable(unittest.TestCase):
    def setUp(self):
        self.calculator = CCRICalculator()
    
    def test_pollution_score_returns_none_when_unavailable(self):
        """Pollution score should return None, not a fake numeric value"""
        score = self.calculator.calculate_pollution_score(None)
        self.assertIsNone(score, "Pollution score must be None when ha_aqi is None")
    
    def test_ccri_confidence_degraded_when_pollution_missing(self):
        """CCRI confidence should be 'degraded' when pollution data missing"""
        ndt = 30.0  # moderate heat
        ha_aqi = None  # missing
        rds = 20.0
        
        components = self.calculator.calculate_component_scores(ndt, ha_aqi, rds)
        
        self.assertEqual(components['ccri_confidence'], 'degraded',
                        "CCRI confidence must be 'degraded' when pollution unavailable")
        self.assertEqual(components['pollution_data_quality'], 'missing',
                        "pollution_data_quality must be 'missing'")
        self.assertIsNone(components['pollution_score'],
                         "pollution_score must be None when unavailable")
    
    def test_ccri_computed_from_heat_only_when_pollution_missing(self):
        """CCRI should use heat score directly, not multiply by fake pollution"""
        ndt = 30.0
        ha_aqi = None
        rds = 0.0  # zero RDS to isolate base CCRI
        
        components = self.calculator.calculate_component_scores(ndt, ha_aqi, rds)
        heat_score = components['heat_score']
        base_ccri = components['base_ccri']
        
        # With pollution missing, base_ccri should equal heat_score
        self.assertAlmostEqual(base_ccri, heat_score, places=1,
                              msg="base_ccri should equal heat_score when pollution unavailable")
    
    def test_alert_message_contains_unavailable_qualifier(self):
        """Alert must explicitly state air quality unavailable, not claim SAFE"""
        ndt = 25.0  # low heat
        ha_aqi = None
        rds = 10.0
        
        ccri, risk_level = self.calculator.calculate_ccri(ndt, ha_aqi, rds)
        components = self.calculator.calculate_component_scores(ndt, ha_aqi, rds)
        
        alert = self.calculator.generate_alert_message(
            ccri, risk_level, ndt, ha_aqi, "Low recovery debt",
            location_name="Test Location",
            pollution_data_quality=components['pollution_data_quality']
        )
        
        # Alert must mention unavailable data
        self.assertIn("DATA UNAVAILABLE", alert.upper(),
                     "Alert must explicitly mention air quality unavailable")
        
        # Must not claim unqualified SAFE when data missing
        if "SAFE" in alert and "unknown" not in alert.lower():
            self.fail("Alert claims SAFE without qualifying that air quality is unknown")
    
    def test_alert_level_elevated_when_safe_tier_but_pollution_missing(self):
        """When heat is low but pollution missing, should be ELEVATED not SAFE"""
        ndt = 25.0  # low heat -> would normally be SAFE
        ha_aqi = None
        rds = 5.0
        
        components = self.calculator.calculate_component_scores(ndt, ha_aqi, rds)
        ccri, risk_level = self.calculator.calculate_ccri(ndt, ha_aqi, rds)
        
        alert = self.calculator.generate_alert_message(
            ccri, risk_level, ndt, ha_aqi, "Low recovery debt",
            pollution_data_quality='missing'
        )
        
        # Risk level should be overridden to ELEVATED
        self.assertIn("ELEVATED", alert,
                     "Risk level must be ELEVATED (not unqualified SAFE) when pollution missing")
        self.assertIn("unknown", alert.lower(),
                     "Alert must acknowledge uncertainty")


if __name__ == '__main__':
    unittest.main()
