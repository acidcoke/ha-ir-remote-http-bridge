"""Minimal client for the Hubitat Maker API."""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

import aiohttp
from yarl import URL

from homeassistant.exceptions import HomeAssistantError

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)

_BASE_URL_RE = re.compile(r"^(https?://[^?#\s]+?/apps/(?:api/)?\d+)(?:[/?#]|$)", re.I)


class MakerApiError(HomeAssistantError):
    """The Maker API could not be reached or returned an error."""


class MakerApiAuthError(MakerApiError):
    """The Maker API rejected the access token."""


def parse_maker_url(url: str, token: str | None = None) -> tuple[str, str | None]:
    """Split any Maker API URL into (base URL, access token).

    Accepts the example URLs shown by the Maker API app, e.g.
    ``http://192.168.1.5/apps/api/38/devices?access_token=abc`` as well as the
    cloud form ``https://cloud.hubitat.com/api/<hub>/apps/38/...``.
    """
    url = url.strip()
    match = _BASE_URL_RE.match(url)
    if not match:
        raise ValueError("not a Maker API URL")
    if not token:
        token = (parse_qs(urlsplit(url).query).get("access_token") or [None])[0]
    return match.group(1), (token.strip() if token else None)


def device_commands(device: dict[str, Any]) -> set[str]:
    """Return the command names of a Maker API device object."""
    commands = set()
    for command in device.get("commands") or []:
        if isinstance(command, dict):
            command = command.get("command")
        if isinstance(command, str):
            commands.add(command)
    return commands


def device_attribute(device: dict[str, Any], name: str) -> Any:
    """Return the current value of an attribute of a Maker API device object."""
    attributes = device.get("attributes")
    if isinstance(attributes, dict):
        return attributes.get(name)
    for attribute in attributes or []:
        if isinstance(attribute, dict) and attribute.get("name") == name:
            return attribute.get("currentValue")
    return None


class MakerApiClient:
    """Talks to one Maker API app instance."""

    def __init__(
        self, session: aiohttp.ClientSession, base_url: str, access_token: str
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._token = access_token

    async def _get(self, *segments: str) -> Any:
        # Every segment is fully percent-encoded (IR codes contain / + =), and
        # yarl is told not to touch that encoding again.
        path = "/".join(quote(str(segment), safe="") for segment in segments)
        url = URL(
            f"{self._base_url}/{path}?access_token={quote(self._token, safe='')}",
            encoded=True,
        )
        try:
            async with self._session.get(url, timeout=REQUEST_TIMEOUT) as resp:
                if resp.status in (401, 403):
                    raise MakerApiAuthError("Maker API rejected the access token")
                if resp.status >= 400:
                    raise MakerApiError(f"Maker API returned HTTP {resp.status}")
                try:
                    return await resp.json(content_type=None)
                except ValueError:
                    return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            # Never include the URL: it carries the access token.
            raise MakerApiError(
                f"Cannot reach the Maker API ({type(err).__name__})"
            ) from None

    async def async_list_devices(self) -> list[dict[str, Any]]:
        """Return all devices exposed by the Maker API app, with commands."""
        result = await self._get("devices", "all")
        if not isinstance(result, list):
            raise MakerApiError("Unexpected answer from the Maker API")
        return [device for device in result if isinstance(device, dict)]

    async def async_get_device(self, device_id: str) -> dict[str, Any]:
        """Return a single device with its current attributes."""
        result = await self._get("devices", device_id)
        if not isinstance(result, dict):
            raise MakerApiError("Unexpected answer from the Maker API")
        return result

    async def async_command(
        self, device_id: str, command: str, value: str | None = None
    ) -> None:
        """Run a device command, optionally with one parameter."""
        segments = ["devices", device_id, command]
        if value is not None:
            segments.append(value)
        await self._get(*segments)
