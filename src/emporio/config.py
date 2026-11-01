"""Every setting in one place, read from the environment."""
import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "var"))

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-flash")
LLM_API_KEY = os.environ.get("LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY", "")
# live = call the provider · record = answer from the recordings, pay only for new requests · replay = recordings only
LLM_MODE = os.environ.get("LLM_MODE", "live")

MAX_OUTPUT_TOKENS = 700
MAX_TOOL_ROUNDS = 6
MAX_MESSAGE_CHARS = 800
HISTORY_MESSAGES = 12

# US$ per million tokens, DeepSeek Flash peak price (the worst case, so the budget is conservative)
PRICE_INPUT_CACHED = 0.006
PRICE_INPUT_MISS = 0.30
PRICE_OUTPUT = 1.20

# With a token set, the site opens only through its private link. Empty (the default) keeps a local run open.
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN", "")

DAILY_BUDGET_USD = float(os.environ.get("DAILY_BUDGET_USD", "1.0"))
RATE_LIMIT_MESSAGES = int(os.environ.get("RATE_LIMIT_MESSAGES", "20"))
RATE_LIMIT_WINDOW_SECONDS = 600

STORE_TZ = ZoneInfo("America/Campo_Grande")
# The dataset is a snapshot: its latest order is 2026-03-22. Order age is measured against this date, while
# opening hours use the real clock. See "Assumptions" in the README.
DATA_AS_OF = date.fromisoformat(os.environ.get("DATA_AS_OF", "2026-03-25"))


def now() -> datetime:
    """Store time. FIXED_NOW freezes it in tests: a clock in the prompt would make every recording useless."""
    fixed = os.environ.get("FIXED_NOW")
    return datetime.fromisoformat(fixed).replace(tzinfo=STORE_TZ) if fixed else datetime.now(STORE_TZ)
