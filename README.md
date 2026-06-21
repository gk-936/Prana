# PRANA

PRANA is a compound climate-risk platform for heat, air quality, and nighttime recovery risk. The mobile app captures the user's location and shows live/past risk results. The backend calculates risk scores and is designed to support WhatsApp alerts, recovery check-ins, and health-worker escalation.

## Current Status

This repository currently contains:

- Flutter mobile app in `mobile_app/`
- Python FastAPI backend in `backend/`
- PRANA formula engine modules at the repo root
- Open-Meteo weather and air-quality integration
- OpenAQ/OpenWeatherMap optional fallback/reference support
- OpenRouter primary LLM adapter with Ollama fallback
- Formula validation notes and regression tests

The project is still in prototype/backend-hardening stage. CCRI and RDS are PRANA custom scores and should be presented as estimated risk signals, not official medical or government indices.

## Architecture

```text
Flutter mobile app
  -> FastAPI backend
    -> Open-Meteo weather forecast
    -> Open-Meteo air-quality forecast
    -> optional OpenAQ station reference
    -> optional OpenWeatherMap weather fallback
    -> PRANA risk engine
    -> future WhatsApp bot + LLM conversation layer
```

## Core Components

| Component | File | Current Role | Status |
| --- | --- | --- | --- |
| NDT | `ndt_calculator.py` | Estimated WBGT plus urban heat offset | PRANA custom |
| Heat-pollution risk | `ha_aqi_calculator.py` | Base AQI plus ozone-specific heat adjustment | PRANA custom |
| RDS | `rds_calculator.py` | Outdoor nighttime recovery-risk estimate | PRANA custom |
| CCRI | `ccri_calculator.py` | Compound risk score from heat, pollution, and recovery | PRANA custom |
| API backend | `backend/main.py` | FastAPI app exposing health and risk endpoints | Prototype |
| LLM adapter | `backend/llm.py` | OpenRouter primary, Ollama fallback | Scaffolded |

See `FORMULA_VALIDATION.md` before making scientific or public-health claims.

## Data Providers

Primary free providers:

- Weather and forecast: Open-Meteo Forecast API
- Air quality: Open-Meteo Air Quality API

Optional fallback/reference providers:

- OpenAQ API for nearby air-quality station measurements
- OpenWeatherMap API for weather fallback

OpenWeatherMap and OpenAQ keys are not required for local development.

## Backend Setup

Create or reuse a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Create local environment config:

```powershell
Copy-Item .env.example .env
```

Start the backend:

```powershell
.\scripts\start_backend.ps1
```

Or run directly:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Local API docs:

```text
http://127.0.0.1:8000/docs
```

For a physical phone on the same Wi-Fi, use your computer's LAN IP in the app, for example:

```text
http://192.168.1.5:8000
```

## Mobile App Setup

The Flutter app lives in `mobile_app/`.

```powershell
cd mobile_app
flutter pub get
flutter run
```

The app currently supports:

- backend URL input
- GPS location detection
- manual latitude/longitude adjustment
- urban heat offset input
- live risk calculation
- session-based past results

## API Endpoints

Current endpoints:

```text
GET /health
POST /risk/current
```

`POST /risk/current` accepts latitude, longitude, location name, and urban heat offset. It returns legacy fields for app compatibility plus structured fields:

- `summary`
- `components`
- `sources`
- `confidence`

See `API_CONTRACT.md` for the full response shape.

## Environment Variables

Use `.env` locally. Never commit it.

Important placeholders are listed in `.env.example`:

- optional weather/air-quality keys:
  - `OPENWEATHER_API_KEY`
  - `OPENAQ_API_KEY`
- WhatsApp:
  - `WHATSAPP_ACCESS_TOKEN`
  - `WHATSAPP_PHONE_NUMBER_ID`
  - `WHATSAPP_VERIFY_TOKEN`
  - `WHATSAPP_APP_SECRET`
- LLM:
  - `LLM_PROVIDER`
  - `OPENROUTER_API_KEY`
  - `OPENROUTER_MODEL`
  - `OLLAMA_BASE_URL`
  - `OLLAMA_MODEL`
- database:
  - `DATABASE_URL`

See `ENVIRONMENT.md` for details.

## Formula Notes

Important current formula decisions:

- NDT is an estimated heat-stress score, not an official measured WBGT.
- Heat-pollution risk no longer multiplies full AQI by temperature.
- Ozone receives the heat-specific adjustment because heat most directly affects ozone chemistry.
- RDS is an outdoor-weather-based recovery-risk estimate because indoor temperature is not available.
- WhatsApp check-ins will later improve RDS by collecting user-reported sleep environment data.
- CCRI is a PRANA custom compound risk score.

See `FORMULA_VALIDATION.md` for source status, limitations, and implementation rules.

## Testing

Run deterministic formula tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Compile backend modules:

```powershell
.\.venv\Scripts\python.exe -m py_compile data_fetcher.py ha_aqi_calculator.py rds_calculator.py ccri_calculator.py prana_system.py backend\main.py backend\llm.py
```

Flutter checks:

```powershell
cd mobile_app
flutter analyze --no-pub
flutter test
```

## Roadmap

Next planned backend work:

1. Add database persistence for users, locations, risk results, and RDS check-ins.
2. Add user/location API endpoints.
3. Add WhatsApp webhook verification and inbound message handling.
4. Add OpenRouter/Ollama-backed conversation handling.
5. Add scheduled 3-hour risk updates and alerting rules.
6. Add health-worker escalation workflows.
7. Later add OpenStreetMap/Landsat/ECOSTRESS-based urban heat offset.

See `ROADMAP.md` for the fuller roadmap.

## Repository Hygiene

Tracked files exclude:

- `.env`
- `.env.*`
- `.venv/`
- logs
- local databases
- Python caches
- Flutter/Android generated build caches

Do not commit secrets. Use `.env.example` for placeholders only.
