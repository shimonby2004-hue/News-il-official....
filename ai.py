import html
import json
import logging
import re
import time

import requests

import config

log = logging.getLogger("newsil.ai")

SYSTEM = """אתה העורך הראשי של ערוץ News IL בטלגרם.

הערוץ הזה לא בא להרדים אנשים. הוא בא לתת אקשן.
אנחנו מחפשים: פיתוחים קיצוניים, מחקרים מטלטלים, בינה מלאכותית שפורצת גבולות, אסונות, רעידות אדמה, סופות, שריפות, בלאגן עולמי, תרחישי סיכון ודברים שגורמים לאנשים לעצור ולקרוא.

תקבל כותרת ותקציר של כתבה. תפקידך לנסח ידיעה חדשה בעברית.

כללים:
1. סגנון: חדשותי, דרמטי, חד, עם אנרגיה. תן תחושה שהעולם זז. הדגש את מה שקיצוני / מסוכן / מפתיע / פורץ דרך.
2. מותר לך לסדר את הסיפור יפה, לחזק את הדרמה, ולהפוך אותו לקריא ומעניין. לא חייב להיות יבש או "אובייקטיבי מדי".
3. כותרת: חזקה ומושכת, עד 12 מילים.
4. גוף: עד 35 שורות קצרות. בלי קישורים, בלי כוכביות, בלי Markdown.
5. אל תציין את שם המקור ואל תוסיף קרדיט (הוא מתווסף אוטומטית).
6. relevant=false רק אם זו פרסומת בוטה, תוכן שיווקי ריק, או משהו שלא מכיל שום אירוע/פיתוח אמיתי.
7. emoji: אחד בלבד שמתאים (🚨 אסון/חירום, 🧬 מחקר, 🤖 בינה מלאכותית, 💥 פיתוח קיצוני, 🌍 אקלים/עולם, ⚠️ אזהרה, 🌋 הר געש, 🌊 צונאמי/שיטפון, 🔥 כללי חזק)."""

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "relevant": {"type": "BOOLEAN"},
        "emoji": {"type": "STRING"},
        "headline": {"type": "STRING"},
        "body": {"type": "STRING"},
    },
    "required": ["relevant", "emoji", "headline", "body"],
}

URL_RE = re.compile(r"https?://\S+|www\.\S+")


def _clean_body(text):
    text = URL_RE.sub("", text or "").replace("*", "").replace("`", "")
    lines, blank = [], False
    for raw in text.splitlines():
        line = re.sub(r"^#+\s*", "", raw.strip())
        if not line:
            if lines and not blank:
                lines.append("")
            blank = True
            continue
        blank = False
        lines.append(line)
    while lines and not lines[-1]:
        lines.pop()
    out, count = [], 0
    for line in lines:
        if line:
            count += 1
            if count > config.MAX_BODY_LINES:
                break
        out.append(line)
    return "\n".join(out)


class Overloaded(RuntimeError):
    """Gemini עמוס או חסום זמנית (503/429/רשת). לא נחשב כישלון של הכתבה."""


class _NotFound(Exception):
    pass


class _BadRequest(Exception):
    pass


FALLBACK_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
]
LAST_ERROR = {"text": None, "time": None}
_dead_models = set()
_use_thinking = True

_BASE_CFG = {"responseMimeType": "application/json", "responseSchema": SCHEMA}
_FULL_CFG = {**_BASE_CFG, "thinkingConfig": {"thinkingBudget": 0}}


def _err_text(r):
    try:
        return r.json()["error"]["message"][:150]
    except Exception:
        return r.text[:150]


def _post(model, payload):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {"x-goog-api-key": config.GEMINI_API_KEY, "Content-Type": "application/json"}
    last = None
    for attempt in range(2):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=90)
        except requests.RequestException as exc:
            last = str(exc)[:100]
            time.sleep(3)
            continue
        if r.status_code == 404:
            raise _NotFound(model)
        if r.status_code == 400:
            raise _BadRequest(r.text[:300])
        if r.status_code in (429, 500, 502, 503, 504):
            last = f"HTTP {r.status_code}: {_err_text(r)}"
            time.sleep(3)
            continue
        if not r.ok:
            raise RuntimeError(f"Gemini HTTP {r.status_code}: {r.text[:200]}")
        return r.json()
    raise Overloaded(f"{model}: {last}")


def _generate(base):
    """מנסה את המודל המועדף; אם אינו קיים או עמוס, עובר למודל הבא."""
    global _use_thinking
    models = [m for m in [config.GEMINI_MODEL] + FALLBACK_MODELS if m not in _dead_models]
    models = list(dict.fromkeys(models))
    busy = []
    for model in models:
        cfgs = (_FULL_CFG, _BASE_CFG) if _use_thinking else (_BASE_CFG,)
        for cfg in cfgs:
            try:
                data = _post(model, {**base, "generationConfig": cfg})
            except _NotFound:
                log.warning("מודל %s לא קיים, לא אשתמש בו שוב", model)
                _dead_models.add(model)
                break
            except Overloaded as exc:
                log.warning("מודל עמוס, מנסה את הבא (%s)", exc)
                busy.append(str(exc))
                break
            except _BadRequest as exc:
                if cfg is _FULL_CFG:
                    continue
                raise RuntimeError(f"Gemini דחה את הבקשה: {exc}") from exc
            if cfg is _BASE_CFG:
                _use_thinking = False
            LAST_ERROR["text"] = None
            return data
    if busy:
        LAST_ERROR.update(text="; ".join(busy)[:300], time=time.time())
        raise Overloaded("; ".join(busy))
    raise RuntimeError("אף מודל Gemini לא זמין. הגדר GEMINI_MODEL לשם מודל קיים")


def current_model():
    for m in [config.GEMINI_MODEL] + FALLBACK_MODELS:
        if m not in _dead_models:
            return m
    return "?"


def edit(article):
    """מחזיר dict: relevant, emoji, headline, body."""
    prompt = (
        f"מקור: {article.source}\n"
        f"כותרת: {article.title}\n"
        f"תקציר: {article.summary[:1800] or '(אין תקציר)'}"
    )
    base = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
    }
    data = _generate(base)
    try:
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        res = json.loads(text)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"תשובת Gemini לא תקינה: {exc}") from exc

    headline = URL_RE.sub("", str(res.get("headline", ""))).replace("*", "").strip()
    body = _clean_body(str(res.get("body", "")))
    relevant = bool(res.get("relevant")) and bool(headline) and bool(body)
    return {
        "relevant": relevant,
        "emoji": (res.get("emoji") or "🔥").strip()[:4],
        "headline": headline,
        "body": body,
    }


RLM = "\u200f"  # סימן כיוון ימין-לשמאל


def build_draft(article, edited):
    """עיצוב ההודעה (HTML של טלגרם)."""
    esc = lambda t: html.escape(t, quote=False)
    title = f"{RLM}{edited['emoji']} <b>{esc(edited['headline'])}</b>"
    credit = f"{RLM}📡 <i>{esc(config.CREDIT)}</i>"
    body = esc(edited["body"])

    fixed = len(title) + len(credit) + 8
    if fixed + len(body) > 3900:
        body = body[: 3900 - fixed].rsplit("\n", 1)[0]
    body = "\n".join((RLM + ln) if ln else ln for ln in body.split("\n"))

    text = f"{title}\n\n{body}\n\n{credit}"
    return {
        "text": text,
        "short": title,
        "image": article.image,
        "video": article.video,
        "url": article.link,
    }
