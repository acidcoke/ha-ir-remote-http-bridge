"""Tests for the IR Remote HTTP Bridge integration."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError

from custom_components.ir_remote_http_bridge.api import parse_maker_url
from custom_components.ir_remote_http_bridge.const import DOMAIN
from custom_components.ir_remote_http_bridge.definitions import (
    BUILTIN_DIR,
    load_definitions,
)

URL = "http://192.168.1.10/apps/api/38/devices?access_token=tok"


@pytest.mark.parametrize(
    ("url", "token", "expected"),
    [
        (URL, None, ("http://192.168.1.10/apps/api/38", "tok")),
        ("http://hub/apps/api/5", "x", ("http://hub/apps/api/5", "x")),
        (
            "https://cloud.hubitat.com/api/abc-1/apps/38/devices/all?access_token=t",
            None,
            ("https://cloud.hubitat.com/api/abc-1/apps/38", "t"),
        ),
    ],
)
def test_parse_maker_url(url, token, expected):
    assert parse_maker_url(url, token) == expected


def test_parse_maker_url_invalid():
    with pytest.raises(ValueError):
        parse_maker_url("http://192.168.1.10/")


def test_builtin_definitions(tmp_path, caplog):
    definitions = load_definitions(tmp_path)
    assert set(definitions) == {"eizo_fr19", "fireplace_heater"}
    assert len(definitions["eizo_fr19"].buttons) == 15
    assert len(definitions["fireplace_heater"].buttons) == 11
    # every button of the JSON exists in the SVG
    assert "has no data-button" not in caplog.text
    assert not list(BUILTIN_DIR.glob("*.xml"))


def test_user_definition(tmp_path):
    (tmp_path / "tv.json").write_text(
        '{"name": "TV", "buttons": [{"id": "power", "name": "Power"}]}'
    )
    (tmp_path / "tv.svg").write_text(
        '<?xml version="1.0"?><svg><rect data-button="power"/></svg>'
    )
    (tmp_path / "broken.json").write_text("{")
    definitions = load_definitions(tmp_path)
    assert definitions["tv"].svg.startswith("<svg")
    assert "broken" not in definitions


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"url": URL}
    )
    # only one device looks like an IR blaster -> device step is skipped
    assert result["step_id"] == "remote"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"definition": "eizo_fr19", "name": "Monitor"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    return result["result"]


async def test_config_flow(hass: HomeAssistant, hub):
    entry = await _setup(hass)
    assert entry.title == "Monitor"
    assert entry.data == {
        "base_url": "http://192.168.1.10/apps/api/38",
        "access_token": "tok",
        "device_id": "42",
        "device_label": "IR Blaster",
        "definition": "eizo_fr19",
        "card": "monitor",
    }
    # a second remote with the same name gets its own card type
    second = await _setup(hass)
    assert second.data["card"] == "monitor-2"


async def test_config_flow_errors(hass: HomeAssistant, hub):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"url": "http://nope"}
    )
    assert result["errors"] == {"url": "invalid_url"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"url": "http://hub/apps/api/1"}
    )
    assert result["errors"] == {"access_token": "token_required"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"url": "http://hub/apps/api/1", "access_token": "bad"}
    )
    assert result["errors"] == {"base": "invalid_auth"}


async def test_learn_send_forget(hass: HomeAssistant, hub):
    entry = await _setup(hass)
    bridge = entry.runtime_data
    name = bridge.code_name("power_on")

    assert hass.states.get("button.monitor_on").state == "unavailable"
    with pytest.raises(HomeAssistantError):
        await bridge.async_send("power_on")

    assert await bridge.async_learn("power_on") == "TmV3Q29kZQ+/="
    await hass.async_block_till_done()
    assert hub.commands[-1] == ("42", "learn", name)
    assert hass.states.get("button.monitor_on").state != "unavailable"

    await hass.services.async_call(
        "button", "press", {"entity_id": "button.monitor_on"}, blocking=True
    )
    assert hub.commands[-1] == ("42", "sendCode", name)

    hass.config_entries.async_update_entry(entry, options={"send_mode": "code"})
    await hass.async_block_till_done()
    bridge = entry.runtime_data  # reloaded, codes come from storage
    await bridge.async_send("power_on")
    assert hub.commands[-1] == ("42", "sendCode", "TmV3Q29kZQ+/=")

    await bridge.async_forget("power_on")
    await hass.async_block_till_done()
    assert hub.commands[-1] == ("42", "forgetCode", name)
    assert hass.states.get("button.monitor_on").state == "unavailable"


async def test_learn_timeout(hass: HomeAssistant, hub):
    entry = await _setup(hass)
    hass.config_entries.async_update_entry(entry, options={"learn_timeout": 0})
    await hass.async_block_till_done()
    hub.code_on_learn = None
    bridge = entry.runtime_data
    with pytest.raises(HomeAssistantError, match="No IR code"):
        await bridge.async_learn("menu")
    assert bridge.learning is None
    assert "menu" not in bridge.codes


async def test_websocket(hass: HomeAssistant, hub, hass_ws_client):
    entry = await _setup(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": f"{DOMAIN}/remotes"})
    msg = await client.receive_json()
    assert msg["result"] == [
        {
            "entry_id": entry.entry_id,
            "title": "Monitor",
            "definition": "eizo_fr19",
            "card": "monitor",
        }
    ]

    await client.send_json_auto_id(
        {"type": f"{DOMAIN}/remote", "entry_id": entry.entry_id}
    )
    remote = (await client.receive_json())["result"]
    assert remote["svg"].startswith("<svg")
    assert remote["learned"] == []
    assert len(remote["buttons"]) == 15

    await client.send_json_auto_id(
        {"type": f"{DOMAIN}/subscribe", "entry_id": entry.entry_id}
    )
    sub_id = (await client.receive_json())["id"]
    assert (await client.receive_json())["event"]["learning"] is None

    await client.send_json_auto_id(
        {"type": f"{DOMAIN}/send", "entry_id": entry.entry_id, "button": "menu"}
    )
    msg = await client.receive_json()
    assert msg["error"]["code"] == "not_learned"

    await client.send_json_auto_id(
        {"type": f"{DOMAIN}/learn", "entry_id": entry.entry_id, "button": "menu"}
    )
    events = [await client.receive_json() for _ in range(3)]
    assert [e["id"] for e in events].count(sub_id) == 2
    result = next(e for e in events if e["id"] != sub_id)
    assert result["result"]["learned"] == ["menu"]
    assert {e["event"]["learning"] for e in events if e["id"] == sub_id} == {
        "menu",
        None,
    }

    await client.send_json_auto_id(
        {"type": f"{DOMAIN}/send", "entry_id": entry.entry_id, "button": "menu"}
    )
    assert (await client.receive_json())["success"]

    await client.send_json_auto_id(
        {"type": f"{DOMAIN}/remote", "entry_id": "missing"}
    )
    assert (await client.receive_json())["error"]["code"] == "not_found"


async def test_remove_entry(hass: HomeAssistant, hub):
    entry = await _setup(hass)
    await entry.runtime_data.async_learn("menu")
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
