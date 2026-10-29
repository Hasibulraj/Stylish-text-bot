import os
import json
import sqlite3
import asyncio
import logging
import urllib.request
from urllib.error import URLError, HTTPError
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# Render Environment Variables:
# BOT_TOKEN = your Telegram bot token
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = 5989928539
DB_CHANNEL_ID = -1003954392340
SECRET_CHANNEL_ID = -1004490787792
DB_PATH = os.environ.get("DB_PATH", "bot_data.sqlite3")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)


# ---------------- DATABASE ----------------
def db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with db() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS shares (
                media_id TEXT PRIMARY KEY,
                channel_id INTEGER NOT NULL,
                files_json TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS file_users (
                media_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                PRIMARY KEY(media_id, user_id)
            )
        """)


def register_user(user_id):
    with db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users(user_id) VALUES(?)",
            (int(user_id),),
        )


def get_users():
    with db() as conn:
        return [
            row[0]
            for row in conn.execute("SELECT user_id FROM users").fetchall()
        ]


def save_share(media_id, channel_id, files):
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO shares(media_id, channel_id, files_json) "
            "VALUES(?,?,?)",
            (str(media_id), int(channel_id), json.dumps(files)),
        )


def get_share(media_id):
    with db() as conn:
        row = conn.execute(
            "SELECT channel_id, files_json FROM shares WHERE media_id=?",
            (str(media_id),),
        ).fetchone()

    if not row:
        return None

    return {"channel_id": row[0], "files": json.loads(row[1])}


def register_file_user(media_id, user_id):
    with db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO file_users(media_id, user_id) VALUES(?,?)",
            (str(media_id), int(user_id)),
        )


def count_file_users(media_id):
    with db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM file_users WHERE media_id=?",
            (str(media_id),),
        ).fetchone()
    return row[0] if row else 0


def format_bytes(size):
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.2f} {unit}"
        value /= 1024


def database_storage_report():
    db_file = Path(DB_PATH)
    files = [
        db_file,
        Path(str(db_file) + "-wal"),
        Path(str(db_file) + "-shm"),
    ]
    sizes = {
        str(path): path.stat().st_size if path.exists() else 0
        for path in files
    }

    with db() as conn:
        users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        shares = conn.execute("SELECT COUNT(*) FROM shares").fetchone()[0]
        file_users = conn.execute(
            "SELECT COUNT(*) FROM file_users"
        ).fetchone()[0]

    total = sum(sizes.values())
    return (
        "💾 <b>DATABASE STORAGE</b>\n\n"
        f"📂 Database: <code>{DB_PATH}</code>\n"
        f"🗃 Main DB: {format_bytes(sizes[str(db_file)])}\n"
        f"📝 WAL file: {format_bytes(sizes[str(db_file) + '-wal'])}\n"
        f"🧩 SHM file: {format_bytes(sizes[str(db_file) + '-shm'])}\n"
        f"📦 Total SQLite files: <b>{format_bytes(total)}</b>\n\n"
        f"👥 Registered users: <b>{users:,}</b>\n"
        f"🔗 Saved share links: <b>{shares:,}</b>\n"
        f"📥 File-download records: <b>{file_users:,}</b>\n\n"
        "ℹ️ This shows the SQLite files used by this bot, not the total Render disk usage."
    )


def is_admin(user_id):
    return bool(user_id and int(user_id) == ADMIN_ID)


async def storage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message
    if not user or not is_admin(user.id) or not message:
        return
    await message.reply_text(
        database_storage_report(),
        parse_mode="HTML",
    )


def _ping_url_sync():
    url = os.environ.get(
        "KEEPALIVE_URL",
        "https://stylish-text-bot-1ycc.onrender.com",
    ).strip()

    if not url:
        return "KEEPALIVE_URL is empty"

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Render-KeepAlive/1.0"},
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return f"Keep-alive ping: HTTP {response.status} from {url}"
    except (URLError, HTTPError, TimeoutError, OSError) as exc:
        return f"Keep-alive ping failed for {url}: {exc}"


async def keepalive_ping(context: ContextTypes.DEFAULT_TYPE):
    try:
        result = await asyncio.to_thread(_ping_url_sync)
        log.info(result)
    except Exception:
        log.exception("Keep-alive ping error")


# ---------------- HELPERS ----------------
def get_message_type(message):
    if message.photo:
        return "photo"
    if message.video:
        return "video"
    if message.document:
        return "document"
    if message.audio:
        return "audio"
    if message.voice:
        return "voice"
    if message.animation:
        return "animation"
    if message.sticker:
        return "sticker"
    if message.video_note:
        return "video_note"
    if message.text:
        return "text"
    return None


async def delete_one(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    try:
        await context.bot.delete_message(
            chat_id=data["chat_id"],
            message_id=data["message_id"],
        )
    except Exception:
        pass


async def delete_many(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    for message_id in data.get("message_ids", []):
        try:
            await context.bot.delete_message(
                chat_id=data["chat_id"],
                message_id=message_id,
            )
        except Exception:
            pass


async def backup_to_secret(message, context):
    try:
        await context.bot.copy_message(
            chat_id=SECRET_CHANNEL_ID,
            from_chat_id=message.chat_id,
            message_id=message.message_id,
        )

        user = message.from_user
        if user:
            name = user.first_name or "User"
            name = (
                name.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            caption = (
                f'👤 Name: <a href="tg://user?id={user.id}">{name}</a>\n\n'
                f'🆔 ID: <code>{user.id}</code>'
            )
            await context.bot.send_message(
                chat_id=SECRET_CHANNEL_ID,
                text=caption,
                parse_mode="HTML",
            )
    except Exception:
        log.exception("Secret-channel backup failed")


# ---------------- /START + SHARE LINKS ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return

    register_user(user.id)

    if not context.args or context.args[0] == "None":
        await message.reply_text(
            "📁 Welcome to File Sharing Bot! ⚡\n\n"
            "Send me any file to get a shareable link."
        )
        return

    media_id = str(context.args[0])
    data = get_share(media_id)

    if not data:
        msg = await message.reply_text("❌ File not found.")
        context.job_queue.run_once(
            delete_one,
            30,
            data={"chat_id": message.chat_id, "message_id": msg.message_id},
        )
        return

    register_file_user(media_id, user.id)
    sent_ids = []

    for item in data["files"]:
        try:
            copied = await context.bot.copy_message(
                chat_id=message.chat_id,
                from_chat_id=data["channel_id"],
                message_id=item["db_message_id"],
            )
            sent_ids.append(copied.message_id)
        except Exception:
            log.exception("Shared item could not be copied")

    if sent_ids:
        note = await context.bot.send_message(
            chat_id=message.chat_id,
            text=(
                "⚠️ These files will be deleted after 30 minutes. "
                "Save or forward them now!"
            ),
            reply_to_message_id=sent_ids[-1],
        )
        sent_ids.append(note.message_id)

        context.job_queue.run_once(
            delete_many,
            1800,
            data={"chat_id": message.chat_id, "message_ids": sent_ids},
        )
    else:
        msg = await message.reply_text("❌ Files Not Found!")
        context.job_queue.run_once(
            delete_one,
            15,
            data={"chat_id": message.chat_id, "message_id": msg.message_id},
        )


# ---------------- /INFO ----------------
async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message:
        return

    if not context.args:
        text = (
            "⚠️ <b>Invalid Usage!</b>\n\n"
            "📌 <b>Usage:</b> <code>/info MEDIA_ID</code>\n"
            "💡 <b>Example:</b> <code>/info 5989928539_382</code>\n\n"
            "ℹ️ File ID is the part after <code>?start=</code> in the share link."
        )
        sent = await message.reply_text(text, parse_mode="HTML")
        context.job_queue.run_once(
            delete_one,
            200,
            data={"chat_id": message.chat_id, "message_id": sent.message_id},
        )
        return
        media_id = str(context.args[0]).strip()
    data = get_share(media_id)

    if not data:
        text = (
            "❌ <b>File Not Found!</b>\n\n"
            f"🆔 <b>File ID:</b> <code>{media_id}</code>\n"
            "⚠️ Please check the ID and try again."
        )
    else:
        text = (
            "📊 <b>FILE STATUS</b>\n"
            f"🆔 <b>File ID:</b> <code>{media_id}</code>\n"
            f"📁 <b>Files saved:</b> {len(data['files'])}\n"
            f"👥 <b>Total Download:</b> {count_file_users(media_id)}"
        )

    sent = await message.reply_text(text, parse_mode="HTML")
    context.job_queue.run_once(
        delete_one,
        200,
        data={"chat_id": message.chat_id, "message_id": sent.message_id},
    )


# ---------------- RECEIVE FILES / TEXT ----------------
async def receive_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return

    # Keep broadcast messages out of the upload/backup flow.
    if is_admin(user.id) and context.user_data.get("awaiting_broadcast"):
        return

    register_user(user.id)
    kind = get_message_type(message)
    if not kind:
        return

    if message.text and message.text.startswith("/"):
        return

    await backup_to_secret(message, context)

    sessions = context.application.bot_data.setdefault("sessions", {})
    key = (message.chat_id, user.id)
    pending = sessions.get(key)

    if not pending:
        pending = {
            "media_id": f"{message.chat_id}_{message.message_id}",
            "chat_id": message.chat_id,
            "files": [],
            "media_message_id": message.message_id,
            "timer_job": None,
            "button_message_id": None,
        }
        sessions[key] = pending

    pending["files"].append({
        "type": kind,
        "source_message_id": message.message_id,
    })
    pending["media_message_id"] = message.message_id

    old_job = pending.get("timer_job")
    if old_job:
        old_job.schedule_removal()

    old_button_id = pending.get("button_message_id")
    if old_button_id:
        try:
            await context.bot.delete_message(
                chat_id=message.chat_id,
                message_id=old_button_id,
            )
        except Exception:
            pass

    sent = await message.reply_text(
        f"📁 Items received: {len(pending['files'])}. "
        "Send more or tap Upload Now.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "📤 𝗨𝗽𝗹𝗼𝗮𝗱 𝗡𝗼𝘄",
                callback_data="upload_now",
            )
        ]]),
    )
    pending["button_message_id"] = sent.message_id
    pending["timer_job"] = context.job_queue.run_once(
        expire_upload,
        120,
        data={"key": list(key), "media_id": pending["media_id"]},
    )


async def expire_upload(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    key = tuple(data["key"])
    sessions = context.application.bot_data.setdefault("sessions", {})
    pending = sessions.get(key)

    if not pending or pending.get("media_id") != data["media_id"]:
        return

    button_id = pending.get("button_message_id")
    if button_id:
        try:
            await context.bot.delete_message(
                chat_id=pending["chat_id"],
                message_id=button_id,
            )
        except Exception:
            pass

    sessions.pop(key, None)

    try:
        expire_msg = await context.bot.send_message(
            chat_id=pending["chat_id"],
            text="⌛ Time expired! Upload session cancelled.",
        )
        context.job_queue.run_once(
            delete_one,
            20,
            data={
                "chat_id": pending["chat_id"],
                "message_id": expire_msg.message_id,
            },
        )
    except Exception:
        pass


async def upload_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    key = (query.message.chat_id, user.id)
    sessions = context.application.bot_data.setdefault("sessions", {})
    pending = sessions.get(key)

    if not pending or not pending["files"]:
        await query.message.reply_text(
            "❌ No pending files found. Please send a file first."
        )
        return

    if pending.get("timer_job"):
        pending["timer_job"].schedule_removal()

    try:
        await query.message.delete()
    except Exception:
        pass

    saved_files = []
    failed_count = 0
    last_error = ""

    for item in pending["files"]:
        try:
            forwarded = await context.bot.forward_message(
                chat_id=DB_CHANNEL_ID,
                from_chat_id=pending["chat_id"],
                message_id=item["source_message_id"],
            )
            saved_files.append({
                "db_message_id": forwarded.message_id,
                "type": item.get("type", "unknown"),
            })
        except Exception as exc:
            failed_count += 1
            last_error = str(exc)
            log.exception("Failed to save item in database channel")

    if saved_files:
        media_id = pending["media_id"]
        save_share(media_id, DB_CHANNEL_ID, saved_files)
        me = await context.bot.get_me()
        share_link = f"https://t.me/{me.username}?start={media_id}"
        sessions.pop(key, None)

        result = f"✅ Upload completed!\n\n📁 Files saved: {len(saved_files)}"
        if failed_count:
            result += f"\n⚠️ Items failed: {failed_count}"
        result += f"\n\n🔗 Your Shareable Link:\n{share_link}"

        await query.message.reply_text(
            result,
            reply_to_message_id=pending.get("media_message_id"),
        )
    else:
        error_text = (
            "❌ Failed to save items to the database channel.\n\n"
            "Please check that the bot is an admin in the database channel "
            "and has permission to post messages."
        )
        if last_error:
            error_text += "\n\nError: " + last_error[:500]
        await query.message.reply_text(error_text)
        sessions.pop(key, None)


# ---------------- BROADCAST ----------------
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message

    if not user or not is_admin(user.id) or not message:
        return

    context.user_data["awaiting_broadcast"] = True
    await message.reply_text(
        "🎙️ <b>Broadcast Ready</b>\n\n"
        "Ab apna text, photo, video, audio, document, sticker, voice, "
        "video note ya animation bhejo.\n\n"
        "HTML formatting / entities Telegram ke original message se preserve "
        "honge.\nCancel: /cancelbroadcast",
        parse_mode="HTML",
    )


async def cancel_broadcast_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user
    message = update.effective_message

    if not user or not is_admin(user.id) or not message:
        return

    context.user_data.pop("awaiting_broadcast", None)
    await message.reply_text("❌ Broadcast cancelled.")


async def broadcast_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user
    message = update.effective_message

    if not user or not is_admin(user.id) or not message:
        return

    if not context.user_data.get("awaiting_broadcast"):
        return

    if message.text and message.text.split()[0].split("@")[0] == "/cancelbroadcast":
        context.user_data.pop("awaiting_broadcast", None)
        await message.reply_text("❌ Broadcast cancelled.")
        return

    supported = (
        message.text or message.photo or message.video or message.audio
        or message.document or message.sticker or message.animation
        or message.voice or message.video_note
    )
    if not supported:
        await message.reply_text("❌ Unsupported message type. Send text or media.")
        return

    users = get_users()
    context.user_data.pop("awaiting_broadcast", None)

    sent = 0
    failed = 0
    blocked = 0

    status = await message.reply_text(
        f"🔁 Broadcast processing...\n👥 Total users: {len(users)}"
    )

    for uid in users:
        try:
            await context.bot.copy_message(
                chat_id=uid,
                from_chat_id=message.chat_id,
                message_id=message.message_id,
            )
            sent += 1
        except Exception as exc:
            failed += 1
            error = str(exc).lower()
            if any(term in error for term in (
                "bot was blocked",
                "user is deactivated",
                "chat not found",
                "bot can't initiate conversation",
                "bot was kicked",
            )):
                blocked += 1
            log.debug("Broadcast to %s failed: %s", uid, exc)

        await asyncio.sleep(0.05)

    report = (
        "✅ <b>BROADCAST COMPLETE</b>\n\n"
        f"👥 Total Users: {len(users)}\n"
        f"📨 Successfully Sent: {sent}\n"
        f"🚫 Blocked (detected): {blocked}\n"
        f"❌ Failed: {failed}"
    )

    try:
        await status.edit_text(report, parse_mode="HTML")
    except Exception:
        await message.reply_text(report, parse_mode="HTML")


# ---------------- ERROR HANDLER ----------------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("Unhandled bot error: %s", context.error)


# ---------------- MAIN ----------------
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("info", info))
    app.add_handler(CommandHandler("storage", storage_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("cancelbroadcast", cancel_broadcast_command))

    app.add_handler(
        CallbackQueryHandler(upload_now, pattern=r"^upload_now$")
    )

    # First handle upload workflow, but it skips admin broadcast messages.
    app.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            receive_message,
        ),
        group=0,
    )

    # Broadcast processing is separate from the old edit/button system.
    app.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            broadcast_message,
        ),
        group=1,
    )

    app.add_error_handler(error_handler)

    app.job_queue.run_repeating(
        keepalive_ping,
        interval=120,
        first=1,
        name="keepalive_ping",
    )

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
    
