"""IR Remote HTTP Bridge: remote control cards for a Hubitat IR blaster."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .api import MakerApiClient
from .bridge import STORAGE_VERSION, RemoteBridge, storage_key
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_BASE_URL,
    CONF_DEFINITION,
    DOMAIN,
    FRONTEND_URL,
    PLATFORMS,
)
from .definitions import async_load_definitions
from .websocket_api import async_register_websocket_api

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type IrRemoteConfigEntry = ConfigEntry[RemoteBridge]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the dashboard card and the websocket API."""
    integration = await async_get_integration(hass, DOMAIN)
    card = Path(__file__).parent / "frontend" / "ir-remote-card.js"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(FRONTEND_URL, str(card), cache_headers=False)]
    )
    add_extra_js_url(hass, f"{FRONTEND_URL}?v={integration.version}")
    async_register_websocket_api(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: IrRemoteConfigEntry) -> bool:
    """Set up one remote."""
    definitions = await async_load_definitions(hass)
    definition = definitions.get(entry.data[CONF_DEFINITION])
    if definition is None:
        raise ConfigEntryError(
            f"Remote definition '{entry.data[CONF_DEFINITION]}' not found"
        )

    client = MakerApiClient(
        async_get_clientsession(hass),
        entry.data[CONF_BASE_URL],
        entry.data[CONF_ACCESS_TOKEN],
    )
    bridge = RemoteBridge(hass, entry, client, definition)
    await bridge.async_load()
    entry.runtime_data = bridge

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Drop entities the (possibly edited) definition no longer declares.
    prefix = f"{entry.entry_id}_"
    expected = (
        {f"{prefix}{button}" for button in definition.button_ids}
        | {f"{prefix}switch_{switch['id']}" for switch in definition.switches}
        | ({f"{prefix}media_player"} if definition.media_player else set())
    )
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.unique_id not in expected:
            registry.async_remove(entity.entity_id)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(
    hass: HomeAssistant, entry: IrRemoteConfigEntry
) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: IrRemoteConfigEntry) -> bool:
    """Unload a remote."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: IrRemoteConfigEntry) -> None:
    """Delete the learned codes of a removed remote."""
    await Store(hass, STORAGE_VERSION, storage_key(entry.entry_id)).async_remove()
