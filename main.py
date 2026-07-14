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



# ==============================
# Serve Frontend
# ==============================

@app.get("/", response_class=HTMLResponse)
def home():

    html_path = os.path.join(
        os.path.dirname(__file__),
        "index.html"
    )

    if os.path.exists(html_path):
        with open(html_path, encoding="utf-8") as f:
            return HTMLResponse(
                content=f.read()
            )

    return HTMLResponse(
        content="<h2>index.html not found</h2>"
    )



# ==============================
# Helper Functions
# ==============================

def inject_urls(data: dict, url: str, base: str) -> dict:

    enc = quote(url, safe="")

    for item in data.get("video", []):
        item["download_url"] = (
            f"{base}/download/{item['format_id']}?url={enc}"
        )

    for item in data.get("audio", []):
        item["download_url"] = (
            f"{base}/download/{item['format_id']}?url={enc}"
        )

    data["audio_mp3_download_url"] = (
        f"{base}/download/bestaudio?url={enc}"
    )

    data["thumbnail_download_url"] = (
        f"{base}/download/thumbnail?url={enc}"
    )


    if "image" in data:
        data["image"]["thumbnail_download_url"] = (
            f"{base}/download/thumbnail?url={enc}"
        )


    return data



def handle_err(e: Exception):

    msg = str(e).lower()

    if any(
        w in msg 
        for w in [
            "login",
            "sign in",
            "cookie",
            "private",
            "auth"
        ]
    ):
        raise HTTPException(
            401,
            detail="Login required."
        )

    raise HTTPException(
        400,
        detail=str(e)
    )



# ==============================
# API Routes
# ==============================


@app.post("/links")
def post_links(
    req: LinkRequest,
    request: Request
):

    try:

        data = get_download_links(
            req.url,
            COOKIES_MAP
        )

        base = str(
            request.base_url
        ).rstrip("/")


        return inject_urls(
            data,
            req.url,
            base
        )


    except HTTPException:
        raise

    except Exception as e:
        handle_err(e)




@app.get("/links")
def get_links(
    url: str = Query(...),
    request: Request = None
):

    try:

        data = get_download_links(
            url,
            COOKIES_MAP
        )


        base = str(
            request.base_url
        ).rstrip("/")


        return inject_urls(
            data,
            url,
            base
        )


    except HTTPException:
        raise

    except Exception as e:
        handle_err(e)




@app.get("/download/{format_id}")
def download(
    format_id: str,
    url: str = Query(...),
    title: str = Query("Media")
):


    ext = "mp4"


    if format_id == "bestaudio":
        ext = "mp3"

    elif format_id == "thumbnail":
        ext = "jpg"



    mime = {

        "mp4": "video/mp4",
        "webm": "video/webm",

        "mp3": "audio/mpeg",
        "m4a": "audio/mp4",

        "jpg": "image/jpeg",
        "png": "image/png"

    }.get(
        ext,
        "application/octet-stream"
    )



    filename = (
        title
        .replace('"',"")
        .replace("'","")
        [:80]
    )



    def generate():

        yield from stream_download(
            url,
            format_id,
            COOKIES_MAP
        )



    return StreamingResponse(
        generate(),
        media_type=mime,
        headers={
            "Content-Disposition":
            f'attachment; filename="{filename}.{ext}"'
        }
    )



# ==============================
# Local Run
# ==============================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )