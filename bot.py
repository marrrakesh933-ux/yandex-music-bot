import os
import requests

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters


TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Я онлайн.\n\n"
        "Пришли мне список музыки или текст — я попробую его проанализировать."
    )


async def message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    await update.message.reply_text("Анализирую...")

    response = requests.post(
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
                        "Анализируй музыкальные предпочтения человека "
                        "по списку исполнителей и треков."
                    ),
                },
                {
                    "role": "user",
                    "content": text,
                },
            ],
        },
        timeout=60,
    )

    if response.status_code != 200:
        await update.message.reply_text(
            f"Ошибка OpenRouter: {response.status_code}"
        )
        return

    data = response.json()
    answer = data["choices"][0]["message"]["content"]

    await update.message.reply_text(answer)


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, message)
    )

    app.run_polling()


if __name__ == "__main__":
    main()
