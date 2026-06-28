"""Calculate Recovery Debt Score (RDS) based on nighttime temperatures"""
import math
from datetime import datetime
from prana.config import *
from backend.logger import get_logger

_log = get_logger("rds")


def _stull_wet_bulb(temp_c, humidity_percent):
    """Wet-bulb temperature via Stull (2011), accurate to ~±1C for typical
    humid-warm conditions. Duplicated here (rather than importing NDTCalculator)
    to keep RDS self-contained and cheap to call per night."""
    if temp_c is None or humidity_percent is None:
        return None
    T = float(temp_c)
    RH = float(humidity_percent)
    return (
        T * math.atan(0.151977 * math.sqrt(RH + 8.313659))
        + math.atan(T + RH)
        - math.atan(RH - 1.676331)
        + 0.00391838 * (RH ** 1.5) * math.atan(0.023101 * RH)
        - 4.686035
    )


class RDSCalculator:
    def __init__(self, onboarding_data=None):
        self.nighttime_temps = []  # Store last 7 nights
        self.onboarding_data = onboarding_data  # Optional dict with ac, roof_material, floor_level, fan, windows_open, occupants

    @staticmethod
    def compute_onboarding_temp_offset(onboarding_data):
        """
        Compute effective indoor temperature offset from onboarding categorical inputs.

        Offsets are applied to outdoor nighttime temp before the RFU threshold
        check. All values are PROTOTYPE_ASSUMPTION — not empirically validated
        for the target population, but each is grounded in a cited mechanism
        (see config.py).

        Recognized keys:
            ac (bool)            -> RDS_ONBOARDING_AC_OFFSET (cooler)
            fan (bool)           -> RDS_ONBOARDING_FAN_OFFSET (cooler)
            windows_open (bool)  -> RDS_ONBOARDING_WINDOW_OFFSET (cooler)
            roof_material (str)  -> 'tin' adds RDS_ONBOARDING_TIN_ROOF_OFFSET (hotter)
            floor_level (str)    -> 'top' adds RDS_ONBOARDING_TOP_FLOOR_OFFSET (hotter)
            occupants (int)      -> +offset per person beyond the first (hotter)

        Returns:
            float: total temperature offset in degC (negative = cooler, positive = hotter).
        """
        if not onboarding_data:
            return 0.0
        offset = 0.0
        # Cooling devices
        if onboarding_data.get('ac'):
            offset += RDS_ONBOARDING_AC_OFFSET
        if onboarding_data.get('fan'):
            offset += RDS_ONBOARDING_FAN_OFFSET
        if onboarding_data.get('windows_open'):
            offset += RDS_ONBOARDING_WINDOW_OFFSET
        # Building envelope
        roof = str(onboarding_data.get('roof_material', '')).lower()
        if roof == 'tin':
            offset += RDS_ONBOARDING_TIN_ROOF_OFFSET
        floor = str(onboarding_data.get('floor_level', '')).lower()
        if floor == 'top':
            offset += RDS_ONBOARDING_TOP_FLOOR_OFFSET
        # Occupancy (metabolic heat load): +offset per person beyond the first
        try:
            occupants = int(onboarding_data.get('occupants', 1) or 1)
        except (TypeError, ValueError):
            occupants = 1
        if occupants > 1:
            offset += (occupants - 1) * RDS_ONBOARDING_PER_EXTRA_OCCUPANT_OFFSET
        return round(offset, 1)

    @staticmethod
    def compute_band_width(onboarding_data):
        """Half-width of the indoor-offset uncertainty band.

        AC widens the band: AC effect depends heavily on usage pattern and
        power reliability (common outages in target wards), so an AC household's
        true offset is less certain than the device list implies.
        """
        width = RDS_INDOOR_OFFSET_BAND_WIDTH
        if onboarding_data and onboarding_data.get('ac'):
            width += RDS_AC_EXTRA_BAND_WIDTH
        return width
    
    def add_night_temperature(self, night_temp, date=None, humidity=None):
        """
        Add a night's minimum temperature to tracking

        Args:
            night_temp: Minimum (dry-bulb) temperature during night (C)
            date: Date of the night (defaults to today)
            humidity: Relative humidity (%) at that nighttime minimum, used for
                      wet-bulb computation. Optional; if absent the night falls
                      back to dry-bulb scoring.
        """
        if date is None:
            date = datetime.now().date()

        # Check if this date already exists
        existing = [n for n in self.nighttime_temps if n['date'] == date]
        if existing:
            for n in self.nighttime_temps:
                if n['date'] == date:
                    n['temp'] = night_temp
                    if humidity is not None:
                        n['humidity'] = humidity
                    break
        else:
            entry = {'date': date, 'temp': night_temp}
            if humidity is not None:
                entry['humidity'] = humidity
            self.nighttime_temps.append(entry)

        # Keep only last 7 nights
        self.nighttime_temps = sorted(self.nighttime_temps, key=lambda x: x['date'], reverse=True)[:RDS_MAX_DAYS]
    
    def calculate_recovery_factor(self, night_temp, indoor_offset=0.0, humidity=None):
        """
        Calculate recovery failure units (RFU) for a single night.

        RFU is 0 when recovery is possible, rising linearly as conditions
        worsen. Two heat-strain pathways are evaluated and the WORST is taken,
        so neither dry heat nor humid heat can be missed:

        - Dry-bulb pathway: effective air temp = night_temp + indoor_offset,
          excess over RDS_NIGHTTIME_THRESHOLD (32C). Captures pure dry heat
          (e.g. a 36C inland night at 40% RH is dangerous even though its
          wet-bulb is moderate).
        - Wet-bulb pathway: wet-bulb of the effective air temp at the night's
          humidity, excess over RDS_NIGHTTIME_WETBULB_THRESHOLD (28C). Captures
          humid heat, where the body cannot cool by evaporation (e.g. a 32C
          coastal night at 80% RH is far worse than the dry-bulb number alone
          suggests).

        Final RFU = max(dry pathway, wet pathway). The two thresholds are
        chosen so that at moderate humidity (~50-60% RH) the pathways roughly
        agree, the wet pathway dominates in humid conditions, and the dry
        pathway dominates in arid conditions.

        Slope: every ~1C of excess over a threshold adds ~10 RFU (Obradovich
        et al. 2017; the /10 divisor remains an un-fitted placeholder).

        Args:
            night_temp: Nighttime outdoor (dry-bulb) temperature (C).
            indoor_offset: Effective indoor dry-bulb offset (degC). Positive =
                           hotter indoors, negative = cooler indoors.
            humidity: Relative humidity (%) for this night, or None.

        Returns:
            Recovery Failure Units (0-100).
        """
        effective_air_temp = night_temp + indoor_offset

        # Dry-bulb pathway (always available)
        dry_excess = effective_air_temp - RDS_NIGHTTIME_THRESHOLD
        dry_rfu = min(100, (dry_excess / 10) * 100) if dry_excess > 0 else 0.0

        # Wet-bulb pathway (only when enabled and humidity known)
        wet_rfu = 0.0
        if RDS_USE_WET_BULB and humidity is not None:
            effective_wet_bulb = _stull_wet_bulb(effective_air_temp, humidity)
            if effective_wet_bulb is not None:
                wet_excess = effective_wet_bulb - RDS_NIGHTTIME_WETBULB_THRESHOLD
                if wet_excess > 0:
                    wet_rfu = min(100, (wet_excess / 10) * 100)

        return max(dry_rfu, wet_rfu)
    
    def calculate_rds(self, debug=False, onboarding_data=None,
                      personalized_offset=None, personalized_band=None):
        """
        Calculate cumulative Recovery Debt Score with uncertainty band

        RDS = sum(RFU x 0.8^days_ago)

        Recent nights weighted more heavily, exponential decay for older nights.
        Returns low/mid/high estimates to reflect indoor temperature uncertainty.

        Args:
            debug: If True, print per-night breakdown
            onboarding_data: Optional dict with 'ac', 'roof_material', 'floor_level'
                             for effective indoor temperature adjustment.
            personalized_offset: Optional float. When provided, overrides the
                             onboarding-derived mid offset with a per-user value
                             learned from sleep check-ins (see
                             prana.personalization). The onboarding offset is
                             ignored for the mid estimate in that case.
            personalized_band: Optional float half-width for the uncertainty
                             band when a personalized offset is supplied (e.g.
                             the posterior SD). Falls back to the onboarding
                             band width if not given.

        Returns:
            Dict with rds_low, rds_mid, rds_high, consecutive_nights, and
            'personalized' (bool) indicating whether the per-user offset was used.
        """
        if not self.nighttime_temps:
            return {
                'rds_low': 0.0,
                'rds_mid': 0.0,
                'rds_high': 0.0,
                'consecutive_nights': 0,
                'personalized': personalized_offset is not None,
            }

        if personalized_offset is not None:
            indoor_offset_mid = round(float(personalized_offset), 1)
            band_width = (personalized_band
                          if personalized_band is not None
                          else self.compute_band_width(onboarding_data or self.onboarding_data))
            personalized = True
        else:
            indoor_offset_mid = self.compute_onboarding_temp_offset(onboarding_data or self.onboarding_data)
            band_width = self.compute_band_width(onboarding_data or self.onboarding_data)
            personalized = False
        indoor_offset_low = indoor_offset_mid - band_width
        indoor_offset_high = indoor_offset_mid + band_width
        
        # Compute RDS at three offset points
        rds_low = self._compute_rds_single_offset(indoor_offset_low, debug=False)
        rds_mid = self._compute_rds_single_offset(indoor_offset_mid, debug=debug)
        rds_high = self._compute_rds_single_offset(indoor_offset_high, debug=False)
        
        # Consecutive nights computed using mid offset
        consecutive_nights = self._compute_consecutive_nights(indoor_offset_mid)
        
        if debug:
            _log.debug("="*60)
            _log.debug("RDS UNCERTAINTY BAND")
            _log.debug("Indoor offset: %.1f degC (mid estimate, %s)", indoor_offset_mid,
                       "personalized" if personalized else "onboarding")
            _log.debug("Band width: ±%.1f degC", band_width)
            _log.debug("RDS low  (offset %.1f): %.1f", indoor_offset_low, rds_low)
            _log.debug("RDS mid  (offset %.1f): %.1f", indoor_offset_mid, rds_mid)
            _log.debug("RDS high (offset %.1f): %.1f", indoor_offset_high, rds_high)
            _log.debug("="*60)
        
        return {
            'rds_low': round(rds_low, 1),
            'rds_mid': round(rds_mid, 1),
            'rds_high': round(rds_high, 1),
            'consecutive_nights': consecutive_nights,
            'personalized': personalized,
        }
    
    def _compute_rds_single_offset(self, indoor_offset, debug=False):
        """Internal: compute RDS for a single indoor offset value"""
        total_rds = 0.0
        today = datetime.now().date()
        
        if debug:
            _log.debug("RDS Calculation Breakdown:")
            _log.debug("%-12s %-8s %-8s %-9s %-8s %-10s %-10s %s",
                       "Date", "Temp", "Offset", "Eff Temp", "RFU", "Days Ago", "Weight", "Contribution")
        
        sorted_nights = sorted(self.nighttime_temps, key=lambda x: x['date'], reverse=True)
        for night in sorted_nights:
            days_ago = (today - night['date']).days
            night_humidity = night.get('humidity')
            effective_temp = night['temp'] + indoor_offset
            rfu = self.calculate_recovery_factor(night['temp'], indoor_offset, humidity=night_humidity)
            weight = RDS_DECAY_FACTOR ** days_ago
            contribution = rfu * weight
            total_rds += contribution
            
            if debug:
                date_str = night['date'].strftime('%Y-%m-%d')
                if days_ago == 0:
                    date_str += " (tonight)"
                _log.debug("%-12s %.1fC  %+7.1f  %7.1fC  %6.1f  %9d  %9.3f  %11.1f",
                           date_str, night['temp'], indoor_offset, effective_temp, rfu, days_ago, weight, contribution)
        
        if debug:
            _log.debug("-" * 90)
            _log.debug("Indoor offset applied: %+.1fC", indoor_offset)
            _log.debug("Total RDS: %.1f", total_rds)
        
        return total_rds
    
    def _compute_consecutive_nights(self, indoor_offset):
        """Internal: count consecutive recent nights that failed recovery.

        A night 'fails' when its RFU > 0, computed by the same humidity-aware
        logic used for scoring, so the consecutive-night count stays consistent
        with the wet-bulb threshold when that mode is active.
        """
        consecutive_nights = 0
        first_hot_night_days_ago = -1
        today = datetime.now().date()
        
        sorted_nights = sorted(self.nighttime_temps, key=lambda x: x['date'], reverse=True)
        for night in sorted_nights:
            days_ago = (today - night['date']).days
            rfu = self.calculate_recovery_factor(
                night['temp'], indoor_offset, humidity=night.get('humidity')
            )
            
            if rfu > 0:
                if consecutive_nights == 0:
                    consecutive_nights = 1
                    first_hot_night_days_ago = days_ago
                elif days_ago == first_hot_night_days_ago + consecutive_nights:
                    consecutive_nights += 1
        
        return consecutive_nights

    def apply_sleep_checkin_adjustment(self, rds_dict, checkin=None):
        """
        Adjust RDS with structured user-reported sleep environment data.

        This is deterministic and capped. The LLM may extract `checkin`, but it
        should not decide the score.
        
        Args:
            rds_dict: Dict with rds_low, rds_mid, rds_high keys
            checkin: Optional sleep check-in data
        
        Returns:
            Adjusted rds_dict and adjustment metadata
        """
        if not checkin:
            return rds_dict, {
                'applied': False,
                'delta': 0.0,
                'reason': 'no_checkin',
                'adjusted_rds_mid': rds_dict['rds_mid'],
            }

        sleep_environment = str(checkin.get('sleep_environment', '')).lower()
        sleep_quality = str(checkin.get('sleep_quality', '')).lower()
        cooling_issue = bool(checkin.get('cooling_issue', False))
        power_issue = bool(checkin.get('power_issue', False))

        delta = 0.0
        reasons = []

        if sleep_environment in {'comfortable', 'cool_enough'} or sleep_quality == 'good':
            delta -= 10.0
            reasons.append('comfortable_sleep_environment')
        elif sleep_environment in {'warm_manageable', 'warm'} or sleep_quality == 'moderate':
            delta += 5.0
            reasons.append('warm_but_manageable')
        elif sleep_environment in {'too_hot', 'cooling_unavailable'} or sleep_quality == 'poor':
            delta += 20.0
            reasons.append('poor_sleep_environment')

        if cooling_issue:
            delta += 10.0
            reasons.append('cooling_issue')
        if power_issue:
            delta += 15.0
            reasons.append('power_issue')

        # Apply delta to all three values
        adjusted_dict = {
            'rds_low': max(0.0, min(200.0, rds_dict['rds_low'] + delta)),
            'rds_mid': max(0.0, min(200.0, rds_dict['rds_mid'] + delta)),
            'rds_high': max(0.0, min(200.0, rds_dict['rds_high'] + delta)),
            'consecutive_nights': rds_dict['consecutive_nights'],
            # Preserve the personalization flag from calculate_rds() so it
            # survives the check-in adjustment and reaches the API response.
            'personalized': rds_dict.get('personalized', False),
        }
        
        return adjusted_dict, {
            'applied': True,
            'delta': round(delta, 1),
            'reason': ','.join(reasons) if reasons else 'checkin_no_score_change',
            'adjusted_rds_mid': round(adjusted_dict['rds_mid'], 1),
            'raw_rds_mid': round(rds_dict['rds_mid'], 1),
        }

    def estimate_recovery_confidence(self, checkin=None):
        if checkin:
            return 'HIGH'
        if len(self.nighttime_temps) >= 3:
            return 'MEDIUM'
        return 'LOW'
    
    def _classify_rds_tier(self, rds_value):
        """Classify RDS into tier: LOW, MODERATE, HIGH, VERY HIGH, CRITICAL"""
        if rds_value < 10:
            return "LOW"
        elif rds_value < 30:
            return "MODERATE"
        elif rds_value < 80:
            return "HIGH"
        elif rds_value < 150:
            return "VERY HIGH"
        else:
            return "CRITICAL"
    
    def get_rds_message(self, rds_dict, outdoor_temp=None):
        """
        Get human-readable recovery debt message with uncertainty band

        Args:
            rds_dict: Dict with rds_low, rds_mid, rds_high from calculate_rds()
            outdoor_temp: Last night's outdoor minimum temperature (C)

        Returns:
            Tuple of (message, color_code)
        """
        if not self.nighttime_temps:
            return "Recovery data unavailable", "UNKNOWN"
        
        # Get the most recent night temperature
        last_night_temp = self.nighttime_temps[0]['temp'] if self.nighttime_temps else outdoor_temp
        
        if last_night_temp is None:
            return "Recovery data unavailable", "UNKNOWN"
        
        rds_low = rds_dict['rds_low']
        rds_mid = rds_dict['rds_mid']
        rds_high = rds_dict['rds_high']
        consecutive_nights = rds_dict['consecutive_nights']
        
        tier_low = self._classify_rds_tier(rds_low)
        tier_mid = self._classify_rds_tier(rds_mid)
        tier_high = self._classify_rds_tier(rds_high)
        
        # Determine color from mid tier
        tier_colors = {
            "LOW": "GREEN",
            "MODERATE": "YELLOW",
            "HIGH": "ORANGE",
            "VERY HIGH": "RED",
            "CRITICAL": "CRITICAL"
        }
        base_color = tier_colors[tier_mid]
        
        # Show range if low and high cross tier boundaries
        if tier_low != tier_high:
            level_str = f"{tier_low} to {tier_high} depending on your room's actual conditions (estimated range: {rds_low:.0f}-{rds_high:.0f})"
        else:
            # Same tier - use mid value
            level_str = f"{tier_mid} (RDS: {rds_mid:.1f})"
        
        # Context message
        if rds_mid > 50:
            if consecutive_nights >= 3:
                if last_night_temp < RDS_NIGHTTIME_THRESHOLD:
                    return f"Recovery debt: {level_str} from {consecutive_nights} consecutive hot nights - tonight cooler at {last_night_temp:.1f}C but cumulative sleep debt remains", base_color
                else:
                    return f"Recovery debt: {level_str} from {consecutive_nights} consecutive hot nights including tonight at {last_night_temp:.1f}C", base_color
            elif consecutive_nights > 0:
                return f"Recovery debt: {level_str} from {consecutive_nights} hot night(s) - tonight forecasted {last_night_temp:.1f}C", base_color
            else:
                return f"Recovery debt: {level_str} from recent nights above 32C - tonight forecasted {last_night_temp:.1f}C", base_color
        else:
            if last_night_temp < RDS_NIGHTTIME_THRESHOLD:
                return f"Recovery debt: {level_str} (outdoor temp {last_night_temp:.1f}C - most homes likely stayed below 32C threshold)", base_color
            elif last_night_temp < 34:
                return f"Recovery debt: {level_str} (outdoor temp {last_night_temp:.1f}C - if your home stayed above 32C, partial recovery failure)", base_color
            else:
                return f"Recovery debt: {level_str} (outdoor temp {last_night_temp:.1f}C - recovery may be impaired if your room stayed above 32C)", base_color
    
    def estimate_nighttime_temp_from_forecast(self, weather_forecast):
        """
        Estimate tonight's minimum temperature from forecast.

        Returns:
            Estimated nighttime minimum (dry-bulb) temperature, or None if the
            forecast is unavailable/stale. For the humidity at that minimum,
            use estimate_nighttime_conditions_from_forecast().
        """
        result = self.estimate_nighttime_conditions_from_forecast(weather_forecast)
        return result['temp'] if result else None

    def estimate_nighttime_conditions_from_forecast(self, weather_forecast):
        """
        Estimate tonight's minimum temperature AND the humidity at that hour.

        Picks the coldest valid future night hour (10 PM - 6 AM, 6-30h ahead),
        and reports the humidity recorded at that same hour so RDS can compute
        a wet-bulb value for the night.

        Args:
            weather_forecast: List of forecast data points.

        Returns:
            Dict {'temp': float, 'humidity': float|None} or None if no valid
            future data. Stale (past) timestamps are discarded; if every point
            is stale, returns None rather than falling back to old data.
        """
        if not weather_forecast:
            return None

        now = datetime.now()
        night_points = []  # (timestamp, temp, humidity)
        stale_count = 0

        for item in weather_forecast:
            if item['timestamp'] <= now:
                stale_count += 1
                continue  # Discard stale forecast points

            time_diff = (item['timestamp'] - now).total_seconds() / 3600
            if 6 <= time_diff <= 30:
                hour = item['timestamp'].hour
                if hour >= 22 or hour <= 6:
                    night_points.append(
                        (item['timestamp'], item['temp'], item.get('humidity'))
                    )

        if stale_count > 0:
            _log.warning("Discarded %d stale forecast points (timestamps in the past)", stale_count)

        if not night_points:
            valid_future = [item for item in weather_forecast if item['timestamp'] > now]
            if not valid_future:
                _log.error("All forecast timestamps stale - no valid future data available")
                return None
            # No night hours in 6-30h window - fall back to coldest of next 8 future hours
            fallback = valid_future[:8]
            coldest = min(fallback, key=lambda x: x['temp'])
            return {'temp': coldest['temp'], 'humidity': coldest.get('humidity')}

        # Coldest night hour; report humidity at that same hour
        _, min_temp, min_humidity = min(night_points, key=lambda x: x[1])
        return {'temp': min_temp, 'humidity': min_humidity}

