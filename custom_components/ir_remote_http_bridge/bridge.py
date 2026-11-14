"""Runtime object of one configured remote."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from .api import MakerApiClient, MakerApiError, device_attribute
from .const import (
    CONF_BASE_URL,
    CONF_DEVICE_ID,
    CONF_LEARN_TIMEOUT,
    CONF_SEND_MODE,
    DEFAULT_LEARN_TIMEOUT,
    DEFAULT_SEND_MODE,
    DOMAIN,
    LEARN_POLL_INTERVAL,
    SEND_GAP,
    SEND_MODE_CODE,
)
from .definitions import RemoteDefinition

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1


class BridgeBusy(HomeAssistantError):
    """The IR blaster is currently learning a code."""


class LearnTimeout(HomeAssistantError):
    """No IR code was received in time."""


class NotLearned(HomeAssistantError):
    """The button has no code yet."""


def signal_updated(entry_id: str) -> str:
    """Dispatcher signal sent when the state of a remote changed."""
    return f"{DOMAIN}_{entry_id}_updated"


def storage_key(entry_id: str) -> str:
    """Storage key of the learned codes of a remote."""
    return f"{DOMAIN}.{entry_id}"


class RemoteBridge:
    """One remote: its layout, its learned codes and the blaster it uses."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: MakerApiClient,
        definition: RemoteDefinition,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.client = client
        self.definition = definition
        self.device_id: str = str(entry.data[CONF_DEVICE_ID])
        self.codes: dict[str, str] = {}
        self.learning: str | None = None
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, storage_key(entry.entry_id)
        )
        # A blaster can only learn one code at a time, no matter how many
        # remotes share it.
        locks = hass.data.setdefault(DOMAIN, {}).setdefault("locks", {})
        key = (entry.data[CONF_BASE_URL], self.device_id)
        self._lock: asyncio.Lock = locks.setdefault(key, asyncio.Lock())
        # Transmissions of one blaster are sent one after the other.
        self._send_lock: asyncio.Lock = locks.setdefault(
            (*key, "send"), asyncio.Lock()
        )

    @property
    def learn_timeout(self) -> int:
        """Seconds to wait for an IR code while learning."""
        return int(self.entry.options.get(CONF_LEARN_TIMEOUT, DEFAULT_LEARN_TIMEOUT))

    async def async_load(self) -> None:
        """Load the learned codes from disk."""
        data = await self._store.async_load() or {}
        self.codes = {
            button: code
            for button, code in (data.get("codes") or {}).items()
            if isinstance(code, str)
        }

    def code_name(self, button_id: str) -> str:
        """Name under which the Hubitat driver keeps the code of a button."""
        return f"ha_{self.entry.entry_id[-8:].lower()}_{button_id}"

    def state(self) -> dict[str, Any]:
        """State pushed to the dashboard cards."""
        return {
            "learned": [b for b in self.definition.button_ids if b in self.codes],
            "learning": self.learning,
            "learn_timeout": self.learn_timeout,
        }

    @callback
    def _notify(self) -> None:
        async_dispatcher_send(self.hass, signal_updated(self.entry.entry_id))

    def _check_button(self, button_id: str) -> None:
        if button_id not in self.definition.button_ids:
            raise HomeAssistantError(f"Unknown button '{button_id}'")

    async def _async_last_learned_code(self) -> str | None:
        device = await self.client.async_get_device(self.device_id)
        value = device_attribute(device, "lastLearnedCode")
        if not isinstance(value, str):
            return None
        # The driver wraps the attribute every 25 characters.
        return re.sub(r"\s+", "", value) or None

    async def async_learn(self, button_id: str) -> str:
        """Put the blaster into learn mode and store the received code."""
        self._check_button(button_id)
        if self._lock.locked():
            raise BridgeBusy("The IR blaster is already learning a code")

        async with self._lock:
            self.learning = button_id
            self._notify()
            try:
                before = await self._async_last_learned_code()
                await self.client.async_command(
                    self.device_id, "learn", self.code_name(button_id)
                )
                deadline = time.monotonic() + self.learn_timeout
                while time.monotonic() < deadline:
                    await asyncio.sleep(LEARN_POLL_INTERVAL)
                    try:
                        code = await self._async_last_learned_code()
                    except MakerApiError as err:
                        _LOGGER.debug("Polling for learned code failed: %s", err)
                        continue
                    if code and code != before:
                        self.codes[button_id] = code
                        await self._store.async_save({"codes": self.codes})
                        return code
                raise LearnTimeout(
                    f"No IR code received within {self.learn_timeout} seconds"
                )
            finally:
                self.learning = None
                self._notify()

    async def async_send(self, button_id: str) -> None:
        """Transmit the code of a button."""
        self._check_button(button_id)
        code = self.codes.get(button_id)
        if code is None:
            raise NotLearned(
                f"Button '{self.definition.button_name(button_id)}' has no code yet"
            )
        if self._lock.locked():
            raise BridgeBusy("The IR blaster is currently learning a code")
        mode = self.entry.options.get(CONF_SEND_MODE, DEFAULT_SEND_MODE)
        value = code if mode == SEND_MODE_CODE else self.code_name(button_id)
        async with self._send_lock:
            await self.client.async_command(self.device_id, "sendCode", value)
            await asyncio.sleep(SEND_GAP)

    async def async_forget(self, button_id: str) -> None:
        """Delete the code of a button."""
        self._check_button(button_id)
        if self.codes.pop(button_id, None) is None:
            return
        await self._store.async_save({"codes": self.codes})
        self._notify()
        try:
            await self.client.async_command(
                self.device_id, "forgetCode", self.code_name(button_id)
            )
        except MakerApiError as err:
            _LOGGER.debug("Could not remove code from the Hubitat driver: %s", err)
