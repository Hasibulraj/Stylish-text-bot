import os
import threading
from flask import Flask
import telebot

# =========================
# CONFIGURATION & INITIALIZATION
# =========================
TOKEN = "YOUR_BOT_TOKEN"  # यहाँ अपना असली टेलीग्राम बोट टोकन डालें
bot = telebot.TeleBot(TOKEN)

PRIVATE_CHANNEL_ID = -1003876247954
ADMIN_USER_ID = 5989928539

# इन-मेमोरी स्टोरेज (डेटाबेस के लिए)
db_storage = {}
user_sessions = {}
user_data_store = {}

# =========================
# FLASK KEEP-ALIVE FOR RENDER (24/7 Active)
# =========================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running live on Render!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


# =========================
# /start COMMAND & FILE SHARING
# =========================
@bot.message_handler(commands=['start'])
def handle_start(message):
    text_parts = message.text.split(" ", 1)
    params = text_parts[1] if len(text_parts) > 1 else None

    if not params or params == "None":
        bot.send_message(
            chat_id=message.chat.id,
            text=(
                "<b>📁 Welcome to File Sharing Bot!</b>\n\n"
                "⚡ <b>Send me any file to get a shareable link instantly.</b>\n\n"
                "<i>• Multiple formats supported\n"
                "• Secure & fast sharing</i>"
            ),
            parse_mode="html"
        )
    else:
        media_id = str(params)
        user_id = str(message.from_user.id)
        files = db_storage.get(media_id)

        if not files:
            bot.send_message(message.chat.id, "⚠️ File not found or expired.")
        else:
            # UNIQUE USER STATISTICS
            all_users_key = "stats_unique_users"
            file_users_key = "stats_file_users_" + media_id

            all_users = db_storage.get(all_users_key, [])
            file_users = db_storage.get(file_users_key, [])

            if user_id not in all_users:
                all_users.append(user_id)
                db_storage[all_users_key] = all_users

            if user_id not in file_users:
                file_users.append(user_id)
                db_storage[file_users_key] = file_users

            # SEND FILES VIA COPY MESSAGE (Removes Forward Tag, Keeps .apk Name)
            sent_msgs = []
            last_message_id = None

            for f in files:
                m = None
                try:
                    m = bot.copy_message(
                        chat_id=message.chat.id,
                        from_chat_id=f["chat_id"],
                        message_id=f["message_id"]
                    )
                except Exception:
                    pass

                if m and m.message_id:
                    sent_msgs.append(m.message_id)
                    last_message_id = m.message_id

            # EXPIRY WARNING
            if last_message_id:
                try:
                    note = bot.send_message(
                        chat_id=message.chat.id,
                        text="⚠️ File will be deleted in 29 min. Forward or save it now!",
                        reply_to_message_id=last_message_id
                    )
                    if note and note.message_id:
                        sent_msgs.append(note.message_id)
                except:
                    pass

            # AUTO DELETE AFTER 30 MIN (1800 seconds)
            if sent_msgs:
                def delete_expired_msgs():
                    for mid in sent_msgs:
                        try:
                            bot.delete_message(chat_id=message.chat.id, message_id=mid)
                        except:
                            pass
                
                t = threading.Timer(1800.0, delete_expired_msgs)
                t.start()


# =========================
# /info COMMAND
# =========================
@bot.message_handler(commands=['info'])
def handle_info(message):
    parts = message.text.split(" ", 1)
    if len(parts) == 1:
        msg = bot.send_message(
            message.chat.id,
            "⚠️ <b>Invalid Usage!</b>\n\n📌 <b>Usage:</b> <code>/info MEDIA_ID</code>",
            parse_mode="html"
        )
        def del_msg():
            try:
                bot.delete_message(message.chat.id, msg.message_id)
            except:
                pass
        threading.Timer(200.0, del_msg).start()
        return

    media_id = parts[1].strip()
    files = db_storage.get(media_id)

    if not files:
        msg = bot.send_message(
            message.chat.id,
            f"❌ <b>File Not Found!</b>\n\n🆔 <code>{media_id}</code>",
            parse_mode="html"
        )
        return

    file_users = db_storage.get("stats_file_users_" + media_id, [])
    unique_downloaders = len(set(map(str, file_users)))

    bot.send_message(
        message.chat.id,
        f"📊 <b>FILE Status:</b>\n👥 <b>Total Download:</b> {unique_downloaders}",
        parse_mode="html"
    )


# =========================
# CALLBACK QUERY (UPLOAD NOW BUTTON)
# =========================
@bot.callback_query_handler(func=lambda call: call.data == "upload_now")
def callback_upload_now(call):
    chat_id = call.message.chat.id
    data = user_data_store.get(chat_id, {}).get("upload_pending")

    if data:
        media_id = data["media_id"]
        files = data["files"]
        media_message_id = data.get("media_message_id")

        # Save to database
        db_storage[media_id] = files

        shareable_link = f"https://telegram.me/{bot.get_me().username}?start={media_id}"

        # Clear pending data
        user_data_store[chat_id]["upload_pending"] = None
        
        # Delete old button message
        button_msg_id = user_data_store.get(chat_id, {}).get("upload_button_message_id")
        if button_msg_id:
            try:
                bot.delete_message(chat_id, button_msg_id)
            except:
                pass

        bot.send_message(
            chat_id=chat_id,
            text=f"✅ Upload complete!\n\n🔗 Shareable Link:\n{shareable_link}",
            reply_to_message_id=media_message_id
        )
    else:
        bot.send_message(chat_id, "❌ File not found. Please send the file again.")


# =========================
# ALL MEDIA & FILE HANDLER
# =========================
@bot.message_handler(content_types=['photo', 'video', 'audio', 'voice', 'document', 'animation', 'sticker', 'text'])
def handle_all_messages(message):
    chat_id = message.chat.id
    text = message.text

    # Finish upload command check
    if text == "✅":
        session = user_data_store.get(chat_id, {}).get("upload_pending")
        if session and session.get("files"):
            media_id = session["media_id"]
            files = session["files"]
            db_storage[media_id] = files

            shareable_link = f"https://telegram.me/{bot.get_me().username}?start={media_id}"
            bot.send_message(chat_id, f"✅ Upload complete!\n\n🔗 Share this link:\n{shareable_link}")
            user_data_store[chat_id]["upload_pending"] = None
        else:
            bot.send_message(chat_id, "❌ No media was uploaded.")
        return

    # Check if input is a media file
    media_types = ['photo', 'video', 'audio', 'voice', 'document', 'animation', 'sticker']
    is_media = any(getattr(message, mt, None) is not None for mt in media_types)

    if is_media:
        # 1. सबसे पहले फाइल को आपके प्राइवेट चैनल में फॉरवर्ड करें ताकि .apk नाम/एक्सटेंशन सुरक्षित रहे
        forwarded_msg = None
        try:
            forwarded_msg = bot.forward_message(
                chat_id=PRIVATE_CHANNEL_ID,
                from_chat_id=chat_id,
                message_id=message.message_id
            )
        except Exception as e:
            print(f"Forward error: {e}")

        if forwarded_msg and forwarded_msg.message_id:
            media_entry = {
                "chat_id": PRIVATE_CHANNEL_ID,
                "message_id": forwarded_msg.message_id
            }

            if chat_id not in user_data_store:
                user_data_store[chat_id] = {}

            pending_data = user_data_store[chat_id].get("upload_pending")

            if pending_data and "files" in pending_data:
                pending_data["files"].append(media_entry)
                pending_data["media_message_id"] = message.message_id
                total_files = len(pending_data["files"])

                # Purana button delete karo
                old_btn = user_data_store[chat_id].get("upload_button_message_id")
                if old_btn:
                    try:
                        bot.delete_message(chat_id, old_btn)
                    except:
                        pass

                markup = telebot.types.InlineKeyboardMarkup()
                markup.add(telebot.types.InlineKeyboardButton("⬆️ Upload Now", callback_data="upload_now"))

                sent = bot.send_message(
                    chat_id,
                    f"📁 Total Files Received: {total_files}\n\n👇 Aur file bhejo ya Upload Now dabao.",
                    reply_to_message_id=message.message_id,
                    reply_markup=markup
                )
                user_data_store[chat_id]["upload_button_message_id"] = sent.message_id

            else:
                media_id = f"{chat_id}_{message.message_id}"
                user_data_store[chat_id]["upload_pending"] = {
                    "media_id": media_id,
                    "files": [media_entry],
                    "media_message_id": message.message_id
                }

                markup = telebot.types.InlineKeyboardMarkup()
                markup.add(telebot.types.InlineKeyboardButton("⬆️ Upload Now", callback_data="upload_now"))

                sent = bot.send_message(
                    chat_id,
                    "📁 File receive!\n\n👇 Aur files bhejo ya Upload Now dabao.",
                    reply_to_message_id=message.message_id,
                    reply_markup=markup
                )
                user_data_store[chat_id]["upload_button_message_id"] = sent.message_id
        else:
            bot.send_message(chat_id, "❌ Failed to save file in private channel. Ensure bot is admin there!")


# =========================
# MAIN ENTRY POINT
# =========================
if __name__ == "__main__":
    # Flask सर्वर को बैकग्राउंड में चलाना ताकि Render इसे लाइव रखे
    t = threading.Thread(target=run_flask)
    t.start()

    print("Bot is starting polling...")
    bot.infinity_polling()
    