"""Binary sensor platform for Popular Times."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PopularTimesCoordinator


def _make_device_info(entry: ConfigEntry, base_name: str) -> DeviceInfo:
    """Build shared DeviceInfo."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=base_name,
        entry_type=DeviceEntryType.SERVICE,
        manufacturer="Google Maps",
        configuration_url=entry.data.get("maps_url"),
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Popular Times binary sensors from a config entry."""
    coordinator: PopularTimesCoordinator = hass.data[DOMAIN][entry.entry_id]
    name = entry.data.get("name", entry.title)

    async_add_entities([
        LiveDataAvailableSensor(coordinator, entry, name),
        OpenClosedSensor(coordinator, entry, name),
    ])


class LiveDataAvailableSensor(CoordinatorEntity[PopularTimesCoordinator], BinarySensorEntity):
    """Binary sensor indicating whether live popularity data is available."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(
        self,
        coordinator: PopularTimesCoordinator,
        entry: ConfigEntry,
        base_name: str,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_live_available"
        self._attr_name = f"{base_name} live"
        self._attr_icon = "mdi:access-point"
        self._attr_device_info = _make_device_info(entry, base_name)

    @property
    def is_on(self) -> bool | None:
        """Return True if live data is available."""
        if not self.coordinator.data:
            return None
        live = self.coordinator.data.get("live", {})
        return live.get("is_live", False)


class OpenClosedSensor(CoordinatorEntity[PopularTimesCoordinator], BinarySensorEntity):
    """Binary sensor indicating whether the place is currently open."""

    _attr_device_class = BinarySensorDeviceClass.OPENING

    def __init__(
        self,
        coordinator: PopularTimesCoordinator,
        entry: ConfigEntry,
        base_name: str,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_open"
        self._attr_name = f"{base_name} open"
        self._attr_device_info = _make_device_info(entry, base_name)

    @property
    def is_on(self) -> bool | None:
        """Return True if the place is open, False if closed, None if unknown."""
        if not self.coordinator.data:
            return None
        opening = self.coordinator.data.get("opening", {})
        return opening.get("is_open")

    @property
    def extra_state_attributes(self) -> dict:
        """Return opening hours details."""
        if not self.coordinator.data:
            return {}
        opening = self.coordinator.data.get("opening", {})
        attrs = {}
        if opening.get("status_text"):
            attrs["status_text"] = opening["status_text"]
        if opening.get("hours"):
            attrs["opening_hours"] = opening["hours"]
        return attrs
