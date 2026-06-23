"""Test Issue 6 fix: CCRI recovery multiplier piecewise scaling"""

import unittest
from ccri_calculator import CCRICalculator


class TestIssue6RecoveryMultiplierScaling(unittest.TestCase):
    def setUp(self):
        self.calculator = CCRICalculator()
    
    def test_multiplier_monotonic_increase(self):
        """Multiplier must increase monotonically with RDS"""
        rds_values = [0, 20, 50, 100, 150, 200]
        multipliers = [self.calculator.recovery_score_to_multiplier(rds) for rds in rds_values]
        
        for i in range(len(multipliers) - 1):
            self.assertLess(multipliers[i], multipliers[i+1],
                           f"Multiplier at RDS={rds_values[i]} must be < multiplier at RDS={rds_values[i+1]}")
    
    def test_rds_200_greater_than_rds_100(self):
        """RDS=200 multiplier must be strictly greater than RDS=100"""
        mult_100 = self.calculator.recovery_score_to_multiplier(100)
        mult_200 = self.calculator.recovery_score_to_multiplier(200)
        
        self.assertGreater(mult_200, mult_100,
                          "RDS=200 multiplier must be > RDS=100 multiplier")
    
    def test_rds_100_greater_than_rds_50(self):
        """RDS=100 multiplier must be strictly greater than RDS=50"""
        mult_50 = self.calculator.recovery_score_to_multiplier(50)
        mult_100 = self.calculator.recovery_score_to_multiplier(100)
        
        self.assertGreater(mult_100, mult_50,
                          "RDS=100 multiplier must be > RDS=50 multiplier")
    
    def test_low_rds_tier_0_to_30(self):
        """RDS 0-30 should scale to ~1.0-1.1x"""
        mult_0 = self.calculator.recovery_score_to_multiplier(0)
        mult_30 = self.calculator.recovery_score_to_multiplier(30)
        
        self.assertAlmostEqual(mult_0, 1.0, places=2,
                              msg="RDS=0 should give multiplier ~1.0")
        self.assertAlmostEqual(mult_30, 1.1, places=2,
                              msg="RDS=30 should give multiplier ~1.1")
    
    def test_mid_rds_tier_30_to_80(self):
        """RDS 30-80 should scale to ~1.1-1.3x"""
        mult_30 = self.calculator.recovery_score_to_multiplier(30)
        mult_80 = self.calculator.recovery_score_to_multiplier(80)
        
        self.assertAlmostEqual(mult_30, 1.1, places=2)
        self.assertAlmostEqual(mult_80, 1.3, places=2,
                              msg="RDS=80 should give multiplier ~1.3 (old cap)")
    
    def test_high_rds_tier_80_to_150(self):
        """RDS 80-150 should scale to ~1.3-1.6x"""
        mult_80 = self.calculator.recovery_score_to_multiplier(80)
        mult_150 = self.calculator.recovery_score_to_multiplier(150)
        
        self.assertAlmostEqual(mult_80, 1.3, places=2)
        self.assertAlmostEqual(mult_150, 1.6, places=2)
    
    def test_critical_rds_uncapped(self):
        """RDS 150+ should continue scaling without ceiling"""
        mult_150 = self.calculator.recovery_score_to_multiplier(150)
        mult_200 = self.calculator.recovery_score_to_multiplier(200)
        mult_300 = self.calculator.recovery_score_to_multiplier(300)
        
        # All must be greater than 1.6
        self.assertGreater(mult_150, 1.59)
        self.assertGreater(mult_200, mult_150)
        self.assertGreater(mult_300, mult_200)
        
        # Verify no plateau - must keep increasing
        self.assertGreater(mult_300, 1.8,
                          "RDS=300 should give multiplier significantly > 1.6 (no cap)")
    
    def test_component_scores_uses_new_multiplier(self):
        """calculate_component_scores must use recovery_score_to_multiplier"""
        ndt = 30.0
        ha_aqi = 100.0
        rds = 150.0  # High RDS
        
        components = self.calculator.calculate_component_scores(ndt, ha_aqi, rds)
        expected_multiplier = self.calculator.recovery_score_to_multiplier(rds)
        
        self.assertAlmostEqual(components['recovery_multiplier'], expected_multiplier, places=3,
                              msg="Component scores must use recovery_score_to_multiplier function")


if __name__ == '__main__':
    unittest.main()
