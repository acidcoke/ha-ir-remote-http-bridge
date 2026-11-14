"""Constants for the IR Remote HTTP Bridge integration."""

from homeassistant.const import Platform

DOMAIN = "ir_remote_http_bridge"
PLATFORMS = [Platform.BUTTON, Platform.MEDIA_PLAYER, Platform.SWITCH]

CONF_BASE_URL = "base_url"
CONF_ACCESS_TOKEN = "access_token"
CONF_DEVICE_ID = "device_id"
CONF_DEVICE_LABEL = "device_label"
CONF_DEFINITION = "definition"
CONF_CARD = "card"
CONF_SEND_MODE = "send_mode"
CONF_LEARN_TIMEOUT = "learn_timeout"

# How a learned code is transmitted through the Hubitat driver:
#   name: sendCode(<name>) - the driver looks the code up in its own state.
#   code: sendCode(<base64>) - the code stored in Home Assistant is sent.
SEND_MODE_NAME = "name"
SEND_MODE_CODE = "code"
DEFAULT_SEND_MODE = SEND_MODE_NAME
DEFAULT_LEARN_TIMEOUT = 30

LEARN_POLL_INTERVAL = 1.0
# Pause between two transmissions so repeated commands ("volume up by 5")
# do not overrun the blaster.
SEND_GAP = 0.4

# Folder inside the Home Assistant config directory for user supplied remotes.
USER_REMOTES_DIR = DOMAIN

FRONTEND_URL = f"/{DOMAIN}/ir-remote-card.js"
