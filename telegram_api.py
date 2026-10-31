import copy
import logging
import time

import requests

log = logging.getLogger("newsil.telegram")


class TelegramError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def _strip_style(markup):
    """מסיר צבע מכפתורים (לגרסאות טלגרם ישנות שלא מכירות אותו)."""
    markup = copy.deepcopy(markup)
    for row in markup.get("inline_keyboard", []):
        for btn in row:
            btn.pop("style", None)
    return markup


class Telegram:
    def __init__(self, token):
        self.base = f"https://api.telegram.org/bot{token}"
        self.session = requests.Session()

    def call(self, method, timeout=40, **params):
        stripped = False
        for attempt in range(3):
            try:
                r = self.session.post(f"{self.base}/{method}", json=params, timeout=timeout)
                data = r.json()
            except (requests.RequestException, ValueError) as exc:
                raise TelegramError(f"{method}: {exc}") from exc
            if data.get("ok"):
                return data["result"]
            code = data.get("error_code")
            desc = data.get("description") or ""
            if code == 429 and attempt < 2:
                time.sleep(min(data.get("parameters", {}).get("retry_after", 5) + 1, 60))
                continue
            if (code == 400 and not stripped and params.get("reply_markup")
                    and any(k in desc.lower() for k in ("button", "style", "markup"))):
                log.warning("כפתור עם צבע נדחה, שולח בלי צבע: %s", desc)
                params["reply_markup"] = _strip_style(params["reply_markup"])
                stripped = True
                continue
            raise TelegramError(f"{method}: {desc}", code)

    # ---------- שליחה ----------
    def send_message(self, chat_id, text, markup=None):
        params = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if markup is not None:
            params["reply_markup"] = markup
        return self.call("sendMessage", **params)

    def _send_media(self, chat_id, kind, url, caption, markup):
        method, field = ("sendVideo", "video") if kind == "video" else ("sendPhoto", "photo")
        return self.call(
            method, chat_id=chat_id, caption=caption, parse_mode="HTML",
            reply_markup=markup, **{field: url},
        )

    def post_draft(self, chat_id, draft, markup=None):
        """סרטון -> תמונה -> טקסט בלבד. נכשלה המדיה? ממשיכים לטקסט."""
        text = draft["text"]
        fits = len(text) <= 1024  # מגבלת כיתוב של טלגרם
        candidates = []
        if draft.get("video"):
            candidates.append(("video", draft["video"]))
        if draft.get("image"):
            candidates.append(("photo", draft["image"]))

        for kind, url in candidates:
            try:
                if fits:
                    self._send_media(chat_id, kind, url, text, markup)
                else:
                    self._send_media(chat_id, kind, url, draft["short"], None)
                    self.send_message(chat_id, text, markup)
                return
            except TelegramError as exc:
                if exc.code != 400:
                    raise
                log.warning("media failed (%s): %s", kind, exc)
        self.send_message(chat_id, text, markup)

    # ---------- קבלת עדכונים ----------
    def get_updates(self, offset=None):
        r = self.session.post(
            f"{self.base}/getUpdates",
            json={"offset": offset, "timeout": 30, "allowed_updates": ["message", "callback_query"]},
            timeout=45,
        )
        data = r.json()
        if not data.get("ok"):
            raise TelegramError(f"getUpdates: {data.get('description')}", data.get("error_code"))
        return data["result"]

    def answer_callback(self, callback_id, text):
        try:
            self.call("answerCallbackQuery", callback_query_id=callback_id, text=text)
        except TelegramError:
            pass

    def clear_buttons(self, chat_id, message_id):
        try:
            self.call("editMessageReplyMarkup", chat_id=chat_id, message_id=message_id,
                      reply_markup={"inline_keyboard": []})
        except TelegramError:
            pass
