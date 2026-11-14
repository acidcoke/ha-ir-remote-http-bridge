"""Config flow: Maker API connection -> IR blaster -> remote layout."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from homeassistant.util import slugify

from .api import (
    MakerApiAuthError,
    MakerApiClient,
    MakerApiError,
    device_commands,
    parse_maker_url,
)
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_BASE_URL,
    CONF_CARD,
    CONF_DEFINITION,
    CONF_DEVICE_ID,
    CONF_DEVICE_LABEL,
    CONF_LEARN_TIMEOUT,
    CONF_SEND_MODE,
    DEFAULT_LEARN_TIMEOUT,
    DEFAULT_SEND_MODE,
    DOMAIN,
    SEND_MODE_CODE,
    SEND_MODE_NAME,
)
from .definitions import async_load_definitions

CONF_URL = "url"
CONF_NAME = "name"

_PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
_URL = TextSelector(TextSelectorConfig(type=TextSelectorType.URL))


def _connection_schema(url: str | None, token: str | None) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_URL, default=url or vol.UNDEFINED): _URL,
            vol.Optional(
                CONF_ACCESS_TOKEN,
                description={"suggested_value": token} if token else None,
            ): _PASSWORD,
        }
    )


class IrRemoteConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a remote control."""

    VERSION = 1

    def __init__(self) -> None:
        self._base_url: str = ""
        self._token: str = ""
        self._devices: dict[str, str] = {}
        self._device_id: str = ""

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return IrRemoteOptionsFlow()

    async def _async_connect(
        self, user_input: dict[str, Any], errors: dict[str, str]
    ) -> list[dict[str, Any]] | None:
        """Validate URL + token, return the device list or fill ``errors``."""
        try:
            base_url, token = parse_maker_url(
                user_input[CONF_URL], user_input.get(CONF_ACCESS_TOKEN)
            )
        except ValueError:
            errors[CONF_URL] = "invalid_url"
            return None
        if not token:
            errors[CONF_ACCESS_TOKEN] = "token_required"
            return None
        client = MakerApiClient(async_get_clientsession(self.hass), base_url, token)
        try:
            devices = await client.async_list_devices()
        except MakerApiAuthError:
            errors["base"] = "invalid_auth"
            return None
        except MakerApiError:
            errors["base"] = "cannot_connect"
            return None
        self._base_url = base_url
        self._token = token
        return devices

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the Maker API URL and access token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            devices = await self._async_connect(user_input, errors)
            if devices is not None:
                # Prefer devices that look like the Tuya IR driver.
                blasters = [
                    d for d in devices if {"learn", "sendCode"} <= device_commands(d)
                ]
                self._devices = {
                    str(d["id"]): str(d.get("label") or d.get("name") or d["id"])
                    for d in (blasters or devices)
                    if "id" in d
                }
                if not self._devices:
                    errors["base"] = "no_devices"
                else:
                    return await self.async_step_device()

        # Reuse the connection of an already configured remote as default.
        url = token = None
        if user_input is not None:
            url = user_input.get(CONF_URL)
            token = user_input.get(CONF_ACCESS_TOKEN)
        elif entries := self._async_current_entries():
            url = entries[-1].data[CONF_BASE_URL]
            token = entries[-1].data[CONF_ACCESS_TOKEN]
        return self.async_show_form(
            step_id="user",
            data_schema=_connection_schema(url, token),
            errors=errors,
        )

    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the IR blaster."""
        if user_input is not None:
            self._device_id = user_input[CONF_DEVICE_ID]
            return await self.async_step_remote()
        if len(self._devices) == 1:
            self._device_id = next(iter(self._devices))
            return await self.async_step_remote()
        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=dev_id, label=label)
                                for dev_id, label in self._devices.items()
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_remote(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the remote layout and a name."""
        definitions = await async_load_definitions(self.hass)
        if not definitions:
            return self.async_abort(reason="no_definitions")

        if user_input is not None:
            definition = definitions[user_input[CONF_DEFINITION]]
            title = (user_input.get(CONF_NAME) or "").strip() or definition.name
            return self.async_create_entry(
                title=title,
                data={
                    CONF_BASE_URL: self._base_url,
                    CONF_ACCESS_TOKEN: self._token,
                    CONF_DEVICE_ID: self._device_id,
                    CONF_DEVICE_LABEL: self._devices.get(self._device_id, ""),
                    CONF_DEFINITION: definition.id,
                    CONF_CARD: self._unique_card_slug(title),
                },
            )

        return self.async_show_form(
            step_id="remote",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEFINITION): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=d.id, label=d.name)
                                for d in definitions.values()
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(CONF_NAME): TextSelector(),
                }
            ),
            description_placeholders={
                "device": self._devices.get(self._device_id, self._device_id)
            },
        )

    def _unique_card_slug(self, title: str) -> str:
        """Stable suffix of the card type (custom:ir-remote-card-<slug>)."""
        base = slugify(title, separator="-") or "remote"
        used = {entry.data.get(CONF_CARD) for entry in self._async_current_entries()}
        slug, index = base, 2
        while slug in used:
            slug, index = f"{base}-{index}", index + 1
        return slug

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the Maker API connection or the blaster of a remote."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            devices = await self._async_connect(user_input, errors)
            if devices is not None:
                device_id = str(user_input[CONF_DEVICE_ID]).strip()
                labels = {
                    str(d.get("id")): str(d.get("label") or d.get("name") or "")
                    for d in devices
                }
                if device_id not in labels:
                    errors[CONF_DEVICE_ID] = "unknown_device"
                else:
                    return self.async_update_reload_and_abort(
                        entry,
                        data_updates={
                            CONF_BASE_URL: self._base_url,
                            CONF_ACCESS_TOKEN: self._token,
                            CONF_DEVICE_ID: device_id,
                            CONF_DEVICE_LABEL: labels[device_id],
                        },
                    )

        current = user_input or {
            CONF_URL: entry.data[CONF_BASE_URL],
            CONF_ACCESS_TOKEN: entry.data[CONF_ACCESS_TOKEN],
            CONF_DEVICE_ID: entry.data[CONF_DEVICE_ID],
        }
        schema = _connection_schema(
            current.get(CONF_URL), current.get(CONF_ACCESS_TOKEN)
        ).extend(
            {
                vol.Required(
                    CONF_DEVICE_ID, default=str(current.get(CONF_DEVICE_ID, ""))
                ): TextSelector()
            }
        )
        return self.async_show_form(
            step_id="reconfigure", data_schema=schema, errors=errors
        )


class IrRemoteOptionsFlow(OptionsFlow):
    """Options of a remote."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit send mode and learn timeout."""
        if user_input is not None:
            user_input[CONF_LEARN_TIMEOUT] = int(user_input[CONF_LEARN_TIMEOUT])
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SEND_MODE,
                        default=options.get(CONF_SEND_MODE, DEFAULT_SEND_MODE),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[SEND_MODE_NAME, SEND_MODE_CODE],
                            translation_key=CONF_SEND_MODE,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                    vol.Required(
                        CONF_LEARN_TIMEOUT,
                        default=options.get(CONF_LEARN_TIMEOUT, DEFAULT_LEARN_TIMEOUT),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=5,
                            max=120,
                            step=1,
                            unit_of_measurement="s",
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )
