import os
import asyncio
import threading
import requests

from flask import Flask, request
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Я онлайн. Пришли мне список треков — я попробую его проанализировать."
    )


async def show_progress(message, stop_event):
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
                "🔎 **Анализирую...**\n\n"
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
    text = update.message.text

    status_message = await update.message.reply_text(
        "🔎 **Анализирую...**\n\n"
        "`░░░░░░░░░░`\n\n"
        "Пожалуйста, подожди.",
        parse_mode="Markdown"
    )

    stop_event = asyncio.Event()

    progress_task = asyncio.create_task(
        show_progress(status_message, stop_event)
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
                            "Ты музыкальный аналитик. "
                            "Анализируй музыкальные предпочтения "
                            "по списку треков. "
                            "Давай подробный, интересный и "
                            "аргументированный анализ."
                        )
                    },
                    {
                        "role": "user",
                        "content": text
                    }
                ]
            },
            timeout=60
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
            "✅ **Анализ завершён!**\n\n"
            "`██████████`",
            parse_mode="Markdown"
        )

        await update.message.reply_text(answer)

    except requests.exceptions.Timeout:
        stop_event.set()
        await progress_task

        await status_message.edit_text(
            "⏱ **Время ожидания истекло.**\n\n"
            "OpenRouter не успел вернуть ответ за 60 секунд.",
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


telegram_app.add_handler(
    CommandHandler("start", start)
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
    # Запускаем Flask отдельно,
    # чтобы Render видел работающий веб-сервис.
    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True
    )

    flask_thread.start()

    # Удаляем старый webhook.
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook",
            timeout=20
        )
    except Exception:
        pass

    # Запускаем Telegram-бота через polling.
    telegram_app.run_polling(
        drop_pending_updates=True
        )
