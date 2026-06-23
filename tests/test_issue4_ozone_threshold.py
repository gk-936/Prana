"""Test Issue 4 fix: Ozone heat factor threshold"""

import unittest
from ha_aqi_calculator import HAAQICalculator


class TestIssue4OzoneHeatThreshold(unittest.TestCase):
    def setUp(self):
        self.calculator = HAAQICalculator()
    
    def test_no_heat_factor_when_o3_below_threshold(self):
        """O3 AQI below threshold should not get heat amplification"""
        base_aqi = 50.0
        pollutant_aqi = {'O3': 20.0}  # Low ozone, below threshold of 50
        temp_c = 40.0  # High temperature
        
        result = self.calculator.calculate_heat_pollution_risk(base_aqi, pollutant_aqi, temp_c)
        
        # O3 AQI should remain unchanged (heat factor = 1.6x but not applied)
        self.assertAlmostEqual(result['ozone_heat_adjusted_aqi'], 20.0, places=1,
                              msg="Low O3 should not be amplified by heat")
        
        # Heat pollution risk should equal base AQI (no ozone increment)
        self.assertAlmostEqual(result['heat_pollution_risk'], base_aqi, places=1,
                              msg="Heat pollution risk should not increase when O3 is low")
    
    def test_heat_factor_applied_when_o3_above_threshold(self):
        """O3 AQI above threshold should get heat amplification"""
        base_aqi = 80.0
        pollutant_aqi = {'O3': 60.0}  # Above threshold of 50
        temp_c = 40.0  # High temperature -> factor = 1 + 0.04*(40-25) = 1.6
        
        result = self.calculator.calculate_heat_pollution_risk(base_aqi, pollutant_aqi, temp_c)
        
        # O3 AQI should be amplified
        expected_adjusted = 60.0 * 1.6  # 96
        self.assertAlmostEqual(result['ozone_heat_adjusted_aqi'], expected_adjusted, places=1,
                              msg="Elevated O3 should be amplified by heat")
        
        # Heat pollution risk should increase
        ozone_increment = (expected_adjusted - 60.0) * 0.5  # blend weight
        expected_heat_pollution = base_aqi + ozone_increment
        self.assertAlmostEqual(result['heat_pollution_risk'], expected_heat_pollution, places=1,
                              msg="Heat pollution risk should increase when O3 is elevated")
        self.assertGreater(result['heat_pollution_risk'], base_aqi,
                          "Heat pollution risk must be greater than base AQI when O3 elevated")
    
    def test_threshold_boundary_at_50(self):
        """O3 AQI exactly at 50 should get heat factor"""
        base_aqi = 60.0
        pollutant_aqi = {'O3': 50.0}  # Exactly at threshold
        temp_c = 35.0
        
        result = self.calculator.calculate_heat_pollution_risk(base_aqi, pollutant_aqi, temp_c)
        
        # Should be amplified since >= threshold
        self.assertGreater(result['ozone_heat_adjusted_aqi'], 50.0,
                          "O3 at threshold should be amplified")
    
    def test_no_o3_data_no_increment(self):
        """When O3 data missing, no heat increment should be added"""
        base_aqi = 80.0
        pollutant_aqi = {'PM2.5': 60.0}  # No O3
        temp_c = 40.0
        
        result = self.calculator.calculate_heat_pollution_risk(base_aqi, pollutant_aqi, temp_c)
        
        self.assertIsNone(result['ozone_heat_adjusted_aqi'])
        self.assertAlmostEqual(result['heat_pollution_risk'], base_aqi, places=1,
                              msg="Without O3 data, heat pollution risk should equal base AQI")


if __name__ == '__main__':
    unittest.main()
