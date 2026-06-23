"""Calculate PRANA heat-pollution risk."""

from config import *


class HAAQICalculator:
    def calculate_ozone_amplification_factor(self, temp_c):
        """
        Calculate ozone heat factor based on temperature.

        Prototype formula:
        ozone_heat_factor = 1 + 0.04 * max(0, T - 25C)

        This factor is applied to ozone AQI/risk only, not the full AQI.
        """
        temp_excess = max(0, temp_c - OAF_BASE_TEMP)
        return 1 + (OAF_COEFFICIENT * temp_excess)

    def calculate_heat_pollution_risk(self, base_aqi, pollutant_aqi, temp_c):
        """
        Calculate PRANA heat-pollution risk with ozone-specific heat adjustment.

        The ozone heat factor is only applied when O3 AQI >= threshold (default 50).
        At low ozone concentrations, the chemistry is NOx-limited rather than
        temperature-limited, so heat-ozone coupling does not apply.

        `heat_pollution_risk` is PRANA custom, not an official AQI.
        """
        pollutant_aqi = pollutant_aqi or {}

        if base_aqi is None:
            return {
                'base_aqi': None,
                'dominant_pollutant': None,
                'pollutant_aqi': pollutant_aqi,
                'ozone_heat_factor': None,
                'ozone_heat_adjusted_aqi': None,
                'heat_pollution_risk': None,
                'legacy_ha_aqi': None,
                'pollution_confidence': 'LOW',
                'method': 'unavailable'
            }

        ozone_heat_factor = self.calculate_ozone_amplification_factor(temp_c)
        ozone_aqi = pollutant_aqi.get('O3')
        
        # Only apply heat factor when O3 AQI is elevated (>= threshold)
        # Below this, ozone chemistry is NOx-limited, not temperature-limited
        if ozone_aqi is not None and ozone_aqi >= OZONE_HEAT_COUPLING_THRESHOLD_AQI:
            ozone_heat_adjusted_aqi = ozone_aqi * ozone_heat_factor
        else:
            ozone_heat_adjusted_aqi = ozone_aqi if ozone_aqi is not None else None

        if ozone_aqi is not None and ozone_heat_adjusted_aqi is not None and ozone_aqi >= OZONE_HEAT_COUPLING_THRESHOLD_AQI:
            ozone_increment = (ozone_heat_adjusted_aqi - ozone_aqi) * OAF_BLEND_WEIGHT
            heat_pollution_risk = base_aqi + ozone_increment
        else:
            heat_pollution_risk = base_aqi

        return {
            'base_aqi': base_aqi,
            'dominant_pollutant': self.get_dominant_pollutant(pollutant_aqi, base_aqi),
            'pollutant_aqi': pollutant_aqi,
            'ozone_heat_factor': ozone_heat_factor,
            'ozone_heat_adjusted_aqi': ozone_heat_adjusted_aqi,
            'heat_pollution_risk': heat_pollution_risk,
            # Compatibility field for existing app/backend naming.
            'legacy_ha_aqi': heat_pollution_risk,
            'pollution_confidence': self.estimate_pollution_confidence(pollutant_aqi),
            'method': 'ozone_specific_heat_adjustment'
        }

    def calculate_ha_aqi(self, base_aqi, temp_c):
        """
        Compatibility wrapper.

        This no longer multiplies full AQI by heat. Without pollutant
        components, return base AQI unchanged.
        """
        return base_aqi

    def forecast_ha_aqi(self, base_aqi, weather_forecast):
        """
        Compatibility forecast output.

        Without forecast pollutant components, the heat-pollution risk remains
        the base AQI. Ozone-specific forecasts should be added separately.
        """
        if not weather_forecast:
            return None

        forecast = []
        for item in weather_forecast:
            temp = item['temp']
            ozone_heat_factor = self.calculate_ozone_amplification_factor(temp)

            forecast.append({
                'timestamp': item['timestamp'],
                'temp': temp,
                'oaf': ozone_heat_factor,
                'ozone_heat_factor': ozone_heat_factor,
                'base_aqi': base_aqi,
                'ha_aqi': base_aqi,
                'heat_pollution_risk': base_aqi
            })

        return forecast

    def get_aqi_category(self, aqi):
        """Get AQI category and health implications."""
        if aqi is None:
            return "UNKNOWN", "No data available"

        if aqi <= 50:
            return "GOOD", "Air quality is satisfactory"
        if aqi <= 100:
            return "MODERATE", "Acceptable for most, sensitive groups should limit prolonged outdoor exposure"
        if aqi <= 150:
            return "UNHEALTHY FOR SENSITIVE", "Sensitive groups may experience health effects"
        if aqi <= 200:
            return "UNHEALTHY", "Everyone may begin to experience health effects"
        if aqi <= 300:
            return "VERY UNHEALTHY", "Health alert - everyone may experience serious effects"
        return "HAZARDOUS", "Emergency conditions - entire population affected"

    def get_dominant_pollutant(self, pollutant_aqi, base_aqi):
        if not pollutant_aqi:
            return 'provider_aqi'

        dominant, value = max(pollutant_aqi.items(), key=lambda item: item[1])
        if abs(value - base_aqi) <= 1:
            return dominant
        return 'provider_aqi'

    def estimate_pollution_confidence(self, pollutant_aqi):
        if not pollutant_aqi:
            return 'MEDIUM'
        if len(pollutant_aqi) >= 3:
            return 'HIGH'
        return 'MEDIUM'
