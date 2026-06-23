"""Calculate Neighbourhood Danger Temperature (NDT) using WBGT"""
import numpy as np
from config import *

class NDTCalculator:
    def __init__(self, urban_heat_offset=0):
        """
        Initialize NDT calculator
        
        Args:
            urban_heat_offset: Temperature offset for urban heat island effect (°C)
                              Typically 2-4°C for low-income wards vs airport
        """
        self.urban_heat_offset = urban_heat_offset
    
    def calculate_wet_bulb_temp(self, temp_c, humidity_percent, pressure_hpa=1013.25):
        """
        Calculate wet bulb temperature using Stull's formula (2011)
        
        Args:
            temp_c: Air temperature in Celsius
            humidity_percent: Relative humidity (0-100)
            pressure_hpa: Atmospheric pressure in hPa
        
        Returns:
            Wet bulb temperature in Celsius
        """
        T = temp_c
        RH = humidity_percent
        
        # Stull (2011) formula - accurate to ±1°C
        Tw = T * np.arctan(0.151977 * np.sqrt(RH + 8.313659)) + \
             np.arctan(T + RH) - \
             np.arctan(RH - 1.676331) + \
             0.00391838 * (RH ** 1.5) * np.arctan(0.023101 * RH) - \
             4.686035
        
        return Tw
    
    def calculate_globe_temp(self, temp_c, wind_speed_ms=0.5, shortwave_radiation=None):
        """
        Estimate globe temperature (approximation for outdoor conditions)
        
        KNOWN LIMITATION: This is a simplified approximation with the following failure modes:
        - Overstates heat stress for people in shade or indoors
        - Understates heat stress on hot surfaces (asphalt, metal) in still air
        - Does not account for solar position, surface reflectivity, or time of day
        
        A full implementation would require solar position modeling and surface-type
        classification, which is out of scope for the current prototype.
        
        ADDITIONAL NOTE ON SHORTWAVE RADIATION DATA:
        - Open-Meteo shortwave_radiation values (both model-derived and satellite-observed)
          represent a backward average over the PRECEDING hour, not an instantaneous value.
        - For fast-changing conditions (sunrise/sunset, passing clouds), this introduces
          a slight lag (~30 min on average).
        - Per Open-Meteo docs, backward-averaged data is preferred for heat stress
          calculations; instant values are meant for direct sensor comparison.
        
        Globe temp is typically 2-8°C higher than air temp in direct sun.
        For simplicity, using empirical formula based on wind speed.
        
        Args:
            temp_c: Air temperature in Celsius
            wind_speed_ms: Wind speed in m/s
            shortwave_radiation: Measured/modeled shortwave radiation (W/m²) if available
        
        Returns:
            Globe temperature in Celsius
        """
        if shortwave_radiation is not None:
            # Approximate radiant heat gain from measured/modelled shortwave radiation.
            solar_gain = min(8.0, max(0.0, shortwave_radiation / 120.0))
            solar_gain = solar_gain / (1 + 0.25 * max(0.0, wind_speed_ms))
        else:
            # Fallback model: higher temps and lower wind = higher globe temp.
            solar_gain = 5.0 / (1 + wind_speed_ms)
        Tg = temp_c + solar_gain
        return Tg
    
    def calculate_wbgt(self, temp_c, humidity_percent, pressure_hpa=1013.25, wind_speed_ms=0.5,
                       wet_bulb_temp=None, shortwave_radiation=None):
        """
        Calculate Wet Bulb Globe Temperature (WBGT)
        
        WBGT = 0.7*Tw + 0.2*Tg + 0.1*Td
        
        Args:
            temp_c: Dry bulb temperature (°C)
            humidity_percent: Relative humidity (%)
            pressure_hpa: Atmospheric pressure (hPa)
            wind_speed_ms: Wind speed (m/s)
        
        Returns:
            WBGT in Celsius
        """
        Td = temp_c
        Tw = wet_bulb_temp
        if Tw is None:
            Tw = self.calculate_wet_bulb_temp(temp_c, humidity_percent, pressure_hpa)
        Tg = self.calculate_globe_temp(temp_c, wind_speed_ms, shortwave_radiation)
        
        wbgt = (WBGT_TW_COEFF * Tw + 
                WBGT_TG_COEFF * Tg + 
                WBGT_TD_COEFF * Td)
        
        return wbgt
    
    def calculate_ndt(self, weather_data):
        """
        Calculate Neighbourhood Danger Temperature (NDT)
        
        NDT = WBGT + Urban Heat Island offset
        
        Args:
            weather_data: Dict with keys: temp, humidity, pressure, wind_speed
        
        Returns:
            NDT in Celsius
        """
        wbgt = self.calculate_wbgt(
            temp_c=weather_data['temp'],
            humidity_percent=weather_data['humidity'],
            pressure_hpa=weather_data.get('pressure', 1013.25),
            wind_speed_ms=weather_data.get('wind_speed', 0.5),
            wet_bulb_temp=weather_data.get('wet_bulb_temp'),
            shortwave_radiation=weather_data.get('shortwave_radiation')
        )
        
        ndt = wbgt + self.urban_heat_offset
        
        return ndt
    
    def get_heat_stress_level(self, ndt):
        """
        Classify heat stress level based on WBGT/NDT
        
        Based on WHO/NIOSH guidelines
        """
        if ndt < 27:
            return "LOW", "Minimal heat stress"
        elif ndt < 30:
            return "MODERATE", "Caution advised for prolonged exposure"
        elif ndt < 32:
            return "HIGH", "High risk for outdoor workers"
        elif ndt < 35:
            return "VERY HIGH", "Extreme caution - limit outdoor activity"
        else:
            return "EXTREME", "Danger - avoid outdoor exposure"
