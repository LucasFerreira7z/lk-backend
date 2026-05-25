import os
import re
import tempfile
import yt_dlp
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DOWNLOAD_DIR = tempfile.mkdtemp()
COOKIES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")


def ydl_base_opts():
    opts = {
        "quiet": True,
        "no_warnings": True,
        "cookiefile": COOKIES,
        "ffmpeg_location": "/usr/bin/ffmpeg",
    }

    visitor_data = os.environ.get("VISITOR_DATA", "")
    po_token     = os.environ.get("PO_TOKEN", "")

    if visitor_data and po_token:
        opts["extractor_args"] = {
            "youtube": {
                "visitor_data": [visitor_data],
                "po_token":     [f"web+{po_token}"],
            }
        }

    return opts


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


@app.route("/debug")
def debug():
    exists = os.path.exists(COOKIES)
    return jsonify({
        "cookies_exists": exists,
        "cookies_size":   os.path.getsize(COOKIES) if exists else 0,
        "po_token_set":   bool(os.environ.get("PO_TOKEN")),
        "visitor_data_set": bool(os.environ.get("VISITOR_DATA")),
        "files": os.listdir(os.getcwd()),
    })


@app.route("/")
def health():
    return jsonify({"status": "ok", "service": "VLTX Backend"})


@app.route("/api/info")
def info():
    video_id = request.args.get("v", "").strip()
    if not video_id:
        return jsonify({"error": "Parametro v obrigatorio"}), 400
    try:
        vid_id = extract_video_id(video_id)
        url = f"https://www.youtube.com/watch?v={vid_id}"
        opts = {**ydl_base_opts(), "skip_download": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            data = ydl.extract_info(url, download=False)
        secs  = data.get("duration", 0) or 0
        views = data.get("view_count", 0) or 0
        if views >= 1_000_000:
            views_str = f"{views/1_000_000:.1f}M visualizacoes"
        elif views >= 1_000:
            views_str = f"{views/1_000:.0f}K visualizacoes"
        else:
            views_str = f"{views} visualizacoes"
        return jsonify({
            "title":    data.get("title", ""),
            "channel":  data.get("uploader", ""),
            "views":    views_str,
            "duration": f"{secs//60}:{secs%60:02d}" if secs else "",
            "thumbUrl": data.get("thumbnail",
                        f"https://img.youtube.com/vi/{vid_id}/mqdefault.jpg"),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/download")
def download():
    video_id = request.args.get("v", "").strip()
    fmt      = request.args.get("fmt", "mp3").strip().lower()
    quality  = request.args.get("q", "128").strip()
    if not video_id:
        return jsonify({"error": "Parametro v obrigatorio"}), 400
    try:
        vid_id = extract_video_id(video_id)
        url    = f"https://www.youtube.com/watch?v={vid_id}"

        if fmt == "mp3":
            audio_quality = quality if quality in ("128", "192", "320") else "192"
            opts = {
                **ydl_base_opts(),
                "format": "bestaudio[ext=m4a]/bestaudio/best",
                "outtmpl": os.path.join(DOWNLOAD_DIR, "%(id)s.%(ext)s"),
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": audio_quality,
                }],
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                data  = ydl.extract_info(url, download=True)
                vid   = data.get("id", vid_id)
                title = safe_name(data.get("title", vid_id))

            filepath = os.path.join(DOWNLOAD_DIR, vid + ".mp3")
            if not os.path.exists(filepath):
                files = sorted(
                    [f for f in os.listdir(DOWNLOAD_DIR) if f.endswith(".mp3")],
                    key=lambda f: os.path.getmtime(os.path.join(DOWNLOAD_DIR, f)),
                    reverse=True,
                )
                if not files:
                    return jsonify({"error": "Arquivo mp3 nao encontrado"}), 500
                filepath = os.path.join(DOWNLOAD_DIR, files[0])

            return send_file(filepath, as_attachment=True,
                             download_name=title + ".mp3",
                             mimetype="audio/mpeg")
        else:
            fmt_map = {
                "360":  "18",                                    # 360p já muxado
                "720":  "22",                                    # 720p já muxado
                "1080": "137+140/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]",
            }
            opts = {
                **ydl_base_opts(),
                "format": fmt_map.get(quality, "22"),
                "outtmpl": os.path.join(DOWNLOAD_DIR, "%(id)s.%(ext)s"),
                "merge_output_format": "mp4",
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                data  = ydl.extract_info(url, download=True)
                vid   = data.get("id", vid_id)
                title = safe_name(data.get("title", vid_id))

            filepath = os.path.join(DOWNLOAD_DIR, vid + ".mp4")
            if not os.path.exists(filepath):
                files = sorted(
                    [f for f in os.listdir(DOWNLOAD_DIR) if f.endswith(".mp4")],
                    key=lambda f: os.path.getmtime(os.path.join(DOWNLOAD_DIR, f)),
                    reverse=True,
                )
                if not files:
                    return jsonify({"error": "Arquivo mp4 nao encontrado"}), 500
                filepath = os.path.join(DOWNLOAD_DIR, files[0])

            return send_file(filepath, as_attachment=True,
                             download_name=title + ".mp4",
                             mimetype="video/mp4")

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
