import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _int(name, default):
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()

APPROVAL_MODE = _bool("APPROVAL_MODE", False)
INTERVAL_SECONDS = max(30, _int("INTERVAL_SECONDS", 120))
MAX_ARTICLES_PER_FEED = _int("MAX_ARTICLES_PER_FEED", 15)
MAX_POSTS_PER_CYCLE = _int("MAX_POSTS_PER_CYCLE", 5)
MAX_ARTICLE_AGE_HOURS = _int("MAX_ARTICLE_AGE_HOURS", 3)
MAX_ATTEMPTS = _int("MAX_ATTEMPTS", 3)
POST_DELAY_SECONDS = _int("POST_DELAY_SECONDS", 4)
MAX_BODY_LINES = 35
DB_PATH = os.getenv("DB_PATH", "newsil.db")

CREDIT = "כתבי News IL בשטח ומעדכנים"
BUTTON_TEXT = "📰 לכתבה המלאה"
BUTTON_STYLE = os.getenv("BUTTON_STYLE", "primary").strip()

DEFAULT_FEEDS = [
    # === חדשות ישראליות ===
    "https://www.ynet.co.il/Integration/StoryRss2.xml",
    "https://rss.walla.co.il/feed/1",
    "https://www.maariv.co.il/Rss/RssFeedsMivzakim",
    "https://www.israelhayom.co.il/rss.xml",

    # === בינה מלאכותית פורצת דרך ===
    "https://openai.com/news/rss.xml",
    "https://deepmind.google/blog/rss.xml",
    "https://huggingface.co/blog/feed.xml",
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "https://www.technologyreview.com/topic/artificial-intelligence/feed/",

    # === מחקרים + מדע קיצוני ===
    "https://www.nature.com/nature.rss",
    "https://www.sciencedaily.com/rss/all.xml",
    "https://phys.org/rss-feed/",
    "https://www.sciencealert.com/feed",
    "https://www.newscientist.com/feed/",

    # === אסונות, רעידות אדמה, אירועים קיצוניים בעולם ===
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_week.atom",
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.atom",
    "https://watchers.news/feed/",
    "https://www.sciencedaily.com/rss/earth_climate.xml",
    "https://phys.org/rss-feed/earth-news/",
    "https://reliefweb.int/updates/rss.xml",
]
FEEDS = [f.strip() for f in os.getenv("FEEDS", "").split(",") if f.strip()] or DEFAULT_FEEDS


def validate():
    missing = []
    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHANNEL_ID", "GEMINI_API_KEY"):
        if not globals()[name]:
            missing.append(name)
    if APPROVAL_MODE and not ADMIN_CHAT_ID:
        missing.append("ADMIN_CHAT_ID (נדרש כש-APPROVAL_MODE=true)")
    return missing
