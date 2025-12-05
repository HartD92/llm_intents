import logging

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util.json import JsonObjectType

from .cache import SQLiteCache
from .const import (
    CONF_GOOGLE_ROUTES_API_KEY,
    CONF_GOOGLE_ROUTES_LATITUDE,
    CONF_GOOGLE_ROUTES_LONGITUDE,
    CONF_GOOGLE_ROUTES_TRAVEL_MODE,
    DOMAIN,
    SERVICE_DEFAULTS,
)

_LOGGER = logging.getLogger(__name__)


class GetTransitTimesTool(llm.Tool):
    """Tool for getting transit times to places."""

    name = "get_transit_times"

    description = "\n".join(
        [
            "Use this tool to get transit times and routes when the user requests or infers they want to know:",
            "- How long it takes to get to a place",
            "- Transit time to a destination",
            "- Directions or route to a location",
            "- When they should leave to arrive at a place",
        ]
    )

    response_directive = "\n".join(
        [
            "Use the route information to answer the user's query.",
            "Focus on the transit time and relevant route details the user is interested in.",
        ]
    )

    parameters = vol.Schema(
        {
            vol.Required(
                "destination", description="The destination address or place name"
            ): str,
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> JsonObjectType:
        """Call the tool."""
        config_data = hass.data[DOMAIN].get("config", {})
        entry = next(iter(hass.config_entries.async_entries(DOMAIN)))
        config_data = {**config_data, **entry.options}

        destination = tool_input.tool_args["destination"]

        api_key = config_data.get(CONF_GOOGLE_ROUTES_API_KEY)
        latitude = config_data.get(CONF_GOOGLE_ROUTES_LATITUDE)
        longitude = config_data.get(CONF_GOOGLE_ROUTES_LONGITUDE)
        travel_mode = config_data.get(
            CONF_GOOGLE_ROUTES_TRAVEL_MODE,
            SERVICE_DEFAULTS.get(CONF_GOOGLE_ROUTES_TRAVEL_MODE),
        )

        if not api_key:
            return {"error": "Google Routes API key not configured"}

        if not latitude or not longitude:
            return {"error": "Origin location (latitude/longitude) not configured"}

        try:
            session = async_get_clientsession(hass)

            # Build the request body for Routes API
            request_body = {
                "origin": {
                    "location": {
                        "latLng": {
                            "latitude": float(latitude),
                            "longitude": float(longitude),
                        }
                    }
                },
                "destination": {"address": destination},
                "travelMode": travel_mode,
                "routingPreference": "TRAFFIC_AWARE",
                "computeAlternativeRoutes": False,
                "languageCode": "en-US",
                "units": "METRIC",
            }

            cache = SQLiteCache()
            cached_response = cache.get(__name__, request_body)
            if cached_response:
                return cached_response

            field_mask = ",".join(
                [
                    "routes.duration",
                    "routes.distanceMeters",
                ]
            )

            headers = {
                "Content-Type": "application/json",
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": field_mask,
            }

            async with session.post(
                "https://routes.googleapis.com/directions/v2:computeRoutes",
                json=request_body,
                headers=headers,
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    routes = data.get("routes", [])

                    if not routes:
                        return {"result": "No route found to destination"}

                    route = routes[0]
                    duration_seconds = int(route.get("duration", "0s").rstrip("s"))
                    distance_meters = route.get("distanceMeters", 0)

                    # Convert to human readable format
                    hours = duration_seconds // 3600
                    minutes = (duration_seconds % 3600) // 60
                    distance_km = distance_meters / 1000

                    if hours > 0:
                        duration_text = f"{hours} hour{'s' if hours != 1 else ''} {minutes} minute{'s' if minutes != 1 else ''}"
                    else:
                        duration_text = f"{minutes} minute{'s' if minutes != 1 else ''}"

                    result = {
                        "destination": destination,
                        "travel_mode": travel_mode.lower().replace("_", " "),
                        "duration": duration_text,
                        "distance": f"{distance_km:.1f} km",
                        "instruction": self.response_directive,
                    }

                    cache.set(__name__, request_body, result)
                    return result

                _LOGGER.error(
                    f"Routes API received a HTTP {resp.status} error from Google: {await resp.text()}"
                )
                return {"error": f"Routes API error: {resp.status}"}

        except Exception as e:
            _LOGGER.error("Routes API error: %s", e)
            return {"error": f"Error getting route: {e!s}"}
