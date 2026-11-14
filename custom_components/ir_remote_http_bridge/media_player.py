"""Media player entity: on/off and volume keys for voice assistants."""

from __future__ import annotations

from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
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
    """Create the media player declared in the remote definition."""
    bridge: RemoteBridge = entry.runtime_data
    if bridge.definition.media_player:
        async_add_entities([IrRemoteMediaPlayer(bridge, bridge.definition.media_player)])


class IrRemoteMediaPlayer(MediaPlayerEntity, RestoreEntity):
    """Maps power and volume services to remote buttons.

    Named like the remote, so "turn <remote> on" and "<remote> louder" work.
    IR is one-way: the state is only what was sent last.
    """

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False
    _attr_assumed_state = True

    def __init__(self, bridge: RemoteBridge, config: dict[str, Any]) -> None:
        self._bridge = bridge
        self._buttons = config
        entry_id = bridge.entry.entry_id
        self._attr_unique_id = f"{entry_id}_media_player"
        self._attr_device_class = MediaPlayerDeviceClass(config["device_class"])
        self._attr_icon = config.get("icon")
        self._attr_state = MediaPlayerState.OFF if "on" in config else MediaPlayerState.ON
        features = MediaPlayerEntityFeature(0)
        if "on" in config:
            features |= (
                MediaPlayerEntityFeature.TURN_ON | MediaPlayerEntityFeature.TURN_OFF
            )
        if "volume_up" in config:
            features |= MediaPlayerEntityFeature.VOLUME_STEP
        if "mute" in config:
            features |= MediaPlayerEntityFeature.VOLUME_MUTE
        self._attr_supported_features = features
        self._attr_is_volume_muted = False if "mute" in config else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=bridge.entry.title,
            manufacturer=bridge.definition.manufacturer,
            model=bridge.definition.model or bridge.definition.name,
        )

    @property
    def available(self) -> bool:
        """At least one of the mapped buttons must be learned."""
        return any(
            button in self._bridge.codes
            for key, button in self._buttons.items()
            if key not in ("device_class", "icon")
        )

    async def async_added_to_hass(self) -> None:
        """Restore the last sent state and follow learn/forget changes."""
        last = await self.async_get_last_state()
        if last is not None and "on" in self._buttons:
            if last.state in (MediaPlayerState.ON, MediaPlayerState.OFF):
                self._attr_state = MediaPlayerState(last.state)
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_updated(self._bridge.entry.entry_id),
                self.async_write_ha_state,
            )
        )

    async def async_turn_on(self) -> None:
        """Send the "on" button."""
        await self._bridge.async_send(self._buttons["on"])
        self._attr_state = MediaPlayerState.ON
        self.async_write_ha_state()

    async def async_turn_off(self) -> None:
        """Send the "off" button."""
        await self._bridge.async_send(self._buttons["off"])
        self._attr_state = MediaPlayerState.OFF
        self.async_write_ha_state()

    async def async_volume_up(self) -> None:
        """Send the "volume up" button."""
        await self._bridge.async_send(self._buttons["volume_up"])

    async def async_volume_down(self) -> None:
        """Send the "volume down" button."""
        await self._bridge.async_send(self._buttons["volume_down"])

    async def async_mute_volume(self, mute: bool) -> None:
        """Send the mute toggle button."""
        await self._bridge.async_send(self._buttons["mute"])
        self._attr_is_volume_muted = mute
        self.async_write_ha_state()
