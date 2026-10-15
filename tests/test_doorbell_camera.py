"""Tests for the doorbell camera and RingIntercomCamera.async_image_since."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant

from custom_components.ring_intercom_camera import camera as camera_mod
from custom_components.ring_intercom_camera.camera import (
    RingIntercomCamera,
    RingIntercomDoorbellCamera,
)

DING = "event.front_door_ding"
DEVICE = SimpleNamespace(name="Front door", device_api_id=1234, kind="intercom_handset_video")
NEW = b"new picture"
OLD = b"old picture"


class FakeCamera:
    """Stands in for RingIntercomCamera: counts captures, can be slow."""

    def __init__(self, delay: float = 0.0, result: bytes | None = NEW) -> None:
        self.calls: list[float] = []
        self.delay = delay
        self.result = result
        self.last_image: bytes | None = OLD

    async def async_image_since(self, since: float) -> bytes | None:
        self.calls.append(since)
        await asyncio.sleep(self.delay)
        return self.result


async def _doorbell(hass: HomeAssistant, camera, history=None) -> RingIntercomDoorbellCamera:
    hass.data["ring_intercom_camera"] = {"config": {"history": {"ding_entity": DING}}}
    hass.states.async_set(DING, "2026-10-14T13:00:00+00:00")
    entity = RingIntercomDoorbellCamera(DEVICE, camera, history)
    entity.hass = hass
    entity.entity_id = "camera.front_door_doorbell"
    # Writing state is not what these tests are about.
    entity.async_write_ha_state = lambda: None
    await entity.async_added_to_hass()
    return entity


async def _ding(hass: HomeAssistant, old: str | None = None) -> None:
    if old is not None:
        hass.states.async_set(DING, old)
    hass.states.async_set(DING, f"2026-10-14T13:00:{time.time() % 60:09.6f}+00:00")
    await hass.async_block_till_done()


async def test_outside_window_serves_last_picture_without_waking(hass: HomeAssistant) -> None:
    camera = FakeCamera()
    entity = await _doorbell(hass, camera)

    assert await entity.async_camera_image() == OLD
    assert camera.calls == []


async def test_ding_starts_capture_and_request_waits_for_it(hass: HomeAssistant) -> None:
    camera = FakeCamera(delay=0.2)
    entity = await _doorbell(hass, camera)

    before = time.time()
    hass.states.async_set(DING, "2026-10-14T13:05:00+00:00")
    # HA has handled the ding (the capture is running in the background) by
    # the time HomeKit's request for the notification picture comes in.
    await hass.async_block_till_done()
    assert await entity.async_camera_image() == NEW
    assert len(camera.calls) >= 1
    assert all(since >= before for since in camera.calls)


async def test_restore_from_unavailable_is_not_a_ding(hass: HomeAssistant) -> None:
    camera = FakeCamera()
    entity = await _doorbell(hass, camera)

    await _ding(hass, old=STATE_UNAVAILABLE)
    hass.states.async_set(DING, STATE_UNKNOWN)
    await hass.async_block_till_done()

    assert camera.calls == []
    assert await entity.async_camera_image() == OLD


async def test_slow_capture_gives_no_picture_rather_than_an_old_one(hass: HomeAssistant) -> None:
    camera = FakeCamera(delay=0.3)
    entity = await _doorbell(hass, camera)
    hass.states.async_set(DING, "2026-10-14T13:05:00+00:00")
    await hass.async_block_till_done()

    with patch.object(camera_mod, "DOORBELL_WAIT_SECONDS", 0.05):
        assert await entity.async_camera_image() is None
    await asyncio.sleep(0.3)  # let the capture finish instead of lingering


async def test_window_expires(hass: HomeAssistant) -> None:
    camera = FakeCamera()
    entity = await _doorbell(hass, camera)
    await _ding(hass)
    calls_after_ding = len(camera.calls)

    with patch.object(camera_mod.time, "time", return_value=time.time() + 31):
        assert await entity.async_camera_image() == OLD
    assert len(camera.calls) == calls_after_ding


async def test_falls_back_to_history_picture_after_restart(
    hass: HomeAssistant, tmp_path
) -> None:
    picture = tmp_path / "ding.jpg"
    picture.write_bytes(b"from history")
    history = SimpleNamespace(
        last_image_entry={"image": "ding.jpg"},
        image_path=lambda entry: picture,
    )
    camera = FakeCamera()
    camera.last_image = None
    entity = await _doorbell(hass, camera, history)

    assert await entity.async_camera_image() == b"from history"


# ---- RingIntercomCamera.async_image_since ----


@pytest.fixture
def ring_camera(hass: HomeAssistant) -> RingIntercomCamera:
    entity = RingIntercomCamera(hass, DEVICE)
    entity.hass = hass
    return entity


async def test_image_since_uses_recent_cache(ring_camera: RingIntercomCamera) -> None:
    ring_camera._last_image = NEW
    ring_camera._last_image_time = time.time()
    with patch.object(ring_camera, "_capture_snapshot") as capture:
        assert await ring_camera.async_image_since(time.time() - 1) == NEW
    capture.assert_not_called()


async def test_image_since_captures_when_cache_is_older(ring_camera: RingIntercomCamera) -> None:
    ring_camera._last_image = OLD
    ring_camera._last_image_time = time.time() - 5
    picture = b"x" * 1000

    async def _capture():
        return picture

    with patch.object(ring_camera, "_capture_snapshot", side_effect=_capture):
        assert await ring_camera.async_image_since(time.time()) == picture


async def test_image_since_never_returns_an_older_picture(ring_camera: RingIntercomCamera) -> None:
    ring_camera._last_image = OLD
    ring_camera._last_image_time = time.time() - 5

    async def _failed_capture():
        return None

    with patch.object(ring_camera, "_capture_snapshot", side_effect=_failed_capture):
        assert await ring_camera.async_image_since(time.time()) is None


async def test_image_since_skips_capture_during_live_view(ring_camera: RingIntercomCamera) -> None:
    ring_camera._last_image = OLD
    ring_camera._last_image_time = time.time() - 5
    with (
        patch.object(type(ring_camera._sessions), "active", new=True),
        patch.object(ring_camera, "_capture_snapshot") as capture,
    ):
        assert await ring_camera.async_image_since(time.time()) is None
    capture.assert_not_called()
