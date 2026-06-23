"""
PRANA System - Complete Temperature Calculation Pipeline
Asia's First Compound Climate Emergency Platform

This integrates:
- NDT: Neighbourhood Danger Temperature (WBGT + urban heat island)
- HA-AQI: Heat-Amplified AQI (thermal chemistry correction)
- RDS: Recovery Debt Score (nighttime sleep deprivation tracking)
- CCRI: Compound Climate Risk Index (multiplicative synergistic risk)
"""

from datetime import datetime, timedelta
from data_fetcher import DataFetcher
from ndt_calculator import NDTCalculator
from ha_aqi_calculator import HAAQICalculator
from rds_calculator import RDSCalculator
from ccri_calculator import CCRICalculator
from config import *
from uhi_lookup import lookup_uhi_offset
from backend.logger import get_logger

logger = get_logger("prana_system")


class PRANASystem:
    def __init__(self, api_key=None, location_name="your ward", urban_heat_offset=None, openaq_api_key=None, onboarding_data=None):
        self.location_name = location_name
        self.onboarding_data = onboarding_data
        if urban_heat_offset is None:
            urban_heat_offset = lookup_uhi_offset(location_name)
        self.data_fetcher = DataFetcher(api_key, openaq_api_key)
        self.ndt_calculator = NDTCalculator(urban_heat_offset)
        self.ha_aqi_calculator = HAAQICalculator()
        self.rds_calculator = RDSCalculator(onboarding_data)
        self.ccri_calculator = CCRICalculator()

        self.current_ndt = None
        self.current_ha_aqi = None
        self.current_rds = None
        self.current_ccri = None
        self.last_update = None

    def update_all(self, lat, lon, sleep_checkin=None, debug=False):
        """
        Update all climate risk metrics.

        Returns:
            Dict with all metrics and alert message
        """
        logger.info("=" * 60)
        logger.info("PRANA SYSTEM UPDATE - %s", self.location_name)
        logger.info("=" * 60)

        # Step 1: Fetch current weather
        logger.info("Step 1: Fetching current weather data...")
        weather = self.data_fetcher.get_current_weather(lat, lon)
        if not weather:
            logger.error("Failed to fetch weather data")
            return None
        logger.info("Weather: %.1fC, %.0f%% humidity", weather['temp'], weather['humidity'])

        # Step 2: Fetch weather forecast (include past days for RDS history)
        logger.info("Step 2: Fetching weather forecast...")
        past_days = RDS_MAX_DAYS if not self.rds_calculator.nighttime_temps else 0
        forecast = self.data_fetcher.get_forecast(lat, lon, hours=24, past_days=past_days)
        if not forecast:
            logger.error("Failed to fetch forecast")
            return None
        logger.info("Forecast: %s data points retrieved", len(forecast))

        # Step 3: Calculate NDT
        logger.info("Step 3: Calculating NDT (WBGT + urban heat island)...")
        ndt = self.ndt_calculator.calculate_ndt(weather)
        heat_level, heat_desc = self.ndt_calculator.get_heat_stress_level(ndt)
        self.current_ndt = ndt
        logger.info("NDT: %.1fC", ndt)
        logger.info("  Heat Stress: %s - %s", heat_level, heat_desc)

        # Step 4: Fetch air quality and calculate heat-pollution risk
        logger.info("Step 4: Calculating heat-pollution risk (ozone-specific heat adjustment)...")
        pollutants = self.data_fetcher.get_air_quality(lat, lon)
        aqi_components = {
            'base_aqi': None,
            'dominant_pollutant': None,
            'pollutant_aqi': {},
            'source': None
        }
        heat_pollution = None
        base_aqi = None
        oaf = None

        if pollutants:
            aqi_components = self.data_fetcher.calculate_pollutant_aqi_components(pollutants, debug=debug)
            base_aqi = aqi_components['base_aqi']
            if base_aqi:
                heat_pollution = self.ha_aqi_calculator.calculate_heat_pollution_risk(
                    base_aqi, aqi_components['pollutant_aqi'], weather['temp']
                )
                oaf = heat_pollution['ozone_heat_factor']
                ha_aqi = heat_pollution['heat_pollution_risk']
                aqi_category, aqi_desc = self.ha_aqi_calculator.get_aqi_category(ha_aqi)
                self.current_ha_aqi = ha_aqi
                logger.info("Base AQI: %.0f", base_aqi)
                logger.info("Dominant pollutant: %s", aqi_components['dominant_pollutant'])
                logger.info("Ozone heat factor: %.2fx at %.1fC", oaf, weather['temp'])
                logger.info("Heat-pollution risk: %.0f (%s)", ha_aqi, aqi_category)
                logger.info("  %s", aqi_desc)
            else:
                self.current_ha_aqi = None
                logger.info("Could not calculate AQI from available pollutants")
        else:
            self.current_ha_aqi = None
            logger.info("No air quality data available for this location")

        # Step 5: Calculate RDS
        logger.info("Step 5: Calculating RDS (nighttime recovery tracking)...")

        # Backfill historical nighttime temps for first-time users
        if past_days > 0:
            self._backfill_rds_history(forecast)

        tonight_min = self.rds_calculator.estimate_nighttime_temp_from_forecast(forecast)
        if tonight_min:
            logger.info("  Tonight's estimated minimum: %.1fC", tonight_min)
            self.rds_calculator.add_night_temperature(tonight_min)

        raw_rds_dict = self.rds_calculator.calculate_rds(debug=debug)
        rds_dict, rds_adjustment = self.rds_calculator.apply_sleep_checkin_adjustment(raw_rds_dict, sleep_checkin)
        self.current_rds = rds_dict['rds_mid']

        rds_message, rds_color = self.rds_calculator.get_rds_message(rds_dict, tonight_min)
        if rds_adjustment['applied']:
            logger.info("RDS adjusted by check-in: %+.1f", rds_adjustment['delta'])
        logger.info("RDS (low/mid/high): %.1f / %.1f / %.1f", rds_dict['rds_low'], rds_dict['rds_mid'], rds_dict['rds_high'])
        logger.info("  %s", rds_message)

        # Step 6: Calculate CCRI
        logger.info("Step 6: Calculating CCRI (compound synergistic risk)...")
        ccri, risk_level = self.ccri_calculator.calculate_ccri(ndt, self.current_ha_aqi, rds_dict['rds_mid'], debug=debug)
        ccri_components = self.ccri_calculator.calculate_component_scores(ndt, self.current_ha_aqi, rds_dict['rds_mid'])
        self.current_ccri = ccri

        level_name, level_desc, level_color = risk_level
        logger.info("CCRI: %.1f/100", ccri)
        logger.info("  Risk Level: %s", level_name)
        logger.info("  %s", level_desc)

        # Step 7: Generate alert
        logger.info("Step 7: Generating personalized alert...")
        pollution_data_quality = ccri_components.get('pollution_data_quality', 'available')
        
        # Extract PM2.5 averaging method for alert qualifier
        pm25_aqi_method = None
        if aqi_components.get('averaging_windows'):
            pm25_aqi_method = aqi_components['averaging_windows'].get('PM2.5')
        
        alert_message = self.ccri_calculator.generate_alert_message(
            ccri, risk_level, ndt, self.current_ha_aqi, rds_message, self.location_name, 
            pollution_data_quality, pm25_aqi_method
        )

        self.last_update = datetime.now()

        logger.info("=" * 60)
        logger.info("ALERT MESSAGE")
        logger.info("=" * 60)
        logger.info(alert_message)
        logger.info("=" * 60)
        logger.info("Update completed at %s", self.last_update.strftime('%Y-%m-%d %H:%M:%S'))
        logger.info("Next update in %s hours", UPDATE_INTERVAL)
        logger.info("=" * 60)

        result = {
            'timestamp': self.last_update,
            'location': self.location_name,
            'ndt': ndt,
            'heat_level': heat_level,
            'ha_aqi': self.current_ha_aqi,
            'heat_pollution_risk': self.current_ha_aqi,
            'base_aqi': base_aqi,
            'oaf': oaf,
            'ozone_heat_factor': oaf,
            'air_quality_components': aqi_components,
            'heat_pollution': heat_pollution,
            'rds': rds_dict,
            'raw_rds': raw_rds_dict,
            'rds_adjustment': rds_adjustment,
            'consecutive_nights': rds_dict['consecutive_nights'],
            'rds_message': rds_message,
            'ccri': ccri,
            'ccri_components': ccri_components,
            'risk_level': level_name,
            'alert_message': alert_message,
            'weather': weather,
            'forecast': forecast,
        }

        result.update(self._build_structured_result(result, weather, pollutants))
        return result

    def get_status_summary(self):
        if not self.last_update:
            return "System not initialized. Run update_all() first."

        age = (datetime.now() - self.last_update).total_seconds() / 3600
        ha_aqi_str = f"{self.current_ha_aqi:.0f}" if self.current_ha_aqi is not None else "N/A"
        return (
            f"\nPRANA System Status - {self.location_name}\n"
            f"Last Updated: {self.last_update.strftime('%Y-%m-%d %H:%M:%S')} ({age:.1f} hours ago)\n\n"
            f"Current Metrics:\n"
            f"- NDT (Heat Stress): {self.current_ndt:.1f}C\n"
            f"- Heat-pollution risk: {ha_aqi_str}\n"
            f"- RDS (Sleep Debt): {self.current_rds:.1f}\n"
            f"- CCRI (Compound Risk): {self.current_ccri:.1f}/100\n\n"
            f"Status: {'UPDATE NEEDED' if age > UPDATE_INTERVAL else 'Current'}\n"
        )

    def _backfill_rds_history(self, forecast):
        """Extract past nights' minimum temps from forecast data and seed RDS."""
        from collections import defaultdict
        nights = defaultdict(list)
        now = datetime.now()

        for item in forecast:
            ts = item['timestamp']
            # Past data only
            if ts >= now:
                continue
            hour = ts.hour
            # Night hours: 10 PM to 6 AM
            if hour >= 22 or hour <= 6:
                night_key = ts.date() if hour <= 6 else ts.date() - timedelta(days=1)
                nights[night_key].append(item['temp'])

        past_count = 0
        for date in sorted(nights.keys()):
            night_min = min(nights[date])
            if not any(n['date'] == date for n in self.rds_calculator.nighttime_temps):
                self.rds_calculator.add_night_temperature(night_min, date)
                past_count += 1

        if past_count:
            logger.info("  Backfilled %s past nights for RDS history", past_count)

    def _build_structured_result(self, result, weather, pollutants):
        weather_source = weather.get('source', 'unknown') if weather else 'unknown'
        air_quality_sources = sorted({
            value.get('source', 'unknown')
            for value in pollutants.values()
            if isinstance(value, dict)
        }) if pollutants else []

        confidence = self._estimate_confidence(weather, pollutants)

        return {
            'summary': {
                'title': f"PRANA risk is {result['risk_level']}",
                'location': result['location'],
                'score': round(result['ccri'], 1),
                'risk_level': result['risk_level'],
                'last_updated': result['timestamp'].isoformat(),
                'confidence': confidence,
            },
            'components': {
                'heat': {
                    'label': 'NDT',
                    'description': 'estimated_wbgt_plus_urban_offset',
                    'value': round(result['ndt'], 1),
                    'unit': 'degC',
                    'level': result['heat_level'],
                    'score': round(result['ccri_components']['heat_score'], 1),
                    'confidence': self._estimate_heat_confidence(weather),
                },
                'air_quality': {
                    'label': 'Heat-pollution risk',
                    'value': round(result['heat_pollution_risk'], 1) if result['heat_pollution_risk'] is not None else None,
                    'unit': 'score',
                    'base_aqi': round(result['base_aqi'], 1) if result['base_aqi'] is not None else None,
                    'dominant_pollutant': result['air_quality_components'].get('dominant_pollutant'),
                    'pollutant_aqi': result['air_quality_components'].get('pollutant_aqi', {}),
                    'averaging_windows': result['air_quality_components'].get('averaging_windows', {}),
                    'pm25_aqi_method': result['air_quality_components'].get('averaging_windows', {}).get('PM2.5'),
                    'ozone_heat_factor': round(result['ozone_heat_factor'], 2) if result['ozone_heat_factor'] is not None else None,
                    'ozone_heat_adjusted_aqi': (
                        round(result['heat_pollution']['ozone_heat_adjusted_aqi'], 1)
                        if result.get('heat_pollution') and result['heat_pollution'].get('ozone_heat_adjusted_aqi') is not None
                        else None
                    ),
                    'score': round(result['ccri_components']['pollution_score'], 1),
                    'method': result['heat_pollution'].get('method') if result.get('heat_pollution') else None,
                    'confidence': result['heat_pollution'].get('pollution_confidence') if result.get('heat_pollution') else 'LOW',
                },
                'recovery': {
                    'label': 'RDS',
                    'description': 'outdoor_nighttime_recovery_risk_proxy',
                    'value': round(result['rds']['rds_mid'], 1),
                    'rds_low': round(result['rds']['rds_low'], 1),
                    'rds_mid': round(result['rds']['rds_mid'], 1),
                    'rds_high': round(result['rds']['rds_high'], 1),
                    'raw_rds_mid': round(result['raw_rds']['rds_mid'], 1),
                    'unit': 'score',
                    'score': round(result['ccri_components']['recovery_score'], 1),
                    'consecutive_hot_nights': result['consecutive_nights'],
                    'adjustment': result['rds_adjustment'],
                    'message': result['rds_message'],
                    'confidence': self.rds_calculator.estimate_recovery_confidence(
                        result['rds_adjustment'] if result['rds_adjustment']['applied'] else None
                    ),
                },
                'compound': {
                    'label': 'CCRI',
                    'value': round(result['ccri'], 1),
                    'unit': 'score',
                    'heat_score': round(result['ccri_components']['heat_score'], 1),
                    'pollution_score': round(result['ccri_components']['pollution_score'], 1) if result['ccri_components']['pollution_score'] is not None else None,
                    'recovery_score': round(result['ccri_components']['recovery_score'], 1),
                    'base_ccri': round(result['ccri_components']['base_ccri'], 1),
                    'recovery_multiplier': round(result['ccri_components']['recovery_multiplier'], 2),
                    'pollution_data_quality': result['ccri_components'].get('pollution_data_quality', 'available'),
                    'ccri_confidence': result['ccri_components'].get('ccri_confidence', 'normal'),
                    'confidence': confidence,
                },
            },
            'sources': {
                'weather': weather_source,
                'air_quality': air_quality_sources,
                'weather_fields': {
                    'wet_bulb_temp': weather.get('wet_bulb_temp') if weather else None,
                    'shortwave_radiation': weather.get('shortwave_radiation') if weather else None,
                },
            },
            'confidence': confidence,
        }

    def _estimate_confidence(self, weather, pollutants):
        if not weather:
            return 'LOW'
        score = 1
        if weather.get('wet_bulb_temp') is not None:
            score += 1
        if weather.get('shortwave_radiation') is not None:
            score += 1
        if pollutants:
            score += 1
        if pollutants and any(
            isinstance(value, dict) and value.get('source') == 'openaq'
            for value in pollutants.values()
        ):
            score += 1
        if score >= 4:
            return 'HIGH'
        if score >= 2:
            return 'MEDIUM'
        return 'LOW'

    def _estimate_heat_confidence(self, weather):
        if not weather:
            return 'LOW'
        score = 1
        if weather.get('wet_bulb_temp') is not None:
            score += 1
        if weather.get('shortwave_radiation') is not None:
            score += 1
        if score >= 3:
            return 'HIGH'
        if score >= 2:
            return 'MEDIUM'
        return 'LOW'


def demo_prana_system():
    logger.info("=" * 60)
    logger.info("PRANA SYSTEM DEMO")
    logger.info("Asia's First Compound Climate Emergency Platform")
    logger.info("=" * 60)

    try:
        from location_detector import get_current_location, get_location_name
        location = get_current_location()
        lat, lon = location['lat'], location['lon']
        location_name = get_location_name(location)
    except Exception as e:
        logger.warning("Location detection failed: %s", e)
        logger.warning("Using Chennai as default...")
        lat, lon = 13.0827, 80.2707
        location_name = "Chennai, India"

    prana = PRANASystem(
        api_key=OPENWEATHER_API_KEY,
        location_name=location_name,
        urban_heat_offset=3.0,
    )

    logger.info("Adding historical nighttime temperatures for RDS tracking...")
    today = datetime.now().date()
    for temp, delta in [(34.5, 3), (35.2, 2), (36.1, 1)]:
        prana.rds_calculator.add_night_temperature(temp, today - timedelta(days=delta))

    result = prana.update_all(lat, lon)

    if result:
        logger.info("PRANA system operational")
    else:
        logger.error("System update failed - check API keys and network connection")


if __name__ == "__main__":
    demo_prana_system()
