import os
import re
import tempfile
import subprocess
import sys
import json

# Forçar versão correta do yt-dlp
try:
    subprocess.check_call([
        sys.executable, "-m", "pip", "install",
        "--force-reinstall", "yt-dlp==2024.12.13"
    ])
except:
    pass

import yt_dlp
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DOWNLOAD_DIR = tempfile.mkdtemp()
COOKIES_FILE = os.path.join(os.path.dirname(__file__), "cookies.txt")

def ydl_opts():
    opts = {
        "quiet": True,
        "no_warnings": True,
    }
    if os.path.exists(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE
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
    return None

@app.route("/")
def health():
    return jsonify({
        "status": "ok",
        "yt_dlp_version": yt_dlp.version.__version__
    })

@app.route("/api/info")
def info():
    video_id = request.args.get("v", "").strip()
    if not video_id:
        return jsonify({"error": "Parametro v obrigatorio"}), 400

    try:
        vid_id = extract_video_id(video_id)
        if not vid_id:
            return jsonify({"error": "ID de video invalido"}), 400

        url = f"https://www.youtube.com/watch?v={vid_id}"

        with yt_dlp.YoutubeDL(ydl_opts()) as ydl:
            info = ydl.extract_info(url, download=False)

        # Verificar se info é válido
        if not info:
            return jsonify({"error": "Vídeo não encontrado"}), 404

        # Extrair dados com segurança
        title = info.get("title", "Sem título") or "Sem título"
        uploader = info.get("uploader", "Desconhecido") or "Desconhecido"
        duration = info.get("duration", 0) or 0
        views = info.get("view_count", 0) or 0

        # Formatar
        duration_str = f"{duration // 60}:{duration % 60:02d}" if duration else ""

        if views >= 1000000:
            views_str = f"{views/1000000:.1f}M visualizacoes"
        elif views >= 1000:
            views_str = f"{views/1000:.0f}K visualizacoes"
        else:
            views_str = f"{views} visualizacoes"

        return jsonify({
            "title": str(title),
            "channel": str(uploader),
            "views": views_str,
            "duration": duration_str,
            "thumbUrl": f"https://img.youtube.com/vi/{vid_id}/mqdefault.jpg",
        })

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
        if not vid_id:
            return jsonify({"error": "ID de video invalido"}), 400

        url = f"https://www.youtube.com/watch?v={vid_id}"

        opts = ydl_opts()
        opts["outtmpl"] = os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s")

        if fmt == "mp3":
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": quality if quality in ("128", "192", "320") else "192",
            }]
        else:
            quality_map = {
                "360": "best[height<=360]",
                "720": "best[height<=720]",
                "1080": "best[height<=1080]",
            }
            opts["format"] = f"{quality_map.get(quality, 'best')}/best"
            opts["merge_output_format"] = "mp4"

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)

        if not info:
            return jsonify({"error": "Falha no download"}), 500

        title = info.get("title", vid_id) or vid_id
        safe_title = re.sub(r'[\\/*?:"<>|]', "-", str(title))[:60].strip()

        ext = "mp3" if fmt == "mp3" else "mp4"
        filename = safe_title + "." + ext
        filepath = os.path.join(DOWNLOAD_DIR, filename)

        # Procurar arquivo
        if not os.path.exists(filepath):
            files = [f for f in os.listdir(DOWNLOAD_DIR) if f.endswith(ext)]
            if not files and ext == "mp4":
                for alt in ["mkv", "webm"]:
                    files = [f for f in os.listdir(DOWNLOAD_DIR) if f.endswith(alt)]
                    if files:
                        ext = alt
                        break

            if not files:
                return jsonify({
                    "error": "Arquivo não encontrado",
                    "dir_contents": os.listdir(DOWNLOAD_DIR)
                }), 500

            files.sort(key=lambda f: os.path.getmtime(os.path.join(DOWNLOAD_DIR, f)), reverse=True)
            filepath = os.path.join(DOWNLOAD_DIR, files[0])
            filename = files[0]

        mime_types = {
            "mp3": "audio/mpeg",
            "mp4": "video/mp4",
            "mkv": "video/x-matroska",
            "webm": "video/webm"
        }

        return send_file(
            filepath,
            as_attachment=True,
            download_name=filename,
            mimetype=mime_types.get(ext, "application/octet-stream")
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
