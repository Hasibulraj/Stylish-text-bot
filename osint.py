import os
import sqlite3
import asyncio
import logging
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

# Set these in Render -> Environment
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = 5989928539
DB_CHANNEL_ID = -1004377906598
SECRET_CHANNEL_ID = -1004324519714
DB_PATH = os.environ.get("DB_PATH", "bot_data.sqlite3")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

# ---------- SQLite storage ----------
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    with db() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
        conn.execute("""CREATE TABLE IF NOT EXISTS shares (
            media_id TEXT PRIMARY KEY,
            channel_id INTEGER NOT NULL,
            files_json TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS file_users (
            media_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            PRIMARY KEY(media_id, user_id)
        )""")

def register_user(user_id: int):
    with db() as conn:
        conn.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (user_id,))

def get_users():
    with db() as conn:
        return [row[0] for row in conn.execute("SELECT user_id FROM users").fetchall()]

def save_share(media_id, channel_id, files):
    import json
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO shares(media_id, channel_id, files_json) VALUES(?,?,?)",
            (media_id, channel_id, json.dumps(files))
        )

def get_share(media_id):
    import json
    with db() as conn:
        row = conn.execute(
            "SELECT channel_id, files_json FROM shares WHERE media_id=?", (media_id,)
        ).fetchone()
    if not row:
        return None
    return {"channel_id": row[0], "files": json.loads(row[1])}

def register_file_user(media_id, user_id):
    with db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO file_users(media_id, user_id) VALUES(?,?)",
            (media_id, user_id)
        )

# ---------- Helpers ----------
def admin_only(user_id):
    return user_id == ADMIN_ID

def get_file_type(message):
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

async def backup_to_secret(message, context):
    try:
        await context.bot.copy_message(
            chat_id=SECRET_CHANNEL_ID,
            from_chat_id=message.chat_id,
            message_id=message.message_id
        )
        user = message.from_user
        name = (user.first_name or "User").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        caption = f'👤 Name: <a href="tg://user?id={user.id}">{name}</a>\n\n🆔 ID: <code>{user.id}</code>'
        await context.bot.send_message(
            chat_id=SECRET_CHANNEL_ID, text=caption, parse_mode="HTML"
        )
    except Exception:
        log.exception("Secret-channel backup failed")

# ---------- /start and share links ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return
    register_user(user.id)

    if not context.args:
        await message.reply_text(
            "📁 Welcome to File Sharing Bot! ⚡\n\nSend me any file to get a shareable link."
        )
        return

    media_id = str(context.args[0])
    data = get_share(media_id)
    if not data:
        sent = await message.reply_text("❌ File not found.")
        context.job_queue.run_once(
            delete_one, 30,
            data={"chat_id": message.chat_id, "message_id": sent.message_id}
        )
        return

    register_file_user(media_id, user.id)
    sent_ids = []
    for item in data["files"]:
        try:
            copied = await context.bot.copy_message(
                chat_id=message.chat_id,
                from_chat_id=data["channel_id"],
                message_id=item["db_message_id"]
            )
            sent_ids.append(copied.message_id)
        except Exception:
            log.exception("Could not copy shared item")
    if sent_ids:
        note = await message.reply_text(
            "⚠️ These files will be deleted after 10 minutes. Save or forward them now!",
            reply_to_message_id=sent_ids[-1]
        )
        sent_ids.append(note.message_id)
        context.job_queue.run_once(
            delete_many, 1800,
            data={"chat_id": message.chat_id, "message_ids": sent_ids}
        )
    else:
        sent = await message.reply_text("❌ Files Not Found!")
        context.job_queue.run_once(
            delete_one, 15,
            data={"chat_id": message.chat_id, "message_id": sent.message_id}
        )

async def delete_one(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    try:
        await context.bot.delete_message(chat_id=data["chat_id"], message_id=data["message_id"])
    except Exception:
        pass

async def delete_many(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    for message_id in data["message_ids"]:
        try:
            await context.bot.delete_message(chat_id=data["chat_id"], message_id=message_id)
        except Exception:
            pass

# ---------- Upload collection ----------
async def receive_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return
    register_user(user.id)

    # Don't let admin's broadcast confirmation/commands enter upload collection.
    if admin_only(user.id) and message.text and message.text.startswith("/"):
        return

    kind = get_file_type(message)
    if not kind:
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

    sent = await message.reply_text(
        f"📁 Items received: {len(pending['files'])}. Send more or tap Upload Now.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📤 Upload Now", callback_data="upload_now")
        ]])
    )
    pending["button_message_id"] = sent.message_id
    pending["timer_job"] = context.job_queue.run_once(
        expire_upload, 120, data={"key": key, "media_id": pending["media_id"]}
    )

async def expire_upload(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    key = tuple(data["key"])
    sessions = context.application.bot_data.setdefault("sessions", {})
    pending = sessions.get(key)
    if not pending or pending.get("media_id") != data["media_id"]:
        return
    try:
        await context.bot.delete_message(
            chat_id=pending["chat_id"], message_id=pending.get("button_message_id")
        )
    except Exception:
        pass
    sessions.pop(key, None)

async def upload_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    key = (query.message.chat_id, user.id)
    sessions = context.application.bot_data.setdefault("sessions", {})
    pending = sessions.get(key)
    if not pending or not pending["files"]:
        await query.message.reply_text("❌ No pending files found. Please send a file first.")
        return

    if pending.get("timer_job"):
        pending["timer_job"].schedule_removal()
    try:
        await query.message.delete()
    except Exception:
        pass

    saved_files = []
    failed = 0
    for item in pending["files"]:
        try:
            forwarded = await context.bot.forward_message(
                chat_id=DB_CHANNEL_ID,
                from_chat_id=pending["chat_id"],
                message_id=item["source_message_id"]
            )
            saved_files.append({
                "db_message_id": forwarded.message_id,
                "type": item["type"]
            })
        except Exception:
            failed += 1
            log.exception("Could not save upload to database channel")

    if saved_files:
        media_id = pending["media_id"]
        save_share(media_id, DB_CHANNEL_ID, saved_files)
        me = await context.bot.get_me()
        share_link = f"https://t.me/{me.username}?start={media_id}"
        sessions.pop(key, None)
        result = f"✅ Upload completed!\n\n📁 Files saved: {len(saved_files)}"
        if failed:
            result += f"\n⚠️ Items failed: {failed}"
        result += f"\n\n🔗 Your Shareable Link:\n{share_link}"
        await query.message.reply_text(result)
    else:
        await query.message.reply_text(
            "❌ Failed to save items to the database channel. Check that the bot is an admin with permission to post."
        )
        sessions.pop(key, None)

# ---------- Edited-message broadcast ----------
async def edited_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.edited_message
    user = update.effective_user
    if not message or not user or not admin_only(user.id):
        return

    # Every edited message from the admin can be offered for broadcast.
    context.application.bot_data["broadcast_pending"] = {
        "chat_id": message.chat_id,
        "message_id": message.message_id,
    }
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Send Broadcast", callback_data="bc_send")],
        [InlineKeyboardButton("❌ Cancel", callback_data="bc_cancel")]
    ])
    await message.reply_text(
        "📢 Is edited message ko sabhi registered users ko bhejna hai?",
        reply_markup=keyboard
    )

async def broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not admin_only(query.from_user.id):
        return

    if query.data == "bc_cancel":
        context.application.bot_data.pop("broadcast_pending", None)
        await query.message.reply_text("❌ Broadcast cancelled.")
        return

    pending = context.application.bot_data.get("broadcast_pending")
    if not pending:
        await query.message.reply_text("❌ No broadcast message selected.")
        return

    users = get_users()
    sent = 0
    failed = 0
    blocked = 0
    for uid in users:
        try:
            await context.bot.copy_message(
                chat_id=uid,
                from_chat_id=pending["chat_id"],
                message_id=pending["message_id"]
            )
            sent += 1
            # Gentle pacing to reduce Telegram flood-limit risk.
            await asyncio.sleep(0.04)
        except Exception as exc:
            failed += 1
            desc = str(exc).lower()
            if "blocked" in desc or "deactivated" in desc or "chat not found" in desc:
                blocked += 1

    context.application.bot_data.pop("broadcast_pending", None)
    await query.message.reply_text(
        "✅ BROADCAST COMPLETE\n\n"
        f"👥 Total Users: {len(users)}\n"
        f"📨 Sent: {sent}\n"
        f"🚫 Blocked (detected): {blocked}\n"
        f"❌ Failed: {failed}"
    )

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update.effective_user.id):
        return
    await update.effective_message.reply_text(
        "📢 Broadcast trigger: kisi bhi apne message ko edit karo. "
        "Edited message par Send Broadcast button aa jayega."
    )

async def cancel_broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update.effective_user.id):
        return
    context.application.bot_data.pop("broadcast_pending", None)
    await update.effective_message.reply_text("❌ Broadcast cancelled.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.exception("Unhandled bot error", exc_info=context.error)

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("cancelbroadcast", cancel_broadcast_command))
    app.add_handler(CallbackQueryHandler(upload_now, pattern=r"^upload_now$"))
    app.add_handler(CallbackQueryHandler(broadcast_callback, pattern=r"^bc_(send|cancel)$"))
    # Edited messages are separate from normal message handling, avoiding Upload Now collisions.
    app.add_handler(MessageHandler(filters.UpdateType.EDITED_MESSAGE, edited_message))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND & ~filters.UpdateType.EDITED_MESSAGE, receive_message))
    app.add_error_handler(error_handler)
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
    
