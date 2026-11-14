"""Button entities: one per learnable remote button."""

from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .bridge import RemoteBridge, signal_updated
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a button entity for every button of the remote."""
    bridge: RemoteBridge = entry.runtime_data
    async_add_entities(
        IrRemoteButton(bridge, button) for button in bridge.definition.buttons
    )


class IrRemoteButton(ButtonEntity):
    """Sends the IR code of one remote button. Unavailable until learned."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, bridge: RemoteBridge, button: dict[str, Any]) -> None:
        self._bridge = bridge
        self._button_id: str = button["id"]
        entry_id = bridge.entry.entry_id
        self._attr_unique_id = f"{entry_id}_{self._button_id}"
        self._attr_name = button["name"]
        self._attr_icon = button.get("icon")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=bridge.entry.title,
            manufacturer=bridge.definition.manufacturer,
            model=bridge.definition.model or bridge.definition.name,
        )

    @property
    def available(self) -> bool:
        """Only learned buttons can be pressed."""
        return self._button_id in self._bridge.codes

    async def async_added_to_hass(self) -> None:
        """Follow learn/forget changes."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_updated(self._bridge.entry.entry_id),
                self.async_write_ha_state,
            )
        )

    async def async_press(self) -> None:
        """Transmit the code."""
        await self._bridge.async_send(self._button_id)
