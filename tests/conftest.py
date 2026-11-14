"""Test fixtures: a fake Hubitat Maker API."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from custom_components.ir_remote_http_bridge.api import MakerApiAuthError

BLASTER = {
    "id": "42",
    "label": "IR Blaster",
    "commands": [{"command": "learn"}, {"command": "sendCode"}],
}
LAMP = {"id": "7", "label": "Lamp", "commands": [{"command": "on"}]}


class FakeHub:
    """Stands in for the hub behind MakerApiClient._get."""

    def __init__(self) -> None:
        self.devices = [BLASTER, LAMP]
        self.last_code = "OLD"
        self.commands: list[tuple[str, ...]] = []
        self.code_on_learn: str | None = "TmV3\nQ29kZQ+/="
        self.valid_token = "tok"

    async def get(self, client, *segments):
        if client._token != self.valid_token:
            raise MakerApiAuthError("bad token")
        if segments == ("devices", "all"):
            return self.devices
        if len(segments) == 2:
            return {
                "id": segments[1],
                "attributes": [
                    {"name": "lastLearnedCode", "currentValue": self.last_code}
                ],
            }
        self.commands.append(tuple(segments[1:]))
        if segments[2] == "learn" and self.code_on_learn:
            self.last_code = self.code_on_learn
        return {}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load the custom integration in every test."""
    return


@pytest.fixture
def hub():
    """Patch the HTTP layer with a fake hub."""
    fake = FakeHub()

    async def _get(self, *segments):
        return await fake.get(self, *segments)

    with (
        patch("custom_components.ir_remote_http_bridge.api.MakerApiClient._get", _get),
        patch("custom_components.ir_remote_http_bridge.bridge.LEARN_POLL_INTERVAL", 0),
    ):
        yield fake
