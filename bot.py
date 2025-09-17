#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

from ya2spotify import resolve_url

logging.basicConfig(
    level=os.getenv("LOGLEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | music-transfer-bot | %(message)s",
)
logger = logging.getLogger(__name__)

def _env(s: str) -> str:
    return (os.getenv(s) or "").strip().strip('"').strip("'")

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Присылай ссылку с music.yandex или open.spotify — конвертирую.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        return
    load_dotenv(Path(__file__).with_name(".env"))
    cid = _env("SPOTIFY_CLIENT_ID")
    csec = _env("SPOTIFY_CLIENT_SECRET")

    res = resolve_url(text, cid, csec)
    if not res.get("ok"):
        await update.message.reply_text(f"⚠️ {res.get('error')}")
        return

    src = res["source"]; dst = res["target"]
    if src["type"] == "track":
        info = src["info"]
        body = [
            "✅ {service} / {type}".format(**dst),
            f"• Title: {info.title}",
            f"• Artist(s): {', '.join(info.artists)}",
        ]
        if getattr(info, "album", None):
            body.append(f"• Album: {info.album}")
        body.append(f"• Link: {dst.get('url')}")
        await update.message.reply_text("\n".join(body))
    elif src["type"] in ("artist", "album"):
        await update.message.reply_text(f"✅ {dst['service']} / {dst['type']}\n{dst.get('url')}")
    else:
        await update.message.reply_text(dst.get("url") or "Готово.")

def main():
    load_dotenv(Path(__file__).with_name(".env"))
    token = _env("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))

    public_url = _env("PUBLIC_URL")
    if public_url:
        logger.info(f"Starting webhook: {public_url} -> http://0.0.0.0:8080/")
        app.run_webhook(
            listen="0.0.0.0",
            port=int(os.getenv("PORT", "8080")),
            url_path="",
            webhook_url=public_url,
        )
    else:
        logger.info("Starting polling mode")
        app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()