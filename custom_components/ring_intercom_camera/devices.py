"""Discovery of Ring Intercom Video devices from the Ring integration."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

_LOGGER = logging.getLogger(__name__)


def intercom_video_devices(hass: HomeAssistant) -> list:
    """Return the intercom_handset_video devices of all Ring config entries."""
    devices = []
    for entry in hass.config_entries.async_entries("ring"):
        ring_data = getattr(entry, "runtime_data", None)
        if ring_data is None:
            continue
        try:
            devices.extend(
                device
                for device in ring_data.devices.other
                if device.kind == "intercom_handset_video"
            )
        except Exception:
            _LOGGER.exception("Error discovering Ring Intercom Video devices")
    return devices


def find_ding_entity(hass: HomeAssistant, device) -> str | None:
    """Return the Ring integration's ding event entity for a device.

    The Ring integration builds the unique id as "<device id>-ding"; the
    entity id itself may have been renamed by the user.
    """
    registry = er.async_get(hass)
    wanted = f"{device.device_api_id}-ding"
    for entry in registry.entities.values():
        if (
            entry.platform == "ring"
            and entry.domain == "event"
            and entry.unique_id == wanted
        ):
            return entry.entity_id
    return None
