# -*- coding: utf-8 -*-
# File Store Bot (pyTelegramBotAPI)
# Install: pip install pyTelegramBotAPI

import base64
import telebot

# ================== SETTINGS ==================
BOT_TOKEN = "8878249238:AAFma9mYj2kGe8frpKc5szVf245FIsSrSBE"          # @BotFather से मिला टोकन
STORAGE_CHANNEL_ID = -1003876247954   # आपका प्राइवेट डेटाबेस चैनल ID
OWNER_IDS = [5989928539]               # सिर्फ ये यूज़र फाइल अपलोड कर सकते हैं
# ==============================================

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
BOT_USERNAME = bot.get_me().username


def encode(msg_id: int) -> str:
    return base64.urlsafe_b64encode(str(msg_id).encode()).decode().rstrip("=")


def decode(token: str) -> int:
    token += "=" * (-len(token) % 4)
    return int(base64.urlsafe_b64decode(token.encode()).decode())


@bot.message_handler(commands=["start"])
def start(message):
    parts = message.text.split(maxsplit=1)

    # लिंक से आया हुआ यूज़र -> फाइल भेजो
    if len(parts) == 2:
        try:
            msg_id = decode(parts[1].strip())
            bot.copy_message(
                chat_id=message.chat.id,
                from_chat_id=STORAGE_CHANNEL_ID,
                message_id=msg_id,
                protect_content=False,
            )
        except Exception as e:
            bot.reply_to(message, "❌ फाइल नहीं मिली या लिंक गलत है।")
            print("send error:", e)
        return

    bot.reply_to(
        message,
        "👋 नमस्ते! मुझे कोई भी फाइल भेजिए, मैं उसका शेयर लिंक बना दूँगा।"
        if message.from_user.id in OWNER_IDS
        else "👋 नमस्ते! फाइल पाने के लिए दिए गए लिंक पर क्लिक करें।",
    )


@bot.message_handler(
    content_types=["document", "video", "audio", "photo", "voice", "animation", "video_note"]
)
def save_file(message):
    if message.from_user.id not in OWNER_IDS:
        return bot.reply_to(message, "⛔ आप फाइल अपलोड नहीं कर सकते।")

    try:
        saved = bot.copy_message(
            chat_id=STORAGE_CHANNEL_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
        link = f"https://t.me/{BOT_USERNAME}?start={encode(saved.message_id)}"
        bot.reply_to(message, f"✅ फाइल सेव हो गई!\n\n🔗 आपका लिंक:\n<code>{link}</code>")
    except Exception as e:
        bot.reply_to(message, f"❌ सेव करने में दिक्कत: {e}")


print("Bot is running...")
bot.infinity_polling(skip_pending=True)
