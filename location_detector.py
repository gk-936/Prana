"""Automatic location detection for PRANA
Uses IP geolocation (free, no API key needed)
"""

import requests
from backend.logger import get_logger

logger = get_logger("location_detector")


def get_current_location():
    """
    Detect user's current location using IP geolocation.

    Returns:
        dict with 'lat', 'lon', 'city', 'country'

    Raises:
        RuntimeError: if location cannot be determined.
    """
    # Method 1: ipapi.co (free, no signup, HTTPS)
    try:
        logger.info("Detecting your location...")
        response = requests.get("https://ipapi.co/json/", timeout=5)

        if response.status_code == 200:
            data = response.json()
            location = {
                "lat": data.get("latitude"),
                "lon": data.get("longitude"),
                "city": data.get("city", "Unknown"),
                "region": data.get("region", ""),
                "country": data.get("country_name", "Unknown"),
                "postal": data.get("postal", ""),
            }
            if location["lat"] is not None and location["lon"] is not None:
                logger.info(
                    "Location detected: %s, %s  (%.4f, %.4f)",
                    location["city"],
                    location["country"],
                    location["lat"],
                    location["lon"],
                )
                return location

    except requests.exceptions.Timeout:
        logger.warning("ipapi.co timed out")
    except requests.exceptions.RequestException as e:
        logger.warning("ipapi.co failed: %s", e)

    # Method 2: ip-api.com (backup, HTTPS)
    try:
        logger.info("Trying backup location service...")
        response = requests.get("https://ip-api.com/json/", timeout=5)

        if response.status_code == 200:
            data = response.json()
            location = {
                "lat": data.get("lat"),
                "lon": data.get("lon"),
                "city": data.get("city", "Unknown"),
                "region": data.get("regionName", ""),
                "country": data.get("country", "Unknown"),
                "postal": data.get("zip", ""),
            }
            if location["lat"] is not None and location["lon"] is not None:
                logger.info(
                    "Location detected: %s, %s  (%.4f, %.4f)",
                    location["city"],
                    location["country"],
                    location["lat"],
                    location["lon"],
                )
                return location

    except requests.exceptions.Timeout:
        logger.warning("ip-api.com timed out")
    except requests.exceptions.RequestException as e:
        logger.warning("ip-api.com failed: %s", e)

    raise RuntimeError("Could not detect location from IP. Please provide coordinates manually.")


def get_location_name(location):
    """Format location name for display"""
    if location["region"] and location["region"] != location["city"]:
        return f"{location['city']}, {location['region']}, {location['country']}"
    return f"{location['city']}, {location['country']}"


if __name__ == "__main__":
    logger.info("=" * 70)
    logger.info("LOCATION DETECTION TEST")
    logger.info("=" * 70)

    try:
        location = get_current_location()
        logger.info("=" * 70)
        logger.info("DETECTED LOCATION")
        logger.info("=" * 70)
        logger.info("City: %s", location["city"])
        logger.info("Region: %s", location["region"])
        logger.info("Country: %s", location["country"])
        logger.info("Latitude: %s", location["lat"])
        logger.info("Longitude: %s", location["lon"])
        if location["postal"]:
            logger.info("Postal Code: %s", location["postal"])
        logger.info("=" * 70)
        logger.info("Location detection working!")
        logger.info("Your PRANA alerts will be for: %s", get_location_name(location))
    except RuntimeError as e:
        logger.error(e)
