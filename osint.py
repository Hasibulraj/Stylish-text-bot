import os
import time
import sqlite3
import threading
import logging
import requests
import telebot

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ============ CONFIGURATION ============
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
ADMIN_ID = 5989928539
APP_URL = os.environ.get("APP_URL", "https://osint-s7db.onrender.com").strip().rstrip("/")
PORT = int(os.environ.get("PORT", "10000"))
DB_PATH = os.environ.get("DB_PATH", "users.db")

if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN":
    raise RuntimeError(
        "BOT_TOKEN missing. Render Dashboard > Environment mein BOT_TOKEN set karein."
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("fancy-text-bot")

bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=4)


# ============ DATABASE HELPERS ============
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
        rows = conn.execute("SELECT user_id FROM users").fetchall()
        return [row[0] for row in rows]
    finally:
        conn.close()


def save_user_preference(user_id, query_text, style_text):
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO user_preferences (user_id, query_text, selected_style, count)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(user_id, query_text, selected_style) DO UPDATE SET
                count = count + 1
        """, (user_id, query_text.lower().strip(), style_text))
        conn.commit()
    finally:
        conn.close()


def get_top_preferred_styles(user_id, query_text):
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT selected_style FROM user_preferences
            WHERE user_id = ? AND query_text = ?
            ORDER BY count DESC LIMIT 1
        """, (user_id, query_text.lower().strip())).fetchall()
        return [row[0] for row in rows]
    finally:
        conn.close()


def add_custom_style_db(template):
    conn = get_db()
    try:
        conn.execute("INSERT OR IGNORE INTO custom_styles (template) VALUES (?)", (template,))
        conn.commit()
    finally:
        conn.close()


def get_custom_styles_db():
    conn = get_db()
    try:
        rows = conn.execute("SELECT id, template FROM custom_styles").fetchall()
        return rows
    finally:
        conn.close()


def delete_custom_style_db(style_id):
    conn = get_db()
    try:
        cursor = conn.execute("DELETE FROM custom_styles WHERE id = ?", (style_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


# ============ FANCY TEXT GENERATOR ============
def generate_fancy_styles(text):
    styles = []
    
    b_sans_u = "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭"
    b_sans_l = "𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇"
    i_sans_u = "𝘈𝘉𝘊𝘋𝘌𝘍𝘎𝘏𝘐𝘑𝘒𝘔𝘕𝘖𝘗𝘘𝘙𝘚𝘛𝘜𝘝𝑾𝘟𝘠𝘡"
    i_sans_l = "𝘢𝘣𝘤𝘥𝘦𝘧𝘨𝘩𝘪𝘫𝘬𝘭𝘮𝘯𝘰𝘱𝘲𝘳𝘴𝘵𝘶𝘷𝘸𝘹𝘺𝘻"
    b_serif_u = "𝐀𝐁𝐂𝐃𝐄𝐅𝐆𝐇𝐈𝐉𝐊𝐋𝐌𝐍𝐎𝐏𝐐𝐑𝐒𝐓𝐔𝐕𝐖𝐗𝐘𝐙"
    b_serif_l = "𝐚𝐛𝐜𝐝𝐞𝐟𝐠𝐡𝐢𝐣𝐤𝐥𝐦𝐧𝐨𝐩𝐪𝐫𝐬𝐭𝐮𝐯𝐰𝐱𝐲𝐳"
    script_u = "𝒜ℬ𝒞𝒟ℰℱ𝒢ℋℐ𝒥𝒦𝒒ℳ𝒩𝒪𝒫𝒬ℛ𝒮𝒯𝒰𝒱𝒲𝒳𝒴𝒵"
    script_l = "𝒶𝒷𝒸𝒹ℯ𝒻ℊ𝒽𝒾𝒿𝓀𝓁𝓂𝓃ℴ𝓅𝓆𝓇𝓈𝓉𝓊𝓿𝓌𝓍𝓎𝓏"
    b_script_u = "𝓐𝓑𝓒𝓓𝓔𝓕𝓖𝓗𝓘𝓙𝓚𝓛𝓜𝓝𝘖𝓟𝓠𝓡𝓢𝓣𝓤𝓥𝓦𝓧𝓨𝓩"
    b_script_l = "𝓪𝚋𝓬𝓭𝓮𝓯𝓰𝓱𝓲𝓳𝑘𝑙𝓶𝓷𝓸𝓹𝔺𝓻𝓼𝓽𝓾𝓿𝔀𝔁𝔂𝔃"
    gothic_u = "𝔄𝔅ℭ𝒟𝔇𝔈𝔉𝔊ℌℑ𝔍𝔎𝔏𝔐𝔑𝔒𝔓𝔔ℜ𝒮𝔗𝔘𝔙𝔚𝔛𝔜ℨ"
    gothic_l = "𝔞𝔟𝔠𝔡𝔢𝔣𝔤𝔥𝔦𝔧𝔨𝔩𝔪𝔫𝔬𝔭𝔮𝔯𝔰𝔱𝔲𝔳𝔴𝔵𝔶𝔷"
    mono_u = "𝙰𝙱𝙲𝙳𝙴𝙵𝙶𝙷𝙸𝙹𝙺𝙻𝙼𝙽𝙾𝙿𝚀𝚁𝚂𝚃𝚄𝚅𝚆𝚇𝚈𝚉"
    mono_l = "𝚊𝚋𝚌𝚍𝚎𝚏𝚐𝚑𝚒𝚓𝚔𝚕𝚖𝚗𝚘𝚙𝚚𝚛𝚜𝚝𝚞𝚟𝚠𝚡𝚢𝚣"

    def c_map(txt, u_str, l_str):
        res = []
        for ch in txt:
            if 'A' <= ch <= 'Z':
                idx = ord(ch) - ord('A')
                res.append(u_str[idx] if idx < len(u_str) else ch)
            elif 'a' <= ch <= 'z':
                idx = ord(ch) - ord('a')
                res.append(l_str[idx] if idx < len(l_str) else ch)
            else:
                res.append(ch)
        return "".join(res)

    styles.append(c_map(text, b_sans_u, b_sans_l))
    styles.append(c_map(text, i_sans_u, i_sans_l))
    styles.append(c_map(text, b_serif_u, b_serif_l))
    styles.append(c_map(text, script_u, script_l))
    styles.append(c_map(text, b_script_u, b_script_l))
    styles.append(c_map(text, gothic_u, gothic_l))
    styles.append(c_map(text, mono_u, mono_l))
    styles.append("".join([c + '\u0336' for c in text]))
    styles.append("".join([c + '\u0332' for c in text]))

    circ_map = {'a':'ⓐ','b':'ⓑ','c':'ⓒ','d':'ⓓ','e':'ⓔ','f':'ⓕ','g':'ⓖ','h':'ⓗ','i':'ⓘ','j':'ⓙ','k':'ⓚ','l':'ⓛ','m':'ⓜ','n':'ⓝ','o':'ⓞ','p':'ⓟ','q':'ⓠ','r':'ⓡ','s':'ⓢ','t':'ⓣ','u':'ⓤ','v':'ⓥ','w':'ⓦ','x':'ⓧ','y':'ⓨ','z':'ⓩ','A':'Ⓐ','B':'Ⓑ','C':'Ⓒ','D':'Ⓓ','E':'Ⓔ','F':'Ⓕ','G':'Ⓖ','H':'Ⓗ','I':'Ⓘ','J':'Ⓙ','K':'Ⓚ','L':'Ⓛ','M':'Ⓜ','N':'Ⓝ','O':'Ⓞ','P':'Ⓟ','Q':'Ⓠ','R':'Ⓡ','S':'Ⓢ','T':'Ⓣ','U':'Ⓤ','V':'Ⓥ','W':'Ⓦ','X':'Ⓧ','Y':'Ⓨ','Z':'Ⓩ'}
    styles.append("".join([circ_map.get(c, c) for c in text]))
    
    black_circ = {'a':'🅐','b':'🅑','c':'🅒','d':'🅓','e':'🅔','f':'🅕','g':'🅖','h':'🅗','i':'🅘','j':'🅙','k':'🅚','l':'🅛','m':'🅜','n':'🅝','o':'🅞','p':'🅟','q':'🅠','r':'🅡','s':'🅢','t':'🅣','u':'🅤','v':'🅥','w':'🅦','x':'🅧','y':'🅨','z':'🅩','A':'🅐','B':'🅑','C':'🅒','D':'🅓','E':'🅔','F':'🅕','G':'🅖','H':'🅗','I':'🅘','J':'🅙','K':'🅚','L':'🅛','M':'🅜','N':'🅝','O':'🅞','P':'🅟','Q':'🅠','R':'🅡','S':'🅢','T':'🅣','U':'🅤','V':'🅥','W':'🅦','X':'🅧','Y':'🅨','Z':'🅩'}
    styles.append("".join([black_circ.get(c, c) for c in text]))
    styles.append(" ".join(list(text.upper())))
    styles.append(" ".join(list(text)))

    decorations = [
        "♥ " + text + " ♥", "💖 " + text + " 💖", "👑 " + text + " 👑", "🔥 " + text + " 🔥", "✨ " + text + " ✨",
        "★ " + text + " ★", "✦ " + text + " ✦", "꧁༺ " + text + " ༻꧂", "【" + text + "】",
        "『" + text + "』", "（" + text + "）", "【 ⚡ " + text + " ⚡ 】", "➳ " + text + " ❥", "⋆ " + text + " ⋆",
        "•·.·´¯`·.·• " + text + " •·.·´¯`·.·•", "▀▄▀▄▀▄ " + text + " ▄▀▄▀▄▀", "░▒▓█ " + text + " █▓▒░",
        "¯\\_(ツ)_/¯ " + text, "(｡◕‿◕｡) " + text, "(っ◔◡◔)っ ♥ " + text + " ♥", "╚» " + text + " «╝"
    ]
    styles.extend(decorations)

    # Admin द्वारा /addstyle से जोड़े गए कस्टम स्टाइल्स को यहाँ अप्लाई किया जाएगा
    custom_rows = get_custom_styles_db()
    for row in custom_rows:
        template = row[1]
        if "{text}" in template:
            styles.append(template.replace("{text}", text))
        else:
            styles.append(template + " " + text)

    unique_styles = []
    for s in styles:
        if s not in unique_styles:
            unique_styles.append(s)

    return unique_styles


# ============ HEALTH-CHECK WEB SERVER ============
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
        server = ThreadingHTTPServer(("0.0.0.0", PORT), HealthHandler)
        server.daemon_threads = True
        logger.info("Health server listening on port %s", PORT)
        server.serve_forever()
    except Exception:
        logger.exception("Health server failed to start")


# ============ SELF-PING EVERY 3 MINUTES ============
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
                response = session.get(APP_URL + "/health", timeout=15)
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
        user_id = message.from_user.id
        first_name = message.from_user.first_name or "User"
        add_user(user_id, first_name)

        welcome_text = (
            "👋 Hello **" + first_name + "**!\n\n"
            "✨ Main ek **Fancy Text Generator Bot** hoon.\n"
            "💬 Aap koi bhi text bhejiye, main uske **Stylish & Fancy Fonts** bana kar bhejunga!\n\n"
            "👇 Abhi koi text type karke bhejiye:"
        )
        
        if user_id == ADMIN_ID:
            welcome_text += (
                "\n\n👑 **Admin Commands:**\n"
                "/addstyle <template> - Naya style add karein (Jaise: /addstyle 🇭 🇮 {text})\n"
                "/liststyles - Sabhi custom styles dekhein\n"
                "/delstyle <id> - Style delete karein\n"
                "/broadcast <msg> - Sabhi ko message bhejein"
            )

        bot.reply_to(message, welcome_text, parse_mode="Markdown")
    except Exception:
        logger.exception("Start command failed")


# ============ ADMIN COMMANDS FOR STYLES ============
@bot.message_handler(commands=["addstyle"])
def add_style_command(message):
    if message.from_user.id != ADMIN_ID:
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        bot.reply_to(message, "⚠️ Usage: /addstyle 🇭 🇮 {text}\n(Aap `{text}` likh sakte hain jahan user ka text aayega)")
        return

    template = parts[1].strip()
    add_custom_style_db(template)
    bot.reply_to(message, f"✅ Naya fancy style successfully add ho gaya!\nTemplate: `{template}`", parse_mode="Markdown")


@bot.message_handler(commands=["liststyles"])
def list_styles_command(message):
    if message.from_user.id != ADMIN_ID:
        return

    rows = get_custom_styles_db()
    if not rows:
        bot.reply_to(message, "📋 Koi bhi custom style add nahi hai.")
        return

    text = "📋 **Custom Added Styles:**\n\n"
    for r_id, template in rows:
        text += f"ID: `{r_id}` | `{template}`\n"
    
    bot.reply_to(message, text, parse_mode="Markdown")


@bot.message_handler(commands=["delstyle"])
def del_style_command(message):
    if message.from_user.id != ADMIN_ID:
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        bot.reply_to(message, "⚠️ Usage: /delstyle <style_id>\n(ID dekhne ke liye /liststyles use karein)")
        return

    try:
        style_id = int(parts[1].strip())
        success = delete_custom_style_db(style_id)
        if success:
            bot.reply_to(message, f"✅ Style ID {style_id} successfully delete kar di gayi hai!")
        else:
            bot.reply_to(message, "⚠️ Yeh Style ID database mein nahi mili.")
    except ValueError:
        bot.reply_to(message, "⚠️ ID ek number honi chahiye.")


# ============ ADMIN BROADCAST COMMAND ============
@bot.message_handler(commands=["broadcast"])
def broadcast_command(message):
    if message.from_user.id != ADMIN_ID:
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        bot.reply_to(message, "⚠️ Usage: /broadcast Aapka message yahan likhein")
        return

    broadcast_msg = parts[1].strip()
    users = get_all_users()
    
    sent_count = 0
    fail_count = 0

    status_msg = bot.reply_to(message, "📢 Broadcasting to " + str(len(users)) + " users...")

    for uid in users:
        try:
            bot.send_message(uid, broadcast_msg)
            sent_count += 1
            time.sleep(0.1)
        except Exception:
            fail_count += 1

    bot.edit_message_text(
        "✅ Broadcast Completed!\n\n📤 Sent: " + str(sent_count) + "\n❌ Failed: " + str(fail_count),
        chat_id=message.chat.id,
        message_id=status_msg.message_id
    )


# ============ HANDLE ALL TEXT MESSAGES ============
@bot.message_handler(func=lambda message: True)
def handle_text_messages(message):
    try:
        user_id = message.from_user.id
        text = message.text.strip()

        if not text or text.startswith("/"):
            return

        add_user(user_id, message.from_user.first_name or "User")

        styles = generate_fancy_styles(text)
        top_styles = get_top_preferred_styles(user_id, text)

        response_text = "🎨 **Fancy Text for:** `" + text + "`\n\n"

        response_text += "📋 **All Fancy Styles:**\n"
        for i, style in enumerate(styles, 1):
            response_text += str(i) + ". `" + style + "`\n"

        if top_styles:
            fav_style = top_styles[0]
            response_text += "\n⚡_⚡ **Aapka Most Used / Favorite Style:**\n`" + fav_style + "`\n"

        if len(response_text) > 4000:
            response_text = response_text[:4000] + "\n...(truncated)"

        # Ab koi bhi message auto-delete nahi hoga, sab screen par rahega
        bot.reply_to(message, response_text, parse_mode="Markdown")

    except Exception:
        logger.exception("Text message handler failed")


# ============ MAIN ============
def main():
    init_db()

    threading.Thread(
        target=start_health_server, daemon=True, name="health-server"
    ).start()

    start_self_ping()
    logger.info("Starting Telegram Bot Polling...")

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
            logger.exception("Telegram polling failed; retrying in 5 seconds")
            time.sleep(5)


if __name__ == "__main__":
    main()
    
