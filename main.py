import logging
import os
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from telegram import Update

from downloader import get_download_links

logger = logging.getLogger("main")

COOKIES_MAP = {
    "Instagram": "www.instagram.com_cookies.txt",
    "Facebook":  "www.facebook.com_cookies.txt",
    "LinkedIn":  "www.linkedin.com_cookies.txt",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the Telegram bot (polling) in the background, inside the SAME
    # process as uvicorn, so a single Render service runs both.
    telegram_app = None
    if os.getenv("BOT_TOKEN"):
        try:
            from telegram_bot import build_application

            telegram_app = build_application()
            await telegram_app.initialize()
            await telegram_app.start()
            await telegram_app.updater.start_polling(
                allowed_updates=Update.ALL_TYPES, drop_pending_updates=True
            )
            logger.info("Telegram bot started alongside the API.")
        except Exception:
            logger.exception("Telegram bot failed to start — API will keep running without it.")
            telegram_app = None
    else:
        logger.info("BOT_TOKEN not set — skipping Telegram bot startup.")

    app.state.telegram_app = telegram_app

    # Local run pe GUI browser mein auto-open karo (Render/production pe skip —
    # RENDER env var Render khud set karta hai, wahan display hi nahi hota).
    if not os.environ.get("RENDER"):
        import threading
        import webbrowser

        port = int(os.environ.get("PORT", 8000))
        url = f"http://127.0.0.1:{port}/"
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    try:
        yield
    finally:
        if telegram_app is not None:
            await telegram_app.updater.stop()
            await telegram_app.stop()
            await telegram_app.shutdown()


app = FastAPI(
    title="Universal Video Downloader API",
    version="10.0.0",
    description="YouTube, Instagram, Facebook, LinkedIn, Twitter/X, TikTok, Vimeo, Reddit, 1000+ platforms",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class LinkRequest(BaseModel):
    url: str


def inject_urls(data: dict, url: str, base: str) -> dict:
    enc = quote(url, safe="")
    for item in data.get("video", []):
        item["download_url"] = f"{base}/download/{item['format_id']}?url={enc}"
    for item in data.get("audio", []):
        item["download_url"] = f"{base}/download/{item['format_id']}?url={enc}"
    data["audio_mp3_download_url"] = f"{base}/download/bestaudio?url={enc}"
    data["thumbnail_download_url"] = f"{base}/download/thumbnail?url={enc}"
    if "image" in data:
        data["image"]["thumbnail_download_url"] = f"{base}/download/thumbnail?url={enc}"
    return data


def handle_err(e: Exception):
    msg = str(e).lower()
    if any(w in msg for w in ["login", "sign in", "cookie", "private", "auth"]):
        raise HTTPException(401, detail="Login required.")
    raise HTTPException(400, detail=str(e))


@app.get("/", response_class=HTMLResponse, summary="Downloader UI")
@app.get("/ui", response_class=HTMLResponse, summary="Downloader UI")
def ui():
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(html_path):
        with open(html_path, encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h2>index.html not found</h2>")


@app.get("/status", summary="Health check + cookies status")
def status_check():
    status = {
        p: ("✅ Ready" if os.path.exists(f) else f"❌ Missing — place {f} in this project's folder")
        for p, f in COOKIES_MAP.items()
    }
    return {
        "status":  "ok",
        "version": "10.0.0",
        "cookies_status": status,
        "no_login_needed": ["YouTube ✅", "Twitter/X ✅", "TikTok ✅", "Vimeo ✅", "Reddit ✅", "Dailymotion ✅"],
        "login_needed":    ["Instagram", "Facebook", "LinkedIn"],
    }


@app.post("/links", summary="POST — all formats + download URLs")
def post_links(req: LinkRequest, request: Request):
    try:
        data = get_download_links(req.url, COOKIES_MAP)
        base = str(request.base_url).rstrip("/")
        return inject_urls(data, req.url, base)
    except HTTPException:
        raise
    except Exception as e:
        handle_err(e)


@app.get("/links", summary="GET — all formats + download URLs")
def get_links(
    url: str = Query(..., description="URL of any supported platform"),
    request: Request = None,
):
    try:
        data = get_download_links(url, COOKIES_MAP)
        base = str(request.base_url).rstrip("/")
        return inject_urls(data, url, base)
    except HTTPException:
        raise
    except Exception as e:
        handle_err(e)


@app.get("/download/{format_id}", summary="Download the file")
def download(
    format_id: str,
    url: str = Query(..., description="Video URL"),
    title: str = Query("Media", description="Filename"),
):
    """
    yt-dlp pehle file ko server ke temp folder mein download/merge karta hai
    (isi step mein time lagta hai — yeh yt-dlp/ffmpeg ki wajah se hai, koi
    workaround nahi hai agar audio+video merge karna hai). Uske baad file size
    pata chal jaata hai, isliye Content-Length header set kar paate hain aur
    browser ko sahi progress bar/percentage dikhta hai jab tak actual transfer
    chalta hai. File poora bhejne ke baad temp folder delete ho jaata hai.
    """
    from downloader import prepare_stream, iter_file

    try:
        info = prepare_stream(url, format_id, COOKIES_MAP)
    except Exception as e:
        handle_err(e)
        return

    ext = "mp4"
    if format_id == "bestaudio":
        ext = "mp3"
    elif format_id == "thumbnail":
        ext = info["path"].rsplit(".", 1)[-1] if "." in info["path"] else "jpg"

    mime = {
        "mp4":  "video/mp4",  "webm": "video/webm",
        "mp3":  "audio/mpeg", "m4a":  "audio/mp4",
        "ogg":  "audio/ogg",  "aac":  "audio/aac",
        "jpg":  "image/jpeg", "jpeg": "image/jpeg",
        "webp": "image/webp", "png":  "image/png",
    }.get(ext, "application/octet-stream")

    clean_title = title.replace('"', '').replace("'", "")[:80]
    filename = f"{clean_title}.{ext}"

    return StreamingResponse(
        iter_file(info["path"], info["cleanup"]),
        media_type=mime,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(info["size"]),
        },
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)