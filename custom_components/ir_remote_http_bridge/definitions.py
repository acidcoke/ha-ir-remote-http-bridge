"""Remote definitions: a JSON description plus an SVG drawing per remote."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
import re
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant

from .const import USER_REMOTES_DIR

_LOGGER = logging.getLogger(__name__)

BUILTIN_DIR = Path(__file__).parent / "remotes"

_ID = vol.All(str, vol.Match(r"^[a-z0-9][a-z0-9_]*$"))

DEFINITION_SCHEMA = vol.Schema(
    {
        vol.Optional("id"): _ID,
        vol.Required("name"): vol.All(str, vol.Length(min=1)),
        vol.Optional("manufacturer"): str,
        vol.Optional("model"): str,
        vol.Optional("svg"): str,
        vol.Required("buttons"): vol.All(
            [
                vol.Schema(
                    {
                        vol.Required("id"): _ID,
                        vol.Required("name"): vol.All(str, vol.Length(min=1)),
                        vol.Optional("icon"): str,
                    }
                )
            ],
            vol.Length(min=1),
        ),
        # On/off entities for voice assistants. "on" and "off" are button ids;
        # use the same id twice for a remote with a single power toggle key.
        vol.Optional("switches", default=list): [
            vol.Schema(
                {
                    vol.Required("id"): _ID,
                    vol.Optional("name"): str,
                    vol.Optional("icon"): str,
                    vol.Required("on"): _ID,
                    vol.Required("off"): _ID,
                }
            )
        ],
        # A media player entity so voice assistants understand "louder",
        # "quieter", "mute" and on/off. All values are button ids.
        vol.Optional("media_player"): vol.Schema(
            {
                vol.Optional("device_class", default="tv"): vol.In(
                    ["tv", "speaker", "receiver"]
                ),
                vol.Optional("icon"): str,
                vol.Optional("on"): _ID,
                vol.Optional("off"): _ID,
                vol.Optional("volume_up"): _ID,
                vol.Optional("volume_down"): _ID,
                vol.Optional("mute"): _ID,
            }
        ),
    }
)

MEDIA_PLAYER_BUTTON_KEYS = ("on", "off", "volume_up", "volume_down", "mute")


@dataclass(frozen=True)
class RemoteDefinition:
    """A remote control layout."""

    id: str
    name: str
    manufacturer: str | None
    model: str | None
    buttons: tuple[dict[str, Any], ...]
    switches: tuple[dict[str, Any], ...]
    media_player: dict[str, Any] | None
    svg: str
    builtin: bool

    @property
    def button_ids(self) -> list[str]:
        """Return the ids of all buttons."""
        return [button["id"] for button in self.buttons]

    def button_name(self, button_id: str) -> str:
        """Return the display name of a button."""
        for button in self.buttons:
            if button["id"] == button_id:
                return button["name"]
        return button_id


def _load_file(json_path: Path, builtin: bool) -> RemoteDefinition:
    data = DEFINITION_SCHEMA(json.loads(json_path.read_text(encoding="utf-8")))
    definition_id = data.get("id", json_path.stem.lower())
    _ID(definition_id)

    button_ids = [button["id"] for button in data["buttons"]]
    if len(set(button_ids)) != len(button_ids):
        raise ValueError("duplicate button ids")

    switch_ids = [switch["id"] for switch in data["switches"]]
    if len(set(switch_ids)) != len(switch_ids):
        raise ValueError("duplicate switch ids")
    for switch in data["switches"]:
        for key in ("on", "off"):
            if switch[key] not in button_ids:
                raise ValueError(
                    f"switch '{switch['id']}' refers to unknown button '{switch[key]}'"
                )

    media_player = data.get("media_player")
    for key in MEDIA_PLAYER_BUTTON_KEYS:
        if media_player and key in media_player and media_player[key] not in button_ids:
            raise ValueError(
                f"media_player refers to unknown button '{media_player[key]}'"
            )
    if media_player and ("on" in media_player) != ("off" in media_player):
        raise ValueError("media_player needs both 'on' and 'off' or neither")
    if media_player and ("volume_up" in media_player) != ("volume_down" in media_player):
        raise ValueError("media_player needs both 'volume_up' and 'volume_down'")

    svg_path = (json_path.parent / data.get("svg", f"{json_path.stem}.svg")).resolve()
    if json_path.parent.resolve() not in svg_path.parents:
        raise ValueError("the SVG file must be in the same folder as the JSON file")
    svg = svg_path.read_text(encoding="utf-8")
    # Drop XML prolog/doctype so the drawing can be inlined into the card.
    svg = svg[max(svg.find("<svg"), 0) :]

    for button_id in button_ids:
        if not re.search(rf"data-button\s*=\s*[\"']{button_id}[\"']", svg):
            _LOGGER.warning(
                "Remote %s: button '%s' has no data-button element in %s",
                definition_id,
                button_id,
                svg_path.name,
            )

    return RemoteDefinition(
        id=definition_id,
        name=data["name"],
        manufacturer=data.get("manufacturer"),
        model=data.get("model"),
        buttons=tuple(data["buttons"]),
        switches=tuple(data["switches"]),
        media_player=media_player,
        svg=svg,
        builtin=builtin,
    )


def load_definitions(user_dir: Path) -> dict[str, RemoteDefinition]:
    """Load built-in and user remotes (blocking). User remotes win on same id."""
    definitions: dict[str, RemoteDefinition] = {}
    for directory, builtin in ((BUILTIN_DIR, True), (user_dir, False)):
        if not directory.is_dir():
            continue
        for json_path in sorted(directory.glob("*.json")):
            try:
                definition = _load_file(json_path, builtin)
            except (OSError, ValueError, vol.Invalid) as err:
                _LOGGER.error("Invalid remote definition %s: %s", json_path, err)
                continue
            definitions[definition.id] = definition
    return definitions


async def async_load_definitions(hass: HomeAssistant) -> dict[str, RemoteDefinition]:
    """Load all remote definitions."""
    user_dir = Path(hass.config.path(USER_REMOTES_DIR))
    return await hass.async_add_executor_job(load_definitions, user_dir)
