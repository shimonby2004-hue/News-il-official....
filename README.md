# News IL 📰

מערכת אוטומטית מלאה: **RSS ← Gemini (עורך) ← Telegram**.

אוספת כתבות מאתרי חדשות ישראליים, מנסחת אותן מחדש בעברית חדשותית ומוציאה אותן לערוץ טלגרם.

---

## מה המערכת עושה

- סורקת פידי RSS (Ynet, וואלה, מעריב, ישראל היום, מאקו)
- מסננת כתבות ישנות / כפולות / לא חדשותיות
- שולחת ל-Gemini לניסוח מחדש (כותרת + גוף + אימוג'י)
- מפרסמת בערוץ עם תמונה/סרטון, כותרת מודגשת, קרדיט וכפתור
- תומכת במצב אישור (שולחת לך קודם עם כפתורי ✅ / ❌)
- מגיבה לפקודות `/start` ו-`/status` בצ'אט פרטי עם הבוט

---

## הגדרה מהירה

### 1. צור בוט טלגרם
1. פתח [@BotFather](https://t.me/BotFather) → `/newbot`
2. שמור את ה-Token
3. הוסף את הבוט **כמנהל** לערוץ שלך עם הרשאת "Post Messages"

### 2. מצא את מזהה הערוץ
- ערוץ ציבורי: `@שם_הערוץ`
- ערוץ פרטי: שלח הודעה בערוץ ואז היכנס ל-  
  `https://api.telegram.org/bot<TOKEN>/getUpdates`  
  וחפש `"chat":{"id":-100...}`

### 3. מפתח Gemini
1. היכנס ל-[Google AI Studio](https://aistudio.google.com/apikey)
2. צור API Key ושמור אותו

### 4. מצא את ה-ID שלך (למצב אישור /status)
שלח `/start` לבוט אחרי שהוא רץ → הוא יחזיר לך את המספר.

---

## פריסה ב-Render (Web Service)

1. העלה את כל הקבצים ל-GitHub (Repository חדש)
2. ב-Render: **New → Web Service** → חבר את הריפו
3. הגדרות:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python main.py`
4. הוסף Environment Variables:

| משתנה | ערך | חובה |
|-------|-----|------|
| `TELEGRAM_BOT_TOKEN` | הטוקן מ-BotFather | ✅ |
| `TELEGRAM_CHANNEL_ID` | `@channel` או `-100...` | ✅ |
| `GEMINI_API_KEY` | מפתח מ-Google AI Studio | ✅ |
| `APPROVAL_MODE` | `false` (או `true`) | |
| `ADMIN_CHAT_ID` | המספר שלך | רק אם APPROVAL_MODE=true |
| `GEMINI_MODEL` | `gemini-3.8-flash` | |
| `INTERVAL_SECONDS` | `120` | |
| `MAX_ARTICLE_AGE_HOURS` | `3` | |

5. לחץ **Deploy**

ב-Logs אמורה להופיע השורה:
```
News IL starting | model=gemini-3.8-flash | ...
```

---

## שמירה על השירות ער (חשוב!)

בתוכנית **Free** של Render השירות נרדם אחרי ~15 דקות בלי תנועה.

**פתרון מומלץ:**
1. פתח חשבון חינמי ב-[UptimeRobot](https://uptimerobot.com)
2. הוסף Monitor מסוג **HTTP(s)**
3. הכנס את הכתובת של השירות (`https://your-app.onrender.com`)
4. בדיקה כל 5 דקות

---

## פקודות בוט

| פקודה | מה עושה |
|-------|---------|
| `/start` | מציג ברכה + את ה-ID שלך |
| `/status` | מצב המערכת (רק ל-ADMIN) |

---

## משתנים אופציונליים

| משתנה | ברירת מחדל | הסבר |
|-------|------------|------|
| `INTERVAL_SECONDS` | 120 | כמה שניות בין סריקות |
| `MAX_POSTS_PER_CYCLE` | 5 | מקסימום ידיעות בסבב אחד |
| `MAX_ARTICLE_AGE_HOURS` | 3 | רק כתבות מהשעות האחרונות |
| `BUTTON_STYLE` | primary | צבע הכפתור: primary / success / danger |
| `FEEDS` | (ברירת מחדל) | רשימת פידים מופרדת בפסיקים |

---

## הרצה מקומית

```bash
pip install -r requirements.txt
cp .env.example .env
# ערוך את .env ומלא את הערכים
python main.py
```

---

## מבנה הקבצים

```
NewsIL/
├── main.py           # הלוגיקה הראשית + scheduler + health server
├── config.py         # הגדרות ומשתני סביבה
├── ai.py             # תקשורת עם Gemini + ניסוח
├── feeds.py          # איסוף וסינון RSS
├── storage.py        # מסד נתונים SQLite
├── telegram_api.py   # שליחה וקבלת הודעות מטלגרם
├── requirements.txt
├── render.yaml
├── .env.example
└── README.md
```

---

## הערות חשובות

- בתוכנית Free אין דיסק קבוע → בכל Deploy ההיסטוריה נמחקת. הסינון לפי גיל מונע הצפה.
- אם רוצים דיסק קבוע → שדרג ל-Starter והגדר `DB_PATH=/data/newsil.db` + Disk.
- המערכת עוברת אוטומטית בין מודלים של Gemini אם אחד עמוס או לא זמין.
- צבע הכפתור עובד רק באפליקציות טלגרם מפברואר 2026 ואילך.
