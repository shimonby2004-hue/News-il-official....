import html
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit

from apscheduler.schedulers.blocking import BlockingScheduler

import ai
import config
import feeds
import storage
from telegram_api import Telegram

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("newsil")

tg = None
STATS = {
    "last_scan": None,
    "posted": 0,
    "errors": 0,
    "summary": "עדיין לא הסתיימה סריקה",
    "last_error": None,
}


# ---------- כפתורים ----------
def _button(text, **fields):
    return {"text": text, **fields}


def source_markup(url):
    btn = _button(config.BUTTON_TEXT, url=url)
    if config.BUTTON_STYLE:
        btn["style"] = config.BUTTON_STYLE
    return {"inline_keyboard": [[btn]]}


def admin_markup(article_id, url):
    return {
        "inline_keyboard": [
            [
                _button("✅ פרסם", callback_data=f"a:{article_id}", style="success"),
                _button("❌ דחה", callback_data=f"r:{article_id}", style="danger"),
            ],
            [_button("🔗 מקור", url=url)],
        ]
    }


# ---------- עיבוד כתבות ----------
def _fail(article, exc):
    n = storage.attempts(article.id) + 1
    status = "failed" if n >= config.MAX_ATTEMPTS else "retry"
    storage.mark(article.id, status, article.link, article.title, attempts=n)
    STATS["errors"] += 1
    STATS["last_error"] = (time.time(), str(exc)[:200])
    log.error("article %s failed (%d/%d): %s", article.id, n, config.MAX_ATTEMPTS, exc)


def process(article):
    try:
        edited = ai.edit(article)
    except ai.Overloaded as exc:
        # תקלה זמנית אצל Gemini: לא סופרים ניסיון, הכתבה תיבדק שוב בסבב הבא
        log.warning("Gemini עמוס, מדלג לסבב הבא: %s", exc)
        STATS["last_error"] = (time.time(), str(exc)[:200])
        return "overloaded"
    except Exception as exc:
        return _fail(article, exc)

    if not edited["relevant"]:
        storage.mark(article.id, "skipped", article.link, article.title)
        log.info("skipped (not news): %s", article.title)
        return

    draft = ai.build_draft(article, edited)
    try:
        if config.APPROVAL_MODE:
            tg.post_draft(config.ADMIN_CHAT_ID, draft, admin_markup(article.id, article.link))
            storage.mark(article.id, "pending", article.link, article.title, draft=json.dumps(draft))
            log.info("sent for approval: %s", article.title)
        else:
            tg.post_draft(config.TELEGRAM_CHANNEL_ID, draft, source_markup(article.link))
            storage.mark(article.id, "posted", article.link, article.title)
            STATS["posted"] += 1
            log.info("posted: %s", article.title)
    except Exception as exc:
        return _fail(article, exc)
    time.sleep(config.POST_DELAY_SECONDS)


def run_cycle():
    try:
        log.info("--- scan start ---")
        posted_before = STATS["posted"]
        known_titles = storage.recent_titles()
        fresh, seen = [], set()
        n_done = n_old = n_dup = 0
        articles = sorted(feeds.collect_articles(), key=lambda a: a.published or time.time(), reverse=True)
        for a in articles:
            if a.id in seen:
                continue
            seen.add(a.id)
            if storage.is_done(a.id):
                n_done += 1
                continue
            if not feeds.age_ok(a):
                n_old += 1
                continue
            if feeds.is_duplicate(a.title, known_titles):
                storage.mark(a.id, "skipped", a.link, a.title)
                n_dup += 1
                log.info("duplicate: %s", a.title)
                continue
            fresh.append(a)
            known_titles.append(a.title)

        batch = list(reversed(fresh[: config.MAX_POSTS_PER_CYCLE]))  # מהישן לחדש
        stopped = False
        for a in batch:
            if process(a) == "overloaded":
                stopped = True
                log.warning("עוצר את הסבב, ינסה שוב בסבב הבא")
                break
        STATS["last_scan"] = time.time()
        STATS["summary"] = (
            f"נמצאו {len(articles)} | כבר טופלו {n_done} | ישנות מדי {n_old} | כפולות {n_dup} | "
            f"חדשות {len(fresh)} | פורסמו {STATS['posted'] - posted_before}"
            + (" | ⚠️ Gemini חסם את הסבב" if stopped else "")
        )
        log.info("scan summary: %s", STATS["summary"])
    except Exception:
        log.exception("cycle crashed (will retry next interval)")


# ---------- הבוט בצ'אט פרטי ----------
def _fmt_time(ts):
    if not ts:
        return "עדיין לא בוצעה"
    try:
        from zoneinfo import ZoneInfo
        return datetime.fromtimestamp(ts, ZoneInfo("Asia/Jerusalem")).strftime("%H:%M:%S")
    except Exception:
        return datetime.fromtimestamp(ts, timezone.utc).strftime("%H:%M:%S") + " UTC"


def handle_message(msg):
    chat = msg.get("chat") or {}
    if chat.get("type") != "private":
        return
    text = (msg.get("text") or "").strip()
    if not text.startswith("/"):
        return
    cmd = text.split()[0].split("@")[0].lower()
    uid = (msg.get("from") or {}).get("id")
    admin = str(config.ADMIN_CHAT_ID)

    if cmd in ("/start", "/id"):
        reply = (
            "👋 שלום! אני הבוט של <b>News IL</b> 📰\n"
            "אני אוסף חדשות, מנסח אותן ומפרסם בערוץ באופן אוטומטי.\n\n"
            f"🆔 ה-ID שלך: <code>{uid}</code>\n"
            "(מנהל המערכת צריך אותו בשביל <code>ADMIN_CHAT_ID</code>)\n\n"
            "פקודות: /status"
        )
    elif cmd == "/status":
        if not admin:
            reply = f"כדי להפעיל את /status הגדר ב-Render: <code>ADMIN_CHAT_ID = {uid}</code>"
        elif str(uid) != admin:
            reply = "אין הרשאה."
        else:
            feed_lines = "\n".join(
                f"{st}  {urlsplit(u).netloc}" for u, st in feeds.FEED_STATUS.items()
            ) or "עדיין לא נסרקו"
            err = STATS["last_error"]
            err_line = ""
            if err:
                err_line = f"\n🔴 שגיאה אחרונה ({_fmt_time(err[0])}): {html.escape(err[1], quote=False)}"
            reply = (
                "🟢 <b>המערכת פעילה</b>\n"
                f"🕒 סריקה אחרונה: {_fmt_time(STATS['last_scan'])}\n"
                f"📊 {STATS['summary']}\n"
                f"📡 מקורות:\n{feed_lines}\n"
                f"⏱ סריקה כל {config.INTERVAL_SECONDS} שניות\n"
                f"📤 פורסמו מאז ההפעלה: {STATS['posted']}\n"
                f"⚠️ שגיאות מאז ההפעלה: {STATS['errors']}\n"
                f"🧠 מודל: {ai.current_model()}\n"
                f"✋ מצב אישור: {'כן' if config.APPROVAL_MODE else 'לא'}"
                + err_line
            )
    else:
        return
    try:
        tg.send_message(chat["id"], reply)
    except Exception as exc:
        log.warning("reply failed: %s", exc)


def handle_callback(cb, admin):
    cid = cb["id"]
    if str(cb["from"]["id"]) != admin:
        tg.answer_callback(cid, "אין הרשאה")
        return
    action, _, article_id = (cb.get("data") or "").partition(":")
    row = storage.get(article_id)
    msg = cb.get("message") or {}
    if not row or row["status"] != "pending":
        tg.answer_callback(cid, "כבר טופל")
        if msg:
            tg.clear_buttons(msg["chat"]["id"], msg["message_id"])
        return

    if action == "a":
        try:
            draft = json.loads(row["draft"])
            tg.post_draft(config.TELEGRAM_CHANNEL_ID, draft, source_markup(draft["url"]))
            storage.set_status(article_id, "posted")
            STATS["posted"] += 1
            tg.answer_callback(cid, "פורסם ✅")
        except Exception as exc:
            log.error("publish after approval failed: %s", exc)
            tg.answer_callback(cid, "הפרסום נכשל, נסה שוב")
            return
    else:
        storage.set_status(article_id, "rejected")
        tg.answer_callback(cid, "נדחה")
    if msg:
        tg.clear_buttons(msg["chat"]["id"], msg["message_id"])


def updates_loop():
    try:
        tg.call("deleteWebhook")  # וובהוק ישן חוסם קבלת הודעות
    except Exception:
        pass
    offset = None
    admin = str(config.ADMIN_CHAT_ID)
    log.info("bot listener started")
    while True:
        try:
            for upd in tg.get_updates(offset):
                offset = upd["update_id"] + 1
                if upd.get("callback_query"):
                    handle_callback(upd["callback_query"], admin)
                elif upd.get("message"):
                    handle_message(upd["message"])
        except Exception as exc:
            log.warning("listener error: %s", exc)
            time.sleep(5)


# ---------- שרת בריאות (ש-Render ידע שהשירות חי) ----------
class Health(BaseHTTPRequestHandler):
    def _reply(self, body=True):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        if body:
            self.wfile.write(b"News IL is running")

    def do_GET(self):
        self._reply()

    def do_HEAD(self):
        self._reply(body=False)

    def log_message(self, *args):
        pass


def start_health_server():
    port = int(os.getenv("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), Health)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("health server on port %d", port)


def main():
    global tg
    missing = config.validate()
    if missing:
        sys.exit("חסרים משתני סביבה: " + ", ".join(missing))

    storage.init()
    tg = Telegram(config.TELEGRAM_BOT_TOKEN)
    log.info(
        "News IL starting | model=%s | approval=%s | feeds=%d | every %ds",
        config.GEMINI_MODEL, config.APPROVAL_MODE, len(config.FEEDS), config.INTERVAL_SECONDS,
    )

    start_health_server()
    threading.Thread(target=updates_loop, daemon=True).start()

    sched = BlockingScheduler(timezone="UTC")
    sched.add_job(
        run_cycle, "interval", seconds=config.INTERVAL_SECONDS,
        next_run_time=datetime.now(timezone.utc),  # סריקה ראשונית מיד
        max_instances=1, coalesce=True,
    )
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("stopped")


if __name__ == "__main__":
    main()
