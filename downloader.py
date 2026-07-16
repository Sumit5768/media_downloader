"""
downloader.py — Universal yt-dlp wrapper
YouTube, Instagram, Facebook, LinkedIn, Twitter/X, TikTok, Vimeo, Reddit, 1000+ sites
"""

import yt_dlp
import os
import uuid
import urllib.request
from urllib.parse import urlparse


def detect_platform(url: str) -> str:
    host = urlparse(url).netloc.lower().replace("www.", "")
    mapping = {
        "youtube.com": "YouTube",   "youtu.be": "YouTube",
        "instagram.com": "Instagram",
        "facebook.com": "Facebook", "fb.watch": "Facebook",
        "linkedin.com": "LinkedIn",
        "twitter.com": "Twitter/X", "x.com": "Twitter/X",
        "tiktok.com": "TikTok",
        "vimeo.com": "Vimeo",
        "reddit.com": "Reddit",
        "dailymotion.com": "Dailymotion",
    }
    for domain, name in mapping.items():
        if domain in host:
            return name
    return "Other"


def _get_cookies(url: str, cookies_map: dict) -> str | None:
    platform = detect_platform(url)
    # Script ki directory mein dhundho (D:\API\)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    cf = cookies_map.get(platform)
    if cf:
        # Pehle as-is check karo, phir script dir mein
        if os.path.exists(cf):
            return cf
        full_path = os.path.join(script_dir, cf)
        if os.path.exists(full_path):
            return full_path
    
    # Generic fallback
    for name in ["cookies.txt"]:
        if os.path.exists(name):
            return name
        full = os.path.join(script_dir, name)
        if os.path.exists(full):
            return full
    return None


def _opts(cookies_file=None, extra=None, url=None):
    o = {
        "quiet":       True,
        "no_warnings": True,
        "noplaylist":  True,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        },
    }
    # LinkedIn ke liye extra headers
    if url and "linkedin.com" in url:
        o["http_headers"].update({
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.linkedin.com/",
        })
    if cookies_file and os.path.exists(cookies_file):
        o["cookiefile"] = cookies_file
    if extra:
        o.update(extra)
    return o


def get_download_links(url: str, cookies_map: dict = None) -> dict:
    cf = _get_cookies(url, cookies_map or {})

    info = None
    try:
        with yt_dlp.YoutubeDL(_opts(cf, url=url)) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        import urllib.request
        import re
        try:
            req = urllib.request.Request(url, method='GET' if 'drive.google.com' in url else 'HEAD')
            req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
            with urllib.request.urlopen(req, timeout=5) as res:
                ctype = res.headers.get('Content-Type', '')
                if 'image/' in ctype:
                    return {
                        "platform": "Image",
                        "title": url.split('/')[-1].split('?')[0] or "Direct Image",
                        "thumbnail": url,
                        "video": [], "audio": []
                    }
                elif 'text/html' in ctype and 'drive.google.com' in url:
                    html = res.read().decode('utf-8', errors='ignore')
                    m = re.search(r'<meta property="og:image" content="([^"]+)">', html)
                    if m:
                        return {
                            "platform": "Google Drive",
                            "title": "Google Drive Photo",
                            "thumbnail": m.group(1),
                            "video": [], "audio": []
                        }
        except Exception:
            pass
        raise Exception(f"Unsupported or yt-dlp error: {e}")

    formats  = info.get("formats") or []
    platform = detect_platform(url)

    # ── Video ──────────────────────────────────────────────────────
    seen_v, videos = set(), []
    for f in formats:
        height = f.get("height")
        width  = f.get("width")
        vcodec = f.get("vcodec", "none")
        acodec = f.get("acodec", "none")
        fmt_id = f.get("format_id", "")
        ext    = f.get("ext", "")
        tbr    = f.get("tbr")  # total bitrate — LinkedIn ke liye fallback

        # Skip karo agar video stream hi nahi hai
        if not fmt_id or vcodec in ("none", None, ""):
            continue

        # Quality label — height se, ya width se, ya tbr se, ya format_note se
        if height:
            quality = f"{height}p"
        elif width:
            quality = f"{width}w"
        elif tbr:
            quality = f"{int(tbr)}kbps"
        else:
            note = f.get("format_note", "").strip()
            quality = note if note else fmt_id

        key = (quality, ext)
        if key not in seen_v:
            seen_v.add(key)
            videos.append({
                "format_id": fmt_id,
                "quality":   quality,
                "ext":       ext,
                "filesize":  f.get("filesize") or f.get("filesize_approx"),
                "fps":       f.get("fps"),
                "has_audio": acodec not in ("none", None, ""),
                "note":      f.get("format_note", ""),
            })

    def _sort_key(x):
        q = x["quality"]
        # height wale pehle (e.g. 1080p)
        if q.endswith("p") and q[:-1].isdigit():
            return (2, int(q[:-1]))
        # width wale (e.g. 1920w)
        if q.endswith("w") and q[:-1].isdigit():
            return (1, int(q[:-1]))
        # kbps wale
        if q.endswith("kbps") and q[:-4].isdigit():
            return (1, int(q[:-4]))
        return (0, 0)

    videos.sort(key=_sort_key, reverse=True)

    # ── Audio ──────────────────────────────────────────────────────
    seen_a, audios = set(), []
    for f in formats:
        vcodec = f.get("vcodec", "none")
        acodec = f.get("acodec", "none")
        fmt_id = f.get("format_id", "")
        ext    = f.get("ext", "")
        abr    = f.get("abr")

        if vcodec in ("none", None) and acodec not in ("none", None) and fmt_id:
            label = f"{int(abr)}kbps" if abr else (acodec or "audio")
            if (label, ext) not in seen_a:
                seen_a.add((label, ext))
                audios.append({
                    "format_id": fmt_id,
                    "quality":   label,
                    "ext":       ext,
                    "filesize":  f.get("filesize") or f.get("filesize_approx"),
                    "abr":       abr,
                })

    audios.sort(key=lambda x: x["abr"] or 0, reverse=True)

    # ── Thumbnails ─────────────────────────────────────────────────
    all_thumbs = [t["url"] for t in (info.get("thumbnails") or []) if t.get("url")]
    best_thumb = info.get("thumbnail") or (all_thumbs[-1] if all_thumbs else None)

    return {
        "platform":   platform,
        "title":      info.get("title") or (info.get("description") or "")[:100],
        "thumbnail":  best_thumb,
        "duration":   info.get("duration"),
        "uploader":   info.get("uploader") or info.get("channel"),
        "view_count": info.get("view_count"),
        "video":      videos,
        "audio":      audios,
        "image": {
            "thumbnail":  best_thumb,
            "thumbnails": all_thumbs,
        },
    }


def download_file(url: str, format_id: str,
                  output_dir="downloads", cookies_map: dict = None) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    uid = str(uuid.uuid4())
    cf  = _get_cookies(url, cookies_map or {})

    # Thumbnail
    if format_id == "thumbnail":
        thumb = None
        try:
            with yt_dlp.YoutubeDL(_opts(cf)) as ydl:
                info = ydl.extract_info(url, download=False)
            thumb = info.get("thumbnail")
        except:
            pass
            
        if not thumb:
            import urllib.request
            import re
            req = urllib.request.Request(url, method='GET' if 'drive.google.com' in url else 'HEAD')
            req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
            try:
                with urllib.request.urlopen(req, timeout=5) as res:
                    ctype = res.headers.get('Content-Type', '')
                    if 'image/' in ctype:
                        thumb = url
                    elif 'text/html' in ctype and 'drive.google.com' in url:
                        html = res.read().decode('utf-8', errors='ignore')
                        m = re.search(r'<meta property="og:image" content="([^"]+)">', html)
                        if m: thumb = m.group(1)
            except:
                pass

        if not thumb:
            raise ValueError("Thumbnail ya image nahi mili")
            
        ext  = thumb.split("?")[0].rsplit(".", 1)[-1] or "jpg"
        ext  = ext if len(ext) <= 5 else "jpg"
        path = os.path.join(output_dir, f"{uid}.{ext}")
        
        req = urllib.request.Request(thumb)
        req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
        with urllib.request.urlopen(req, timeout=10) as res, open(path, 'wb') as f:
            f.write(res.read())
            
        return {"file_path": path, "filename": os.path.basename(path), "ext": ext}

    # Best Audio MP3
    if format_id == "bestaudio":
        out  = os.path.join(output_dir, f"{uid}.%(ext)s")
        opts = _opts(cf, url=url, extra={
            "format":  "bestaudio/best",
            "outtmpl": out,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        })
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        path = os.path.join(output_dir, f"{uid}.mp3")
        return {"file_path": path, "filename": os.path.basename(path), "ext": "mp3"}

    # Video + Audio merge
    out  = os.path.join(output_dir, f"{uid}.%(ext)s")
    opts = _opts(cf, url=url, extra={
        "format":              f"{format_id}+bestaudio/{format_id}/best",
        "merge_output_format": "mp4",
        "outtmpl":             out,
    })
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    path = os.path.join(output_dir, f"{uid}.mp4")
    if not os.path.exists(path):
        for f in os.listdir(output_dir):
            if f.startswith(uid):
                path = os.path.join(output_dir, f)
                break

    ext = path.rsplit(".", 1)[-1] if "." in path else "mp4"
    return {"file_path": path, "filename": os.path.basename(path), "ext": ext}


if __name__ == "__main__":
    import sys, json
    u = sys.argv[1] if len(sys.argv) > 1 else input("URL: ").strip()
    print(json.dumps(get_download_links(u), indent=2, ensure_ascii=False))

def prepare_stream(url: str, format_id: str, cookies_map: dict = None) -> dict:
    """
    yt-dlp se file ko ek temp folder mein download/merge karta hai aur
    path + size + cleanup() function return karta hai.

    Yeh function ka size return karna zaroori hai taaki main.py Content-Length
    header set kar sake — is header ke bina browser progress % / size nahi
    dikha sakta, chahe streaming kitni bhi sahi ho.
    """
    import tempfile, shutil

    cf = _get_cookies(url, cookies_map or {})
    tmpdir = tempfile.mkdtemp()

    def cleanup():
        shutil.rmtree(tmpdir, ignore_errors=True)

    try:
        # Thumbnail — seedha URL se download karo (chota, tez)
        if format_id == "thumbnail":
            try:
                with yt_dlp.YoutubeDL(_opts(cf)) as ydl:
                    info = ydl.extract_info(url, download=False)
                thumb_url = info.get("thumbnail", "")
            except Exception:
                thumb_url = url

            ext = thumb_url.split("?")[0].rsplit(".", 1)[-1] or "jpg"
            ext = ext if len(ext) <= 5 else "jpg"
            path = os.path.join(tmpdir, f"thumb.{ext}")

            req = urllib.request.Request(thumb_url)
            req.add_header("User-Agent", "Mozilla/5.0")
            with urllib.request.urlopen(req, timeout=15) as res, open(path, "wb") as f:
                shutil.copyfileobj(res, f)

        else:
            uid = str(uuid.uuid4())
            out = os.path.join(tmpdir, f"{uid}.%(ext)s")

            if format_id == "bestaudio":
                opts = _opts(cf, url=url, extra={
                    "format": "bestaudio/best",
                    "outtmpl": out,
                    "postprocessors": [{
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }],
                })
            else:
                opts = _opts(cf, url=url, extra={
                    "format": f"{format_id}+bestaudio/{format_id}/best",
                    "merge_output_format": "mp4",
                    "outtmpl": out,
                })

            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])

            path = None
            for f in os.listdir(tmpdir):
                if f.startswith(uid):
                    path = os.path.join(tmpdir, f)
                    break
            if not path or not os.path.exists(path):
                raise FileNotFoundError("yt-dlp file not created")

        size = os.path.getsize(path)
        return {"path": path, "size": size, "cleanup": cleanup}

    except Exception:
        cleanup()
        raise


def iter_file(path: str, cleanup, chunk_size: int = 512 * 1024):
    """Chunk-by-chunk file reader. Cleanup temp folder once fully sent (or on error)."""
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield chunk
    finally:
        cleanup()


def stream_download(url: str, format_id: str, cookies_map: dict = None):
    """Kept for backward compatibility — downloads fully then streams from disk."""
    info = prepare_stream(url, format_id, cookies_map)
    yield from iter_file(info["path"], info["cleanup"])