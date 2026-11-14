"""Websocket API used by the dashboard card."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .api import MakerApiError
from .bridge import BridgeBusy, LearnTimeout, NotLearned, RemoteBridge, signal_updated
from .const import CONF_CARD, DOMAIN


@callback
def async_register_websocket_api(hass: HomeAssistant) -> None:
    """Register all websocket commands."""
    websocket_api.async_register_command(hass, ws_list_remotes)
    websocket_api.async_register_command(hass, ws_get_remote)
    websocket_api.async_register_command(hass, ws_subscribe)
    websocket_api.async_register_command(hass, ws_learn)
    websocket_api.async_register_command(hass, ws_send)
    websocket_api.async_register_command(hass, ws_forget)


def _bridge(hass: HomeAssistant, entry_id: str) -> RemoteBridge | None:
    entry = hass.config_entries.async_get_entry(entry_id)
    if (
        entry is None
        or entry.domain != DOMAIN
        or entry.state is not ConfigEntryState.LOADED
    ):
        return None
    return entry.runtime_data


def _require_bridge(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> RemoteBridge | None:
    bridge = _bridge(hass, msg["entry_id"])
    if bridge is None:
        connection.send_error(msg["id"], "not_found", "Remote not found or not loaded")
    return bridge


def _send_error(
    connection: websocket_api.ActiveConnection, msg_id: int, err: Exception
) -> None:
    if isinstance(err, LearnTimeout):
        code = "learn_timeout"
    elif isinstance(err, BridgeBusy):
        code = "busy"
    elif isinstance(err, NotLearned):
        code = "not_learned"
    elif isinstance(err, MakerApiError):
        code = "hub_error"
    else:
        code = "failed"
    connection.send_error(msg_id, code, str(err))


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/remotes"})
@callback
def ws_list_remotes(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """List all loaded remotes."""
    remotes = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        bridge: RemoteBridge = entry.runtime_data
        remotes.append(
            {
                "entry_id": entry.entry_id,
                "title": entry.title,
                "definition": bridge.definition.id,
                "card": entry.data.get(CONF_CARD) or entry.entry_id.lower(),
            }
        )
    connection.send_result(msg["id"], remotes)


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/remote", vol.Required("entry_id"): str}
)
@callback
def ws_get_remote(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return layout, drawing and state of a remote."""
    if (bridge := _require_bridge(hass, connection, msg)) is None:
        return
    definition = bridge.definition
    connection.send_result(
        msg["id"],
        {
            "entry_id": bridge.entry.entry_id,
            "title": bridge.entry.title,
            "definition": definition.id,
            "buttons": [
                {"id": button["id"], "name": button["name"]}
                for button in definition.buttons
            ],
            "svg": definition.svg,
            **bridge.state(),
        },
    )


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/subscribe", vol.Required("entry_id"): str}
)
@callback
def ws_subscribe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Push learned/learning state changes of a remote."""
    entry_id = msg["entry_id"]
    if _require_bridge(hass, connection, msg) is None:
        return

    @callback
    def forward() -> None:
        # Look the bridge up again: the entry may have been reloaded.
        if (bridge := _bridge(hass, entry_id)) is not None:
            connection.send_message(
                websocket_api.event_message(msg["id"], bridge.state())
            )

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(
        hass, signal_updated(entry_id), forward
    )
    connection.send_result(msg["id"])
    forward()


_BUTTON_COMMAND = {vol.Required("entry_id"): str, vol.Required("button"): str}


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/learn", **_BUTTON_COMMAND}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_learn(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Learn the code of a button. Answers once a code arrived or on timeout."""
    if (bridge := _require_bridge(hass, connection, msg)) is None:
        return
    try:
        await bridge.async_learn(msg["button"])
    except HomeAssistantError as err:
        _send_error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], bridge.state())


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/send", **_BUTTON_COMMAND}
)
@websocket_api.async_response
async def ws_send(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Transmit the code of a button."""
    if (bridge := _require_bridge(hass, connection, msg)) is None:
        return
    try:
        await bridge.async_send(msg["button"])
    except HomeAssistantError as err:
        _send_error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/forget", **_BUTTON_COMMAND}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_forget(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Delete the code of a button."""
    if (bridge := _require_bridge(hass, connection, msg)) is None:
        return
    try:
        await bridge.async_forget(msg["button"])
    except HomeAssistantError as err:
        _send_error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], bridge.state())
