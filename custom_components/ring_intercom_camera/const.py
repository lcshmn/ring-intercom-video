"""Constants for the Ring Intercom Camera integration."""

from __future__ import annotations

DOMAIN = "ring_intercom_camera"

# hass.data[DOMAIN] key holding one LiveSessionTracker per device_api_id.
DATA_SESSION_TRACKERS = "session_trackers"

# hass.data[DOMAIN] key holding the validated configuration.yaml block.
DATA_CONFIG = "config"
# hass.data[DOMAIN] key holding one DingHistory start task per device_api_id.
DATA_HISTORIES = "histories"

CONF_HISTORY = "history"
CONF_DAYS = "days"
CONF_DING_ENTITY = "ding_entity"
