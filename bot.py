import os
import asyncio
import threading
import requests

from flask import Flask
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]

app = Flask(__name__)

telegram_app = Application.builder().token(TELEGRAM_TOKEN).build()

# Здесь храним последний отправленный пользователем плейлист
user_playlists = {}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Я онлайн.\n\n"
        "Пришли мне свой плейлист списком треков.\n"
        "После этого напиши /make — я подберу похожую музыку."
    )


async def make(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in user_playlists:
        await update.message.reply_text(
            "У меня пока нет твоего плейлиста.\n\n"
            "Сначала пришли список треков, а потом используй /make."
        )
        return

    playlist = user_playlists[user_id]

    status_message = await update.message.reply_text(
        "🎧 **Создаю новый плейлист...**\n\n"
        "`░░░░░░░░░░`\n\n"
        "Подбираю музыку, похожую на твою.",
        parse_mode="Markdown"
    )

    stop_event = asyncio.Event()

    progress_task = asyncio.create_task(
        show_progress(status_message, stop_event, "Подбираю похожую музыку...")
    )

    try:
        response = await asyncio.to_thread(
            requests.post,
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "openrouter/free",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Ты музыкальный куратор. "
                            "Твоя задача — создавать НОВЫЙ плейлист "
                            "на основе уже существующего списка треков.\n\n"

                            "Не анализируй пользователя и не пиши психологический "
                            "портрет. Не объясняй музыкальные предпочтения.\n\n"

                            "Нужно подобрать музыку, которая действительно "
                            "похожа на исходный плейлист по звучанию, жанрам, "
                            "атмосфере, исполнителям, энергии и стилю.\n\n"

                            "ВАЖНО:\n"
                            "- Не повторяй треки из исходного списка.\n"
                            "- Старайся находить менее очевидные, но подходящие "
                            "варианты.\n"
                            "- Можно использовать разных исполнителей.\n"
                            "- Подбирай 30 треков.\n"
                            "- Каждый трек должен существовать.\n"
                            "- Не придумывай названия песен.\n\n"

                            "Формат ответа строго такой:\n"
                            "1. Исполнитель — Трек\n"
                            "2. Исполнитель — Трек\n"
                            "3. Исполнитель — Трек\n"
                            "и так далее до 30."
                        )
                    },
                    {
                        "role": "user",
                        "content": (
                            "Вот мой исходный плейлист:\n\n"
                            + playlist
                            + "\n\n"
                            "Создай на его основе новый плейлист "
                            "из 30 похожих треков."
                        )
                    }
                ]
            },
            timeout=90
        )

        stop_event.set()
        await progress_task

        if response.status_code != 200:
            await status_message.edit_text(
                f"❌ **Ошибка OpenRouter:** {response.status_code}\n\n"
                f"{response.text[:1000]}",
                parse_mode="Markdown"
            )
            return

        data = response.json()

        answer = data["choices"][0]["message"]["content"]

        await status_message.edit_text(
            "✅ **Новый плейлист готов!**\n\n"
            "`██████████`",
            parse_mode="Markdown"
        )

        await update.message.reply_text(
            "🎧 **Вот что я подобрал:**\n\n" + answer,
            parse_mode="Markdown"
        )

    except requests.exceptions.Timeout:
        stop_event.set()
        await progress_task

        await status_message.edit_text(
            "⏱ **Время ожидания истекло.**\n\n"
            "Попробуй ещё раз через несколько секунд.",
            parse_mode="Markdown"
        )

    except Exception as e:
        stop_event.set()
        await progress_task

        await status_message.edit_text(
            "❌ **Произошла ошибка.**\n\n"
            f"`{str(e)[:1000]}`",
            parse_mode="Markdown"
        )


async def show_progress(message, stop_event, text):
    frames = [
        "░░░░░░░░░░",
        "█░░░░░░░░░",
        "██░░░░░░░░",
        "███░░░░░░░",
        "████░░░░░░",
        "█████░░░░░",
        "██████░░░░",
        "███████░░░",
        "████████░░",
        "█████████░",
        "██████████",
        "█████████░",
        "████████░░",
        "███████░░░",
        "██████░░░░",
        "█████░░░░░",
        "████░░░░░░",
        "███░░░░░░░",
        "██░░░░░░░░",
        "█░░░░░░░░░",
    ]

    index = 0

    while not stop_event.is_set():
        try:
            await message.edit_text(
                f"🎧 **{text}**\n\n"
                f"`{frames[index]}`\n\n"
                "Пожалуйста, подожди.",
                parse_mode="Markdown"
            )
        except Exception:
            pass

        index = (index + 1) % len(frames)

        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=1.5
            )
        except asyncio.TimeoutError:
            pass


async def message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # Сохраняем присланный пользователем плейлист
    user_playlists[user_id] = text

    await update.message.reply_text(
        "✅ Плейлист получил.\n\n"
        "Теперь напиши /make — и я подберу "
        "новую музыку, похожую на него."
    )


telegram_app.add_handler(
    CommandHandler("start", start)
)

telegram_app.add_handler(
    CommandHandler("make", make)
)

telegram_app.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        message
    )
)


@app.get("/")
def health():
    return "Bot is alive"


def run_flask():
    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False
    )


if __name__ == "__main__":
    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True
    )

    flask_thread.start()

    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook",
            timeout=20
        )
    except Exception:
        pass

    telegram_app.run_polling(
        drop_pending_updates=True
    )
