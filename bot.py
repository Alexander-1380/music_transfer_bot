#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import logging
from pathlib import Path
from typing import Optional, Dict, Any

from dotenv import load_dotenv

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ===== ЛОГИ =====
logging.basicConfig(
    level=os.environ.get("LOGLEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("music-transfer-bot")

# ===== .env =====
for p in (Path(__file__).with_name(".env"), Path(__file__).parents[1] / ".env"):
    if p.exists():
        load_dotenv(p)
        break

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
PUBLIC_URL         = os.getenv("PUBLIC_URL", "").rstrip("/")  # напр. https://music-transfer-bot.getsome.work/tg-bot
WEBHOOK_SECRET     = os.getenv("WEBHOOK_SECRET", "").strip()
PORT               = int(os.getenv("PORT", "8080"))
LISTEN_ADDR        = os.getenv("LISTEN_ADDR", "0.0.0.0")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is missing in environment/.env")

# ===== ИМПОРТ ЯДРА (без resolve_url) =====
import ya2spotify
from ya2spotify import (
    # Yandex → Spotify
    parse_yandex_track, parse_yandex_artist, parse_yandex_album,
    find_spotify_track, find_spotify_artist, find_spotify_album,
    # Spotify → Yandex
    spotify_get_track_by_id, spotify_get_artist_by_id, spotify_get_album_by_id,
    find_yandex_track, find_yandex_artist, find_yandex_album,
    get_spotify_token,
)

log.info(
    "[BOOT] bot.py=%s | cwd=%s | ya2spotify_file=%s | venv=%s",
    __file__, os.getcwd(), getattr(ya2spotify, "__file__", "unknown"),
    os.getenv("VIRTUAL_ENV", ""),
)

# ===== УТИЛИТЫ =====
URL_RE = re.compile(r'https?://\S+', re.IGNORECASE)

def extract_first_url(text: str) -> Optional[str]:
    m = URL_RE.search(text or "")
    return m.group(0) if m else None

def sp_norm_path(path: str) -> str:
    # Spotify иногда присылает /intl-ru/track/... — нормализуем
    return re.sub(r"^/intl-[a-z]{2}(?:-[a-z]{2})?/", "/", path, flags=re.I)

def detect_kind(url: str) -> Dict[str, str]:
    """Определяем сервис и тип (track/artist/album)."""
    from urllib.parse import urlparse
    up = urlparse(url)
    host = (up.netloc or "").lower().replace("www.","")
    path = up.path or ""

    if "open.spotify.com" in host:
        p = sp_norm_path(path)
        if re.search(r"/track/([A-Za-z0-9]+)", p): return {"service":"spotify", "type":"track"}
        if re.search(r"/artist/([A-Za-z0-9]+)", p): return {"service":"spotify", "type":"artist"}
        if re.search(r"/album/([A-Za-z0-9]+)", p): return {"service":"spotify", "type":"album"}
        return {"service":"spotify", "type":"unknown"}

    if "music.yandex" in host:
        if re.search(r"/track/\d+", path) or re.search(r"/album/\d+/track/\d+", path): return {"service":"yandex", "type":"track"}
        if re.search(r"/artist/\d+", path): return {"service":"yandex", "type":"artist"}
        if re.search(r"/album/\d+/?$", path): return {"service":"yandex", "type":"album"}
        return {"service":"yandex", "type":"unknown"}

    return {"service":"unknown", "type":"unknown"}

def fmt_ok(target: Dict[str, Any]) -> str:
    lines = [f"✅ <b>{target.get('service','?')}</b> / <i>{target.get('type','?')}</i>"]
    if target.get("title"):
        lines.append(f"• Title: <code>{target['title']}</code>")
    if target.get("artists"):
        lines.append(f"• Artist(s): <code>{', '.join(target['artists'])}</code>")
    if target.get("album"):
        lines.append(f"• Album: <code>{target['album']}</code>")
    if target.get("url"):
        lines.append(f"• Link: {target['url']}")
    return "\n".join(lines)

def fmt_err(msg: str) -> str:
    return f"⚠️ {msg}"

# ===== ХЭНДЛЕРЫ =====
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "Привет! Я MusicTransferBot 🎵\n\n"
        "Пришли ссылку из <b>Яндекс.Музыки</b> или <b>Spotify</b> — "
        "я постараюсь найти соответствие и верну ссылку в другом сервисе.\n\n"
        "Поддерживаются: треки, исполнители, альбомы."
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    url = extract_first_url(text)
    if not url:
        await update.message.reply_text("Пришлите ссылку на Яндекс.Музыку или Spotify.")
        return

    kind = detect_kind(url)
    svc, typ = kind["service"], kind["type"]

    try:
        # Получим токен Spotify один раз и кэшируем в context.bot_data
        token = context.bot_data.get("sp_token")
        if token is None:
            cid = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
            csec = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
            if cid and csec:
                token = get_spotify_token(cid, csec)
                context.bot_data["sp_token"] = token

        if svc == "yandex":
            if typ == "track":
                tinfo = parse_yandex_track(url)
                if not token:
                    await update.message.reply_text(fmt_err("Нет Spotify-кредов в .env, не могу искать на Spotify."))
                    return
                sp = find_spotify_track(token, tinfo)
                if not sp:
                    await update.message.reply_text(fmt_err("Трека нет в Spotify."))
                    return
                await update.message.reply_text(
                    fmt_ok({"service":"spotify","type":"track","url":sp.url,"title":sp.title,"artists":sp.artists,"album":sp.album}),
                    parse_mode=ParseMode.HTML, disable_web_page_preview=True
                )
                return

            if typ == "artist":
                ainfo = parse_yandex_artist(url)
                if not token:
                    await update.message.reply_text(fmt_err("Нет Spotify-кредов в .env, не могу искать на Spotify."))
                    return
                sp = find_spotify_artist(token, ainfo.name)
                if not sp:
                    await update.message.reply_text(fmt_err("Артиста нет в Spotify."))
                    return
                await update.message.reply_text(
                    fmt_ok({"service":"spotify","type":"artist","url":sp.url,"title":sp.name}),
                    parse_mode=ParseMode.HTML, disable_web_page_preview=True
                )
                return

            if typ == "album":
                alb = parse_yandex_album(url)
                if not token:
                    await update.message.reply_text(fmt_err("Нет Spotify-кредов в .env, не могу искать на Spotify."))
                    return
                sp = find_spotify_album(token, alb)
                if not sp:
                    await update.message.reply_text(fmt_err("Альбома нет в Spotify."))
                    return
                await update.message.reply_text(
                    fmt_ok({"service":"spotify","type":"album","url":sp.url,"title":sp.title,"artists":sp.artists}),
                    parse_mode=ParseMode.HTML, disable_web_page_preview=True
                )
                return

            await update.message.reply_text("Не удалось распознать тип ссылки Яндекс.Музыки.")

        elif svc == "spotify":
            from urllib.parse import urlparse
            p = sp_norm_path(urlparse(url).path)

            if typ == "track":
                m = re.search(r"/track/([A-Za-z0-9]+)", p)
                if not m:
                    await update.message.reply_text(fmt_err("Не удалось извлечь track id из ссылки Spotify."))
                    return
                info = spotify_get_track_by_id(token, m.group(1))
                ya = find_yandex_track(info)
                if not ya:
                    await update.message.reply_text(fmt_err("Трека нет в Яндекс.Музыке."))
                    return
                await update.message.reply_text(
                    fmt_ok({"service":"yandex","type":"track","url":ya,"title":info.title,"artists":info.artists,"album":info.album}),
                    parse_mode=ParseMode.HTML, disable_web_page_preview=True
                )
                return

            if typ == "artist":
                m = re.search(r"/artist/([A-Za-z0-9]+)", p)
                if not m:
                    await update.message.reply_text(fmt_err("Не удалось извлечь artist id из ссылки Spotify."))
                    return
                info = spotify_get_artist_by_id(token, m.group(1))
                ya = find_yandex_artist(info)
                if not ya:
                    await update.message.reply_text(fmt_err("Артиста нет в Яндекс.Музыке."))
                    return
                await update.message.reply_text(
                    fmt_ok({"service":"yandex","type":"artist","url":ya,"title":info.name}),
                    parse_mode=ParseMode.HTML, disable_web_page_preview=True
                )
                return

            if typ == "album":
                m = re.search(r"/album/([A-Za-z0-9]+)", p)
                if not m:
                    await update.message.reply_text(fmt_err("Не удалось извлечь album id из ссылки Spotify."))
                    return
                info = spotify_get_album_by_id(token, m.group(1))
                ya = find_yandex_album(info)
                if not ya:
                    await update.message.reply_text(fmt_err("Альбома нет в Яндекс.Музыке."))
                    return
                await update.message.reply_text(
                    fmt_ok({"service":"yandex","type":"album","url":ya,"title":info.title,"artists":info.artists}),
                    parse_mode=ParseMode.HTML, disable_web_page_preview=True
                )
                return

            await update.message.reply_text("Не удалось распознать тип ссылки Spotify.")

        else:
            await update.message.reply_text("Пришлите ссылку на Яндекс.Музыку или Spotify.")

    except Exception as e:
        log.exception("Handle failed: %r", e)
        await update.message.reply_text(f"❌ Ошибка: {e!r}")

# ===== ЗАПУСК =====
def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    if PUBLIC_URL:
        log.info("Starting webhook: %s -> http://%s:%s/", PUBLIC_URL, LISTEN_ADDR, PORT)
        app.run_webhook(
            listen=LISTEN_ADDR,
            port=PORT,
            url_path="",  # nginx проксирует /tg-bot/ → сюда
            webhook_url=PUBLIC_URL,
            secret_token=WEBHOOK_SECRET or None,
            drop_pending_updates=True,
        )
    else:
        log.warning("PUBLIC_URL is not set — running in polling mode")
        app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()