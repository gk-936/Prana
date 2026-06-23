"""Configuration for PRANA Climate Risk System"""
import os
from dotenv import load_dotenv

load_dotenv()

# API Keys
OPENWEATHER_API_KEY = os.getenv('OPENWEATHER_API_KEY', '')
OPENAQ_API_KEY = os.getenv('OPENAQ_API_KEY', '')  # Get free key from https://openaq.org

# WhatsApp Business Cloud API / provider
WHATSAPP_ACCESS_TOKEN = os.getenv('WHATSAPP_ACCESS_TOKEN', '')
WHATSAPP_PHONE_NUMBER_ID = os.getenv('WHATSAPP_PHONE_NUMBER_ID', '')
WHATSAPP_VERIFY_TOKEN = os.getenv('WHATSAPP_VERIFY_TOKEN', '')
WHATSAPP_APP_SECRET = os.getenv('WHATSAPP_APP_SECRET', '')

# LLM provider for WhatsApp bot
LLM_PROVIDER = os.getenv('LLM_PROVIDER', 'openrouter')
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', '')
OPENROUTER_BASE_URL = os.getenv('OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1')
OPENROUTER_MODEL = os.getenv('OPENROUTER_MODEL', '')
OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', '')

# Runtime
APP_ENV = os.getenv('APP_ENV', 'development')
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./prana.db')

# API Endpoints
OPENMETEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPENMETEO_AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
OPENMETEO_SATELLITE_RADIATION_URL = "https://satellite-api.open-meteo.com/v1/archive"
OPENWEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
OPENWEATHER_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
OPENAQ_URL = "https://api.openaq.org/v3/locations"  # v3 locations endpoint
NASA_POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"

# WBGT Coefficients (ISO 7243 / Liljegren)
WBGT_TW_COEFF = 0.7  # Wet bulb temperature
WBGT_TG_COEFF = 0.2  # Globe temperature
WBGT_TD_COEFF = 0.1  # Dry bulb temperature

# Ozone Amplification Factor (Shen et al. 2020)
OAF_BASE_TEMP = 25.0  # Celsius
OAF_COEFFICIENT = 0.04
OAF_BLEND_WEIGHT = 0.5  # Weight for heat-driven ozone increment blended into base AQI
OZONE_HEAT_COUPLING_THRESHOLD_AQI = 50  # Only apply heat factor when O3 AQI >= this (NOx-limited below)

# Recovery Debt Score
RDS_NIGHTTIME_THRESHOLD = 32.0  # Celsius - no recovery above this
RDS_DECAY_FACTOR = 0.8  # Exponential decay for past nights
RDS_MAX_DAYS = 7  # Track last 7 nights
RDS_ONBOARDING_AC_OFFSET = -3.0  # degC: effective indoor temp reduction from AC (PROTOTYPE_ASSUMPTION)
RDS_ONBOARDING_TIN_ROOF_OFFSET = 2.0  # degC: additional indoor heat from tin roof (PROTOTYPE_ASSUMPTION)
RDS_ONBOARDING_TOP_FLOOR_OFFSET = 1.5  # degC: additional indoor heat from top floor unshaded (PROTOTYPE_ASSUMPTION)
RDS_INDOOR_OFFSET_BAND_WIDTH = 2.0  # degC, ± band around onboarding offset estimate

# CCRI Thresholds
CCRI_SAFE = 20
CCRI_ELEVATED = 40
CCRI_HIGH = 60
CCRI_CRITICAL = 80
# Above 80 = COMPOUND EMERGENCY

# Update frequency (hours)
UPDATE_INTERVAL = 3
