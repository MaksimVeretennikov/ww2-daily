"""Central configuration. Values are read from environment variables so the
same code runs locally (with a .env you export yourself) and inside the cloud
routine (where they come from the environment settings)."""

import os

# --- Channel / cadence -------------------------------------------------------

# How many years back the "on this day" anchor points. The channel posts what
# happened exactly this many years ago.
YEARS_BACK = 85

# Timezone the channel's audience lives in. All date math is anchored here.
TIMEZONE = "Europe/Moscow"

TELEGRAM_CHANNEL = os.environ.get("TELEGRAM_CHANNEL", "@ww2_dnevnik")

# --- Length targets ----------------------------------------------------------

# Telegram photo captions are hard-capped at 1024 characters. We send the photo
# caption (short description) plus the post body in a single message, so the two
# together must stay under the cap. Targets below leave headroom.
TG_CAPTION_TARGET = 150        # russian one-line description of the photo
TG_POST_TARGET = 850           # russian post body
TG_CAPTION_HARD_CAP = 1024     # Telegram limit for a photo caption

X_POST_TARGET = 260            # english short post for X

# --- Photo selection ---------------------------------------------------------

# Reject images whose original date is clearly post-war (keeps archival look).
PHOTO_MAX_YEAR = 1950
# How many Commons candidates to keep for Claude to choose from.
PHOTO_CANDIDATES = 8

# --- History / context -------------------------------------------------------

# How many recent posts to feed back as context so topics don't repeat and the
# tone stays varied.
HISTORY_CONTEXT_POSTS = 30

# Path to the persistent state file (relative to repo root).
STATE_PATH = os.environ.get("STATE_PATH", "state/history.json")

# --- Flags -------------------------------------------------------------------

def _flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")

DRY_RUN = _flag("DRY_RUN")
X_ENABLED = _flag("X_ENABLED")

# --- Secrets (read lazily by the modules that need them) ---------------------

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

X_CREDENTIALS = {
    "api_key": os.environ.get("X_API_KEY", ""),
    "api_secret": os.environ.get("X_API_SECRET", ""),
    "access_token": os.environ.get("X_ACCESS_TOKEN", ""),
    "access_token_secret": os.environ.get("X_ACCESS_TOKEN_SECRET", ""),
    "bearer_token": os.environ.get("X_BEARER_TOKEN", ""),
}

# --- HTTP --------------------------------------------------------------------

# A descriptive User-Agent is required by Wikimedia APIs and is good manners
# everywhere else.
USER_AGENT = (
    "WW2DailyBot/1.0 (https://t.me/ww2_dnevnik; daily WW2 history channel)"
)
HTTP_TIMEOUT = 30
