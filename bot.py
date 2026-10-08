import os
import asyncio
import threading
import re
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


TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]
YANDEX_TOKEN = os.environ["YANDEX_TOKEN"]

app = Flask(__name__)

telegram_app = (
    Application.builder()
    .token(TELEGRAM_TOKEN)
    .build()
)


# ==================================================
# YANDEX MUSIC
# ==================================================

try:
    yandex_client = Client(
        YANDEX_TOKEN,
        report_unknown_fields=False
    ).init()

    print("Yandex Music client initialized")

except Exception as e:
    yandex_client = None
    print(
        "Yandex Music initialization error:",
        repr(e)
    )


# ==================================================
# DATA
# ==================================================

user_playlists = {}
user_results = {}


# ==================================================
# START
# ==================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "Я онлайн.\n\n"
        "Пришли мне список треков.\n\n"
        "/make — подобрать похожую музыку\n"
        "/playlist — создать плейлист в Яндекс Музыке"
    )


# ==================================================
# PROGRESS
# ==================================================

async def show_progress(
    message,
    stop_event,
    text
):

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
                f"🎧 {text}\n\n"
                f"{frames[index]}\n\n"
                "Пожалуйста, подожди."
            )
        except Exception:
            pass

        index = (
            index + 1
        ) % len(frames)

        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=1.5
            )
        except asyncio.TimeoutError:
            pass


# ==================================================
# RECEIVE PLAYLIST
# ==================================================

async def message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    text = update.message.text.strip()

    if not text:
        await update.message.reply_text(
            "Пришли список треков текстом."
        )
        return

    user_playlists[user_id] = text

    # Старый результат удаляем,
    # потому что исходный плейлист изменился.
    user_results.pop(
        user_id,
        None
    )

    await update.message.reply_text(
        "✅ Плейлист получил.\n\n"
        "Теперь напиши /make."
    )


# ==================================================
# CLEAN AI LINE
# ==================================================

def clean_ai_line(line):

    line = line.strip()

    # Убираем markdown
    line = line.replace("**", "")
    line = line.replace("__", "")
    line = line.replace("`", "")

    # Убираем нумерацию
    line = re.sub(
        r"^\s*\d+\s*[\.\)\-:]\s*",
        "",
        line
    )

    # Убираем bullet
    line = re.sub(
        r"^\s*[-*•]\s*",
        "",
        line
    )

    return line.strip()


# ==================================================
# SPLIT ARTIST / TITLE
# ==================================================

def parse_track_line(line):

    line = clean_ai_line(line)

    if not line:
        return None

    separators = [
        " — ",
        " – ",
        " - ",
        " —",
        "–",
        "-"
    ]

    for separator in separators:

        if separator in line:

            parts = line.split(
                separator,
                1
            )

            artist = parts[0].strip()
            title = parts[1].strip()

            if artist and title:

                return {
                    "artist": artist,
                    "title": title,
                    "query": f"{artist} {title}"
                }

    return {
        "artist": "",
        "title": line,
        "query": line
    }


# ==================================================
# SEARCH YANDEX
# ==================================================

def search_yandex_track(query):

    if yandex_client is None:
        return None

    try:

        print(
            "YANDEX SEARCH:",
            query
        )

        # ------------------------------------------
        # FIRST SEARCH
        # ------------------------------------------

        result = yandex_client.search(
            query,
            type_="track",
            page=0
        )

        if (
            result
            and result.tracks
            and result.tracks.results
        ):

            track = result.tracks.results[0]

        else:

            # --------------------------------------
            # SECOND SEARCH:
            # title only / simplified query
            # --------------------------------------

            parsed = parse_track_line(query)

            fallback_query = (
                parsed["title"]
                if parsed
                else query
            )

            print(
                "YANDEX FALLBACK:",
                fallback_query
            )

            result = yandex_client.search(
                fallback_query,
                type_="track",
                page=0
            )

            if (
                not result
                or not result.tracks
                or not result.tracks.results
            ):
                return None

            track = result.tracks.results[0]

        # ------------------------------------------
        # DATA
        # ------------------------------------------

        title = track.title

        artists = ", ".join(
            artist.name
            for artist in track.artists
        )

        track_id = track.id

        album_id = None

        if track.albums:

            album_id = track.albums[0].id

        # ------------------------------------------
        # URL
        # ------------------------------------------

        if album_id:

            url = (
                "https://music.yandex.ru/album/"
                f"{album_id}/track/{track_id}"
            )

        else:

            url = (
                "https://music.yandex.ru/track/"
                f"{track_id}"
            )

        print(
            "YANDEX FOUND:",
            artists,
            "-",
            title
        )

        return {
            "title": title,
            "artists": artists,
            "track_id": track_id,
            "album_id": album_id,
            "url": url,
        }

    except Exception as e:

        print(
            "YANDEX SEARCH ERROR:",
            repr(e)
        )

        return None


# ==================================================
# MAKE
# ==================================================

async def make(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    if user_id not in user_playlists:

        await update.message.reply_text(
            "Сначала пришли мне исходный список треков."
        )

        return

    if yandex_client is None:

        await update.message.reply_text(
            "❌ Яндекс Музыка не подключена.\n\n"
            "Проверь YANDEX_TOKEN в Render."
        )

        return

    source_playlist = user_playlists[user_id]

    status_message = await update.message.reply_text(
        "🎧 Создаю новый плейлист...\n\n"
        "░░░░░░░░░░\n\n"
        "Подбираю похожую музыку."
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

        # ==================================================
        # OPENROUTER
        # ==================================================

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
                            "You are a professional music curator.\n\n"

                            "The user will give you an existing "
                            "playlist.\n\n"

                            "Create a NEW playlist of 30 REAL songs "
                            "that sound similar to it.\n\n"

                            "Match:\n"
                            "- genre\n"
                            "- sound\n"
                            "- atmosphere\n"
                            "- energy\n"
                            "- production\n"
                            "- artists\n"
                            "- musical style\n\n"

                            "Do NOT analyze personality.\n"
                            "Do NOT explain psychology.\n"
                            "Do NOT explain your choices.\n\n"

                            "Do NOT repeat songs from the source playlist.\n\n"

                            "IMPORTANT:\n"
                            "Return ONLY song lines.\n"
                            "One song per line.\n\n"

                            "Format:\n"
                            "Artist — Song\n\n"

                            "Exactly 30 songs."
                        )
                    },

                    {
                        "role": "user",

                        "content": (
                            "SOURCE PLAYLIST:\n\n"
                            + source_playlist
                            + "\n\n"
                            "Give me 30 similar real songs."
                        )
                    }

                ]
            },

            timeout=90
        )

        # ==================================================
        # OPENROUTER ERROR
        # ==================================================

        if response.status_code != 200:

            stop_event.set()

            try:
                await progress_task
            except Exception:
                pass

            await status_message.edit_text(
                "❌ OpenRouter error:\n\n"
                f"{response.status_code}\n\n"
                f"{response.text[:1500]}"
            )

            return

        # ==================================================
        # PARSE RESPONSE
        # ==================================================

        data = response.json()

        ai_answer = (
            data["choices"][0]["message"]["content"]
        )

        print(
            "========== OPENROUTER =========="
        )

        print(ai_answer)

        print(
            "================================"
        )

        stop_event.set()

        try:
            await progress_task
        except Exception:
            pass

        await status_message.edit_text(
            "🔎 ИИ подобрал треки.\n\n"
            "Теперь ищу их в Яндекс Музыке..."
        )

        # ==================================================
        # SEARCH
        # ==================================================

        results = []

        parsed_lines = []

        for raw_line in ai_answer.splitlines():

            parsed = parse_track_line(
                raw_line
            )

            if parsed:
                parsed_lines.append(parsed)

        print(
            "AI TRACKS:",
            len(parsed_lines)
        )

        # Ищем максимум 40 кандидатов,
        # чтобы получить до 30 хороших результатов.
        for parsed in parsed_lines[:40]:

            query = parsed["query"]

            found = await asyncio.to_thread(
                search_yandex_track,
                query
            )

            if found:

                duplicate = False

                for existing in results:

                    if (
                        existing["track_id"]
                        ==
                        found["track_id"]
                    ):
                        duplicate = True
                        break

                if not duplicate:

                    results.append(found)

            if len(results) >= 30:
                break

        # ==================================================
        # NOTHING FOUND
        # ==================================================

        if not results:

            print(
                "NO YANDEX RESULTS"
            )

            await status_message.edit_text(
                "❌ Яндекс Музыка не вернула ни одного трека.\n\n"
                "Посмотри Render → Logs: там будут строки "
                "`YANDEX SEARCH` и `YANDEX SEARCH ERROR`."
            )

            return

        # ==================================================
        # SAVE RESULTS
        # ==================================================

        user_results[user_id] = results

        await status_message.edit_text(
            "✅ Готово!\n\n"
            f"Нашёл {len(results)} треков "
            "в Яндекс Музыке.\n\n"
            "Можно написать /playlist — "
            "и я создам настоящий плейлист."
        )

        # ==================================================
        # SEND TRACKS
        # ==================================================

        for number, track in enumerate(
            results,
            start=1
        ):

            text = (
                f"🎵 {number}. "
                f"{track['artists']} — "
                f"{track['title']}"
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

            try:

                await update.message.reply_text(
                    text,
                    reply_markup=keyboard
                )

            except Exception as e:

                print(
                    "TELEGRAM SEND ERROR:",
                    repr(e)
                )

                await update.message.reply_text(
                    f"{number}. "
                    f"{track['artists']} - "
                    f"{track['title']}\n\n"
                    f"{track['url']}"
                )

            await asyncio.sleep(
                0.15
            )

        await update.message.reply_text(
            "🎧 Всё.\n\n"
            "Чтобы собрать эти треки "
            "в один плейлист Яндекс Музыки:\n\n"
            "/playlist"
        )

    except requests.exceptions.Timeout:

        stop_event.set()

        try:
            await progress_task
        except Exception:
            pass

        await status_message.edit_text(
            "⏱ OpenRouter слишком долго отвечает.\n\n"
            "Попробуй /make ещё раз."
        )

    except Exception as e:

        stop_event.set()

        try:
            await progress_task
        except Exception:
            pass

        print(
            "MAKE ERROR:",
            repr(e)
        )

        await status_message.edit_text(
            "❌ Ошибка:\n\n"
            f"{str(e)[:1500]}"
        )


# ==================================================
# CREATE PLAYLIST
# ==================================================

def create_yandex_playlist(
    results
):

    if yandex_client is None:

        raise Exception(
            "Yandex client is not initialized"
        )

    # Создаём плейлист
    playlist = (
        yandex_client.users_playlists_create(
            "AI Playlist",
            visibility="private"
        )
    )

    if not playlist:

        raise Exception(
            "Yandex did not create playlist"
        )

    kind = playlist.kind

    added = 0

    # ВАЖНО:
    # перед каждым добавлением получаем
    # актуальную ревизию плейлиста.
    for track in results:

        track_id = track.get(
            "track_id"
        )

        album_id = track.get(
            "album_id"
        )

        if not track_id or not album_id:
            continue

        try:

            current_playlist = (
                yandex_client.users_playlists(
                    kind
                )
            )

            revision = (
                current_playlist.revision
            )

            track_count = getattr(
                current_playlist,
                "track_count",
                added
            )

            yandex_client.users_playlists_insert_track(
                kind,
                track_id,
                album_id,
                at=track_count,
                revision=revision
            )

            added += 1

            print(
                "PLAYLIST ADDED:",
                track["artists"],
                "-",
                track["title"]
            )

        except Exception as e:

            print(
                "PLAYLIST ADD ERROR:",
                repr(e)
            )

    # UID аккаунта
    try:

        uid = (
            yandex_client.me.account.uid
        )

    except Exception:

        uid = None

    if uid:

        url = (
            "https://music.yandex.ru/users/"
            f"{uid}/playlists/{kind}"
        )

    else:

        url = (
            "https://music.yandex.ru/"
        )

    return {
        "url": url,
        "added": added,
        "kind": kind,
    }


# ==================================================
# /PLAYLIST
# ==================================================

async def playlist_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    if yandex_client is None:

        await update.message.reply_text(
            "❌ Яндекс Музыка не подключена."
        )

        return

    if user_id not in user_results:

        await update.message.reply_text(
            "У меня пока нет готового списка.\n\n"
            "Сначала сделай:\n"
            "/make"
        )

        return

    results = user_results[user_id]

    status_message = await update.message.reply_text(
        "📀 Создаю плейлист в Яндекс Музыке...\n\n"
        "Добавляю треки."
    )

    try:

        result = await asyncio.to_thread(
            create_yandex_playlist,
            results
        )

        added = result["added"]
        url = result["url"]

        if added == 0:

            await status_message.edit_text(
                "❌ Плейлист создался, "
                "но ни одного трека добавить не удалось.\n\n"
                "Проверь Render Logs."
            )

            return

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🎧 Открыть плейлист",
                        url=url
                    )
                ]
            ]
        )

        await status_message.edit_text(
            "✅ Плейлист создан!\n\n"
            f"Добавлено треков: {added}\n\n"
            "Он находится в твоём аккаунте "
            "Яндекс Музыки.",
            reply_markup=keyboard
        )

    except Exception as e:

        print(
            "PLAYLIST ERROR:",
            repr(e)
        )

        await status_message.edit_text(
            "❌ Не удалось создать плейлист.\n\n"
            f"{str(e)[:1500]}"
        )


# ==================================================
# FLASK
# ==================================================

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


# ==================================================
# TELEGRAM
# ==================================================

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
    CommandHandler(
        "playlist",
        playlist_command
    )
)

telegram_app.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        message
    )
)


# ==================================================
# RUN
# ==================================================

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
