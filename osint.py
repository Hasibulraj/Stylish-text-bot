
import os
import time
import sqlite3
import threading
import logging
import html
import requests
import telebot

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ============ CONFIGURATION ============

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
ADMIN_ID = 5989928539
APP_URL = os.environ.get(
    "APP_URL", "https://osint-s7db.onrender.com"
).strip().rstrip("/")
PORT = int(os.environ.get("PORT", "10000"))
DB_PATH = os.environ.get("DB_PATH", "users.db")

if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN":
    raise RuntimeError(
        "BOT_TOKEN missing. Render Environment mein BOT_TOKEN set karein."
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("fancy-text-bot")

bot = telebot.TeleBot(
    BOT_TOKEN,
    threaded=True,
    num_threads=4
)

# ============ DATABASE ============

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_db():
    conn = get_db()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT,
                status TEXT DEFAULT 'active'
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                user_id INTEGER,
                query_text TEXT,
                selected_style TEXT,
                count INTEGER DEFAULT 1,
                PRIMARY KEY (user_id, query_text, selected_style)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS custom_styles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template TEXT UNIQUE
            )
        """)

        conn.commit()
        logger.info("Database initialized: %s", DB_PATH)
    finally:
        conn.close()


def add_user(user_id, first_name):
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO users (user_id, first_name, status)
            VALUES (?, ?, 'active')
            ON CONFLICT(user_id) DO UPDATE SET
                first_name = excluded.first_name,
                status = 'active'
        """, (user_id, first_name))
        conn.commit()
    finally:
        conn.close()


def get_all_users():
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT user_id FROM users
            WHERE status = 'active'
        """).fetchall()
        return [row[0] for row in rows]
    finally:
        conn.close()


def save_user_preference(user_id, query_text, style_text):
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO user_preferences
                (user_id, query_text, selected_style, count)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(user_id, query_text, selected_style)
            DO UPDATE SET count = count + 1
        """, (user_id, query_text.lower().strip(), style_text))
        conn.commit()
    finally:
        conn.close()


def get_top_preferred_styles(user_id, query_text):
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT selected_style
            FROM user_preferences
            WHERE user_id = ? AND query_text = ?
            ORDER BY count DESC
            LIMIT 1
        """, (user_id, query_text.lower().strip())).fetchall()
        return [row[0] for row in rows]
    finally:
        conn.close()


def add_custom_style_db(template):
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO custom_styles (template) VALUES (?)",
            (template,)
        )
        conn.commit()
    finally:
        conn.close()


def get_custom_styles_db():
    conn = get_db()
    try:
        return conn.execute(
            "SELECT id, template FROM custom_styles ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


def delete_custom_style_db(style_id):
    conn = get_db()
    try:
        cursor = conn.execute(
            "DELETE FROM custom_styles WHERE id = ?",
            (style_id,)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def deactivate_user(user_id):
    conn = get_db()
    try:
        conn.execute(
            "UPDATE users SET status = 'inactive' WHERE user_id = ?",
            (user_id,)
        )
        conn.commit()
    finally:
        conn.close()


# ============ EXACTLY 10 FANCY FONTS ============

def generate_fancy_styles(text):
    styles = []

    # 1. Double-struck
    ds_upper = "𝔸𝔹ℂ𝔻𝔼𝔽𝔾ℍ𝕀𝕁𝕂𝕃𝕄ℕ𝕆ℙℚℝ𝕊𝕋𝕌𝕍𝕎𝕏𝕐ℤ"
    ds_lower = "𝕒𝕓𝕔𝕕𝕖𝕗𝕘𝕙𝕚𝕛𝕜𝕝𝕞𝕟𝕠𝕡𝕢𝕣𝕤𝕥𝕦𝕧𝕨𝕩𝕪𝕫"

    # 2. Circled
    circ_upper = "ⒶⒷⒸⒹⒺⒻⒼⒽⒾⒿⓀⓁⓂⓃⓄⓅⓆⓇⓈⓉⓊⓋⓌⓍⓎⓏ"
    circ_lower = "ⓐⓑⓒⓓⓔⓕⓖⓗⓘⓙⓚⓛⓜⓝⓞⓟⓠⓡⓢⓣⓤⓥⓦⓧⓨⓩ"

    # 3. Negative circled letters
    neg_upper = "🅐🅑🅒🅓🅔🅕🅖🅗🅘🅙🅚🅛🅜🅝🅞🅟🅠🅡🅢🅣🅤🅥🅦🅧🅨🅩"
    neg_lower = neg_upper.lower()

    # 4. Squared letters
    sq_upper = "🄰🄱🄲🄳🄴🄵🄶🄷🄸🄹🄺🄻🄼🄽🄾🄿🅀🅁🅂🅃🅄🅅🅆🅇🅈🅉"
    sq_lower = "abcdefghijklmnopqrstuvwxyz"

    # 5. Small caps approximation
    small_caps = {
        'a':'ᴀ', 'b':'ʙ', 'c':'ᴄ', 'd':'ᴅ', 'e':'ᴇ',
        'f':'ғ', 'g':'ɢ', 'h':'ʜ', 'i':'ɪ', 'j':'ᴊ',
        'k':'ᴋ', 'l':'ʟ', 'm':'ᴍ', 'n':'ɴ', 'o':'ᴏ',
        'p':'ᴘ', 'q':'ǫ', 'r':'ʀ', 's':'s', 't':'ᴛ',
        'u':'ᴜ', 'v':'ᴠ', 'w':'ᴡ', 'x':'x', 'y':'ʏ',
        'z':'ᴢ'
    }

    # 6. Monospace
    mono_upper = "𝙰𝙱𝙲𝙳𝙴𝙵𝙶𝙷𝙸𝙹𝙺𝙻𝙼𝙽𝙾𝙿𝚀𝚁𝚂𝚃𝚄𝚅𝚆𝚇𝚈𝚉"
    mono_lower = "𝚊𝚋𝚌𝚍𝚎𝚏𝚐𝚑𝚒𝚓𝚔𝚕𝚖𝚗𝚘𝚙𝚚𝚛𝚜𝚝𝚞𝚟𝚠𝚡𝚢𝚣"

    # 7. Bold serif
    bold_upper = "𝐀𝐁𝐂𝐃𝐄𝐅𝐆𝐇𝐈𝐉𝐊𝐋𝐌𝐍𝐎𝐏𝐐𝐑𝐒𝐓𝐔𝐕𝐖𝐗𝐘𝐙"
    bold_lower = "𝐚𝐛𝐜𝐝𝐞𝐟𝐠𝐡𝐢𝐣𝐤𝐥𝐦𝐧𝐨𝐩𝐪𝐫𝐬𝐭𝐮𝐯𝐰𝐱𝐲𝐳"

    # 8. Bold sans italic
    bi_upper = "𝘼𝘽𝘾𝘿𝙀𝙁𝙂𝙃𝙄𝙅𝙆𝙇𝙈𝙉𝙊𝙋𝙌𝙍𝙎𝙏𝙐𝙑𝙒𝙓𝙔𝙕"
    bi_lower = "𝙖𝙗𝙘𝙙𝙚𝙛𝙜𝙝𝙞𝙟𝙠𝙡𝙢𝙣𝙤𝙥𝙦𝙧𝙨𝙩𝙪𝙫𝙬𝙭𝙮𝙯"

    # 9. Block decoration
    # 10. Bold sans uppercase

    def map_font(value, upper, lower):
        result = []
        for ch in value:
            if 'A' <= ch <= 'Z':
                result.append(upper[ord(ch) - ord('A')])
            elif 'a' <= ch <= 'z':
                result.append(lower[ord(ch) - ord('a')])
            else:
                result.append(ch)
        return ''.join(result)

    styles.append(map_font(text, ds_upper, ds_lower))
    styles.append(map_font(text, circ_upper, circ_lower))
    styles.append(map_font(text, neg_upper, neg_lower))
    styles.append(map_font(text, sq_upper, sq_lower))
    styles.append(''.join(
        small_caps.get(ch.lower(), ch) if ch.isascii() and ch.isalpha()
        else ch for ch in text
    ))
    styles.append(map_font(text, mono_upper, mono_lower))
    styles.append(map_font(text, bold_upper, bold_lower))
    styles.append(map_font(text, bi_upper, bi_lower))

    # Decorated letters: retain original case
    styles.append('░' + '░'.join(text) + '░')

    # Bold sans uppercase
    bold_sans_upper = "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭"
    styles.append(map_font(text.upper(), bold_sans_upper, bold_sans_upper))

    return styles


# ============ SAFE TELEGRAM TEXT ============

def send_long_html(chat_id, text, reply_to_message_id=None):
    # Telegram text messages are limited to 4096 characters.
    # Split by lines to avoid breaking individual font rows.
    chunks = []
    current = ""

    for line in text.split("\n"):
        candidate = line if not current else current + "\n" + line

        if len(candidate) > 3800 and current:
            chunks.append(current)
            current = line
        else:
            current = candidate

    if current:
        chunks.append(current)

    for index, chunk in enumerate(chunks):
        bot.send_message(
            chat_id,
            chunk,
            parse_mode="HTML",
            reply_to_message_id=(
                reply_to_message_id if index == 0 else None
            )
        )


# ============ HEALTH CHECK ============

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/", "/health"):
            self.send_response(404)
            self.end_headers()
            return

        body = b"Bot service is running"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


def start_health_server():
    try:
        server = ThreadingHTTPServer(
            ("0.0.0.0", PORT), HealthHandler
        )
        server.daemon_threads = True
        logger.info("Health server listening on port %s", PORT)
        server.serve_forever()
    except Exception:
        logger.exception("Health server failed")


# ============ SELF PING ============

def start_self_ping():
    session = requests.Session()
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET"]
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))

    def worker():
        time.sleep(20)
        while True:
            try:
                response = session.get(
                    APP_URL + "/health", timeout=15
                )
                logger.info("Self-ping: HTTP %s", response.status_code)
                response.close()
            except requests.RequestException:
                logger.exception("Self-ping failed")
            time.sleep(180)

    threading.Thread(
        target=worker, daemon=True, name="self-ping"
    ).start()


# ============ START COMMAND ============

@bot.message_handler(commands=["start"])
def send_welcome(message):
    try:
        user = message.from_user
        if not user:
            return

        add_user(user.id, user.first_name or "User")

        welcome = (
            "👋 Hello <b>" + html.escape(user.first_name or "User") + "</b>!\n\n"
            "✨ Main ek <b>Fancy Text Generator Bot</b> hoon.\n"
            "💬 Koi bhi text bhejiye aur main 10 stylish fonts banaunga!\n\n"
            "👇 Abhi koi text type karke bhejiye:"
        )

        if user.id == ADMIN_ID:
            welcome += (
                "\n\n👑 <b>Admin Commands:</b>\n"
                "/addstyle &lt;text&gt; - Custom style save karein\n"
                "/liststyles - Custom styles dekhein\n"
                "/delstyle &lt;id&gt; - Custom style delete karein\n"
                "/broadcast &lt;msg&gt; - Sabhi active users ko message"
            )

        bot.send_message(
            message.chat.id,
            welcome,
            parse_mode="HTML"
        )
    except Exception:
        logger.exception("Start command failed")


# ============ ADMIN STYLE COMMANDS ============

@bot.message_handler(commands=["addstyle"])
def add_style_command(message):
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        bot.reply_to(
            message,
            "Usage: /addstyle 👻{text}👻\n"
            "Note: Saved custom styles are not included in the 10-font output."
        )
        return

    template = parts[1].strip()
    add_custom_style_db(template)

    bot.reply_to(message, "Custom style database mein save ho gaya.")


@bot.message_handler(commands=["liststyles"])
def list_styles_command(message):
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return

    rows = get_custom_styles_db()
    if not rows:
        bot.reply_to(message, "Koi custom style save nahi hai.")
        return

    lines = ["<b>Saved Custom Styles</b>\n"]
    for style_id, template in rows:
        lines.append(
            "ID: <code>" + str(style_id) + "</code> | "
            + html.escape(template)
        )

    send_long_html(message.chat.id, "\n".join(lines))


@bot.message_handler(commands=["delstyle"])
def del_style_command(message):
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /delstyle 1")
        return

    try:
        style_id = int(parts[1].strip())
        if delete_custom_style_db(style_id):
            bot.reply_to(message, "Custom style delete ho gaya.")
        else:
            bot.reply_to(message, "Yeh style ID nahi mili.")
    except ValueError:
        bot.reply_to(message, "Style ID number honi chahiye.")


# ============ BROADCAST ============

@bot.message_handler(commands=["broadcast"])
def broadcast_command(message):
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        bot.reply_to(message, "Usage: /broadcast Aapka message")
        return

    broadcast_msg = parts[1].strip()
    users = get_all_users()

    sent_count = 0
    fail_count = 0

    status_msg = bot.reply_to(
        message,
        "Broadcast shuru...\nTotal active users: " + str(len(users))
    )

    for uid in users:
        try:
            bot.send_message(uid, broadcast_msg)
            sent_count += 1
            time.sleep(0.05)
        except Exception as exc:
            fail_count += 1
            error_code = getattr(exc, "error_code", None)

            # Only deactivate users who have blocked the bot
            # or whose accounts are no longer accessible.
            if error_code == 403:
                deactivate_user(uid)

    try:
        bot.edit_message_text(
            "Broadcast complete!\n\n"
            "Sent: " + str(sent_count) + "\n"
            "Failed: " + str(fail_count),
            chat_id=message.chat.id,
            message_id=status_msg.message_id
        )
    except Exception:
        logger.exception("Could not update broadcast status")


# ============ TEXT HANDLER ============

@bot.message_handler(
    content_types=["text"],
    func=lambda message: True
)
def handle_text_messages(message):
    try:
        if not message.from_user:
            return

        original_text = message.text or ""
        text = original_text.strip()

        if not text or text.startswith("/"):
            return

        user = message.from_user
        add_user(user.id, user.first_name or "User")

        styles = generate_fancy_styles(text)

        lines = [
            "🎨 <b>Fancy Text Generator</b>",
            "Original: <code>" + html.escape(text) + "</code>",
            "",
            "<b>10 Stylish Fonts:</b>",
            ""
        ]

        for index, style in enumerate(styles, 1):
            lines.append(
                str(index) + ". <code>" + html.escape(style) + "</code>"
            )

        # Do not append custom styles: output remains exactly 10.
        send_long_html(
            message.chat.id,
            "\n".join(lines),
            reply_to_message_id=message.message_id
        )

    except Exception:
        logger.exception("Text handler failed")
        try:
            bot.reply_to(
                message,
                "Text process nahi ho paya. Thoda chhota text try karein."
            )
        except Exception:
            pass


# ============ MAIN ============

def main():
    init_db()

    threading.Thread(
        target=start_health_server,
        daemon=True,
        name="health-server"
    ).start()

    start_self_ping()

    logger.info("Starting Telegram bot polling...")

    while True:
        try:
            bot.infinity_polling(
                timeout=30,
                long_polling_timeout=25,
                allowed_updates=["message"],
                skip_pending=False
            )
        except KeyboardInterrupt:
            logger.info("Shutdown requested")
            break
        except Exception:
            logger.exception("Polling failed; retrying in 5 seconds")
            time.sleep(5)


if __name__ == "__main__":
    main()
