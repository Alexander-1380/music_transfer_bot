#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import os
import urllib.parse
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# Импортируем из твоего модуля
from ya2spotify import (
    parse_yandex_track, parse_yandex_artist, parse_yandex_album,
    find_spotify_track, find_spotify_artist, find_spotify_album,
    get_spotify_token,
)

# ---------- Helpers ----------
YANDEX_HOSTS = {"music.yandex.ru", "music.yandex.com", "music.yandex.by", "music.yandex.kz", "music.yandex.ua"}

def detect_kind(url: str) -> str:
    """Возвращает 'track' / 'artist' / 'album' или ''."""
    try:
        p = urllib.parse.urlparse(url)
        if p.netloc not in YANDEX_HOSTS:
            return ""
        path = p.path
        if re.search(r"/album/\d+/track/\d+", path) or re.search(r"/track/\d+", path):
            return "track"
        if re.search(r"/artist/\d+$", path) or re.search(r"/artist/\d+/?", path):
            return "artist"
        if re.search(r"/album/\d+/?$", path):
            return "album"
        return ""
    except Exception:
        return ""

def extract_first_url(text: str) -> str | None:
    m = re.search(r"https?://\S+", text)
    return m.group(0) if m else None

# ---------- Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send me a Yandex.Music link (track / artist / album), and I’ll return the Spotify link."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    url = extract_first_url(text)
    if not url:
        await update.message.reply_text("Please send a Yandex.Music URL.")
        return

    kind = detect_kind(url)
    if not kind:
        await update.message.reply_text("Unsupported URL. Send /track/<id>, /artist/<id>, or /album/<id> from music.yandex.*")
        return

    # Токен Spotify (кэшировать в памяти приложения)
    token = context.bot_data.get("spotify_token")
    if not token:
        cid = os.getenv("SPOTIFY_CLIENT_ID") or ""
        csec = os.getenv("SPOTIFY_CLIENT_SECRET") or ""
        try:
            token = get_spotify_token(cid, csec)
        except Exception as e:
            await update.message.reply_text(f"Spotify auth failed: {e}")
            return
        context.bot_data["spotify_token"] = token

    try:
        if kind == "track":
            tinfo = parse_yandex_track(url)
            sp_t = find_spotify_track(token, tinfo)
            if sp_t:
                await update.message.reply_text(
                    f"*Track*\n"
                    f"Yandex: {tinfo.title} — {', '.join(tinfo.artists)}\n"
                    f"Spotify: [{sp_t.title} — {', '.join(sp_t.artists)}]({sp_t.url})",
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True,
                )
            else:
                await update.message.reply_text("No such track on Spotify.")

        elif kind == "artist":
            ainfo = parse_yandex_artist(url)
            sp_a = find_spotify_artist(token, ainfo.name)
            if sp_a:
                await update.message.reply_text(
                    f"*Artist*\n"
                    f"Yandex: {ainfo.name}\n"
                    f"Spotify: [{sp_a.name}]({sp_a.url})",
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True,
                )
            else:
                await update.message.reply_text("No such artist on Spotify.")

        elif kind == "album":
            alb = parse_yandex_album(url)
            sp_alb = find_spotify_album(token, alb)
            if sp_alb:
                await update.message.reply_text(
                    f"*Album*\n"
                    f"Yandex: {alb.title} — {', '.join(alb.artists)}\n"
                    f"Spotify: [{sp_alb.title} — {', '.join(sp_alb.artists)}]({sp_alb.url})",
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True,
                )
            else:
                await update.message.reply_text("No such album on Spotify.")

    except Exception as e:
        # Любая ошибка — краткое сообщение
        await update.message.reply_text(f"Error: {e}")

# ---------- Entrypoint ----------
def main():
    load_dotenv(Path(__file__).with_name(".env"))
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing in .env")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # long polling
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()