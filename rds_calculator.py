"""Calculate Recovery Debt Score (RDS) based on nighttime temperatures"""
from datetime import datetime
from config import *
from backend.logger import get_logger

_log = get_logger("rds")

class RDSCalculator:
    def __init__(self, onboarding_data=None):
        self.nighttime_temps = []  # Store last 7 nights
        self.onboarding_data = onboarding_data  # Optional dict with ac, roof_material, floor_level

    @staticmethod
    def compute_onboarding_temp_offset(onboarding_data):
        """
        Compute effective indoor temperature offset from onboarding categorical inputs.

        Offsets are applied to outdoor nighttime temp before RFU threshold check.
        All values are PROTOTYPE_ASSUMPTION — not empirically validated.

        Args:
            onboarding_data: dict with keys 'ac' (bool), 'roof_material' (str),
                             'floor_level' (str), or None.

        Returns:
            float: total temperature offset in degC (negative = cooler, positive = hotter).
        """
        if not onboarding_data:
            return 0.0
        offset = 0.0
        if onboarding_data.get('ac'):
            offset += RDS_ONBOARDING_AC_OFFSET
        roof = onboarding_data.get('roof_material', '').lower()
        if roof == 'tin':
            offset += RDS_ONBOARDING_TIN_ROOF_OFFSET
        floor = onboarding_data.get('floor_level', '').lower()
        if floor == 'top':
            offset += RDS_ONBOARDING_TOP_FLOOR_OFFSET
        return round(offset, 1)
    
    def add_night_temperature(self, night_temp, date=None):
        """
        Add a night's minimum temperature to tracking
        
        Args:
            night_temp: Minimum temperature during night (C)
            date: Date of the night (defaults to today)
        """
        if date is None:
            date = datetime.now().date()
        
        # Check if this date already exists
        existing = [n for n in self.nighttime_temps if n['date'] == date]
        if existing:
            for n in self.nighttime_temps:
                if n['date'] == date:
                    n['temp'] = night_temp
                    break
        else:
            self.nighttime_temps.append({
                'date': date,
                'temp': night_temp
            })
        
        # Keep only last 7 nights
        self.nighttime_temps = sorted(self.nighttime_temps, key=lambda x: x['date'], reverse=True)[:RDS_MAX_DAYS]
    
    def calculate_recovery_factor(self, night_temp, indoor_offset=0.0):
        """
        Calculate recovery factor for a single night

        RFU (Recovery Failure Units):
        - Below 32C (effective): RFU = 0 (full recovery possible)
        - Above 32C (effective): RFU increases linearly

        Based on Obradovich et al. (2017):
        Every 10C rise increases sleep insufficiency by 20.1%

        Args:
            night_temp: Nighttime outdoor temperature (C)
            indoor_offset: Effective indoor temperature offset (degC).
                           Positive = hotter indoors, Negative = cooler indoors.

        Returns:
            Recovery Failure Units (0-100)
        """
        effective_temp = night_temp + indoor_offset
        if effective_temp < RDS_NIGHTTIME_THRESHOLD:
            return 0.0

        temp_excess = effective_temp - RDS_NIGHTTIME_THRESHOLD
        rfu = min(100, (temp_excess / 10) * 100)

        return rfu
    
    def calculate_rds(self, debug=False, onboarding_data=None):
        """
        Calculate cumulative Recovery Debt Score with uncertainty band

        RDS = sum(RFU x 0.8^days_ago)

        Recent nights weighted more heavily, exponential decay for older nights.
        Returns low/mid/high estimates to reflect indoor temperature uncertainty.

        Args:
            debug: If True, print per-night breakdown
            onboarding_data: Optional dict with 'ac', 'roof_material', 'floor_level'
                             for effective indoor temperature adjustment.

        Returns:
            Dict with rds_low, rds_mid, rds_high, consecutive_nights
        """
        if not self.nighttime_temps:
            return {
                'rds_low': 0.0,
                'rds_mid': 0.0,
                'rds_high': 0.0,
                'consecutive_nights': 0,
            }

        indoor_offset_mid = self.compute_onboarding_temp_offset(onboarding_data or self.onboarding_data)
        indoor_offset_low = indoor_offset_mid - RDS_INDOOR_OFFSET_BAND_WIDTH
        indoor_offset_high = indoor_offset_mid + RDS_INDOOR_OFFSET_BAND_WIDTH
        
        # Compute RDS at three offset points
        rds_low = self._compute_rds_single_offset(indoor_offset_low, debug=False)
        rds_mid = self._compute_rds_single_offset(indoor_offset_mid, debug=debug)
        rds_high = self._compute_rds_single_offset(indoor_offset_high, debug=False)
        
        # Consecutive nights computed using mid offset
        consecutive_nights = self._compute_consecutive_nights(indoor_offset_mid)
        
        if debug:
            _log.debug("="*60)
            _log.debug("RDS UNCERTAINTY BAND")
            _log.debug("Indoor offset: %.1f degC (mid estimate)", indoor_offset_mid)
            _log.debug("Band width: ±%.1f degC", RDS_INDOOR_OFFSET_BAND_WIDTH)
            _log.debug("RDS low  (offset %.1f): %.1f", indoor_offset_low, rds_low)
            _log.debug("RDS mid  (offset %.1f): %.1f", indoor_offset_mid, rds_mid)
            _log.debug("RDS high (offset %.1f): %.1f", indoor_offset_high, rds_high)
            _log.debug("="*60)
        
        return {
            'rds_low': round(rds_low, 1),
            'rds_mid': round(rds_mid, 1),
            'rds_high': round(rds_high, 1),
            'consecutive_nights': consecutive_nights,
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
            effective_temp = night['temp'] + indoor_offset
            rfu = self.calculate_recovery_factor(night['temp'], indoor_offset)
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
        """Internal: compute consecutive hot nights using given offset"""
        consecutive_nights = 0
        first_hot_night_days_ago = -1
        today = datetime.now().date()
        
        sorted_nights = sorted(self.nighttime_temps, key=lambda x: x['date'], reverse=True)
        for night in sorted_nights:
            days_ago = (today - night['date']).days
            effective_temp = night['temp'] + indoor_offset
            
            if effective_temp >= RDS_NIGHTTIME_THRESHOLD:
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
        Estimate tonight's minimum temperature from forecast
        
        Args:
            weather_forecast: List of forecast data points
        
        Returns:
            Estimated nighttime minimum temperature or None if forecast unavailable/stale
        """
        if not weather_forecast:
            return None
        
        # Find temperatures during night hours (10 PM - 6 AM local time)
        night_temps = []
        now = datetime.now()
        stale_count = 0
        
        for item in weather_forecast:
            # Validate timestamp is in the future
            if item['timestamp'] <= now:
                stale_count += 1
                continue  # Discard stale forecast points
            
            # Calculate hours from now
            time_diff = (item['timestamp'] - now).total_seconds() / 3600
            
            # Look at next 6-30 hours for tonight/tomorrow morning
            if 6 <= time_diff <= 30:
                hour = item['timestamp'].hour
                # Night hours: 10 PM to 6 AM
                if hour >= 22 or hour <= 6:
                    night_temps.append((item['timestamp'], item['temp']))
        
        if stale_count > 0:
            _log.warning("Discarded %d stale forecast points (timestamps in the past)", stale_count)
        
        if not night_temps:
            # No valid future night temps found - check if we have any valid future data at all
            valid_future_count = sum(1 for item in weather_forecast if item['timestamp'] > now)
            if valid_future_count == 0:
                _log.error("All forecast timestamps stale - no valid future data available")
                return None  # Return None instead of falling back to potentially stale data
            
            # We have future data but no night hours in 6-30h window - use next 8 hours as fallback
            all_temps = [item['temp'] for item in weather_forecast if item['timestamp'] > now][:8]
            if all_temps:
                return min(all_temps)
            return None

        return min(temp for _, temp in night_temps)

