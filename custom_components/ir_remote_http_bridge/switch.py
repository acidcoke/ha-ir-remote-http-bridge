"""Switch entities: on/off pairs of remote buttons, e.g. for voice assistants."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .bridge import RemoteBridge, signal_updated
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the switches declared in the remote definition."""
    bridge: RemoteBridge = entry.runtime_data
    async_add_entities(
        IrRemoteSwitch(bridge, switch) for switch in bridge.definition.switches
    )


class IrRemoteSwitch(SwitchEntity, RestoreEntity):
    """Sends one button for "on" and one for "off".

    IR is one-way, so the state is only what was sent last. With a toggle key
    (same button for on and off) it drifts when the original remote is used.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_assumed_state = True

    def __init__(self, bridge: RemoteBridge, switch: dict[str, Any]) -> None:
        self._bridge = bridge
        self._on: str = switch["on"]
        self._off: str = switch["off"]
        entry_id = bridge.entry.entry_id
        self._attr_unique_id = f"{entry_id}_switch_{switch['id']}"
        # Without a name the entity is called like the remote itself, which is
        # what one wants to say to a voice assistant.
        self._attr_name = switch.get("name")
        self._attr_icon = switch.get("icon")
        self._attr_is_on = False
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=bridge.entry.title,
            manufacturer=bridge.definition.manufacturer,
            model=bridge.definition.model or bridge.definition.name,
        )

    @property
    def available(self) -> bool:
        """Both buttons must be learned."""
        return self._on in self._bridge.codes and self._off in self._bridge.codes

    async def async_added_to_hass(self) -> None:
        """Restore the last sent state and follow learn/forget changes."""
        if (last := await self.async_get_last_state()) is not None:
            self._attr_is_on = last.state == STATE_ON
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_updated(self._bridge.entry.entry_id),
                self.async_write_ha_state,
            )
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Send the "on" button."""
        await self._bridge.async_send(self._on)
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Send the "off" button."""
        await self._bridge.async_send(self._off)
        self._attr_is_on = False
        self.async_write_ha_state()
