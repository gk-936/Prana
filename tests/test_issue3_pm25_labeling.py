"""Test Issue 3 fix: PM2.5 NowCast vs instantaneous labeling"""

import unittest
from ccri_calculator import CCRICalculator


class TestIssue3PM25Labeling(unittest.TestCase):
    def setUp(self):
        self.calculator = CCRICalculator()
    
    def test_nowcast_label_appears_in_alert(self):
        """Alert should show '(12h average)' when PM2.5 uses NowCast"""
        ndt = 30.0
        ha_aqi = 120.0
        rds = 20.0
        
        ccri, risk_level = self.calculator.calculate_ccri(ndt, ha_aqi, rds)
        
        alert = self.calculator.generate_alert_message(
            ccri, risk_level, ndt, ha_aqi, "Moderate recovery",
            pm25_aqi_method="nowcast_12h"
        )
        
        self.assertIn("12h average", alert,
                     "Alert must show '12h average' qualifier for NowCast PM2.5")
        self.assertIn("120", alert,
                     "AQI value must be present")
    
    def test_instantaneous_label_appears_in_alert(self):
        """Alert should show '(instant reading, may change quickly)' for instantaneous PM2.5"""
        ndt = 30.0
        ha_aqi = 150.0
        rds = 20.0
        
        ccri, risk_level = self.calculator.calculate_ccri(ndt, ha_aqi, rds)
        
        alert = self.calculator.generate_alert_message(
            ccri, risk_level, ndt, ha_aqi, "Moderate recovery",
            pm25_aqi_method="instantaneous"
        )
        
        self.assertIn("instant reading", alert.lower(),
                     "Alert must show 'instant reading' qualifier")
        self.assertIn("may change quickly", alert.lower(),
                     "Alert must warn that instantaneous reading may change")
    
    def test_no_qualifier_when_method_unknown(self):
        """When PM2.5 method is None, show AQI without qualifier"""
        ndt = 30.0
        ha_aqi = 100.0
        rds = 20.0
        
        ccri, risk_level = self.calculator.calculate_ccri(ndt, ha_aqi, rds)
        
        alert = self.calculator.generate_alert_message(
            ccri, risk_level, ndt, ha_aqi, "Moderate recovery",
            pm25_aqi_method=None
        )
        
        self.assertIn("100", alert,
                     "AQI value must be present")
        # Should not have either qualifier
        self.assertNotIn("12h average", alert)
        self.assertNotIn("instant reading", alert.lower())
    
    def test_labels_distinguish_nowcast_from_instant(self):
        """The two labels must be clearly distinguishable"""
        ndt = 30.0
        ha_aqi = 100.0
        rds = 20.0
        ccri, risk_level = self.calculator.calculate_ccri(ndt, ha_aqi, rds)
        
        alert_nowcast = self.calculator.generate_alert_message(
            ccri, risk_level, ndt, ha_aqi, "Moderate", pm25_aqi_method="nowcast_12h"
        )
        
        alert_instant = self.calculator.generate_alert_message(
            ccri, risk_level, ndt, ha_aqi, "Moderate", pm25_aqi_method="instantaneous"
        )
        
        # Verify they contain different qualifiers
        self.assertIn("12h", alert_nowcast)
        self.assertNotIn("12h", alert_instant)
        self.assertIn("instant", alert_instant.lower())
        self.assertNotIn("instant", alert_nowcast.lower())


if __name__ == '__main__':
    unittest.main()
