

import logging
import os
import re

import httpx
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ─────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_BASE_URL = os.getenv("API_BASE_URL", "https://media-downloader-hvwf.onrender.com/").rstrip("/")

if not BOT_TOKEN:
    raise SystemExit("BOT_TOKEN is missing. Add BOT_TOKEN=xxxx to your .env file.")

MAX_VIDEO_BUTTONS = 8  # keep the keyboard from getting too long
REQUEST_TIMEOUT = 30.0

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("telegram_bot")

URL_PATTERN = re.compile(r"https?://\S+")


def _human_size(num_bytes):
    if not num_bytes:
        return ""
    size = float(num_bytes)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.0f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


# ─────────────────────────────────────────────────────────────────────────
# Handlers
# ─────────────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! Send me a video/audio URL (example:-YouTube, Instagram, Facebook, "
        "Twitter/X, TikTok, Vimeo, Reddit, etc.).\n\n"
        "I'll reply with download buttons — tap one and it will download "
        "straight to your device through your browser."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    match = URL_PATTERN.search(text)

    if not match:
        await update.message.reply_text("That doesn't look like a valid link. Please send a URL.")
        return

    url = match.group(0)
    status_msg = await update.message.reply_text("🔎 Checking the link...")

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(f"{API_BASE_URL}/links", params={"url": url})
    except httpx.RequestError as e:
        await status_msg.edit_text(
            f"❌ Could not reach the download server at {API_BASE_URL}.\n"
            f"Make sure main.py is running.\n\nDetails: {e}"
        )
        return

    if resp.status_code != 200:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        await status_msg.edit_text(f"❌ Error ({resp.status_code}): {detail}")
        return

    data = resp.json()
    title = (data.get("title") or "Media")[:60]

    buttons = []

    # Video options
    for v in data.get("video", [])[:MAX_VIDEO_BUTTONS]:
        size = _human_size(v.get("filesize"))
        label = f"🎬 {v['quality']} {v['ext']}" + (f" ({size})" if size else "")
        download_url = v.get("download_url")
        if download_url:
            buttons.append([InlineKeyboardButton(label, url=download_url)])

    # Best audio -> MP3
    mp3_url = data.get("audio_mp3_download_url")
    if mp3_url:
        buttons.append([InlineKeyboardButton("🎵 MP3 Audio (best)", url=mp3_url)])

    # Thumbnail
    thumb_url = data.get("thumbnail_download_url")
    if thumb_url:
        buttons.append([InlineKeyboardButton("🖼 Thumbnail", url=thumb_url)])

    if not buttons:
        await status_msg.edit_text("❌ No downloadable formats were found for this link.")
        return

    caption = f"*{title}*\n\nTap a format to download — it opens in your browser and downloads directly, no size limit."
    await status_msg.edit_text(
        caption, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons)
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled exception", exc_info=context.error)


# ─────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    logger.info(f"Bot starting (polling mode). Using API at {API_BASE_URL} ...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()