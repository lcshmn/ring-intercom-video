"""Ding history: a snapshot per ding, kept for a configurable number of days.

Opt-in via configuration.yaml:

    ring_intercom_camera:
      history:
        days: 14

On every ding of the Ring integration's ``event.<name>_ding`` entity, an entry
is recorded at once and the next snapshot captured within
``HISTORY_CAPTURE_WINDOW`` seconds is attached to it. The history requests
that capture itself, so it works without any automation; when an automation
captures at the same moment, both share the same session (the camera joins an
in-flight capture), so the battery-powered device is only woken once.

Images go to ``<media>/ring_intercom/<device>/<YYYY-MM-DD>/<HH-MM-SS>.jpg``.
``/media`` rather than ``/config/www``: the latter is served without
authentication, which is no place for pictures of visitors. The media
browser shows the folder out of the box.

Day folders older than ``days`` are deleted, together with their entries.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
import logging
from pathlib import Path
import re
import shutil
from typing import Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util, slugify

from .const import (
    CONF_DAYS,
    CONF_DING_ENTITY,
    CONF_HISTORY,
    DATA_CONFIG,
    DATA_HISTORIES,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# How long after a ding a finished capture still counts as that ding's
# picture. Covers an automation that first closes live views, then captures.
HISTORY_CAPTURE_WINDOW = 30
PRUNE_INTERVAL = timedelta(hours=1)
STORAGE_VERSION = 1
MEDIA_SUBDIR = "ring_intercom"
_DAY_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class DingHistory:
    """Records dings and their snapshots for one intercom."""

    def __init__(
        self, hass: HomeAssistant, device, days: int, ding_entity: str | None
    ) -> None:
        """Initialize."""
        self._hass = hass
        self._device = device
        self._days = days
        self._ding_entity_override = ding_entity
        media_root = hass.config.media_dirs.get("local") or hass.config.path("media")
        self._dir = Path(media_root) / MEDIA_SUBDIR / slugify(device.name)
        self._media_root = Path(media_root)
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.history_{device.device_api_id}"
        )
        # Newest last. Each: {"time": iso, "image": path relative to media root | None}
        self._entries: list[dict[str, Any]] = []
        self._pending: dict[str, Any] | None = None
        self._cancel_pending: Callable[[], None] | None = None
        self._capture: Callable[[], Awaitable[bytes | None]] | None = None
        self._listeners: list[Callable[[], None]] = []

    # ---- setup ----

    async def async_start(self) -> None:
        """Load stored entries, start listening for dings and pruning."""
        if data := await self._store.async_load():
            self._entries = data.get("entries", [])
        await self._async_prune()

        if ding_entity := self._ding_entity_override or self._find_ding_entity():
            _LOGGER.debug(
                "Ding history for %s listens to %s", self._device.name, ding_entity
            )
            async_track_state_change_event(
                self._hass, [ding_entity], self._handle_ding_state
            )
        else:
            _LOGGER.warning(
                "Ding history for %s: no ding event entity of the Ring "
                "integration found, so no dings will be recorded. Set "
                "ring_intercom_camera: history: ding_entity: to fix this",
                self._device.name,
            )

        async_track_time_interval(
            self._hass, self._async_prune_interval, PRUNE_INTERVAL
        )

    def _find_ding_entity(self) -> str | None:
        """Return the Ring integration's ding event entity for this device.

        The Ring integration builds the unique id as "<device id>-ding"; the
        entity id itself may have been renamed by the user.
        """
        registry = er.async_get(self._hass)
        wanted = f"{self._device.device_api_id}-ding"
        for entry in registry.entities.values():
            if (
                entry.platform == "ring"
                and entry.domain == "event"
                and entry.unique_id == wanted
            ):
                return entry.entity_id
        return None

    def set_capture(self, capture: Callable[[], Awaitable[bytes | None]]) -> None:
        """Register the camera's request for a picture of this moment."""
        self._capture = capture

    # ---- state for the entities ----

    @property
    def entries(self) -> list[dict[str, Any]]:
        """Return entries, newest first."""
        return list(reversed(self._entries))

    @property
    def last_entry(self) -> dict[str, Any] | None:
        """Return the newest entry."""
        return self._entries[-1] if self._entries else None

    @property
    def last_image_entry(self) -> dict[str, Any] | None:
        """Return the newest entry that has a picture."""
        for entry in reversed(self._entries):
            if entry.get("image"):
                return entry
        return None

    def image_path(self, entry: dict[str, Any]) -> Path | None:
        """Return the absolute path of an entry's picture."""
        return self._media_root / entry["image"] if entry.get("image") else None

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Subscribe to changes. Returns a callable that unsubscribes."""
        self._listeners.append(listener)

        def _remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _remove

    @callback
    def _changed(self) -> None:
        self._store.async_delay_save(lambda: {"entries": self._entries}, 1)
        for listener in list(self._listeners):
            listener()

    # ---- ding → entry → picture ----

    @callback
    def _handle_ding_state(self, event: Event[EventStateChangedData]) -> None:
        """Record a ding.

        Skips startup restores (no old state) and the entity coming back from
        unavailable; "unknown" → timestamp is a real first ding.
        """
        old, new = event.data["old_state"], event.data["new_state"]
        if (
            old is None
            or new is None
            or old.state == STATE_UNAVAILABLE
            or new.state in (STATE_UNAVAILABLE, STATE_UNKNOWN)
        ):
            return

        entry = {"time": dt_util.now().isoformat(), "image": None}
        self._entries.append(entry)
        self._set_pending(entry)
        self._changed()

        if self._capture is not None:
            self._hass.async_create_background_task(
                self._async_capture_for_ding(), f"{DOMAIN} history capture"
            )

    async def _async_capture_for_ding(self) -> None:
        """Request a snapshot so dings get a picture without any automation."""
        assert self._capture is not None
        if image := await self._capture():
            # No-op if the capture already delivered it via async_on_image.
            await self.async_on_image(image)

    @callback
    def _set_pending(self, entry: dict[str, Any]) -> None:
        if self._cancel_pending:
            self._cancel_pending()

        @callback
        def _expire(_now: datetime) -> None:
            if self._pending is entry:
                _LOGGER.debug(
                    "Ding history for %s: no picture within %ds",
                    self._device.name, HISTORY_CAPTURE_WINDOW,
                )
                self._pending = None
            self._cancel_pending = None

        self._pending = entry
        self._cancel_pending = async_call_later(
            self._hass, HISTORY_CAPTURE_WINDOW, _expire
        )

    async def async_on_image(self, image: bytes) -> None:
        """Attach a freshly captured picture to the pending ding, if any."""
        entry = self._pending
        if entry is None:
            return
        self._pending = None
        if self._cancel_pending:
            self._cancel_pending()
            self._cancel_pending = None

        when = datetime.fromisoformat(entry["time"])
        path = self._dir / when.strftime("%Y-%m-%d") / f"{when.strftime('%H-%M-%S')}.jpg"
        try:
            await self._hass.async_add_executor_job(_write_file, path, image)
        except OSError:
            _LOGGER.exception("Could not store ding picture at %s", path)
            return
        entry["image"] = str(path.relative_to(self._media_root))
        self._changed()

    # ---- retention ----

    async def _async_prune_interval(self, _now: datetime) -> None:
        await self._async_prune()

    async def _async_prune(self) -> None:
        """Delete entries and day folders older than the configured days."""
        cutoff = dt_util.now().date() - timedelta(days=self._days - 1)

        kept = [
            e for e in self._entries
            if datetime.fromisoformat(e["time"]).date() >= cutoff
        ]
        removed = await self._hass.async_add_executor_job(
            _delete_old_day_dirs, self._dir, cutoff
        )
        if removed:
            _LOGGER.debug(
                "Ding history for %s: deleted %s", self._device.name, removed
            )
        if len(kept) != len(self._entries):
            self._entries = kept
            self._changed()


def _write_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _delete_old_day_dirs(base: Path, cutoff: date) -> list[str]:
    """Delete <base>/<YYYY-MM-DD> folders before cutoff.

    Only touches folders named like a date, so nothing else a user keeps
    there can be removed.
    """
    if not base.is_dir():
        return []
    removed = []
    for child in base.iterdir():
        if not (child.is_dir() and _DAY_DIR.match(child.name)):
            continue
        try:
            day = date.fromisoformat(child.name)
        except ValueError:
            continue
        if day < cutoff:
            shutil.rmtree(child)
            removed.append(child.name)
    return removed


async def async_get_history(hass: HomeAssistant, device) -> DingHistory | None:
    """Return the started history for a device, or None if not configured.

    Called from several platforms; the first call creates and starts it, the
    others wait for that same start.
    """
    conf = hass.data.get(DOMAIN, {}).get(DATA_CONFIG, {}).get(CONF_HISTORY)
    if conf is None:
        return None

    histories: dict[int, asyncio.Task[DingHistory]] = hass.data[DOMAIN].setdefault(
        DATA_HISTORIES, {}
    )
    if (task := histories.get(device.device_api_id)) is None:

        async def _create() -> DingHistory:
            history = DingHistory(
                hass, device, conf[CONF_DAYS], conf.get(CONF_DING_ENTITY)
            )
            await history.async_start()
            return history

        task = histories[device.device_api_id] = hass.async_create_task(_create())
    return await asyncio.shield(task)
