"""Discovery of Ring Intercom Video devices from the Ring integration."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant

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
