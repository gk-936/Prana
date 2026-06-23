"""Test Issue 7 fix: Forecast timestamp validation"""

import unittest
from datetime import datetime, timedelta
from rds_calculator import RDSCalculator


class TestIssue7ForecastTimestampValidation(unittest.TestCase):
    def setUp(self):
        self.calculator = RDSCalculator()
    
    def test_stale_timestamps_discarded(self):
        """Forecast points with timestamps in the past should be discarded"""
        now = datetime.now()
        
        # Create forecast with stale data
        forecast = [
            {'timestamp': now - timedelta(hours=2), 'temp': 30.0},  # Stale
            {'timestamp': now - timedelta(hours=1), 'temp': 31.0},  # Stale
            {'timestamp': now + timedelta(hours=8), 'temp': 28.0},  # Valid future
            {'timestamp': now + timedelta(hours=23), 'temp': 26.0},  # Valid night
        ]
        
        result = self.calculator.estimate_nighttime_temp_from_forecast(forecast)
        
        # Should use valid future data, not stale
        self.assertIsNotNone(result, "Should return a temperature from valid future data")
    
    def test_all_stale_returns_none(self):
        """When all timestamps are stale, return None not fallback to stale data"""
        now = datetime.now()
        
        # All stale
        forecast = [
            {'timestamp': now - timedelta(hours=3), 'temp': 30.0},
            {'timestamp': now - timedelta(hours=2), 'temp': 31.0},
            {'timestamp': now - timedelta(hours=1), 'temp': 32.0},
        ]
        
        result = self.calculator.estimate_nighttime_temp_from_forecast(forecast)
        
        self.assertIsNone(result, "Must return None when all forecast data is stale")
    
    def test_mixed_stale_and_valid(self):
        """Mixed stale and valid data - only valid should be used"""
        now = datetime.now()
        
        forecast = [
            {'timestamp': now - timedelta(hours=1), 'temp': 40.0},  # Stale, high temp
            {'timestamp': now + timedelta(hours=10), 'temp': 25.0},  # Valid, low temp
            {'timestamp': now + timedelta(hours=24), 'temp': 27.0},  # Valid night
        ]
        
        result = self.calculator.estimate_nighttime_temp_from_forecast(forecast)
        
        # Should be 25.0 (from valid data), not influenced by stale 40.0
        self.assertIsNotNone(result)
        self.assertLess(result, 30.0, "Result should not be influenced by stale high temperature")
    
    def test_future_data_prevents_duplicate_rds(self):
        """Valid future data should not cause duplicate RDS entries"""
        now = datetime.now()
        today = now.date()
        
        # Add an RDS entry for today
        self.calculator.add_night_temperature(30.0, today)
        self.assertEqual(len(self.calculator.nighttime_temps), 1)
        
        # Forecast with valid future night data
        forecast = [
            {'timestamp': now + timedelta(hours=10), 'temp': 28.0},
            {'timestamp': now + timedelta(hours=24), 'temp': 26.0},
        ]
        
        tonight_min = self.calculator.estimate_nighttime_temp_from_forecast(forecast)
        self.assertIsNotNone(tonight_min)
        
        # If we add this, it should update existing entry, not duplicate
        self.calculator.add_night_temperature(tonight_min, today)
        self.assertEqual(len(self.calculator.nighttime_temps), 1,
                        "Should not create duplicate entries for same date")
    
    def test_boundary_timestamp_exactly_now(self):
        """Timestamp exactly equal to now should be discarded (not strictly future)"""
        now = datetime.now()
        
        forecast = [
            {'timestamp': now, 'temp': 35.0},  # Exactly now - should be discarded
            {'timestamp': now + timedelta(hours=10), 'temp': 25.0},  # Valid
        ]
        
        result = self.calculator.estimate_nighttime_temp_from_forecast(forecast)
        
        # Should use only the strictly future data
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 25.0, places=1)


if __name__ == '__main__':
    unittest.main()
