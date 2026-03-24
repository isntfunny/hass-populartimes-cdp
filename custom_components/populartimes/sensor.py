"""Sensor platform for Popular Times."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, DAYS_EN
from .coordinator import PopularTimesCoordinator

_LOGGER = logging.getLogger(__name__)


def _get_historical_now(data: dict | None) -> int | None:
    """Get historical popularity for the current day and hour."""
    if not data:
        return None
    popular_times = data.get("popular_times", {})
    now = dt_util.now()
    day_name = DAYS_EN[now.weekday()]
    hours = popular_times.get(day_name, [0] * 24)
    if now.hour < len(hours):
        return hours[now.hour]
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Popular Times sensors from a config entry."""
    coordinator: PopularTimesCoordinator = hass.data[DOMAIN][entry.entry_id]
    name = entry.data.get("name", entry.title)

    async_add_entities([
        CurrentPopularitySensor(coordinator, entry, name),
        UsualPopularitySensor(coordinator, entry, name),
        PopularityDifferenceSensor(coordinator, entry, name),
    ])


class PopularTimesBaseSensor(CoordinatorEntity[PopularTimesCoordinator], SensorEntity):
    """Base class for Popular Times sensors."""

    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: PopularTimesCoordinator,
        entry: ConfigEntry,
        base_name: str,
        suffix: str,
        icon: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{suffix}"
        self._attr_name = f"{base_name} {suffix}"
        self._attr_icon = icon
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=base_name,
            entry_type=DeviceEntryType.SERVICE,
            manufacturer="Google Maps",
            configuration_url=entry.data.get("maps_url"),
        )

    @property
    def extra_state_attributes(self) -> dict:
        """Return shared attributes."""
        if not self.coordinator.data:
            return {}

        data = self.coordinator.data
        live = data.get("live", {})

        return {
            "maps_name": data.get("name"),
            "address": data.get("address"),
            "maps_url": data.get("maps_url"),
            "popularity_is_live": live.get("is_live", False),
        }


class CurrentPopularitySensor(PopularTimesBaseSensor):
    """Sensor showing the current (live) popularity."""

    def __init__(
        self, coordinator: PopularTimesCoordinator, entry: ConfigEntry, name: str
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, entry, name, "current", "mdi:account-group")

    @property
    def native_value(self) -> int | None:
        """Return current popularity. Falls back to historical if no live data."""
        if not self.coordinator.data:
            return None

        live = self.coordinator.data.get("live", {})
        if live.get("is_live"):
            return live.get("current_pct")

        return _get_historical_now(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict:
        """Return attributes including per-day historical data."""
        attrs = super().extra_state_attributes
        if not self.coordinator.data:
            return attrs

        popular_times = self.coordinator.data.get("popular_times", {})
        for day in DAYS_EN:
            attrs[f"popularity_{day.lower()}"] = popular_times.get(day, [0] * 24)

        return attrs


class UsualPopularitySensor(PopularTimesBaseSensor):
    """Sensor showing the usual (historical) popularity for this hour."""

    def __init__(
        self, coordinator: PopularTimesCoordinator, entry: ConfigEntry, name: str
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, entry, name, "usual", "mdi:chart-timeline-variant")

    @property
    def native_value(self) -> int | None:
        """Return the usual popularity for the current hour."""
        if not self.coordinator.data:
            return None

        live = self.coordinator.data.get("live", {})
        if live.get("is_live") and live.get("usual_pct") is not None:
            return live.get("usual_pct")

        return _get_historical_now(self.coordinator.data)


class PopularityDifferenceSensor(PopularTimesBaseSensor):
    """Sensor showing the difference between current and usual popularity."""

    def __init__(
        self, coordinator: PopularTimesCoordinator, entry: ConfigEntry, name: str
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, entry, name, "difference", "mdi:swap-vertical")

    @property
    def native_value(self) -> int | None:
        """Return the difference: current - usual. Positive = busier than normal."""
        if not self.coordinator.data:
            return None

        live = self.coordinator.data.get("live", {})
        if not live.get("is_live"):
            return 0

        current = live.get("current_pct")
        usual = live.get("usual_pct") or _get_historical_now(self.coordinator.data)

        if current is not None and usual is not None:
            return current - usual
        return None
