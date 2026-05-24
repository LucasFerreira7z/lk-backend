"""
VLTX — Backend YouTube (Flask + yt-dlp)
=========================================
Usando yt-dlp ao invés de pytube (mais estável e atualizado)

Instalar:
  pip install flask flask-cors yt-dlp

Rodar local:
  python server.py
"""

import os
import re
import tempfile
import yt_dlp
from flask import Flask, jsonify, request, send_file, Response
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # permite chamadas do GitHub Pages

DOWNLOAD_DIR = tempfile.mkdtemp()


# ─── Utilitário ───────────────────────────────────────────────
def extract_video_id(url_or_id: str) -> str:
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
    raise ValueError("ID de vídeo inválido")


def safe_name(title: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "-", title)[:60].strip()


# ─── Rota health check ────────────────────────────────────────
@app.route("/")
def health():
    return jsonify({"status": "ok", "service": "VLTX Backend"})


# ─── Rota 1: info do vídeo ────────────────────────────────────
@app.route("/api/info")
def info():
    video_id = request.args.get("v", "").strip()
    if not video_id:
        return jsonify({"error": "Parâmetro 'v' obrigatório"}), 400

    try:
        vid_id = extract_video_id(video_id)
        url = f"https://www.youtube.com/watch?v={vid_id}"

        ydl_opts = {"quiet": True, "skip_download": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        secs = info.get("duration", 0) or 0
        duration = f"{secs // 60}:{secs % 60:02d}" if secs else ""

        views = info.get("view_count", 0) or 0
        if views >= 1_000_000:
            views_str = f"{views / 1_000_000:.1f}M visualizações"
        elif views >= 1_000:
            views_str = f"{views / 1_000:.0f}K visualizações"
        else:
            views_str = f"{views} visualizações"

        return jsonify({
            "title":    info.get("title", ""),
            "channel":  info.get("uploader", ""),
            "views":    views_str,
            "duration": duration,
            "thumbUrl": info.get("thumbnail", f"https://img.youtube.com/vi/{vid_id}/mqdefault.jpg"),
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Rota 2: download ─────────────────────────────────────────
@app.route("/api/download")
def download():
    video_id = request.args.get("v", "").strip()
    fmt      = request.args.get("fmt", "mp3").strip().lower()
    quality  = request.args.get("q", "128").strip()

    if not video_id:
        return jsonify({"error": "Parâmetro 'v' obrigatório"}), 400

    try:
        vid_id   = extract_video_id(video_id)
        url      = f"https://www.youtube.com/watch?v={vid_id}"
        out_path = DOWNLOAD_DIR

        if fmt == "mp3":
            # Qualidade de áudio solicitada
            audio_quality = quality if quality in ("128", "192", "320") else "192"

            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": os.path.join(out_path, "%(title)s.%(ext)s"),
                "quiet": True,
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": audio_quality,
                }],
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info    = ydl.extract_info(url, download=True)
                title   = safe_name(info.get("title", vid_id))
                mp3file = os.path.join(out_path, title + ".mp3")

                # yt-dlp pode nomear diferente — encontra o arquivo .mp3 mais recente
                if not os.path.exists(mp3file):
                    files = sorted(
                        [f for f in os.listdir(out_path) if f.endswith(".mp3")],
                        key=lambda f: os.path.getmtime(os.path.join(out_path, f)),
                        reverse=True,
                    )
                    if not files:
                        return jsonify({"error": "Arquivo MP3 não encontrado após download"}), 500
                    mp3file = os.path.join(out_path, files[0])

            return send_file(
                mp3file,
                as_attachment=True,
                download_name=title + ".mp3",
                mimetype="audio/mpeg",
            )

        else:  # mp4
            # Mapeia qualidade → formato yt-dlp
            quality_fmt = {
                "360":  "18",                              # 360p muxed
                "720":  "22",                              # 720p muxed
                "1080": "bestvideo[ext=mp4]+bestaudio/best", # 1080p (precisa ffmpeg)
            }.get(quality, "22")

            ydl_opts = {
                "format": quality_fmt,
                "outtmpl": os.path.join(out_path, "%(title)s.%(ext)s"),
                "quiet": True,
                "merge_output_format": "mp4",
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info    = ydl.extract_info(url, download=True)
                title   = safe_name(info.get("title", vid_id))
                mp4file = os.path.join(out_path, title + ".mp4")

                if not os.path.exists(mp4file):
                    files = sorted(
                        [f for f in os.listdir(out_path) if f.endswith(".mp4")],
                        key=lambda f: os.path.getmtime(os.path.join(out_path, f)),
                        reverse=True,
                    )
                    if not files:
                        return jsonify({"error": "Arquivo MP4 não encontrado após download"}), 500
                    mp4file = os.path.join(out_path, files[0])

            return send_file(
                mp4file,
                as_attachment=True,
                download_name=title + ".mp4",
                mimetype="video/mp4",
            )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Iniciar ──────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"✅ VLTX Backend rodando na porta {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
