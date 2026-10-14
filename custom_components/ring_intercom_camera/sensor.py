"""Sensor listing recent dings (ding history)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .devices import intercom_video_devices
from .history import DingHistory, async_get_history

# Entries exposed as an attribute; older ones stay on disk and in the media
# browser, they just aren't listed here.
MAX_LISTED_ENTRIES = 50


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up one sensor per intercom, if the ding history is enabled."""
    entities = []
    for device in intercom_video_devices(hass):
        if history := await async_get_history(hass, device):
            entities.append(RingIntercomDingHistorySensor(device, history))
    if entities:
        async_add_entities(entities)


class RingIntercomDingHistorySensor(SensorEntity):
    """State: time of the last ding. Attribute `entries`: recent dings."""

    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    # The list changes with every ding; recording it each time would only
    # bloat the database with data that is on disk anyway.
    _unrecorded_attributes = frozenset({"entries"})

    def __init__(self, device, history: DingHistory) -> None:
        """Initialize."""
        self._history = history
        self._attr_name = f"{device.name} Ding History"
        self._attr_unique_id = f"ring_intercom_ding_history_{device.device_api_id}"

    async def async_added_to_hass(self) -> None:
        """Subscribe to history changes."""
        self.async_on_remove(self._history.add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> datetime | None:
        """Return the time of the last ding."""
        entry = self._history.last_entry
        return datetime.fromisoformat(entry["time"]) if entry else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return recent dings, newest first.

        `image` is a media-source URI (open it in the media browser), or None
        when no picture could be taken for that ding.
        """
        return {
            "entries": [
                {
                    "time": entry["time"],
                    "image": (
                        f"media-source://media_source/local/{entry['image']}"
                        if entry.get("image")
                        else None
                    ),
                }
                for entry in self._history.entries[:MAX_LISTED_ENTRIES]
            ],
        }
