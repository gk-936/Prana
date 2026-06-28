"""Calculate Compound Climate Risk Index (CCRI)"""
from prana.config import *
from backend.logger import get_logger

_log = get_logger("ccri")

class CCRICalculator:
    def __init__(self):
        pass
    
    def calculate_heat_score(self, ndt):
        """
        Calculate heat component score (0-100)
        
        Based on WBGT/NDT thresholds
        
        Args:
            ndt: Neighbourhood Danger Temperature (degC)
        
        Returns:
            Heat score (0-100)
        """
        if ndt < 27:
            return self._linear_scale(ndt, 20, 27, 0, 20)
        elif ndt < 30:
            return self._linear_scale(ndt, 27, 30, 20, 40)
        elif ndt < 32:
            return self._linear_scale(ndt, 30, 32, 40, 60)
        elif ndt < 35:
            return self._linear_scale(ndt, 32, 35, 60, 80)
        else:
            return min(100, self._linear_scale(ndt, 35, 40, 80, 100))
    
    def calculate_pollution_score(self, ha_aqi):
        """
        Calculate air pollution component score (0-100)
        
        Based on HA-AQI values
        
        Args:
            ha_aqi: Heat-Amplified AQI or None if unavailable
        
        Returns:
            Pollution score (0-100) or None if no AQI data available
        """
        if ha_aqi is None:
            return None  # Return None instead of defaulting to fake score
        
        if ha_aqi <= 50:
            return self._linear_scale(ha_aqi, 0, 50, 0, 20)
        elif ha_aqi <= 100:
            return self._linear_scale(ha_aqi, 50, 100, 20, 40)
        elif ha_aqi <= 150:
            return self._linear_scale(ha_aqi, 100, 150, 40, 60)
        elif ha_aqi <= 200:
            return self._linear_scale(ha_aqi, 150, 200, 60, 80)
        else:
            return min(100, self._linear_scale(ha_aqi, 200, 300, 80, 100))

    def calculate_recovery_score(self, rds):
        """Convert RDS into a capped 0-100 component score."""
        return max(0, min(100, rds))

    def recovery_score_to_multiplier(self, rds_mid):
        """
        Convert RDS to recovery multiplier using piecewise scaling.
        
        Reflects RDS severity tiers:
        - RDS 0-30:   multiplier scales linearly up to 1.1x
        - RDS 30-80:  multiplier scales up to 1.3x (matches old cap)
        - RDS 80-150: multiplier scales up to 1.6x
        - RDS 150+:   multiplier continues scaling upward, no hard ceiling
        
        Args:
            rds_mid: Midpoint RDS estimate
        
        Returns:
            Recovery multiplier (>= 1.0)
        """
        rds = max(0.0, rds_mid)  # Clamp to non-negative
        
        if rds <= 30:
            # Low to moderate: scale from 1.0 to 1.1x
            return 1.0 + (rds / 30) * 0.1
        elif rds <= 80:
            # High: scale from 1.1 to 1.3x
            return 1.1 + ((rds - 30) / 50) * 0.2
        elif rds <= 150:
            # Very high: scale from 1.3 to 1.6x
            return 1.3 + ((rds - 80) / 70) * 0.3
        else:
            # Critical: continue scaling beyond 1.6x, uncapped
            return 1.6 + (rds - 150) * 0.005

    def calculate_component_scores(self, ndt, ha_aqi, rds):
        """
        Return transparent CCRI component scores and multiplier.
        
        When pollution data is missing, CCRI is computed using only heat and recovery,
        treating pollution as NEUTRAL (excluded from multiplicative formula).
        """
        heat_score = self.calculate_heat_score(ndt)
        pollution_score = self.calculate_pollution_score(ha_aqi)
        recovery_score = self.calculate_recovery_score(rds)
        
        pollution_data_quality = "available" if pollution_score is not None else "missing"
        
        # Compute CCRI: if pollution unavailable, use heat score only (not multiplied by fake pollution)
        if pollution_score is not None:
            base_ccri = (heat_score * pollution_score) / 100
        else:
            # Pollution data missing - use heat score directly as base (neutral pollution contribution)
            base_ccri = heat_score
        
        recovery_multiplier = self.recovery_score_to_multiplier(rds)
        ccri_confidence = "normal" if pollution_score is not None else "degraded"

        return {
            'heat_score': heat_score,
            'pollution_score': pollution_score,
            'recovery_score': recovery_score,
            'base_ccri': base_ccri,
            'recovery_multiplier': recovery_multiplier,
            'pollution_data_quality': pollution_data_quality,
            'ccri_confidence': ccri_confidence,
        }
    
    def calculate_ccri(self, ndt, ha_aqi, rds, debug=False):
        """
        Calculate Compound Climate Risk Index

        CCRI = base_ccri x recovery_multiplier(RDS)
          where base_ccri = (H_score x P_score) / 100 when pollution is available,
          or base_ccri = H_score when pollution is unavailable (neutral pollution).

        The recovery multiplier is piecewise and uncapped (see
        recovery_score_to_multiplier): 1.0-1.1x for RDS 0-30, up to 1.3x for
        30-80, up to 1.6x for 80-150, and 1.6x + 0.005 per point above 150.

        Multiplicative structure reflects synergistic mortality.

        Args:
            ndt: Neighbourhood Danger Temperature (degC)
            ha_aqi: Heat-Amplified AQI or None if unavailable
            rds: Recovery Debt Score
            debug: If True, print component scores

        Returns:
            CCRI value (0-100+) and risk level
        """
        component_scores = self.calculate_component_scores(ndt, ha_aqi, rds)
        h_score = component_scores['heat_score']
        p_score = component_scores['pollution_score']
        
        # Base compound risk (multiplicative)
        base_ccri = component_scores['base_ccri']
        
        # Amplify by recovery debt
        rds_multiplier = component_scores['recovery_multiplier']
        
        ccri = base_ccri * rds_multiplier
        
        # DEBUG OUTPUT
        if debug:
            _log.debug("=" * 60)
            _log.debug("CCRI CALCULATION DEBUG")
            _log.debug("=" * 60)
            _log.debug("Heat Score (H):        %.1f/100  (from NDT %.1f degC)", h_score, ndt)
            if p_score is not None:
                _log.debug("Pollution Score (P):   %.1f/100  (from HA-AQI %.1f)", p_score, ha_aqi)
            else:
                _log.debug("Pollution Score (P):   UNAVAILABLE")
                _log.debug("  WARNING: Air quality data unavailable - CCRI computed from heat only")
            _log.debug("RDS:                   %.1f/100", rds)
            _log.debug("")
            if p_score is not None:
                _log.debug("Base CCRI = (H x P) / 100")
                _log.debug("          = (%.1f x %.1f) / 100", h_score, p_score)
                _log.debug("          = %.1f", base_ccri)
            else:
                _log.debug("Base CCRI = H (pollution unavailable)")
                _log.debug("          = %.1f", base_ccri)
            _log.debug("")
            _log.debug("RDS Multiplier = recovery_score_to_multiplier(RDS)  [piecewise, uncapped]")
            _log.debug("               = %.3fx  (for RDS %.1f)", rds_multiplier, rds)
            _log.debug("")
            _log.debug("Final CCRI = %.1f x %.3f", base_ccri, rds_multiplier)
            _log.debug("           = %.1f/100", ccri)
            _log.debug("=" * 60)
        
        return ccri, self.get_risk_level(ccri)
    
    def get_risk_level(self, ccri):
        """
        Classify CCRI into risk levels
        
        Returns:
            Risk level and description
        """
        if ccri < CCRI_SAFE:
            return "SAFE", "No significant compound risk", "GREEN"
        elif ccri < CCRI_ELEVATED:
            return "ELEVATED", "Monitor conditions, vulnerable groups should be cautious", "YELLOW"
        elif ccri < CCRI_HIGH:
            return "HIGH", "Significant risk - limit outdoor exposure, check on vulnerable", "ORANGE"
        elif ccri < CCRI_CRITICAL:
            return "CRITICAL", "Dangerous conditions - avoid outdoor activity, activate support systems", "RED"
        else:
            return "COMPOUND EMERGENCY", "Life-threatening conditions - emergency protocols active", "CRITICAL"
    
    def _linear_scale(self, value, in_min, in_max, out_min, out_max):
        """Linear interpolation between ranges"""
        value = max(in_min, min(in_max, value))  # Clamp to range
        return out_min + (value - in_min) * (out_max - out_min) / (in_max - in_min)
    
    def generate_alert_message(self, ccri, risk_level, ndt, ha_aqi, rds_message, location_name="your area", pollution_data_quality="available", pm25_aqi_method=None):
        """
        Generate personalized alert message
        
        Args:
            ccri: CCRI value
            risk_level: Tuple (level, description, color)
            ndt: Neighbourhood Danger Temperature
            ha_aqi: Heat-Amplified AQI or None if unavailable
            rds_message: Recovery debt message
            location_name: Name of ward/location
            pollution_data_quality: "available" or "missing"
            pm25_aqi_method: "nowcast_12h" or "instantaneous" or None
        
        Returns:
            Alert message string
        """
        level, desc, color = risk_level
        
        # Override risk level wording if pollution data is missing
        if pollution_data_quality == "missing" and level == "SAFE":
            level = "ELEVATED (air quality unknown)"
            desc = "Heat conditions are low, but air quality data unavailable - vulnerable groups should remain cautious"
        
        message = f"*** PRANA CLIMATE ALERT - {location_name}\n\n"
        message += f"Risk Level: {level} ({ccri:.1f}/100)\n"
        message += f"{desc}\n\n"
        message += f"*** Current Conditions:\n"
        message += f"- Heat Stress (NDT): {ndt:.1f} degC\n"
        
        if ha_aqi is not None:
            # Add PM2.5 method qualifier if available
            aqi_qualifier = ""
            if pm25_aqi_method == "nowcast_12h":
                aqi_qualifier = " (12h average)"
            elif pm25_aqi_method == "instantaneous":
                aqi_qualifier = " (instant reading, may change quickly)"
            message += f"- Air Quality (HA-AQI): {ha_aqi:.0f}{aqi_qualifier}\n"
        else:
            message += f"- Air Quality: DATA UNAVAILABLE\n"
        
        message += f"- Sleep Recovery: {rds_message}\n\n"
        
        # Specific guidance based on risk level
        if level == "SAFE":
            message += "[OK] Conditions are safe. Normal activities can continue."
        elif "ELEVATED" in level:
            message += "WARNING: Stay hydrated. Vulnerable individuals should limit outdoor exposure."
            if pollution_data_quality == "missing":
                message += " Air quality data unavailable - exercise extra caution if sensitive to pollution."
        elif level == "HIGH":
            message += "WARNING: HIGH RISK:\n- Stay indoors during peak heat\n- Drink water frequently\n- Check on elderly neighbors"
        elif level == "CRITICAL":
            message += "[CRITICAL] CRITICAL:\n- Avoid outdoor work\n- Seek cool shelter\n- Emergency cooling centers open\n- Contact health workers if feeling unwell"
        else:  # COMPOUND EMERGENCY
            message += "[EMERGENCY] EMERGENCY:\n- STAY INDOORS\n- Activate emergency support\n- Health workers on alert\n- Reply HELP for immediate assistance"
        
        return message


