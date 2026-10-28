
import os
import time
import html
import json
import sqlite3
import logging
import threading
import requests
import telebot

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ============ CONFIGURATION ============

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
ADMIN_ID = 5989928539
APP_URL = os.environ.get(
    "APP_URL",
    "https://osint-s7db.onrender.com"
).strip().rstrip("/")
PORT = int(os.environ.get("PORT", "10000"))
DB_PATH = os.environ.get("DB_PATH", "users.db")

if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN":
    raise RuntimeError("Please set BOT_TOKEN in Render Environment.")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("fancy-text-bot")

bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=4)


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
            CREATE TABLE IF NOT EXISTS custom_styles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template TEXT UNIQUE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_cleanup (
                chat_id INTEGER PRIMARY KEY,
                input_message_id INTEGER,
                output_message_ids TEXT DEFAULT '[]'
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
            SELECT user_id FROM users WHERE status = 'active'
        """).fetchall()
        return [row[0] for row in rows]
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
        return conn.execute("""
            SELECT id, template FROM custom_styles ORDER BY id
        """).fetchall()
    finally:
        conn.close()


def delete_custom_style_db(style_id):
    conn = get_db()
    try:
        cur = conn.execute(
            "DELETE FROM custom_styles WHERE id = ?", (style_id,)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def save_cleanup_data(chat_id, input_id, output_ids):
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO chat_cleanup
            (chat_id, input_message_id, output_message_ids)
            VALUES (?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                input_message_id = excluded.input_message_id,
                output_message_ids = excluded.output_message_ids
        """, (chat_id, input_id, json.dumps(output_ids)))
        conn.commit()
    finally:
        conn.close()


def get_cleanup_data(chat_id):
    conn = get_db()
    try:
        row = conn.execute("""
            SELECT input_message_id, output_message_ids
            FROM chat_cleanup WHERE chat_id = ?
        """, (chat_id,)).fetchone()

        if not row:
            return None, []

        try:
            ids = json.loads(row[1] or "[]")
        except (ValueError, TypeError):
            ids = []

        return row[0], ids
    finally:
        conn.close()


# ============ 10 FANCY FONTS ============

def generate_fancy_styles(text):
    styles = []

    fonts = [
        (
            "𝔸𝔹ℂ𝔻𝔼𝔽𝔾ℍ𝕀𝕁𝕂𝕃𝕄ℕ𝕆ℙℚℝ𝕊𝕋𝕌𝕍𝕎𝕏𝕐ℤ",
            "𝕒𝕓𝕔𝕕𝕖𝕗𝕘𝕙𝕚𝕛𝕜𝕝𝕞𝕟𝕠𝕡𝕢𝕣𝕤𝕥𝕦𝕧𝕨𝕩𝕪𝕫"
        ),
        (
            "ⒶⒷⒸⒹⒺⒻⒼⒽⒾⒿⓀⓁⓂⓃⓄⓅⓆⓇⓈⓉⓊⓋⓌⓍⓎⓏ",
            "ⓐⓑⓒⓓⓔⓕⓖⓗⓘⓙⓚⓛⓜⓝⓞⓟⓠⓡⓢⓣⓤⓥⓦⓧⓨⓩ"
        ),
        (
            "🅐🅑🅒🅓🅔🅕🅖🅗🅘🅙🅚🅛🅜🅝🅞🅟🅠🅡🅢🅣🅤🅥🅦🅧🅨🅩",
            "🅐🅑🅒🅓🅔🅕🅖🅗🅘🅙🅚🅛🅜🅝🅞🅟🅠🅡🅢🅣🅤🅥🅦🅧🅨🅩"
        ),
        (
            "🄰🄱🄲🄳🄴🄵🄶🄷🄸🄹🄺🄻🄼🄽🄾🄿🅀🅁🅂🅃🅄🅅🅆🅇🅈🅉",
            "abcdefghijklmnopqrstuvwxyz"
        ),
        (
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "abcdefghijklmnopqrstuvwxyz"
        ),
        (
            "𝙰𝙱𝙲𝙳𝙴𝙵𝙶𝙷𝙸𝙹𝙺𝙻𝙼𝙽𝙾𝙿𝚀𝚁𝚂𝚃𝚄𝚅𝚆𝚇𝚈𝚉",
            "𝚊𝚋𝚌𝚍𝚎𝚏𝚐𝚑𝚒𝚓𝚔𝚕𝚖𝚗𝚘𝚙𝚚𝚛𝚜𝚝𝚞𝚟𝚠𝚡𝚢𝚣"
        ),
        (
            "𝐀𝐁𝐂𝐃𝐄𝐅𝐆𝐇𝐈𝐉𝐊𝐋𝐌𝐍𝐎𝐏𝐐𝐑𝐒𝐓𝐔𝐕𝐖𝐗𝐘𝐙",
            "𝐚𝐛𝐜𝐝𝐞𝐟𝐠𝐡𝐢𝐣𝐤𝐥𝐦𝐧𝐨𝐩𝐪𝐫𝐬𝐭𝐮𝐯𝐰𝐱𝐲𝐳"
        ),
        (
            "𝘼𝘽𝘾𝘿𝙀𝙁𝙂𝙃𝙄𝙅𝙆𝙇𝙈𝙉𝙊𝙋𝙌𝙍𝙎𝙏𝙐𝙑𝙒𝙓𝙔𝙕",
            "𝙖𝙗𝙘𝙙𝙚𝙛𝙜𝙝𝙞𝙟𝙠𝙡𝙢𝙣𝙤𝙥𝙦𝙧𝙨𝙩𝙪𝙫𝙬𝙭𝙮𝙯"
        ),
        (
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "abcdefghijklmnopqrstuvwxyz"
        ),
        (
            "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭",
            "𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇"
        )
    ]

    small_caps = {
        "a": "ᴀ", "b": "ʙ", "c": "ᴄ", "d": "ᴅ",
        "e": "ᴇ", "f": "ғ", "g": "ɢ", "h": "ʜ",
        "i": "ɪ", "j": "ᴊ", "k": "ᴋ", "l": "ʟ",
        "m": "ᴍ", "n": "ɴ", "o": "ᴏ", "p": "ᴘ",
        "q": "ǫ", "r": "ʀ", "s": "s", "t": "ᴛ",
        "u": "ᴜ", "v": "ᴠ", "w": "ᴡ", "x": "x",
        "y": "ʏ", "z": "ᴢ"
    }

    def map_font(value, upper, lower):
        result = []
        for ch in value:
            if "A" <= ch <= "Z":
                result.append(upper[ord(ch) - 65])
            elif "a" <= ch <= "z":
                result.append(lower[ord(ch) - 97])
            else:
                result.append(ch)
        return "".join(result)

    for i, font in enumerate(fonts):
        if i == 4:
            styles.append("".join(
                small_caps.get(ch.lower(), ch)
                if ch.isascii() and ch.isalpha() else ch
                for ch in text
            ))
        elif i == 8:
            styles.append("░" + "░".join(text) + "░")
        else:
            styles.append(map_font(text, font[0], font[1]))

    return styles


def get_all_output_styles(text):
    styles = generate_fancy_styles(text)

    for style_id, template in get_custom_styles_db():
        if "{text}" in template:
            result = template.replace("{text}", text)
            if result not in styles:
                styles.append(result)

    return styles


# ============ SEND OUTPUT AND TRACK MESSAGE IDS ============

def send_text_chunks(chat_id, text, reply_to_message_id=None):
    chunks = []
    current = ""

    for line in text.split("\n"):
        while len(line) > 3000:
            chunks.append(line[:3000])
            line = line[3000:]

        candidate = line if not current else current + "\n" + line

        if len(candidate) > 3500 and current:
            chunks.append(current)
            current = line
        else:
            current = candidate

    if current:
        chunks.append(current)

    sent_ids = []

    for index, chunk in enumerate(chunks):
        sent = bot.send_message(
            chat_id,
            chunk,
            parse_mode="HTML",
            reply_to_message_id=(
                reply_to_message_id if index == 0 else None
            )
        )
        sent_ids.append(sent.message_id)

    return sent_ids


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


# ============ CLEAN PREVIOUS MESSAGES ============

def clean_previous_messages(chat_id):
    old_input_id, old_output_ids = get_cleanup_data(chat_id)

    if old_input_id:
        try:
            bot.delete_message(chat_id, old_input_id)
        except Exception as exc:
            logger.info("Could not delete previous input: %s", exc)

    for message_id in old_output_ids:
        try:
            bot.delete_message(chat_id, message_id)
        except Exception as exc:
            logger.info("Could not delete previous output: %s", exc)


# ============ START COMMAND ============

@bot.message_handler(commands=["start"])
def send_welcome(message):
    try:
        user = message.from_user
        if not user:
            return

        add_user(user.id, user.first_name or "User")

        welcome = (
            "👋 Hello " + html.escape(user.first_name or "User") + "!\n\n"
            "✨ Welcome to Fancy Text Generator Bot.\n"
            "💬 Send any text to get 10 stylish fonts.\n\n"
            "👇 Send your text now!"
        )

        if user.id == ADMIN_ID:
            welcome += (
                "\n\n👑 ADMIN COMMANDS\n\n"
                "/addstyle 👑 {text} 👑 - Add style\n"
                "/liststyles - List custom styles\n"
                "/delstyle ID - Delete style\n"
                "/broadcast MESSAGE - Broadcast message\n"
                "/stats - View bot statistics\n"
                "/start - Show this menu"
            )

        bot.send_message(message.chat.id, welcome)

    except Exception:
        logger.exception("Start command failed")


# ============ ADD STYLE ============

@bot.message_handler(commands=["addstyle"])
def add_style_command(message):
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return

    parts = (message.text or "").split(maxsplit=1)

    if len(parts) < 2 or not parts[1].strip():
        bot.reply_to(
            message,
            "Usage:\n/addstyle 👑 {text} 👑\n\n"
            "Example:\n/addstyle ꧁༺ {text} ༻꧂"
        )
        return

    template = parts[1].strip()

    if "{text}" not in template:
        bot.reply_to(
            message,
            "Template mein {text} zaroor hona chahiye.\n"
            "Example: /addstyle 👑 {text} 👑"
        )
        return

    add_custom_style_db(template)
    bot.reply_to(message, "✅ Custom style save ho gaya!\n\n" + template)


# ============ LIST STYLES ============

@bot.message_handler(commands=["liststyles"])
def list_styles_command(message):
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return

    rows = get_custom_styles_db()

    if not rows:
        bot.reply_to(message, "Abhi koi custom style nahi hai.")
        return

    lines = ["📋 CUSTOM STYLES", ""]

    for style_id, template in rows:
        lines.append("ID: " + str(style_id))
        lines.append(html.escape(template))
        lines.append("")

    send_text_chunks(message.chat.id, "\n".join(lines))


# ============ DELETE STYLE ============

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
    except ValueError:
        bot.reply_to(message, "Style ID number honi chahiye.")
        return

    if delete_custom_style_db(style_id):
        bot.reply_to(message, "🗑️ Style ID " + str(style_id) + " delete ho gaya.")
    else:
        bot.reply_to(message, "Yeh style ID nahi mili.")


# ============ BROADCAST ============

@bot.message_handler(commands=["broadcast"])
def broadcast_command(message):
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return

    parts = (message.text or "").split(maxsplit=1)

    if len(parts) < 2 or not parts[1].strip():
        bot.reply_to(message, "Usage: /broadcast Your message here")
        return

    broadcast_message = parts[1].strip()
    users = get_all_users()

    status = bot.reply_to(
        message, "📢 Broadcast starting...\nUsers: " + str(len(users))
    )

    sent = 0
    failed = 0

    for user_id in users:
        try:
            bot.send_message(user_id, broadcast_message)
            sent += 1
            time.sleep(0.05)
        except Exception as exc:
            failed += 1
            if getattr(exc, "error_code", None) == 403:
                deactivate_user(user_id)
            logger.warning("Broadcast failed for %s: %s", user_id, exc)

    try:
        bot.edit_message_text(
            "✅ Broadcast complete!\n\n"
            "📤 Sent: " + str(sent) + "\n"
            "❌ Failed: " + str(failed),
            chat_id=message.chat.id,
            message_id=status.message_id
        )
    except Exception:
        logger.exception("Broadcast status update failed")


# ============ STATS ============

@bot.message_handler(commands=["stats"])
def stats_command(message):
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return

    conn = get_db()
    try:
        total = conn.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        active = conn.execute(
            "SELECT COUNT(*) FROM users WHERE status='active'"
        ).fetchone()[0]

        inactive = conn.execute(
            "SELECT COUNT(*) FROM users WHERE status='inactive'"
        ).fetchone()[0]

        custom = conn.execute(
            "SELECT COUNT(*) FROM custom_styles"
        ).fetchone()[0]

        bot.send_message(
            message.chat.id,
            "📊 BOT STATISTICS\n\n"
            "👥 Total users: " + str(total) + "\n"
            "✅ Active users: " + str(active) + "\n"
            "🚫 Inactive users: " + str(inactive) + "\n"
            "🎨 Custom styles: " + str(custom)
        )
    finally:
        conn.close()


# ============ TEXT HANDLER ============

@bot.message_handler(content_types=["text"], func=lambda message: True)
def handle_text_messages(message):
    try:
        if not message.from_user:
            return

        text = (message.text or "").strip()

        if not text or text.startswith("/"):
            return

        if len(text) > 300:
            bot.reply_to(message, "Please send text up to 300 characters.")
            return

        user_id = message.from_user.id
        chat_id = message.chat.id

        add_user(user_id, message.from_user.first_name or "User")

        # Cleanup only in private chat.
        # Commands and previous messages are not deleted.
        if message.chat.type == "private":
            clean_previous_messages(chat_id)

        styles = get_all_output_styles(text)

        lines = [
            "🎨 <b>Fancy Text Generator</b>",
            "",
            "📝 <b>Original:</b>",
            "<code>" + html.escape(text) + "</code>",
            "",
            "✨ <b>Stylish Fonts:</b>",
            ""
        ]

        for index, style in enumerate(styles, 1):
            lines.append(
                str(index) + ". <code>" + html.escape(style) + "</code>"
            )
            lines.append("")

        output = "\n".join(lines).strip()

        output_ids = send_text_chunks(
            chat_id,
            output,
            reply_to_message_id=None
        )

        if message.chat.type == "private":
            save_cleanup_data(
                chat_id, message.message_id, output_ids
            )

    except Exception:
        logger.exception("Text handler failed")
        try:
            bot.reply_to(message, "Text process nahi ho paya. Dobara try karein.")
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
                              
