"""Config flow for Popular Times integration."""

from __future__ import annotations

import logging
from functools import partial
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_ADDRESS, CONF_CDP_URL, CONF_SKIP_LIVE_CHECK, DEFAULT_CDP_URL, DOMAIN
from .scraper import ConnectionFailed, scrape_popular_times

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ADDRESS): str,
        vol.Required(CONF_CDP_URL, default=DEFAULT_CDP_URL): str,
        vol.Optional("name", default=""): str,
        vol.Optional(CONF_SKIP_LIVE_CHECK, default=False): bool,
    }
)


class PopularTimesConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Popular Times."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            cdp_url = user_input[CONF_CDP_URL]
            skip_check = user_input.get(CONF_SKIP_LIVE_CHECK, False)
            name = user_input.get("name", "").strip()

            # Validate by actually scraping
            result = None
            try:
                result = await self.hass.async_add_executor_job(
                    partial(scrape_popular_times, cdp_url, address)
                )
            except ConnectionFailed:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during validation")
                errors["base"] = "unknown"

            if not errors:
                has_popular_times = result and any(
                    any(h > 0 for h in hours)
                    for hours in result.get("popular_times", {}).values()
                )

                if not has_popular_times and not skip_check:
                    errors["base"] = "no_data"

            if not errors:
                place_name = result.get("name", address) if result else address
                resolved_addr = result.get("address", address) if result else address
                title = name or place_name or address
                unique_id = f"{place_name}_{resolved_addr}"

                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=title,
                    data={
                        CONF_ADDRESS: address,
                        CONF_CDP_URL: cdp_url,
                        "name": title,
                        "maps_url": result.get("maps_url", "") if result else "",
                    },
                )

        # Build schema with suggested values to preserve user input on error
        schema = self.add_suggested_values_to_schema(
            STEP_USER_DATA_SCHEMA, user_input
        ) if user_input else STEP_USER_DATA_SCHEMA

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )
