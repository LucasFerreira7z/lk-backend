import base64
import os
import re
import tempfile

import yt_dlp
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DOWNLOAD_DIR = tempfile.mkdtemp()
COOKIES_FILE = os.path.join(DOWNLOAD_DIR, "cookies.txt")

_cookies_b64 = os.environ.get("YT_COOKIES_B64", "")
if _cookies_b64:
    with open(COOKIES_FILE, "wb") as f:
        f.write(base64.b64decode(_cookies_b64))


def extract_video_id(url_or_id):
    patterns = [
        r"youtu\.be/([^?&\s]+)",
        r"youtube\.com/watch\?.*v=([^&\s]+)",
        r"youtube\.com/shorts/([^?&\s]+)",
        r"youtube\.com/embed/([^?&\s]+)",
        r"^([a-zA-Z0-9_-]{11})$",
    ]
    for pat in patterns:
        m = re.search(pat, url_or_id)
        if m:
            return m.group(1)
    raise ValueError("ID de video invalido")


def safe_name(title):
    return re.sub(r'[\\/*?:"<>|]', "-", title)[:60].strip()


def make_url(vid_id):
    return f"https://www.youtube.com/watch?v={vid_id}"


def build_opts(extra=None):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extractor_retries": 3,
        "extractor_args": {
            "youtube": {
                "player_client": ["web"],
            }
        },
    }
    if os.path.exists(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE
    if extra:
        opts.update(extra)
    return opts


@app.route("/")
def health():
    return jsonify({"status": "ok", "service": "VLTX Backend"})


@app.route("/api/status")
def status():
    return jsonify({
        "cookies_loaded": os.path.exists(COOKIES_FILE),
        "cookies_env_set": bool(os.environ.get("YT_COOKIES_B64", "")),
    })


@app.route("/api/info")
def info():
    video_id = request.args.get("v", "").strip()
    if not video_id:
        return jsonify({"error": "Parametro v obrigatorio"}), 400
    try:
        vid_id = extract_video_id(video_id)
        url = make_url(vid_id)
        with yt_dlp.YoutubeDL(build_opts({"skip_download": True})) as ydl:
            meta = ydl.extract_info(url, download=False)
        secs = meta.get("duration") or 0
        views = meta.get("view_count") or 0
        if views >= 1_000_000:
            views_str = f"{views / 1_000_000:.1f}M visualizacoes"
        elif views >= 1_000:
            views_str = f"{views / 1_000:.0f}K visualizacoes"
        else:
            views_str = f"{views} visualizacoes"
        return jsonify(
            {
                "title": meta.get("title", ""),
                "channel": meta.get("uploader", ""),
                "views": views_str,
                "duration": f"{secs // 60}:{secs % 60:02d}" if secs else "",
                "thumbUrl": meta.get("thumbnail", ""),
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/download")
def download():
    video_id = request.args.get("v", "").strip()
    fmt = request.args.get("fmt", "mp3").strip().lower()
    quality = request.args.get("q", "128").strip()
    if not video_id:
        return jsonify({"error": "Parametro v obrigatorio"}), 400
    try:
        vid_id = extract_video_id(video_id)
        url = make_url(vid_id)

        with yt_dlp.YoutubeDL(build_opts({"skip_download": True})) as ydl:
            meta = ydl.extract_info(url, download=False)
        title = safe_name(meta.get("title", vid_id))

        if fmt == "mp3":
            out_path = os.path.join(DOWNLOAD_DIR, title + ".mp3")
            if os.path.exists(out_path):
                os.remove(out_path)
            opts = build_opts({
                "format": "bestaudio/best",
                "outtmpl": os.path.join(DOWNLOAD_DIR, title + ".%(ext)s"),
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": quality,
                    }
                ],
            })
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            return send_file(
                out_path,
                as_attachment=True,
                download_name=title + ".mp3",
                mimetype="audio/mpeg",
            )
        else:
            height_map = {"360": "360", "720": "720", "1080": "1080"}
            max_height = height_map.get(quality, "720")
            out_path = os.path.join(DOWNLOAD_DIR, title + ".mp4")
            if os.path.exists(out_path):
                os.remove(out_path)
            opts = build_opts({
                "format": f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]/best",
                "outtmpl": os.path.join(DOWNLOAD_DIR, title + ".%(ext)s"),
                "merge_output_format": "mp4",
            })
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            return send_file(
                out_path,
                as_attachment=True,
                download_name=title + ".mp4",
                mimetype="video/mp4",
            )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
