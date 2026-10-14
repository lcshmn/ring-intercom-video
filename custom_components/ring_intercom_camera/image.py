"""Image entity showing the picture of the most recent ding (ding history)."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .devices import intercom_video_devices
from .history import DingHistory, async_get_history


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up one entity per intercom, if the ding history is enabled."""
    entities = []
    for device in intercom_video_devices(hass):
        if history := await async_get_history(hass, device):
            entities.append(RingIntercomLastDingImage(hass, device, history))
    if entities:
        async_add_entities(entities)


class RingIntercomLastDingImage(ImageEntity):
    """The stored picture of the latest ding that has one.

    Served through Home Assistant's authenticated image proxy, so it can be
    shown on a dashboard without exposing the file publicly.
    """

    _attr_should_poll = False
    _attr_content_type = "image/jpeg"

    def __init__(self, hass: HomeAssistant, device, history: DingHistory) -> None:
        """Initialize."""
        super().__init__(hass)
        self._history = history
        self._attr_name = f"{device.name} Last Ding"
        self._attr_unique_id = f"ring_intercom_last_ding_{device.device_api_id}"
        self._entry = history.last_image_entry
        self._attr_image_last_updated = self._entry_time()

    def _entry_time(self) -> datetime | None:
        return datetime.fromisoformat(self._entry["time"]) if self._entry else None

    async def async_added_to_hass(self) -> None:
        """Subscribe to history changes."""
        self.async_on_remove(self._history.add_listener(self._handle_change))

    @callback
    def _handle_change(self) -> None:
        entry = self._history.last_image_entry
        if entry is self._entry:
            return
        self._entry = entry
        self._attr_image_last_updated = self._entry_time()
        self.async_write_ha_state()

    async def async_image(self) -> bytes | None:
        """Return the picture's bytes."""
        if self._entry is None:
            return None
        if (path := self._history.image_path(self._entry)) is None:
            return None
        try:
            return await self.hass.async_add_executor_job(path.read_bytes)
        except OSError:
            return None
