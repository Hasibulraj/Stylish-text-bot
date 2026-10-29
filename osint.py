
import os
import time
import uuid
import logging
import threading
import psycopg2
import telebot

from psycopg2.extras import RealDictCursor
from flask import Flask, request, abort

# ==================================================
# CONFIGURATION - Set these in Render Environment
# ==================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
CHANNEL_ID = os.environ.get("CHANNEL_ID", "").strip()
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").strip().rstrip("/")
PORT = int(os.environ.get("PORT", "10000"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

if not CHANNEL_ID:
    raise RuntimeError("CHANNEL_ID is missing")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing")

CHANNEL_ID = int(CHANNEL_ID)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

logger = logging.getLogger(__name__)

bot = telebot.TeleBot(BOT_TOKEN, threaded=True)
app = Flask(__name__)

BOT_USERNAME = None
DB_LOCK = threading.RLock()


# ==================================================
# DATABASE
# ==================================================

def get_connection():
    return psycopg2.connect(
        DATABASE_URL,
        connect_timeout=15,
        cursor_factory=RealDictCursor
    )


def init_db():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS stored_files (
                    token TEXT PRIMARY KEY,
                    channel_id BIGINT NOT NULL,
                    message_id BIGINT NOT NULL,
                    sender_id BIGINT NOT NULL,
                    sender_name TEXT NOT NULL DEFAULT '',
                    original_chat_id BIGINT NOT NULL,
                    original_message_id BIGINT NOT NULL,
                    file_name TEXT NOT NULL DEFAULT '',
                    file_type TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
    logger.info("Database initialized")


def save_file(data):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO stored_files (
                    token, channel_id, message_id,
                    sender_id, sender_name,
                    original_chat_id, original_message_id,
                    file_name, file_type
                )
                VALUES (
                    %(token)s, %(channel_id)s, %(message_id)s,
                    %(sender_id)s, %(sender_name)s,
                    %(original_chat_id)s, %(original_message_id)s,
                    %(file_name)s, %(file_type)s
                )
                ON CONFLICT (token) DO NOTHING
            """, data)


def get_file(token):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT *
                FROM stored_files
                WHERE token = %s
            """, (token,))
            return cur.fetchone()


# ==================================================
# HELPERS
# ==================================================

def get_sender_name(user):
    if not user:
        return "Unknown"

    first = user.first_name or ""
    last = user.last_name or ""
    full_name = (first + " " + last).strip()

    if user.username:
        return full_name + " (@" + user.username + ")"

    return full_name or str(user.id)


def identify_file(message):
    """
    Returns file type and original filename where available.
    Text-only messages are not accepted.
    """

    if message.document:
        return "document", message.document.file_name or "document"

    if message.video:
        return "video", message.video.file_name or "video"

    if message.animation:
        return "animation", message.animation.file_name or "animation"

    if message.audio:
        return "audio", message.audio.file_name or "audio"

    if message.voice:
        return "voice", "voice.ogg"

    if message.video_note:
        return "video_note", "video_note"

    if message.photo:
        return "photo", "photo.jpg"

    if message.sticker:
        return "sticker", "sticker"

    return None, None


def get_start_link(token):
    if not BOT_USERNAME:
        raise RuntimeError("Bot username is not initialized")

    return "https://t.me/" + BOT_USERNAME + "?start=" + token


def build_upload_keyboard(token):
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton(
            text="⬆️ Upload Now",
            callback_data="upload:" + token
        )
    )
    return markup


# ==================================================
# FILE RECEIVER
# ==================================================

@bot.message_handler(
    content_types=[
        "document",
        "photo",
        "video",
        "audio",
        "voice",
        "animation",
        "sticker",
        "video_note"
    ],
    func=lambda message: message.chat.type == "private"
)
def receive_file(message):
    sender = message.from_user

    if not sender:
        bot.reply_to(
            message,
            "Unable to identify the sender of this file."
        )
        return

    file_type, file_name = identify_file(message)

    if not file_type:
        return

    status = bot.reply_to(
        message,
        "⏳ Saving your file to the private channel..."
    )

    try:
        # Forward the original message so Telegram can retain
        # forwarding attribution where Telegram permits it.
        forwarded = bot.forward_message(
            chat_id=CHANNEL_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id
        )

        token = uuid.uuid4().hex

        sender_name = get_sender_name(sender)

        record = {
            "token": token,
            "channel_id": CHANNEL_ID,
            "message_id": forwarded.message_id,
            "sender_id": sender.id,
            "sender_name": sender_name,
            "original_chat_id": message.chat.id,
            "original_message_id": message.message_id,
            "file_name": file_name,
            "file_type": file_type
        }

        save_file(record)

        share_link = get_start_link(token)

        caption = (
            "✅ File saved successfully.\n\n"
            "📁 File: " + file_name + "\n"
            "🔗 Shareable link:\n" + share_link + "\n\n"
            "Each file has its own link."
        )

        bot.edit_message_text(
            caption,
            chat_id=status.chat.id,
            message_id=status.message_id,
            reply_markup=build_upload_keyboard(token)
        )

    except Exception:
        logger.exception("Could not save incoming file")

        try:
            bot.edit_message_text(
                "❌ Unable to save this file. Please try again later.",
                chat_id=status.chat.id,
                message_id=status.message_id
            )
        except Exception:
            pass


# ==================================================
# UPLOAD NOW BUTTON
# ==================================================

@bot.callback_query_handler(
    func=lambda call: bool(call.data)
    and call.data.startswith("upload:")
)
def upload_now(call):
    token = call.data.split(":", 1)[1]

    try:
        record = get_file(token)

        if not record:
            bot.answer_callback_query(
                call.id,
                "File record not found.",
                show_alert=True
            )
            return

        if call.from_user.id != record["sender_id"]:
            bot.answer_callback_query(
                call.id,
                "This button belongs to another user.",
                show_alert=True
            )
            return

        # The file is already saved in the private channel.
        # Return its permanent bot start link.
        link = get_start_link(token)

        bot.answer_callback_query(
            call.id,
            "Your shareable link is ready."
        )

        bot.send_message(
            call.message.chat.id,
            "🔗 Your file link:\n" + link,
            reply_to_message_id=call.message.message_id
        )

    except Exception:
        logger.exception("Upload button failed")

        try:
            bot.answer_callback_query(
                call.id,
                "Something went wrong. Please try again.",
                show_alert=True
            )
        except Exception:
            pass


# ==================================================
# SHARE LINK /start HANDLER
# ==================================================

@bot.message_handler(
    commands=["start"],
    func=lambda message: message.chat.type == "private"
)
def start_handler(message):
    parts = (message.text or "").split(maxsplit=1)

    if len(parts) < 2:
        bot.reply_to(
            message,
            "👋 Welcome to File Store Bot!\n\n"
            "Send me a file to save it and receive a shareable link."
        )
        return

    token = parts[1].strip()

    # Tokens are generated as 32 hexadecimal characters.
    if len(token) != 32 or any(
        char not in "0123456789abcdef" for char in token.lower()
    ):
        bot.reply_to(message, "❌ Invalid shareable link.")
        return

    try:
        record = get_file(token)

        if not record:
            bot.reply_to(
                message,
                "❌ File not found. The link may be invalid."
            )
            return

        # Copy the channel message instead of forwarding it again.
        # This delivers the original stored media without exposing
        # the private channel to the recipient.
        copied = bot.copy_message(
            chat_id=message.chat.id,
            from_chat_id=record["channel_id"],
            message_id=record["message_id"]
        )

        logger.info(
            "Delivered token=%s to user=%s, message=%s",
            token,
            message.from_user.id,
            copied.message_id
        )

    except Exception:
        logger.exception("Share link delivery failed")

        bot.reply_to(
            message,
            "❌ Could not deliver this file. "
            "Please try again later."
        )


# ==================================================
# OPTIONAL HEALTH CHECK WEB SERVER
# ==================================================

@app.route("/", methods=["GET"])
def home():
    return "Telegram File Store Bot is running", 200


@app.route("/health", methods=["GET"])
def health():
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()

        return {"status": "ok", "database": "connected"}, 200

    except Exception:
        logger.exception("Health check failed")
        return {"status": "error"}, 503


# ==================================================
# STARTUP
# ==================================================

def run_web_server():
    app.run(
        host="0.0.0.0",
        port=PORT,
        threaded=True,
        use_reloader=False
    )


def main():
    global BOT_USERNAME

    init_db()

    BOT_USERNAME = bot.get_me().username

    logger.info("Starting bot @%s", BOT_USERNAME)

    if WEBHOOK_URL:
        webhook_url = WEBHOOK_URL + "/" + BOT_TOKEN

        bot.remove_webhook()
        time.sleep(1)

        bot.set_webhook(
            url=webhook_url,
            allowed_updates=["message", "callback_query"]
        )

        @app.route("/" + BOT_TOKEN, methods=["POST"])
        def telegram_webhook():
            if request.headers.get("content-type", "").split(";")[0] != (
                "application/json"
            ):
                abort(403)

            json_update = request.get_data().decode("utf-8")

            update = telebot.types.Update.de_json(json_update)
            bot.process_new_updates([update])

            return "OK", 200

        logger.info("Webhook enabled")
        run_web_server()

    else:
        bot.remove_webhook()
        logger.info("Using long polling")

        # Render Background Worker is recommended for polling.
        bot.infinity_polling(
            skip_pending=False,
            allowed_updates=["message", "callback_query"],
            timeout=30,
            long_polling_timeout=30
        )


if __name__ == "__main__":
    main()
    
