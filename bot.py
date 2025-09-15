#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import logging
from pathlib import Path
from typing import Optional

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

# === ЛОГИ ===
logging.basicConfig(
    level=os.environ.get("LOGLEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("music-transfer-bot")

# === ЗАГРУЗКА .env (рядом с ботом или на уровень выше) ===
for p in (Path(__file__).with_name(".env"), Path(__file__).parents[1] / ".env"):
    if p.exists():
        load_dotenv(p)
        break

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
PUBLIC_URL         = os.getenv("PUBLIC_URL", "").rstrip("/")  # напр. https://music-transfer-bot.getsome.work/tg-bot
WEBHOOK_SECRET     = os.getenv("WEBHOOK_SECRET", "").strip()
PORT               = int(os.getenv("PORT", "8080"))
LISTEN_ADDR        = os.getenv("LISTEN_ADDR", "0.0.0.0")  # под nginx обычно 127.0.0.1 или 0.0.0.0

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is missing in environment/.env")

# === ИМПОРТ ЯДРА ===
import ya2spotify
from ya2spotify import resolve_url  # универсальная точка входа (Яндекс <-> Spotify)

# Отладочная подпись в логи — убедимся, что грузится правильный файл
log.info(
    "[BOOT] bot.py path=%s | cwd=%s | ya2spotify=%s | venv=%s",
    __file__,
    os.getcwd(),
    getattr(ya2spotify, "__file__", "unknown"),
    os.getenv("VIRTUAL_ENV", ""),
)


# === ВСПОМОГАТЕЛЬНОЕ ===
URL_RE = re.compile(r'https?://\S+', re.IGNORECASE)

def extract_first_url(text: str) -> Optional[str]:
    m = URL_RE.search(text or "")
    return m.group(0) if m else None


def format_result(res: dict) -> str:
    """Компактный ответ пользователю по результату resolve_url()."""
    if not res.get("ok"):
        return f"⚠️ {res.get('error', 'Не удалось обработать ссылку.')}"
    tgt = res.get("target", {})
    svc = tgt.get("service", "unknown")
    typ = tgt.get("type", "unknown")
    url = tgt.get("url", "—")

    # немного богаче формат, если есть дополнительные поля
    lines = [f"✅ <b>{svc}</b> / <i>{typ}</i>"]
    if "title" in tgt:
        lines.append(f"• Title: <code>{tgt['title']}</code>")
    if "artists" in tgt and tgt["artists"]:
        lines.append(f"• Artist(s): <code>{', '.join(tgt['artists'])}</code>")
    if "album" in tgt and tgt["album"]:
        lines.append(f"• Album: <code>{tgt['album']}</code>")
    lines.append(f"• Link: {url}")
    return "\n".join(lines)


# === ХЭНДЛЕРЫ ===
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
        await update.message.reply_text("Пришли ссылку на Яндекс.Музыку или Spotify.")
        return

    try:
        res = resolve_url(url)  # внутри сам определит тип/направление
        reply = format_result(res)
        await update.message.reply_text(reply, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e:
        log.exception("Resolve failed: %r", e)
        await update.message.reply_text(f"❌ Ошибка: {e!r}")


# === ЗАПУСК ПРИЛОЖЕНИЯ ===
def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # роутинг
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    if PUBLIC_URL:
        # Режим вебхука за Nginx: PUBLIC_URL — полный внешний путь до прокси-локации, напр.
        #   https://music-transfer-bot.getsome.work/tg-bot
        # В nginx location /tg-bot/ проксирует на 127.0.0.1:8080/
        webhook_url = PUBLIC_URL  # без завершающего / — ок
        log.info("Starting webhook: %s -> http://%s:%s/", webhook_url, LISTEN_ADDR, PORT)

        app.run_webhook(
            listen=LISTEN_ADDR,
            port=PORT,
            url_path="",  # принимаем на / (локально за прокси)
            webhook_url=webhook_url,  # внешний путь
            secret_token=WEBHOOK_SECRET or None,
            drop_pending_updates=True,
        )
    else:
        # Фолбэк: polling (удобно локально)
        log.warning("PUBLIC_URL is not set — running in polling mode")
        app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()