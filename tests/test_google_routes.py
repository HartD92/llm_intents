"""Test the Google Routes tool."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from custom_components.llm_intents.const import (
    CONF_GOOGLE_ROUTES_API_KEY,
    CONF_GOOGLE_ROUTES_ENABLED,
    CONF_GOOGLE_ROUTES_LATITUDE,
    CONF_GOOGLE_ROUTES_LONGITUDE,
    CONF_GOOGLE_ROUTES_TRAVEL_MODE,
    DOMAIN,
)
from custom_components.llm_intents.GoogleRoutes import GetTransitTimesTool


class TestGoogleRoutes:
    """Test Google Routes tool."""

    @pytest.fixture
    def hass(self):
        """Create a mock Home Assistant instance."""
        hass = Mock(spec=HomeAssistant)
        hass.data = {}

        # Mock config entry
        mock_entry = Mock()
        mock_entry.options = {}
        hass.config_entries = Mock()
        hass.config_entries.async_entries = Mock(return_value=[mock_entry])

        return hass

    @pytest.fixture
    def config_data(self):
        """Create test configuration data."""
        return {
            CONF_GOOGLE_ROUTES_ENABLED: True,
            CONF_GOOGLE_ROUTES_API_KEY: "test_routes_key",
            CONF_GOOGLE_ROUTES_LATITUDE: "40.7128",
            CONF_GOOGLE_ROUTES_LONGITUDE: "-74.0060",
            CONF_GOOGLE_ROUTES_TRAVEL_MODE: "DRIVE",
        }

    async def test_tool_initialization(self):
        """Test that the tool initializes with correct properties."""
        tool = GetTransitTimesTool()

        assert tool.name == "get_transit_times"
        assert "transit times" in tool.description.lower()
        assert "route" in tool.description.lower()
        assert tool.parameters is not None

    async def test_get_transit_times_success(self, hass, config_data):
        """Test successful route calculation."""
        hass.data[DOMAIN] = {"config": config_data}

        tool = GetTransitTimesTool()

        # Mock the HTTP response
        mock_session = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "routes": [
                    {
                        "duration": "1200s",
                        "distanceMeters": 5000,
                        "legs": [
                            {
                                "duration": "1200s",
                                "distanceMeters": 5000,
                            }
                        ],
                    }
                ]
            }
        )

        class MockContext:
            def __init__(self, response):
                self.response = response

            async def __aenter__(self):
                return self.response

            async def __aexit__(self, *args):
                return None

        def mock_post(*args, **kwargs):
            return MockContext(mock_response)

        mock_session.post = mock_post

        tool_input = Mock(spec=llm.ToolInput)
        tool_input.tool_args = {"destination": "Times Square, New York"}

        llm_context = Mock(spec=llm.LLMContext)

        with patch(
            "custom_components.llm_intents.GoogleRoutes.async_get_clientsession",
            return_value=mock_session,
        ), patch(
            "custom_components.llm_intents.GoogleRoutes.SQLiteCache"
        ) as mock_cache:
            mock_cache_instance = Mock()
            mock_cache_instance.get = Mock(return_value=None)
            mock_cache_instance.set = Mock()
            mock_cache.return_value = mock_cache_instance

            result = await tool.async_call(hass, tool_input, llm_context)

            assert "destination" in result
            assert "duration" in result
            assert "distance" in result
            assert result["destination"] == "Times Square, New York"
            assert "20 minute" in result["duration"]
            assert "5.0 km" in result["distance"]

    async def test_get_transit_times_no_api_key(self, hass):
        """Test error when API key is not configured."""
        hass.data[DOMAIN] = {
            "config": {
                CONF_GOOGLE_ROUTES_ENABLED: True,
                CONF_GOOGLE_ROUTES_LATITUDE: "40.7128",
                CONF_GOOGLE_ROUTES_LONGITUDE: "-74.0060",
            }
        }

        tool = GetTransitTimesTool()

        tool_input = Mock(spec=llm.ToolInput)
        tool_input.tool_args = {"destination": "Times Square"}

        llm_context = Mock(spec=llm.LLMContext)

        result = await tool.async_call(hass, tool_input, llm_context)

        assert "error" in result
        assert "API key not configured" in result["error"]

    async def test_get_transit_times_no_origin(self, hass):
        """Test error when origin location is not configured."""
        hass.data[DOMAIN] = {
            "config": {
                CONF_GOOGLE_ROUTES_ENABLED: True,
                CONF_GOOGLE_ROUTES_API_KEY: "test_key",
            }
        }

        tool = GetTransitTimesTool()

        tool_input = Mock(spec=llm.ToolInput)
        tool_input.tool_args = {"destination": "Times Square"}

        llm_context = Mock(spec=llm.LLMContext)

        result = await tool.async_call(hass, tool_input, llm_context)

        assert "error" in result
        assert "Origin location" in result["error"]

    async def test_get_transit_times_no_route_found(self, hass, config_data):
        """Test when no route is found."""
        hass.data[DOMAIN] = {"config": config_data}

        tool = GetTransitTimesTool()

        mock_session = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"routes": []})

        class MockContext:
            def __init__(self, response):
                self.response = response

            async def __aenter__(self):
                return self.response

            async def __aexit__(self, *args):
                return None

        def mock_post(*args, **kwargs):
            return MockContext(mock_response)

        mock_session.post = mock_post

        tool_input = Mock(spec=llm.ToolInput)
        tool_input.tool_args = {"destination": "Invalid Place"}

        llm_context = Mock(spec=llm.LLMContext)

        with patch(
            "custom_components.llm_intents.GoogleRoutes.async_get_clientsession",
            return_value=mock_session,
        ), patch(
            "custom_components.llm_intents.GoogleRoutes.SQLiteCache"
        ) as mock_cache:
            mock_cache_instance = Mock()
            mock_cache_instance.get = Mock(return_value=None)
            mock_cache.return_value = mock_cache_instance

            result = await tool.async_call(hass, tool_input, llm_context)

            assert "result" in result
            assert "No route found" in result["result"]

    async def test_get_transit_times_api_error(self, hass, config_data):
        """Test handling of API errors."""
        hass.data[DOMAIN] = {"config": config_data}

        tool = GetTransitTimesTool()

        mock_session = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status = 500
        mock_response.text = AsyncMock(return_value="Internal Server Error")

        class MockContext:
            def __init__(self, response):
                self.response = response

            async def __aenter__(self):
                return self.response

            async def __aexit__(self, *args):
                return None

        def mock_post(*args, **kwargs):
            return MockContext(mock_response)

        mock_session.post = mock_post

        tool_input = Mock(spec=llm.ToolInput)
        tool_input.tool_args = {"destination": "Times Square"}

        llm_context = Mock(spec=llm.LLMContext)

        with patch(
            "custom_components.llm_intents.GoogleRoutes.async_get_clientsession",
            return_value=mock_session,
        ), patch(
            "custom_components.llm_intents.GoogleRoutes.SQLiteCache"
        ) as mock_cache:
            mock_cache_instance = Mock()
            mock_cache_instance.get = Mock(return_value=None)
            mock_cache.return_value = mock_cache_instance

            result = await tool.async_call(hass, tool_input, llm_context)

            assert "error" in result
            assert "500" in result["error"]

    async def test_get_transit_times_with_hours(self, hass, config_data):
        """Test duration formatting with hours."""
        hass.data[DOMAIN] = {"config": config_data}

        tool = GetTransitTimesTool()

        mock_session = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "routes": [
                    {
                        "duration": "7200s",  # 2 hours
                        "distanceMeters": 100000,
                    }
                ]
            }
        )

        class MockContext:
            def __init__(self, response):
                self.response = response

            async def __aenter__(self):
                return self.response

            async def __aexit__(self, *args):
                return None

        def mock_post(*args, **kwargs):
            return MockContext(mock_response)

        mock_session.post = mock_post

        tool_input = Mock(spec=llm.ToolInput)
        tool_input.tool_args = {"destination": "Boston"}

        llm_context = Mock(spec=llm.LLMContext)

        with patch(
            "custom_components.llm_intents.GoogleRoutes.async_get_clientsession",
            return_value=mock_session,
        ), patch(
            "custom_components.llm_intents.GoogleRoutes.SQLiteCache"
        ) as mock_cache:
            mock_cache_instance = Mock()
            mock_cache_instance.get = Mock(return_value=None)
            mock_cache_instance.set = Mock()
            mock_cache.return_value = mock_cache_instance

            result = await tool.async_call(hass, tool_input, llm_context)

            assert "2 hours 0 minutes" in result["duration"]

    async def test_get_transit_times_cached(self, hass, config_data):
        """Test that cached results are returned."""
        hass.data[DOMAIN] = {"config": config_data}

        tool = GetTransitTimesTool()

        cached_result = {
            "destination": "Times Square",
            "duration": "20 minutes",
            "distance": "5.0 km",
        }

        tool_input = Mock(spec=llm.ToolInput)
        tool_input.tool_args = {"destination": "Times Square"}

        llm_context = Mock(spec=llm.LLMContext)

        with patch(
            "custom_components.llm_intents.GoogleRoutes.SQLiteCache"
        ) as mock_cache:
            mock_cache_instance = Mock()
            mock_cache_instance.get = Mock(return_value=cached_result)
            mock_cache.return_value = mock_cache_instance

            result = await tool.async_call(hass, tool_input, llm_context)

            assert result == cached_result
            mock_cache_instance.get.assert_called_once()

    async def test_get_transit_times_exception(self, hass, config_data):
        """Test exception handling."""
        hass.data[DOMAIN] = {"config": config_data}

        tool = GetTransitTimesTool()

        tool_input = Mock(spec=llm.ToolInput)
        tool_input.tool_args = {"destination": "Times Square"}

        llm_context = Mock(spec=llm.LLMContext)

        with patch(
            "custom_components.llm_intents.GoogleRoutes.async_get_clientsession",
            side_effect=Exception("Network error"),
        ), patch(
            "custom_components.llm_intents.GoogleRoutes.SQLiteCache"
        ) as mock_cache:
            mock_cache_instance = Mock()
            mock_cache_instance.get = Mock(return_value=None)
            mock_cache.return_value = mock_cache_instance

            result = await tool.async_call(hass, tool_input, llm_context)

            assert "error" in result
            assert "Network error" in result["error"]

    async def test_travel_mode_configuration(self, hass):
        """Test different travel modes."""
        travel_modes = ["DRIVE", "WALK", "BICYCLE", "TRANSIT", "TWO_WHEELER"]

        for mode in travel_modes:
            config = {
                CONF_GOOGLE_ROUTES_ENABLED: True,
                CONF_GOOGLE_ROUTES_API_KEY: "test_key",
                CONF_GOOGLE_ROUTES_LATITUDE: "40.7128",
                CONF_GOOGLE_ROUTES_LONGITUDE: "-74.0060",
                CONF_GOOGLE_ROUTES_TRAVEL_MODE: mode,
            }

            hass.data[DOMAIN] = {"config": config}

            tool = GetTransitTimesTool()

            mock_session = AsyncMock()
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(
                return_value={
                    "routes": [
                        {
                            "duration": "600s",
                            "distanceMeters": 1000,
                        }
                    ]
                }
            )

            class MockContext:
                def __init__(self, response):
                    self.response = response

                async def __aenter__(self):
                    return self.response

                async def __aexit__(self, *args):
                    return None

            def mock_post(*args, **kwargs):
                return MockContext(mock_response)

            mock_session.post = mock_post

            tool_input = Mock(spec=llm.ToolInput)
            tool_input.tool_args = {"destination": "Central Park"}

            llm_context = Mock(spec=llm.LLMContext)

            with patch(
                "custom_components.llm_intents.GoogleRoutes.async_get_clientsession",
                return_value=mock_session,
            ), patch(
                "custom_components.llm_intents.GoogleRoutes.SQLiteCache"
            ) as mock_cache:
                mock_cache_instance = Mock()
                mock_cache_instance.get = Mock(return_value=None)
                mock_cache_instance.set = Mock()
                mock_cache.return_value = mock_cache_instance

                result = await tool.async_call(hass, tool_input, llm_context)

                assert "travel_mode" in result
                assert mode.lower().replace("_", " ") in result["travel_mode"]
