import os
from urllib.parse import quote
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from downloader import get_download_links, stream_download

COOKIES_MAP = {
    "Instagram": "www.instagram.com_cookies.txt",
    "Facebook":  "www.facebook.com_cookies.txt",
    "LinkedIn":  "www.linkedin.com_cookies.txt",
}

app = FastAPI(
    title="Universal Video Downloader API",
    version="10.0.0",
    description="YouTube, Instagram, Facebook, LinkedIn, Twitter/X, TikTok, Vimeo, Reddit, 1000+ platforms",
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


@app.get("/ui", response_class=HTMLResponse, summary="Downloader UI")
def ui():
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(html_path):
        with open(html_path, encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h2>index.html not found</h2>")


@app.get("/", summary="Health check + cookies status")
def root():
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
    The file is NOT saved on the server — it streams directly to the browser.
    Single download, no double download, no temp files left in the downloads folder.
    """
    ext = "mp4"
    if format_id == "bestaudio":
        ext = "mp3"
    elif format_id == "thumbnail":
        ext = "jpg"

    mime = {
        "mp4":  "video/mp4",  "webm": "video/webm",
        "mp3":  "audio/mpeg", "m4a":  "audio/mp4",
        "ogg":  "audio/ogg",  "aac":  "audio/aac",
        "jpg":  "image/jpeg", "jpeg": "image/jpeg",
        "webp": "image/webp", "png":  "image/png",
    }.get(ext, "application/octet-stream")

    clean_title = title.replace('"', '').replace("'", "")[:80]
    filename = f"{clean_title}.{ext}"

    def generate():
        yield from stream_download(url, format_id, COOKIES_MAP)

    return StreamingResponse(
        generate(),
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)