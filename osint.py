
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
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = 5989928539
DB_CHANNEL_ID = -1003954392340
SECRET_CHANNEL_ID = -1004490787792
DB_PATH = os.environ.get("DB_PATH", "bot_data.sqlite3")
KEEPALIVE_URL = os.environ.get(
    "KEEPALIVE_URL",
    "https://stylish-text-bot-1ycc.onrender.com"
).strip()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)


# DATABASE
def db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
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
            (int(user_id),)
        )


def get_users():
    with db() as conn:
        return [
            r[0] for r in
            conn.execute("SELECT user_id FROM users").fetchall()
        ]


def save_share(media_id, channel_id, files):
    with db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO shares
            (media_id, channel_id, files_json) VALUES(?,?,?)""",
            (str(media_id), int(channel_id), json.dumps(files))
        )


def get_share(media_id):
    with db() as conn:
        row = conn.execute(
            "SELECT channel_id, files_json FROM shares WHERE media_id=?",
            (str(media_id),)
        ).fetchone()
    if not row:
        return None
    return {"channel_id": row[0], "files": json.loads(row[1])}


def register_file_user(media_id, user_id):
    with db() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO file_users(media_id, user_id)
            VALUES(?,?)""",
            (str(media_id), int(user_id))
        )


def count_file_users(media_id):
    with db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM file_users WHERE media_id=?",
            (str(media_id),)
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
    paths = [
        db_file,
        Path(str(db_file) + "-wal"),
        Path(str(db_file) + "-shm")
    ]
    sizes = {
        str(p): p.stat().st_size if p.exists() else 0
        for p in paths
    }

    with db() as conn:
        users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        shares = conn.execute("SELECT COUNT(*) FROM shares").fetchone()[0]
        records = conn.execute(
            "SELECT COUNT(*) FROM file_users"
        ).fetchone()[0]

    return (
        "💾 <b>DATABASE STORAGE STATUS</b>\n\n"
        f"📂 Database: <code>{DB_PATH}</code>\n"
        f"🗃 Main DB: {format_bytes(sizes[str(db_file)])}\n"
        f"📝 WAL: {format_bytes(sizes[str(db_file) + '-wal'])}\n"
        f"🧩 SHM: {format_bytes(sizes[str(db_file) + '-shm'])}\n"
        f"📦 Total SQLite: <b>{format_bytes(sum(sizes.values()))}</b>\n\n"
        f"👥 Registered users: <b>{users:,}</b>\n"
        f"🔗 Saved links: <b>{shares:,}</b>\n"
        f"📥 Download records: <b>{records:,}</b>\n\n"
        "ℹ️ SQLite storage only, not total Render disk usage."
    )


def is_admin(user_id):
    return bool(user_id and int(user_id) == ADMIN_ID)


async def status_command(update, context):
    user = update.effective_user
    if not user or not is_admin(user.id):
        return
    await update.effective_message.reply_text(
        database_storage_report(), parse_mode="HTML"
    )


async def storage_command(update, context):
    await status_command(update, context)


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


async def delete_one(context):
    data = context.job.data
    try:
        await context.bot.delete_message(
            chat_id=data["chat_id"],
            message_id=data["message_id"]
        )
    except Exception:
        pass


async def delete_many(context):
    data = context.job.data
    for mid in data.get("message_ids", []):
        try:
            await context.bot.delete_message(
                chat_id=data["chat_id"], message_id=mid
            )
        except Exception:
            pass


async def keepalive_ping(context):
    if not KEEPALIVE_URL:
        return

    def ping():
        req = urllib.request.Request(
            KEEPALIVE_URL,
            headers={"User-Agent": "Render-KeepAlive/1.0"}
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.status

    try:
        status = await asyncio.to_thread(ping)
        log.info("Keep-alive HTTP %s", status)
    except (URLError, HTTPError, TimeoutError, OSError):
        log.exception("Keep-alive ping failed")


async def backup_to_secret(message, context):
    try:
        await context.bot.copy_message(
            chat_id=SECRET_CHANNEL_ID,
            from_chat_id=message.chat_id,
            message_id=message.message_id
        )
        user = message.from_user
        if user:
            name = (user.first_name or "User")
            name = (name.replace("&", "&amp;")
                    .replace("<", "&lt;").replace(">", "&gt;"))
            await context.bot.send_message(
                chat_id=SECRET_CHANNEL_ID,
                text=(
                    f'👤 Name: <a href="tg://user?id={user.id}">'
                    f'{name}</a>\n\n🆔 ID: <code>{user.id}</code>'
                ),
                parse_mode="HTML"
            )
    except Exception:
        log.exception("Secret-channel backup failed")
        
    saved_files = []
    failed_count = 0
    last_error = ""

    for item in pending["files"]:
        try:
            forwarded = await context.bot.forward_message(
                chat_id=DB_CHANNEL_ID,
                from_chat_id=pending["chat_id"],
                message_id=item["source_message_id"]
            )
            saved_files.append({
                "db_message_id": forwarded.message_id,
                "type": item.get("type", "unknown")
            })
        except Exception as exc:
            failed_count += 1
            last_error = str(exc)
            log.exception("Failed to save item")

    if saved_files:
        media_id = pending["media_id"]
        save_share(media_id, DB_CHANNEL_ID, saved_files)

        me = await context.bot.get_me()
        share_link = f"https://t.me/{me.username}?start={media_id}"
        sessions.pop(key, None)

        result = (
            "✅ Upload completed!\n\n"
            f"📁 Files saved: {len(saved_files)}"
        )
        if failed_count:
            result += f"\n⚠️ Items failed: {failed_count}"
        result += f"\n\n🔗 Your Shareable Link:\n{share_link}"

        await query.message.reply_text(
            result,
            reply_to_message_id=pending.get("media_message_id")
        )
    else:
        error_text = (
            "❌ Failed to save files to the database channel.\n"
            "Check bot admin permissions and posting access."
        )
        if last_error:
            error_text += "\n\nError: " + last_error[:400]

        await query.message.reply_text(error_text)
        sessions.pop(key, None)


# NEW BROADCAST
async def broadcast_command(update, context):
    user = update.effective_user
    message = update.effective_message

    if not user or not is_admin(user.id) or not message:
        return

    target = message.reply_to_message

    if not target:
        await message.reply_text(
            "🎙️ Broadcast instructions:\n\n"
            "1. Send your message, photo, video or file.\n"
            "2. Reply to it with /broadcast.\n\n"
            "Cancel command: /cancel"
        )
        return

    users = get_users()
    status_msg = await message.reply_text(
        "<b>🔁 Broadcast Processing...</b>",
        parse_mode="HTML"
    )

    success = 0
    fail = 0
    blocked = 0

    for uid in users:
        try:
            await context.bot.copy_message(
                chat_id=uid,
                from_chat_id=target.chat_id,
                message_id=target.message_id
            )
            success += 1
        except Exception as exc:
            fail += 1
            error = str(exc).lower()
            if any(term in error for term in (
                "bot was blocked",
                "user is deactivated",
                "chat not found",
                "bot can't initiate conversation"
            )):
                blocked += 1

        await asyncio.sleep(0.04)

    await status_msg.edit_text(
        "<b>🎙️ BROADCAST DONE\n\n"
        f"👥 Total: {len(users)}\n"
        f"✅ Success: {success}\n"
        f"❌ Failed: {fail}\n"
        f"🚫 Blocked (detected): {blocked}</b>",
        parse_mode="HTML"
    )


async def cancel_broadcast_command(update, context):
    user = update.effective_user
    if not user or not is_admin(user.id):
        return

    await update.effective_message.reply_text(
        "❌ No pending broadcast. Nothing is running."
    )


# ERROR HANDLER
async def error_handler(update, context):
    log.error("Unhandled bot error: %s", context.error)


# MAIN
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("info", info))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("storage", storage_command))

    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("cancel", cancel_broadcast_command))
    app.add_handler(
        CommandHandler("cancelbroadcast", cancel_broadcast_command)
    )

    app.add_handler(
        CallbackQueryHandler(upload_now, pattern=r"^upload_now$")
    )

    app.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            receive_message
        )
    )

    app.add_error_handler(error_handler)

    app.job_queue.run_repeating(
        keepalive_ping,
        interval=120,
        first=1,
        name="keepalive_ping"
    )

    log.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
        
