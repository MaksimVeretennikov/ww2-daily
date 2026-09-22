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

# --- Poll (Telegram quiz) ----------------------------------------------------

# Telegram sendPoll limits (quiz mode). We validate against these before posting.
POLL_QUESTION_MAX = 300
POLL_OPTION_MAX = 100
POLL_EXPLANATION_MAX = 200
# How many recent polls to show the model so it doesn't repeat itself.
POLL_HISTORY_CONTEXT = 40

# --- Photo selection ---------------------------------------------------------

# Reject images whose original date is clearly post-war (keeps archival look).
PHOTO_MAX_YEAR = 1950
# How many Commons candidates to keep for Claude to choose from.
PHOTO_CANDIDATES = 8
# Width of the thumbnail we ask Commons for — and the file we actually publish.
# Wikimedia serves a fixed set of standard widths straight from cache and asks
# bots to use those instead of full-resolution originals (its 429 responses say
# so outright). 1280 is such a standard width, and Telegram downscales anything
# wider anyway, so the original buys us nothing but throttling.
PHOTO_THUMB_WIDTH = 1280
# Narrower fallback width, tried when a service refuses the default thumbnail —
# Telegram will not fetch a file larger than 5 MB from a URL.
PHOTO_FALLBACK_WIDTH = 800

# --- History / context -------------------------------------------------------

# How many recent posts to feed back as context so topics don't repeat and the
# tone stays varied.
HISTORY_CONTEXT_POSTS = 30

# Path to the persistent state file (relative to repo root).
STATE_PATH = os.environ.get("STATE_PATH", "state/history.json")
# Poll history lives in its own file so it doesn't bloat the post history.
POLLS_PATH = os.environ.get("POLLS_PATH", "state/polls.json")

# --- Flags -------------------------------------------------------------------

def _flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")

DRY_RUN = _flag("DRY_RUN")
X_ENABLED = _flag("X_ENABLED")

# --- Secrets (read lazily by the modules that need them) ---------------------

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

# X cross-post via the user's Buffer, through a tiny make.com webhook
# (Webhook -> Buffer Create Status with media). Empty = disabled.
BUFFER_WEBHOOK_URL = os.environ.get("BUFFER_WEBHOOK_URL", "")

# VK cross-post to a community you own. Needs a USER access token with scopes
# wall,photos,groups,offline (community tokens can't upload wall photos).
VK_ACCESS_TOKEN = os.environ.get("VK_ACCESS_TOKEN", "")
VK_GROUP_ID = os.environ.get("VK_GROUP_ID", "")   # numeric community id (positive)
VK_FOOTER = os.environ.get("VK_FOOTER", "")        # e.g. a link back to Telegram
VK_API_VERSION = "5.199"
# VK has no quiz polls: the daily quiz goes out as a plain poll that closes
# after this many hours (0 = never), and the answer is revealed the next day
# as a community comment under the poll post.
VK_POLL_HOURS = int(os.environ.get("VK_POLL_HOURS", "24") or 0)
# What to mirror: "all" (posts, rubrics and the quiz) or "polls" (the quiz
# only — for when an external Telegram→VK crossposter already copies the
# posts with their photos and a second copy would be a duplicate).
VK_MIRROR = os.environ.get("VK_MIRROR", "all").strip().lower() or "all"

X_CREDENTIALS = {
    "api_key": os.environ.get("X_API_KEY", ""),
    "api_secret": os.environ.get("X_API_SECRET", ""),
    "access_token": os.environ.get("X_ACCESS_TOKEN", ""),
    "access_token_secret": os.environ.get("X_ACCESS_TOKEN_SECRET", ""),
    "bearer_token": os.environ.get("X_BEARER_TOKEN", ""),
}

# --- RSS feed (VK import, Дзен) ---------------------------------------------

# Served by GitHub Pages from docs/ (Settings → Pages → branch main, /docs).
FEED_BASE_URL = os.environ.get(
    "FEED_BASE_URL", "https://maksimveretennikov.github.io/ww2-daily/")
FEED_PATH = os.environ.get("FEED_PATH", "docs/feed.xml")
FEED_IMG_DIR = os.path.join(os.path.dirname(FEED_PATH), "img")
FEED_TITLE = "Дневник Второй Мировой"
FEED_DESCRIPTION = "Что происходило во Второй мировой ровно 85 лет назад — каждый день"
FEED_LINK = "https://t.me/ww2_dnevnik"      # where an imported item points to
FEED_MAX_ITEMS = 30

# --- HTTP --------------------------------------------------------------------

# A descriptive User-Agent is required by Wikimedia APIs and is good manners
# everywhere else.
USER_AGENT = (
    "WW2DailyBot/1.0 (https://t.me/ww2_dnevnik; daily WW2 history channel)"
)
HTTP_TIMEOUT = 30

# Retries for rate-limited / transient failures (see http.py). Wikimedia
# throttles the shared egress IP of cloud sessions in short bursts, so a few
# backed-off attempts are the difference between a photo and a text-only post.
HTTP_RETRIES = 4            # extra attempts after the first one
HTTP_BACKOFF = 2            # seconds before the first retry, doubled after each
HTTP_RETRY_MAX_WAIT = 20    # cap per wait: Retry-After asks for 600, which a
                            # run fetching a dozen images cannot sit out
HTTP_RETRY_BUDGET = 150     # total seconds a single run may spend waiting, so
                            # a long throttling window can't stall the routine
