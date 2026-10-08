import os
import requests
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]
RENDER_URL = os.environ["RENDER_EXTERNAL_URL"]

app = Flask(__name__)

telegram_app = Application.builder().token(TELEGRAM_TOKEN).build()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Я онлайн. Пришли мне список треков — я попробую его проанализировать."
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
                    "content": "Ты музыкальный аналитик. Анализируй музыкальные предпочтения по списку треков."
                },
                {
                    "role": "user",
                    "content": text
                }
            ]
        },
        timeout=60
    )

    if response.status_code != 200:
        await update.message.reply_text(
            f"Ошибка OpenRouter: {response.status_code}"
        )
        return

    data = response.json()
    answer = data["choices"][0]["message"]["content"]

    await update.message.reply_text(answer)


telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(
    MessageHandler(filters.TEXT & ~filters.COMMAND, message)
)


@app.get("/")
def health():
    return "Bot is alive"


@app.post("/telegram")
def telegram_webhook():
    import asyncio

    data = request.get_json(force=True)
    update = Update.de_json(data, telegram_app.bot)

    asyncio.run(telegram_app.initialize())
    asyncio.run(telegram_app.process_update(update))
    asyncio.run(telegram_app.shutdown())

    return "OK"


if __name__ == "__main__":
    import requests as req

    webhook_url = RENDER_URL + "/telegram"

    req.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook",
        json={"url": webhook_url},
        timeout=20
    )

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
