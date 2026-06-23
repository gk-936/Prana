"""Test Open-Meteo Satellite Radiation API capabilities"""

import requests
from datetime import datetime, timedelta

# Test coordinates: Chennai
lat, lon = 13.0827, 80.2707

print("Testing Open-Meteo Satellite Radiation API")
print("=" * 60)

# Test 1: Can we get current/today data?
print("\nTest 1: Current day data (today)")
today = datetime.now().date()
params_today = {
    'latitude': lat,
    'longitude': lon,
    'hourly': 'shortwave_radiation',
    'models': 'satellite_radiation_seamless',
    'start_date': today.isoformat(),
    'end_date': today.isoformat(),
}

try:
    response = requests.get(
        "https://satellite-api.open-meteo.com/v1/archive",
        params=params_today,
        timeout=10
    )
    response.raise_for_status()
    data = response.json()
    
    print(f"Status: {response.status_code}")
    print(f"Hourly times count: {len(data.get('hourly', {}).get('time', []))}")
    if data.get('hourly', {}).get('time'):
        print(f"First time: {data['hourly']['time'][0]}")
        print(f"Last time: {data['hourly']['time'][-1]}")
        print(f"Sample radiation values: {data['hourly']['shortwave_radiation'][:5]}")
    print(f"Response keys: {list(data.keys())}")
except Exception as e:
    print(f"ERROR: {e}")

# Test 2: Can we get future data?
print("\n\nTest 2: Future data (tomorrow)")
tomorrow = (datetime.now() + timedelta(days=1)).date()
params_future = {
    'latitude': lat,
    'longitude': lon,
    'hourly': 'shortwave_radiation',
    'models': 'satellite_radiation_seamless',
    'start_date': tomorrow.isoformat(),
    'end_date': tomorrow.isoformat(),
}

try:
    response = requests.get(
        "https://satellite-api.open-meteo.com/v1/archive",
        params=params_future,
        timeout=10
    )
    response.raise_for_status()
    data = response.json()
    
    print(f"Status: {response.status_code}")
    print(f"Hourly times count: {len(data.get('hourly', {}).get('time', []))}")
    if data.get('hourly', {}).get('time'):
        print(f"Future data available: YES")
        print(f"First time: {data['hourly']['time'][0]}")
    else:
        print(f"Future data available: NO")
except Exception as e:
    print(f"ERROR: {e}")

# Test 3: What if we omit start/end dates?
print("\n\nTest 3: No date parameters (defaults)")
params_no_date = {
    'latitude': lat,
    'longitude': lon,
    'hourly': 'shortwave_radiation',
    'models': 'satellite_radiation_seamless',
}

try:
    response = requests.get(
        "https://satellite-api.open-meteo.com/v1/archive",
        params=params_no_date,
        timeout=10
    )
    response.raise_for_status()
    data = response.json()
    
    print(f"Status: {response.status_code}")
    print(f"Response: {data}")
except Exception as e:
    print(f"ERROR: {e}")

print("\n" + "=" * 60)
print("CONCLUSION:")
print("- Archive endpoint can provide TODAY data: [check test 1]")
print("- Archive endpoint can provide FUTURE data: [check test 2]")
print("- Recommendation: [based on results above]")
