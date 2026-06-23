import unittest
from datetime import date, datetime, timedelta

from ccri_calculator import CCRICalculator
from data_fetcher import DataFetcher
from ha_aqi_calculator import HAAQICalculator
from ndt_calculator import NDTCalculator
from prana_system import PRANASystem
from rds_calculator import RDSCalculator


class AQIComponentTests(unittest.TestCase):
    def setUp(self):
        self.fetcher = DataFetcher(api_key=None)

    def test_pm25_uses_updated_good_breakpoint(self):
        self.assertAlmostEqual(self.fetcher._calculate_pm25_aqi(9.0), 50.0, places=1)

    def test_provider_us_aqi_preserved_with_components(self):
        pollutants = {
            'us_aqi': {'value': 78, 'unit': 'AQI', 'source': 'open-meteo-cams'},
            'pm2.5': {'value': 18, 'unit': 'ug/m3'},
            'o3': {'value': 80, 'unit': 'ug/m3'},
        }

        result = self.fetcher.calculate_pollutant_aqi_components(pollutants)

        self.assertEqual(result['base_aqi'], 78)
        self.assertEqual(result['source'], 'open-meteo-cams')
        self.assertIn('PM2.5', result['pollutant_aqi'])
        self.assertIn('O3', result['pollutant_aqi'])
        self.assertIn('averaging_windows', result)

    def test_pm25_nowcast_uses_weighted_average(self):
        from data_fetcher import _pm25_nowcast
        # Uniform values -> NowCast == the value itself
        self.assertAlmostEqual(_pm25_nowcast([20.0] * 12), 20.0, places=3)

    def test_pm25_nowcast_weights_recent_higher(self):
        from data_fetcher import _pm25_nowcast
        # Spike in most recent hour should pull average up vs older hours
        older = [10.0] * 11
        recent = [80.0]
        nowcast = _pm25_nowcast(older + recent)
        self.assertGreater(nowcast, 10.0)
        self.assertLess(nowcast, 80.0)

    def test_pm25_nowcast_applied_when_history_present(self):
        pollutants = {
            'pm2.5': {
                'value': 50.0,
                'unit': 'ug/m3',
                'history_12h': [10.0] * 11 + [50.0],
            }
        }
        result = self.fetcher.calculate_pollutant_aqi_components(pollutants)
        self.assertEqual(result['averaging_windows'].get('PM2.5'), 'nowcast_12h')

    def test_pm25_instantaneous_when_no_history(self):
        pollutants = {
            'pm2.5': {'value': 18.0, 'unit': 'ug/m3'}
        }
        result = self.fetcher.calculate_pollutant_aqi_components(pollutants)
        self.assertEqual(result['averaging_windows'].get('PM2.5'), 'instantaneous')

    def test_pm10_breakpoints(self):
        self.assertAlmostEqual(self.fetcher._calculate_pm10_aqi(54), 50.0, places=1)
        self.assertAlmostEqual(self.fetcher._calculate_pm10_aqi(154), 100.0, places=1)
        self.assertAlmostEqual(self.fetcher._calculate_pm10_aqi(254), 150.0, places=1)

    def test_o3_breakpoints(self):
        self.assertAlmostEqual(self.fetcher._calculate_o3_aqi(0.054), 50.0, places=1)
        self.assertAlmostEqual(self.fetcher._calculate_o3_aqi(0.07), 100.0, places=1)

    def test_co_breakpoints(self):
        self.assertAlmostEqual(self.fetcher._calculate_co_aqi(4.4), 50.0, places=1)
        self.assertAlmostEqual(self.fetcher._calculate_co_aqi(9.4), 100.0, places=1)

    def test_no2_breakpoints(self):
        self.assertAlmostEqual(self.fetcher._calculate_no2_aqi(53), 50.0, places=1)
        self.assertAlmostEqual(self.fetcher._calculate_no2_aqi(100), 100.0, places=1)


class HeatPollutionRiskTests(unittest.TestCase):
    def setUp(self):
        self.calculator = HAAQICalculator()

    def test_pm25_dominant_day_has_heat_coupling(self):
        """PM2.5-dominant day: heat increment from ozone blends into base AQI."""
        result = self.calculator.calculate_heat_pollution_risk(
            base_aqi=150,
            pollutant_aqi={'PM2.5': 150, 'O3': 60},
            temp_c=35,
        )
        self.assertAlmostEqual(result['ozone_heat_factor'], 1.4, places=2)
        self.assertAlmostEqual(result['ozone_heat_adjusted_aqi'], 84.0, places=1)
        # New blending: increment = (84-60)*0.5 = 12; risk = 150 + 12 = 162
        self.assertAlmostEqual(result['heat_pollution_risk'], 162.0, places=1)
        # Heat coupling is nonzero (risk > base_aqi)
        self.assertGreater(result['heat_pollution_risk'], result['base_aqi'])

    def test_ozone_dominant_day_has_heat_coupling(self):
        """Ozone-dominant day: heat increment blends on top of base AQI."""
        result = self.calculator.calculate_heat_pollution_risk(
            base_aqi=95,
            pollutant_aqi={'PM2.5': 70, 'O3': 90},
            temp_c=35,
        )
        self.assertAlmostEqual(result['ozone_heat_adjusted_aqi'], 126.0, places=1)
        # New blending: increment = (126-90)*0.5 = 18; risk = 95 + 18 = 113
        self.assertAlmostEqual(result['heat_pollution_risk'], 113.0, places=1)
        # Heat coupling is nonzero (risk > base_aqi)
        self.assertGreater(result['heat_pollution_risk'], result['base_aqi'])

    def test_pm10_dominant_day_has_heat_coupling(self):
        """PM10-dominant day: heat increment from ozone still applies."""
        result = self.calculator.calculate_heat_pollution_risk(
            base_aqi=120,
            pollutant_aqi={'PM10': 120, 'O3': 50},
            temp_c=38,
        )
        self.assertAlmostEqual(result['ozone_heat_factor'], 1.52, places=2)
        self.assertAlmostEqual(result['ozone_heat_adjusted_aqi'], 76.0, places=1)
        # New blending: increment = (76-50)*0.5 = 13; risk = 120 + 13 = 133
        self.assertAlmostEqual(result['heat_pollution_risk'], 133.0, places=1)
        # Heat coupling is nonzero (risk > base_aqi)
        self.assertGreater(result['heat_pollution_risk'], result['base_aqi'])


class RDSTests(unittest.TestCase):
    def test_rds_accumulates_recent_hot_nights_with_decay(self):
        calculator = RDSCalculator()
        today = date.today()
        calculator.add_night_temperature(34.0, today)
        calculator.add_night_temperature(34.0, today - timedelta(days=1))

        result = calculator.calculate_rds()

        self.assertAlmostEqual(result['rds_mid'], 36.0, places=1)
        self.assertEqual(result['consecutive_nights'], 2)

    def test_cool_night_has_zero_recovery_failure(self):
        calculator = RDSCalculator()
        calculator.add_night_temperature(28.0, date.today())

        result = calculator.calculate_rds()

        self.assertEqual(result['rds_mid'], 0.0)
        self.assertEqual(result['consecutive_nights'], 0)

    def test_onboarding_adjustment_increases_rds_for_tin_roof_top_floor(self):
        onboarding = {'ac': False, 'roof_material': 'tin', 'floor_level': 'top'}
        calculator = RDSCalculator(onboarding_data=onboarding)
        today = date.today()
        calculator.add_night_temperature(31.0, today)

        result = calculator.calculate_rds()
        # Expected offset: tin(+2.0) + top(+1.5) = +3.5
        # Effective temp = 31 + 3.5 = 34.5 >= 32, so RFU > 0
        self.assertGreater(result['rds_mid'], 0.0)

    def test_onboarding_adjustment_reduces_rds_for_ac(self):
        onboarding = {'ac': True, 'roof_material': 'concrete', 'floor_level': 'ground'}
        calculator = RDSCalculator(onboarding_data=onboarding)
        today = date.today()
        calculator.add_night_temperature(33.0, today)

        no_adjust = RDSCalculator()
        no_adjust.add_night_temperature(33.0, today)

        result_with = calculator.calculate_rds()
        result_without = no_adjust.calculate_rds()

        # AC offset = -3.0, so effective temp = 30.0 < 32 => RFU = 0
        self.assertEqual(result_with['rds_mid'], 0.0)
        # Without adjustment, 33C > 32C => RFU > 0
        self.assertGreater(result_without['rds_mid'], 0.0)

    def test_onboarding_adjustment_no_onboarding_matches_standard(self):
        standard = RDSCalculator()
        with_onboarding = RDSCalculator(onboarding_data=None)
        today = date.today()
        standard.add_night_temperature(34.0, today)
        with_onboarding.add_night_temperature(34.0, today)

        result_std = standard.calculate_rds()
        result_wob = with_onboarding.calculate_rds()

        self.assertAlmostEqual(result_std['rds_mid'], result_wob['rds_mid'], places=5)

    def test_rds_empty_nights_returns_zero(self):
        result = RDSCalculator().calculate_rds()
        self.assertEqual(result['rds_mid'], 0.0)
        self.assertEqual(result['consecutive_nights'], 0)

    def test_rds_extreme_heat_caps_rfu(self):
        calc = RDSCalculator()
        calc.add_night_temperature(60.0, date.today())
        result = calc.calculate_rds()
        # RFU capped at 100, so RDS <= 100
        self.assertAlmostEqual(result['rds_mid'], 100.0, places=1)
        self.assertEqual(result['consecutive_nights'], 1)

    def test_rds_single_cool_night_all_past_hot(self):
        calc = RDSCalculator()
        today = date.today()
        calc.add_night_temperature(34.0, today - timedelta(days=2))
        calc.add_night_temperature(35.0, today - timedelta(days=1))
        calc.add_night_temperature(28.0, today)
        result = calc.calculate_rds()
        # Consecutive hot nights: yesterday (35C) + day before (34C) = 2
        self.assertEqual(result['consecutive_nights'], 2)
        # RDS should reflect past hot nights with decay
        self.assertGreater(result['rds_mid'], 0.0)

    def test_rds_onboarding_adjustment_via_method_arg(self):
        calc = RDSCalculator()
        calc.add_night_temperature(33.0, date.today())
        result_no = calc.calculate_rds()
        result_ac = calc.calculate_rds(onboarding_data={'ac': True})
        # With AC (-3C), effective temp = 30 < 32 -> RFU = 0
        self.assertEqual(result_ac['rds_mid'], 0.0)
        self.assertGreater(result_no['rds_mid'], 0.0)


class NDTTests(unittest.TestCase):
    def setUp(self):
        from ndt_calculator import NDTCalculator
        self.calculator = NDTCalculator(urban_heat_offset=0)

    def test_wbgt_formula_weights_exact(self):
        # With wet_bulb=30, wind_speed=0.5, no shortwave:
        #   solar_gain = 5.0 / (1 + 0.5) = 3.333...
        #   Tg = 33 + 3.333 = 36.333...
        #   WBGT = 0.7*30 + 0.2*36.333 + 0.1*33 = 21 + 7.267 + 3.3 = 31.567
        result = self.calculator.calculate_wbgt(
            temp_c=33, humidity_percent=70,
            wet_bulb_temp=30, wind_speed_ms=0.5,
            shortwave_radiation=None,
        )
        self.assertAlmostEqual(result, 31.567, places=1)

    def test_wbgt_with_solar_radiation_and_high_wind(self):
        # With wet_bulb=32, wind_speed=1.0, shortwave=600:
        #   solar_gain = min(8.0, 600/120) = 5.0
        #   solar_gain = 5.0 / (1 + 0.25*1.0) = 4.0
        #   Tg = 35 + 4.0 = 39.0
        #   WBGT = 0.7*32 + 0.2*39 + 0.1*35 = 22.4 + 7.8 + 3.5 = 33.7
        result = self.calculator.calculate_wbgt(
            temp_c=35, humidity_percent=80,
            wet_bulb_temp=32, wind_speed_ms=1.0,
            shortwave_radiation=600,
        )
        self.assertAlmostEqual(result, 33.7, places=1)

    def test_urban_heat_offset_added(self):
        from ndt_calculator import NDTCalculator
        base = NDTCalculator(urban_heat_offset=0).calculate_ndt(
            {'temp': 33, 'humidity': 70, 'wind_speed': 0.5}
        )
        offset = NDTCalculator(urban_heat_offset=3).calculate_ndt(
            {'temp': 33, 'humidity': 70, 'wind_speed': 0.5}
        )
        self.assertAlmostEqual(offset - base, 3.0, places=5)

    def test_ndt_with_partial_weather_data(self):
        # Should not crash when optional fields are missing
        result = self.calculator.calculate_ndt(
            {'temp': 30, 'humidity': 50}
        )
        self.assertIsInstance(result, float)

    def test_heat_stress_levels(self):
        self.assertEqual(self.calculator.get_heat_stress_level(26)[0], 'LOW')
        self.assertEqual(self.calculator.get_heat_stress_level(28)[0], 'MODERATE')
        self.assertEqual(self.calculator.get_heat_stress_level(31)[0], 'HIGH')
        self.assertEqual(self.calculator.get_heat_stress_level(33)[0], 'VERY HIGH')
        self.assertEqual(self.calculator.get_heat_stress_level(36)[0], 'EXTREME')


class StructuredResponseTests(unittest.TestCase):
    def test_recovery_component_has_description_field(self):
        from prana_system import PRANASystem
        system = PRANASystem(location_name="Test City")
        now = datetime.now()
        result = {
            'timestamp': now,
            'location': 'Test City',
            'risk_level': 'ELEVATED',
            'ccri': 35.0,
            'ndt': 30.5,
            'heat_level': 'MODERATE',
            'ha_aqi': 85,
            'heat_pollution_risk': 85,
            'base_aqi': 80,
            'oaf': 1.2,
            'ozone_heat_factor': 1.2,
            'heat_pollution': {
                'ozone_heat_adjusted_aqi': 96.0,
                'ozone_heat_factor': 1.2,
                'method': 'ozone_specific_heat_adjustment',
                'pollution_confidence': 'MEDIUM',
            },
            'air_quality_components': {
                'dominant_pollutant': 'PM2.5',
                'pollutant_aqi': {'PM2.5': 80, 'O3': 60},
                'averaging_windows': {'PM2.5': 'instantaneous'},
            },
            'rds': {'rds_low': 23.0, 'rds_mid': 25.0, 'rds_high': 27.0, 'consecutive_nights': 1},
            'raw_rds': {'rds_low': 23.0, 'rds_mid': 25.0, 'rds_high': 27.0, 'consecutive_nights': 1},
            'rds_adjustment': {
                'applied': False, 'delta': 0.0, 'reason': 'no_checkin',
                'adjusted_rds': {'rds_low': 23.0, 'rds_mid': 25.0, 'rds_high': 27.0, 'consecutive_nights': 1},
            },
            'consecutive_nights': 1,
            'rds_message': 'Recovery debt: MODERATE ...',
            'ccri_components': {
                'heat_score': 30.0,
                'pollution_score': 25.0,
                'recovery_score': 25.0,
                'base_ccri': 7.5,
                'recovery_multiplier': 1.075,
            },
        }
        weather = {
            'source': 'open-meteo',
            'temp': 30, 'humidity': 60,
            'wet_bulb_temp': 22.0,
            'shortwave_radiation': 500.0,
        }
        pollutants = {
            'pm2.5': {'value': 25, 'unit': 'ug/m3'},
            'o3': {'value': 80, 'unit': 'ug/m3'},
        }
        structured = system._build_structured_result(result, weather, pollutants)

        self.assertEqual(structured['components']['recovery']['description'],
                         'outdoor_nighttime_recovery_risk_proxy')
        self.assertEqual(structured['components']['heat']['description'],
                         'estimated_wbgt_plus_urban_offset')
        self.assertIn('title', structured['summary'])
        self.assertIn('confidence', structured)
        self.assertIn('sources', structured)


class CCRITests(unittest.TestCase):
    def test_ccri_returns_safe_for_low_compound_risk(self):
        ccri, risk = CCRICalculator().calculate_ccri(ndt=28, ha_aqi=60, rds=0)
        self.assertLess(ccri, 20)
        self.assertEqual(risk[0], 'SAFE')

    def test_ccri_emergency_tier_at_extreme(self):
        ccri, risk = CCRICalculator().calculate_ccri(ndt=36, ha_aqi=250, rds=100)
        self.assertGreater(ccri, 80)
        self.assertEqual(risk[0], 'COMPOUND EMERGENCY')

    def test_ccri_uses_default_pollution_when_ha_aqi_none(self):
        ccri, risk = CCRICalculator().calculate_ccri(ndt=35, ha_aqi=None, rds=50)
        self.assertIsInstance(ccri, float)
        self.assertGreater(ccri, 0)

    def test_ccri_recovery_multiplier_range(self):
        comp = CCRICalculator().calculate_component_scores(ndt=30, ha_aqi=100, rds=100)
        # RDS=100 in high tier (80-150): piecewise scaling gives ~1.3-1.6x
        self.assertGreater(comp['recovery_multiplier'], 1.3)
        self.assertLess(comp['recovery_multiplier'], 1.6)
        # No-recovery case
        comp_zero = CCRICalculator().calculate_component_scores(ndt=30, ha_aqi=100, rds=0)
        self.assertAlmostEqual(comp_zero['recovery_multiplier'], 1.0, places=4)

    def test_ccri_score_rises_with_rds(self):
        low_rds, _ = CCRICalculator().calculate_ccri(ndt=33, ha_aqi=150, rds=0)
        high_rds, _ = CCRICalculator().calculate_ccri(ndt=33, ha_aqi=150, rds=100)
        self.assertGreater(high_rds, low_rds)


if __name__ == '__main__':
    unittest.main()
