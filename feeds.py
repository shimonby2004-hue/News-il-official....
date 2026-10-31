import hashlib
import html
import logging
import re
import time
from calendar import timegm
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import requests

import config

log = logging.getLogger("newsil.feeds")

TAG_RE = re.compile(r"<[^>]+>")
IMG_RE = re.compile(r"<img[^>]+?src=[\"']([^\"']+)[\"']", re.I)
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")
UA = {"User-Agent": "Mozilla/5.0 (compatible; NewsIL-Bot/1.0)"}

# סטטוס אחרון של כל פיד (לצורך /status)
FEED_STATUS = {}


@dataclass
class Article:
    id: str
    title: str
    summary: str
    link: str
    source: str
    published: Optional[float]
    image: Optional[str]
    video: Optional[str]


def normalize_url(url):
    p = urlsplit(url.strip())
    q = [(k, v) for k, v in parse_qsl(p.query) if not (k.startswith("utm_") or k in {"fbclid", "gclid"})]
    return urlunsplit((p.scheme, p.netloc.lower(), p.path.rstrip("/"), urlencode(q), ""))


def make_id(url):
    return hashlib.sha1(normalize_url(url).encode()).hexdigest()[:16]


def strip_html(s):
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", s or ""))).strip()


def _ext(url):
    return url.lower().split("?")[0]


def _is_image(url, typ=""):
    return typ.startswith("image") or _ext(url).endswith(IMG_EXT)


def _is_video(url, typ=""):
    return typ == "video/mp4" or _ext(url).endswith(".mp4")


def _extract_media(entry):
    image = video = None
    cands = []  # (url, type)
    for m in entry.get("media_content") or []:
        cands.append((m.get("url", ""), m.get("type") or m.get("medium") or ""))
    for m in entry.get("media_thumbnail") or []:
        cands.append((m.get("url", ""), "image"))
    for e in entry.get("enclosures") or []:
        cands.append((e.get("href") or e.get("url", ""), e.get("type", "")))
    for l in entry.get("links") or []:
        if l.get("rel") == "enclosure":
            cands.append((l.get("href", ""), l.get("type", "")))

    for url, typ in cands:
        if not url.startswith("http"):
            continue
        if not video and _is_video(url, typ):
            video = url
        elif not image and _is_image(url, typ):
            image = url

    if not image:  # תמונה בתוך גוף הכתבה
        body = " ".join(c.get("value", "") for c in entry.get("content") or [])
        body += " " + (entry.get("summary") or entry.get("description") or "")
        for url in IMG_RE.findall(body):
            if url.startswith("http") and not re.search(r"pixel|1x1|tracking|spacer", url, re.I):
                image = url
                break
    return image, video


def fetch_feed(url):
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()
    parsed = feedparser.parse(r.content)
    source = (parsed.feed.get("title") or urlsplit(url).netloc).strip()
    out = []
    for e in parsed.entries[: config.MAX_ARTICLES_PER_FEED]:
        link = e.get("link")
        title = strip_html(e.get("title", ""))
        if not link or not title:
            continue
        summary = strip_html(e.get("summary") or e.get("description") or "")
        if not summary and e.get("content"):
            summary = strip_html(e["content"][0].get("value", ""))
        ts = e.get("published_parsed") or e.get("updated_parsed")
        image, video = _extract_media(e)
        out.append(
            Article(
                id=make_id(link), title=title, summary=summary, link=link, source=source,
                published=float(timegm(ts)) if ts else None, image=image, video=video,
            )
        )
    return out


def collect_articles():
    """כל פיד מטופל בנפרד - תקלה באחד לא מפילה את הסבב."""
    all_articles = []
    for url in config.FEEDS:
        try:
            items = fetch_feed(url)
            FEED_STATUS[url] = f"✅ {len(items)}"
            log.info("feed ok: %s (%d)", url, len(items))
            all_articles.extend(items)
        except Exception as exc:
            FEED_STATUS[url] = f"❌ {str(exc)[:40]}"
            log.warning("feed failed: %s (%s)", url, exc)
    return all_articles


def _tokens(title):
    return {w for w in re.findall(r"\w+", title.lower()) if len(w) > 2}


def is_duplicate(title, known_titles, threshold=0.6):
    a = _tokens(title)
    if not a:
        return False
    for other in known_titles:
        b = _tokens(other)
        if b and len(a & b) / len(a | b) >= threshold:
            return True
    return False


def age_ok(article):
    if article.published is None:
        return True
    return time.time() - article.published <= config.MAX_ARTICLE_AGE_HOURS * 3600
