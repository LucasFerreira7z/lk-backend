import os
import re
import tempfile
import subprocess
import sys

# Garantir que yt-dlp está atualizado
try:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"])
except:
    pass

import yt_dlp
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DOWNLOAD_DIR = tempfile.mkdtemp()
COOKIES = os.path.join(os.path.dirname(__file__), "cookies.txt")

def ydl_opts():
    """Configurações básicas do yt-dlp"""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extractor_args": "youtube:player_client=android",
    }
    if os.path.exists(COOKIES):
        opts["cookiefile"] = COOKIES
    return opts

def extract_video_id(url_or_id):
    """Extrai o ID do vídeo"""
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
    return jsonify({"status": "ok", "service": "VLTX Backend"})

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
            data = ydl.extract_info(url, download=False)

        # Verificar se data é válido
        if not data or not isinstance(data, dict):
            return jsonify({"error": "Falha ao extrair dados"}), 500

        # Extrair informações com segurança
        title = data.get("title", "Sem título") or "Sem título"
        channel = data.get("uploader", "Desconhecido") or "Desconhecido"
        duration_raw = data.get("duration", 0) or 0
        views_raw = data.get("view_count", 0) or 0

        # Formatar duração
        mins = duration_raw // 60
        secs = duration_raw % 60
        duration = f"{mins}:{secs:02d}" if duration_raw > 0 else ""

        # Formatar visualizações
        if views_raw >= 1000000:
            views = f"{views_raw/1000000:.1f}M visualizacoes"
        elif views_raw >= 1000:
            views = f"{views_raw/1000:.0f}K visualizacoes"
        else:
            views = f"{views_raw} visualizacoes"

        # Thumbnail
        thumbnail = data.get("thumbnail", f"https://img.youtube.com/vi/{vid_id}/mqdefault.jpg")

        return jsonify({
            "title": title,
            "channel": channel,
            "views": views,
            "duration": duration,
            "thumbUrl": thumbnail,
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

        # Configurar opções de download
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
            # Formato de vídeo com fallback
            quality_map = {
                "360": "best[height<=360]",
                "720": "best[height<=720]",
                "1080": "best[height<=1080]",
            }
            opts["format"] = f"{quality_map.get(quality, 'best')}/best"
            opts["merge_output_format"] = "mp4"

        # Download
        with yt_dlp.YoutubeDL(opts) as ydl:
            data = ydl.extract_info(url, download=True)

        if not data or not isinstance(data, dict):
            return jsonify({"error": "Falha no download"}), 500

        # Nome do arquivo
        title = data.get("title", vid_id) or vid_id
        safe_title = re.sub(r'[\\/*?:"<>|]', "-", title)[:60].strip()

        # Extensão
        ext = "mp3" if fmt == "mp3" else "mp4"
        filename = safe_title + "." + ext
        filepath = os.path.join(DOWNLOAD_DIR, filename)

        # Se não encontrar, procura o arquivo mais recente
        if not os.path.exists(filepath):
            all_files = [f for f in os.listdir(DOWNLOAD_DIR) if f.endswith(ext)]
            if not all_files and ext == "mp4":
                # Tenta outros formatos
                for alt_ext in ["mkv", "webm"]:
                    all_files = [f for f in os.listdir(DOWNLOAD_DIR) if f.endswith(alt_ext)]
                    if all_files:
                        ext = alt_ext
                        break

            if not all_files:
                return jsonify({"error": "Arquivo não encontrado"}), 500

            # Pega o arquivo mais recente
            all_files.sort(key=lambda f: os.path.getmtime(os.path.join(DOWNLOAD_DIR, f)), reverse=True)
            filepath = os.path.join(DOWNLOAD_DIR, all_files[0])
            filename = all_files[0]

        # MIME type
        mime_types = {
            "mp3": "audio/mpeg",
            "mp4": "video/mp4",
            "mkv": "video/x-matroska",
            "webm": "video/webm"
        }
        mimetype = mime_types.get(ext, "application/octet-stream")

        return send_file(
            filepath,
            as_attachment=True,
            download_name=filename,
            mimetype=mimetype
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
