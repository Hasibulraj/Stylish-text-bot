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
            ORDER BY count DESC LIMIT 3
        """, (user_id, query_text.lower().strip())).fetchall()
        return [row[0] for row in rows]
    finally:
        conn.close()


# ============ MASSIVE FANCY TEXT GENERATOR (100+ STYLES) ============
def generate_fancy_styles(text):
    styles = []
    
    # Character maps for unicode transformations
    b_sans_u = "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭"
    b_sans_l = "𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇"
    i_sans_u = "𝘈𝘉𝘊𝘋𝘌𝘍𝘎𝘏𝘐𝘒𝘔𝘕𝘖𝘗𝘘𝘙𝘚𝘛𝘜𝘝𝘟"
    i_sans_l = "𝘢𝘣𝘤𝘥𝘦𝘧𝘨𝘩𝘪j𝘬𝘭𝘮𝘯𝘰𝘱𝘲𝘳𝘴𝘵𝘶𝘷𝘸𝘹𝘺𝘻"
    b_serif_u = "𝐀𝐁𝐂𝐃𝐄𝐅𝐆𝐇𝐈𝐉𝐊𝐋𝐌𝐍𝐎𝐏𝐐𝐑𝐒𝐓𝐔𝐕𝐖𝐗𝐘𝐙"
    b_serif_l = "𝐚𝐛𝐜𝐝𝐞𝐟𝐠𝐡𝐢𝐣𝐤𝐥𝐦𝐧𝐨𝐩𝐪𝐫𝐬𝐭𝐮𝐯𝐰𝐱𝐲𝐳"
    script_u = "𝒜ℬ𝒞𝒟ℰℱ𝒢ℋℐ𝒥𝒦ℒℳ𝒩𝒪𝒫𝒬ℛ𝒮𝒯𝒰𝒱𝒲𝒳𝒴𝒵"
    script_l = "𝒶𝒷𝒸𝒹ℯ𝒻ℊ𝒽𝒾𝒿𝓀𝓁𝓂𝓃ℴ𝓅𝓆𝓇𝓈𝓉𝓊𝓿𝓌𝓍𝓎𝓏"
    b_script_u = "𝓐𝓑𝓒𝓓𝓔𝓕𝓖𝓗𝓘𝓙𝓚𝓛𝓜𝓝𝘖𝓟𝓠𝓡𝓢𝓣𝓤𝓥𝓦𝓧𝓨𝓩"
    b_script_l = "𝓪𝚋𝓬𝓭𝓮𝓯𝓰𝓱𝓲𝓳𝑘𝑙𝓶𝓷𝓸𝓹𝓺𝓻𝓼𝓽𝓾𝓿𝔀𝔁𝔂𝔃"
    gothic_u = "𝔄𝔅ℭ𝒟𝔇𝔈𝔉𝔊ℌℑ𝔍𝔎𝔏𝔐𝔑𝔒𝔓𝔔ℜ𝒮𝔗𝔘𝔙𝔚𝔛𝔜ℨ"
    gothic_l = "𝔞𝔟𝔠𝔡𝔢𝔣𝔤𝔥𝔦𝔧𝔨𝔩𝔪𝔫𝔬𝔭𝔮𝔯𝔰𝔱𝔲𝔳𝔴𝔵𝔶𝔷"
    mono_u = "𝙰𝙱𝙲𝙳𝙴𝙵𝙶𝙷𝙸𝙹𝙺𝙻𝙼𝙽𝙾𝙿𝚀𝚁𝚂𝚃𝚄𝚅𝚆𝚇𝚈𝚉"
    mono_l = "𝚊𝚋𝚌𝚍𝚎𝚏𝚐𝚑𝚒𝚓𝚔𝚕𝚖𝚗𝚘𝚙𝚚𝚛𝚜𝚝𝚞𝚟𝚠𝚡𝚢𝚣"
    db_u = "𝔸𝔹ℂ𝔻𝔼𝔽𝔾ℍ𝕀𝕁𝕂𝕃𝕄ℕ𝕆ℙℚℝ𝕊𝕋𝕌𝕍𝕎𝕏𝕐ℤ"
    db_l = "𝕒𝕓𝕔𝕕𝕖𝔗𝕘𝕙𝕚𝕛𝕜𝕝𝕞𝕟𝕠𝕡𝕢𝕣𝕤𝕥𝕦𝕧𝕨𝕩𝕪🇿"

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

    # 1-10 Basic Unicode Fonts
    styles.append(c_map(text, b_sans_u, b_sans_l))
    styles.append(c_map(text, i_sans_u, i_sans_l))
    styles.append(c_map(text, b_serif_u, b_serif_l))
    styles.append(c_map(text, script_u, script_l))
    styles.append(c_map(text, b_script_u, b_script_l))
    styles.append(c_map(text, gothic_u, gothic_l))
    styles.append(c_map(text, mono_u, mono_l))
    styles.append(c_map(text, db_u, db_l))
    styles.append("".join([c + '\u0336' for c in text])) # Strikethrough
    styles.append("".join([c + '\u0332' for c in text])) # Underline

    # 11-25 Circled & Squared
    circ_map = {'a':'ⓐ','b':'ⓑ','c':'ⓒ','d':'ⓓ','e':'ⓔ','f':'ⓕ','g':'ⓖ','h':'ⓗ','i':'ⓘ','j':'ⓙ','k':'ⓚ','l':'ⓛ','m':'ⓜ','n':'ⓝ','o':'ⓞ','p':'ⓟ','q':'ⓠ','r':'ⓡ','s':'ⓢ','t':'ⓣ','u':'ⓤ','v':'ⓥ','w':'ⓦ','x':'ⓧ','y':'ⓨ','z':'ⓩ','A':'Ⓐ','B':'Ⓑ','C':'Ⓒ','D':'Ⓓ','E':'Ⓔ','F':'Ⓕ','G':'Ⓖ','H':'Ⓗ','I':'Ⓘ','J':'Ⓙ','K':'Ⓚ','L':'Ⓛ','M':'Ⓜ','N':'Ⓝ','O':'Ⓞ','P':'Ⓟ','Q':'Ⓠ','R':'Ⓡ','S':'Ⓢ','T':'Ⓣ','U':'Ⓤ','V':'Ⓥ','W':'Ⓦ','X':'Ⓧ','Y':'Ⓨ','Z':'Ⓩ'}
    styles.append("".join([circ_map.get(c, c) for c in text]))
    
    # Black filled bubble simulation (like in video)
    black_circ = {'a':'🅐','b':'🅑','c':'🅒','d':'🅓','e':'🅔','f':'🅕','g':'🅖','h':'🅗','i':'🅘','j':'🅙','k':'🅚','l':'🅛','m':'🅜','n':'🅝','o':'🅞','p':'🅟','q':'🅠','r':'🅡','s':'🅢','t':'🅣','u':'🅤','v':'🅥','w':'🅦','x':'🅧','y':'🅨','z':'🅩','A':'🅐','B':'🅑','C':'🅒','D':'🅓','E':'🅔','F':'🅕','G':'🅖','H':'🅗','I':'🅘','J':'🅙','K':'🅚','L':'🅛','M':'🅜','N':'🅝','O':'🅞','P':'🅟','Q':'🅠','R':'🅡','S':'🅢','T':'🅣','U':'🅤','V':'🅥','W':'🅦','X':'🅧','Y':'🅨','Z':'🅩'}
    styles.append("".join([black_circ.get(c, c) for c in text]))
    styles.append(" ".join(list(text.upper())))
    styles.append(" ".join(list(text)))
    
    flip_map = {'a':'ɐ','b':'q','c':'ɔ','d':'p','e':'ǝ','f':'ɟ','g':'ƃ','h':'ɥ','i':'ᴉ','j':'ɾ','k':'ʞ','l':'l','m':'ɯ','n':'u','o':'o','p':'d','q':'b','r':'ɹ','s':'s','t':'ʇ','u':'n','v':'ʌ','w':'ʍ','x':'x','y':'ʎ','z':'z'}
    styles.append("".join([flip_map.get(c.lower(), c) for c in reversed(text)]))

    # 26-60 Decorations, Hearts, Brackets, Aesthetics (as shown in video)
    decorations = [
        f"♥ {text} ♥", f"💖 {text} 💖", f"👑 {text} 👑", f"🔥 {text} 🔥", f"✨ {text} ✨",
        f"★ {text} ★", f"✦ {text} ✦", f" ུ {text} ུ ", f"꧁༺ {text} ༻꧂", f"【{text}】",
        f"『{text}』", f"（{text}）", f"【 ⚡ {text} ⚡ 】", f"➳ {text} ❥", f"⋆ {text} ⋆",
        f"⟦ {text} ⟧", f"⟨ {text} ⟩", f"⟅ {text} ⟆", f"⦅ {text} ⦆", f"【 {text} 】",
        f"《 {text} 》", f"〈 {text} 〉", f"⦃ {text} ⦄", f"⟪ {text} ⟫", f"⦉ {text} ⦊",
        f"•·.·´¯`·.·• {text} •·.·´¯`·.·•", f"¤¸¸.•´¯`•.¸¸.¤ {text} ¤¸¸.•´¯`•.¸¸.¤",
        f"§{~*~}{text}{{~*~}}§", f"▀▄▀▄▀▄ {text} ▄▀▄▀▄▀", f"░▒▓█ {text} █▓▒░",
        f"¯\\_(ツ)_/¯ {text}", f"(｡◕‿◕｡) {text}", f"ʕ•ᴥ•ʔ {text}", f"(っ◔◡◔)っ ♥ {text} ♥",
        f"╚» {text} «╝", f"╔═.♥.═╗ {text} ╚═.♥.═╝", f"┌(▀Ĺ▀l|)┐ {text}"
    ]
    styles.extend(decorations)

    # 61-100 Expanding through combined unicode accents & creative styles to match 100 items
    accents_combos = [
        ('\u0334', '\u0335'), ('\u0337', '\u0338'), ('\u0339', ''), ('\u033A', ''),
        ('\u033B', ''), ('\u033C', ''), ('\u033F', ''), ('\u0346', ''),
        ('\u034A', ''), ('\u034B', ''), ('\u034C', ''), ('\u0350', ''),
        ('\u0351', ''), ('\u0352', ''), ('\u0357', ''), ('\u0358', ''),
        ('\u0360', ''), ('\u0361', ''), ('\u0362', '')
    ]
    
    for ac1, ac2 in accents_combos:
        styles.append("".join([c + ac1 + ac2 for c in text]))

    # Generate additional stylized permutations to reach ~100 styles
    base_variants = [
        f"~*~*{text}*~*~", f"---{text}---", f"=== {text} ===", f"*** {text} ***",
        f".:*~*:._.:*~*:{text}:*~*:. _.:*~*:.", f"xXx_{text}_xXx", f"°°°{text}°°°",
        f"•·.·´{text}´·.·•", f"♦{text}♦", f"♠{text}♠", f"♣{text}♣", f"♠{text}♠",
        f"♫ {text} ♫", f"♬ {text} ♬", f"⚡ {text} ⚡", f"❄️ {text} ❄️", f"☔ {text} ☔"
    ]
    styles.extend(base_variants)

    # Ensure uniqueness and exact 100+ items limit check
    unique_styles = []
    for s in styles:
        if s not in unique_styles:
            unique_styles.append(s)
            
    while len(unique_styles) < 100:
        unique_styles.append(f"꧁༺ {text} ⟡ {len(unique_styles)+1} ༻꧂")

    return unique_styles[:100]


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


# ============ AUTO-DELETE HELPER ============
def delayed_delete(chat_id, message_ids, delay=15):
    def worker():
        time.sleep(delay)
        for msg_id in message_ids:
            try:
                bot.delete_message(chat_id, msg_id)
            except Exception:
                pass
    threading.Thread(target=worker, daemon=True).start()


# ============ START COMMAND ============
@bot.message_handler(commands=["start"])
def send_welcome(message):
    try:
        user_id = message.from_user.id
        first_name = message.from_user.first_name or "User"
        add_user(user_id, first_name)

        welcome_text = (
            f"👋 Hello **{first_name}**!\n\n"
            "✨ Main ek **Fancy Text Generator Bot** hoon.\n"
            "💬 Aap koi bhi text bhejiye, main uske **100+ Stylish & Fancy Fonts** bana kar bhejunga!\n\n"
            "👇 Abhi koi text type karke bhejiye:"
        )
        
        reply_msg = bot.reply_to(message, welcome_text, parse_mode="Markdown")
        delayed_delete(message.chat.id, [message.message_id, reply_msg.message_id], delay=20)
    except Exception:
        logger.exception("Start command failed")


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

    status_msg = bot.reply_to(message, f"📢 Broadcasting to {len(users)} users...")

    for uid in users:
        try:
            bot.send_message(uid, broadcast_msg)
            sent_count += 1
            time.sleep(0.1)
        except Exception:
            fail_count += 1

    bot.edit_message_text(
        f"✅ Broadcast Completed!\n\n📤 Sent: {sent_count}\n❌ Failed: {fail_count}",
        chat_id=message.chat.id,
        message_id=status_msg.message_id
    )


# ============ HANDLE ALL TEXT MESSAGES (100 STYLES) ============
@bot.message_handler(func=lambda message: True)
def handle_text_messages(message):
    try:
        user_id = message.from_user.id
        text = message.text.strip()

        if not text or text.startswith("/"):
            return

        add_user(user_id, message.from_user.first_name or "User")

        # Generate 100 styles
        styles = generate_fancy_styles(text)
        top_styles = get_top_preferred_styles(user_id, text)

        response_text = f"🎨 **Fancy Text for:** `{text}`\n\n"

        if top_styles:
            response_text += "⭐ **Aapke Most Used Styles:**\n"
            for idx, st in enumerate(top_styles, 1):
                response_text += f"{idx}. `{st}`\n"
            response_text += "\n-------------------\n\n"

        response_text += "📋 **All 100 Fancy Styles:**\n"
        for i, style in enumerate(styles, 1):
            response_text += f"{i}. `{style}`\n"

        if len(response_text) > 4000:
            response_text = response_text[:4000] + "\n...(truncated)"

        reply_msg = bot.reply_to(message, response_text, parse_mode="Markdown")
        delayed_delete(message.chat.id, [message.message_id, reply_msg.message_id], delay=60)

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
    