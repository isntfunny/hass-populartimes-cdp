"""DataUpdateCoordinator for Popular Times."""

import logging
from datetime import timedelta
from functools import partial

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL
from .scraper import ConnectionFailed, scrape_popular_times

_LOGGER = logging.getLogger(__name__)


class PopularTimesCoordinator(DataUpdateCoordinator):
    """Coordinator to fetch popular times data."""

    def __init__(
        self, hass: HomeAssistant, cdp_url: str, address: str, scan_interval_min: int = DEFAULT_SCAN_INTERVAL
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Popular Times",
            update_interval=timedelta(minutes=scan_interval_min),
        )
        self.cdp_url = cdp_url
        self.address = address

    async def _async_update_data(self) -> dict:
        """Fetch data from Google Maps via pychrome CDP."""
        try:
            return await self.hass.async_add_executor_job(
                partial(scrape_popular_times, self.cdp_url, self.address)
            )
        except ConnectionFailed as err:
            raise UpdateFailed(f"CDP connection failed: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Error fetching popular times: {err}") from err
