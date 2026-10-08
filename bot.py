import os
import asyncio
import threading
import requests

from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from yandex_music import Client


# =========================
# ENVIRONMENT VARIABLES
# =========================

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]
YANDEX_TOKEN = os.environ["YANDEX_TOKEN"]


# =========================
# APP
# =========================

app = Flask(__name__)

telegram_app = (
    Application.builder()
    .token(TELEGRAM_TOKEN)
    .build()
)


# Yandex Music client
yandex_client = Client(YANDEX_TOKEN).init()


# Last playlist for every Telegram user
user_playlists = {}


# =========================
# START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "Я онлайн.\n\n"
        "Пришли мне список треков.\n\n"
        "После этого напиши /make — "
        "я подберу похожую музыку и найду её в Яндекс Музыке."
    )


# =========================
# PROGRESS ANIMATION
# =========================

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


# =========================
# SAVE PLAYLIST
# =========================

async def message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    text = update.message.text.strip()

    user_playlists[user_id] = text

    await update.message.reply_text(
        "✅ **Плейлист получил.**\n\n"
        "Теперь напиши `/make`.\n\n"
        "Я подберу похожие треки и проверю их в Яндекс Музыке.",
        parse_mode="Markdown"
    )


# =========================
# SEARCH YANDEX MUSIC
# =========================

def search_yandex_track(query):

    try:

        result = yandex_client.search(
            query,
            type_="track",
            page=0
        )

        tracks = result.tracks

        if not tracks:
            return None

        if not tracks.results:
            return None

        track = tracks.results[0]

        title = track.title

        artists = ", ".join(
            artist.name
            for artist in track.artists
        )

        track_id = track.id

        album_id = None

        if track.albums:
            album_id = track.albums[0].id

        if album_id:
            url = (
                f"https://music.yandex.ru/album/"
                f"{album_id}/track/{track_id}"
            )
        else:
            url = (
                f"https://music.yandex.ru/track/{track_id}"
            )

        return {
            "title": title,
            "artists": artists,
            "url": url,
        }

    except Exception as e:

        print(
            "Yandex search error:",
            str(e)
        )

        return None


# =========================
# MAKE PLAYLIST
# =========================

async def make(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    if user_id not in user_playlists:

        await update.message.reply_text(
            "У меня пока нет исходного плейлиста.\n\n"
            "Сначала пришли мне список треков."
        )

        return

    playlist = user_playlists[user_id]

    status_message = await update.message.reply_text(
        "🎧 **Создаю новый плейлист...**\n\n"
        "`░░░░░░░░░░`\n\n"
        "Подбираю похожую музыку.",
        parse_mode="Markdown"
    )

    stop_event = asyncio.Event()

    progress_task = asyncio.create_task(
        show_progress(
            status_message,
            stop_event,
            "Подбираю похожую музыку..."
        )
    )

    try:

        # =========================
        # OPENROUTER
        # =========================

        response = await asyncio.to_thread(
            requests.post,

            "https://openrouter.ai/api/v1/chat/completions",

            headers={
                "Authorization":
                    f"Bearer {OPENROUTER_API_KEY}",

                "Content-Type":
                    "application/json",
            },

            json={

                "model": "openrouter/free",

                "messages": [

                    {
                        "role": "system",

                        "content": (

                            "You are a music curator.\n\n"

                            "Create a NEW playlist based on "
                            "the user's existing playlist.\n\n"

                            "Do NOT analyze the user's personality.\n"
                            "Do NOT explain their psychology.\n"

                            "Find music similar by:\n"
                            "- sound\n"
                            "- genre\n"
                            "- atmosphere\n"
                            "- energy\n"
                            "- production\n"
                            "- artists\n"
                            "- musical style\n\n"

                            "Do not repeat songs from the original playlist.\n\n"

                            "Return exactly 30 real songs.\n\n"

                            "Use this format ONLY:\n\n"

                            "Artist — Song\n"
                            "Artist — Song\n"
                            "Artist — Song\n\n"

                            "No numbering.\n"
                            "No explanations."
                        )
                    },

                    {
                        "role": "user",

                        "content": (
                            "Here is my existing playlist:\n\n"
                            + playlist
                            + "\n\n"
                            "Create 30 similar songs."
                        )
                    }

                ]
            },

            timeout=90
        )


        if response.status_code != 200:

            stop_event.set()

            await progress_task

            await status_message.edit_text(
                f"❌ OpenRouter error: "
                f"{response.status_code}\n\n"
                f"{response.text[:1000]}"
            )

            return


        data = response.json()

        ai_answer = (
            data["choices"][0]
            ["message"]["content"]
        )


        # =========================
        # SEARCH IN YANDEX
        # =========================

        await status_message.edit_text(
            "🔎 **Проверяю треки в Яндекс Музыке...**\n\n"
            "`████░░░░░░`",
            parse_mode="Markdown"
        )


        lines = ai_answer.splitlines()

        results = []

        for line in lines:

            line = line.strip()

            if not line:
                continue

            # Remove accidental numbering
            line = line.lstrip(
                "0123456789.-) "
            ).strip()

            if "—" not in line and "-" not in line:
                continue

            found = await asyncio.to_thread(
                search_yandex_track,
                line
            )

            if found:

                results.append(found)

            # Stop at 30
            if len(results) >= 30:
                break


        stop_event.set()

        await progress_task


        if not results:

            await status_message.edit_text(
                "❌ Не удалось найти "
                "рекомендации в Яндекс Музыке.\n\n"
                "Попробуй ещё раз."
            )

            return


        await status_message.edit_text(
            f"✅ **Готово!**\n\n"
            f"Нашёл {len(results)} треков "
            f"в Яндекс Музыке.",
            parse_mode="Markdown"
        )


        # =========================
        # SEND TRACKS
        # =========================

        for number, track in enumerate(
            results,
            start=1
        ):

            text = (
                f"🎵 **{number}. "
                f"{track['artists']} — "
                f"{track['title']}**"
            )

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "▶️ Открыть в Яндекс Музыке",
                            url=track["url"]
                        )
                    ]
                ]
            )

            await update.message.reply_text(
                text,
                parse_mode="Markdown",
                reply_markup=keyboard
            )

            # Small pause so Telegram isn't flooded
            await asyncio.sleep(0.15)


        await update.message.reply_text(
            "🎧 **Плейлист закончен.**\n\n"
            "Все найденные треки можно открыть "
            "прямо в Яндекс Музыке.",
            parse_mode="Markdown"
        )


    except requests.exceptions.Timeout:

        stop_event.set()

        await progress_task

        await status_message.edit_text(
            "⏱ **Время ожидания истекло.**\n\n"
            "Попробуй `/make` ещё раз.",
            parse_mode="Markdown"
        )


    except Exception as e:

        stop_event.set()

        await progress_task

        print(
            "MAKE ERROR:",
            repr(e)
        )

        await status_message.edit_text(
            "❌ **Произошла ошибка.**\n\n"
            f"`{str(e)[:1000]}`",
            parse_mode="Markdown"
        )


# =========================
# FLASK
# =========================

@app.get("/")
def health():

    return "Bot is alive"


def run_flask():

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False
    )


# =========================
# TELEGRAM
# =========================

telegram_app.add_handler(
    CommandHandler(
        "start",
        start
    )
)

telegram_app.add_handler(
    CommandHandler(
        "make",
        make
    )
)

telegram_app.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        message
    )
)


# =========================
# MAIN
# =========================

if __name__ == "__main__":

    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True
    )

    flask_thread.start()


    try:

        requests.post(
            f"https://api.telegram.org/"
            f"bot{TELEGRAM_TOKEN}/deleteWebhook",
            timeout=20
        )

    except Exception:
        pass


    telegram_app.run_polling(
        drop_pending_updates=True
    )
