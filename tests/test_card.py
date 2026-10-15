"""Tests for serving the ding history card."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.ring_intercom_camera import CARD_URL, _async_register_card


async def test_card_is_served_and_loaded_in_dashboards(
    hass: HomeAssistant, hass_client
) -> None:
    assert await async_setup_component(hass, "http", {})
    with patch(
        "custom_components.ring_intercom_camera.add_extra_js_url"
    ) as add_extra_js_url:
        await _async_register_card(hass)

    url = add_extra_js_url.call_args.args[1]
    assert url.startswith(f"{CARD_URL}?v=")

    client = await hass_client()
    response = await client.get(url)
    assert response.status == 200
    assert "customElements.define(\"ring-ding-history-card\"" in await response.text()
