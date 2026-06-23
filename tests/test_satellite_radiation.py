"""Test satellite radiation integration"""

import unittest
from unittest.mock import patch, MagicMock
from data_fetcher import DataFetcher


class TestSatelliteRadiation(unittest.TestCase):
    def setUp(self):
        self.fetcher = DataFetcher(api_key=None)
        self.lat, self.lon = 13.0827, 80.2707  # Chennai
    
    @patch('data_fetcher.DataFetcher._get_satellite_radiation')
    def test_fallback_to_model_when_satellite_fails(self, mock_satellite):
        """Weather fetch must work even if satellite radiation call fails"""
        # Satellite returns None (failed or unavailable)
        mock_satellite.return_value = None
        
        # Mock successful forecast API response with model radiation
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'current': {
                'time': '2026-06-23T10:00',
                'temperature_2m': 32.0,
                'relative_humidity_2m': 65.0,
                'surface_pressure': 1010.0,
                'wind_speed_10m': 2.5,
            },
            'hourly': {
                'time': ['2026-06-23T10:00'],
                'wet_bulb_temperature_2m': [28.0],
                'shortwave_radiation': [650.0],  # Model-derived fallback
                'direct_radiation': [500.0],
                'diffuse_radiation': [150.0],
            }
        }
        self.fetcher._session.get = MagicMock(return_value=mock_response)
        
        weather = self.fetcher._get_openmeteo_current_weather(self.lat, self.lon)
        
        self.assertIsNotNone(weather, "Weather must be returned even if satellite fails")
        self.assertEqual(weather['shortwave_radiation'], 650.0,
                        "Must use model-derived radiation when satellite unavailable")
    
    @patch('data_fetcher.DataFetcher._get_satellite_radiation')
    def test_satellite_radiation_used_when_available(self, mock_satellite):
        """Satellite radiation should be used when available, not model value"""
        # Satellite returns value
        mock_satellite.return_value = 720.0  # Satellite-observed
        
        # Mock forecast API response with different model radiation
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'current': {
                'time': '2026-06-23T10:00',
                'temperature_2m': 32.0,
                'relative_humidity_2m': 65.0,
                'surface_pressure': 1010.0,
                'wind_speed_10m': 2.5,
            },
            'hourly': {
                'time': ['2026-06-23T10:00'],
                'wet_bulb_temperature_2m': [28.0],
                'shortwave_radiation': [650.0],  # Model value (should be ignored)
                'direct_radiation': [500.0],
                'diffuse_radiation': [150.0],
            }
        }
        self.fetcher._session.get = MagicMock(return_value=mock_response)
        
        weather = self.fetcher._get_openmeteo_current_weather(self.lat, self.lon)
        
        self.assertIsNotNone(weather)
        self.assertEqual(weather['shortwave_radiation'], 720.0,
                        "Must use satellite radiation when available, not model value")
        self.assertNotEqual(weather['shortwave_radiation'], 650.0,
                           "Must NOT use model radiation when satellite is available")
    
    @patch('data_fetcher.DataFetcher._get_satellite_radiation')
    def test_get_current_weather_still_works_without_satellite(self, mock_satellite):
        """Integration test: current weather must work if satellite endpoint fails"""
        # Satellite fails and returns None
        mock_satellite.return_value = None
        
        # Mock forecast API success
        forecast_response = MagicMock()
        forecast_response.status_code = 200
        forecast_response.json.return_value = {
            'current': {
                'time': '2026-06-23T10:00',
                'temperature_2m': 32.0,
                'relative_humidity_2m': 65.0,
            },
            'hourly': {
                'time': ['2026-06-23T10:00'],
                'wet_bulb_temperature_2m': [28.0],
                'shortwave_radiation': [650.0],
            }
        }
        
        self.fetcher._session.get = MagicMock(return_value=forecast_response)
        
        weather = self.fetcher._get_openmeteo_current_weather(self.lat, self.lon)
        
        self.assertIsNotNone(weather, "Weather must work even if satellite API fails completely")
        self.assertIsNotNone(weather.get('shortwave_radiation'),
                            "Shortwave radiation must still be present (from model)")


if __name__ == '__main__':
    unittest.main()
