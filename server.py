import os
import re
import tempfile
import subprocess
import sys
import json
import time
import random

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
COOKIES_DIR = os.path.join(os.path.dirname(__file__), "cookies")
COOKIES_FILE = os.path.join(COOKIES_DIR, "cookies.txt")

# Criar diretório de cookies se não existir
os.makedirs(COOKIES_DIR, exist_ok=True)

def ydl_opts():
    """Configurações do yt-dlp com fallbacks"""
    opts = {
        "quiet": True,
        "no_warnings": False,
        # Tentar diferentes clientes para evitar bloqueio
        "extractor_args": "youtube:player_client=android,ios,web",
        # User agent aleatório para evitar detecção
        "user_agent": random.choice([
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
            "Mozilla/5.0 (Linux; Android 13; SM-G998B) AppleWebKit/537.36",
        ]),
        # Rate limiting
        "sleep_interval_requests": random.uniform(1, 3),
        "sleep_interval": random.uniform(1, 3),
        "max_sleep_interval": 5,
        # Tentar usar Node.js se disponível
        "js_runtimes": {
            "node": {
                "path": "node",
                "flags": []
            }
        },
    }

    # Adicionar cookies se existirem
    if os.path.exists(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE

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
    return jsonify({
        "status": "ok",
        "service": "VLTX Backend",
        "cookies_available": os.path.exists(COOKIES_FILE)
    })

@app.route("/api/upload-cookies", methods=["POST"])
def upload_cookies():
    """Endpoint para fazer upload de cookies.txt"""
    if "cookies" not in request.files:
        return jsonify({"error": "Arquivo cookies.txt não enviado"}), 400

    file = request.files["cookies"]
    file.save(COOKIES_FILE)

    return jsonify({"message": "Cookies salvos com sucesso!"})

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

        data = None
        errors = []

        # Tentativa 1: Com todas as configurações
        try:
            with yt_dlp.YoutubeDL(ydl_opts()) as ydl:
                data = ydl.extract_info(url, download=False)
                if isinstance(data, str):
                    raise Exception(data)
        except Exception as e:
            errors.append(f"Tentativa 1: {str(e)}")

            # Tentativa 2: Configuração mínima
            try:
                opts_min = {
                    "quiet": True,
                    "skip_download": True,
                    "extractor_args": "youtube:player_client=android",
                    "user_agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36",
                }
                with yt_dlp.YoutubeDL(opts_min) as ydl:
                    data = ydl.extract_info(url, download=False)
            except Exception as e2:
                errors.append(f"Tentativa 2: {str(e2)}")

                # Tentativa 3: Via linha de comando
                try:
                    cmd = ["yt-dlp", "-j", "--extractor-args", "youtube:player_client=android", url]
                    if os.path.exists(COOKIES_FILE):
                        cmd.extend(["--cookies", COOKIES_FILE])

                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                    if result.returncode == 0:
                        data = json.loads(result.stdout)
                    else:
                        errors.append(f"Tentativa 3: {result.stderr}")
                except Exception as e3:
                    errors.append(f"Tentativa 3: {str(e3)}")

        if not data or not isinstance(data, dict):
            error_msg = " | ".join(errors)
            return jsonify({
                "error": "Não foi possível extrair informações do vídeo",
                "details": error_msg,
                "hint": "O YouTube pode estar bloqueando o IP. Considere fazer upload de cookies.txt"
            }), 500

        # Extrair informações
        title = str(data.get("title") or "Sem título")
        channel = str(data.get("uploader") or data.get("channel") or "Desconhecido")
        duration_raw = int(data.get("duration") or 0)
        views_raw = int(data.get("view_count") or 0)

        # Formatar duração
        duration = f"{duration_raw // 60}:{duration_raw % 60:02d}" if duration_raw > 0 else ""

        # Formatar visualizações
        if views_raw >= 1000000:
            views = f"{views_raw/1000000:.1f}M visualizacoes"
        elif views_raw >= 1000:
            views = f"{views_raw/1000:.0f}K visualizacoes"
        else:
            views = f"{views_raw} visualizacoes"

        thumbnail = str(data.get("thumbnail") or f"https://img.youtube.com/vi/{vid_id}/mqdefault.jpg")

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

        # Download com retry
        data = None
        for attempt in range(3):
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    data = ydl.extract_info(url, download=True)
                break
            except Exception as e:
                if attempt == 2:  # Última tentativa
                    raise e
                time.sleep(random.uniform(2, 5))  # Esperar antes de tentar novamente

        if not isinstance(data, dict):
            return jsonify({"error": "Falha no download"}), 500

        title = str(data.get("title") or vid_id)
        safe_title = re.sub(r'[\\/*?:"<>|]', "-", title)[:60].strip()

        ext = "mp3" if fmt == "mp3" else "mp4"
        filename = safe_title + "." + ext
        filepath = os.path.join(DOWNLOAD_DIR, filename)

        # Procurar arquivo
        if not os.path.exists(filepath):
            all_files = [f for f in os.listdir(DOWNLOAD_DIR) if f.endswith(ext)]
            if not all_files and ext == "mp4":
                for alt_ext in ["mkv", "webm"]:
                    all_files = [f for f in os.listdir(DOWNLOAD_DIR) if f.endswith(alt_ext)]
                    if all_files:
                        ext = alt_ext
                        break

            if not all_files:
                return jsonify({"error": "Arquivo não encontrado"}), 500

            all_files.sort(key=lambda f: os.path.getmtime(os.path.join(DOWNLOAD_DIR, f)), reverse=True)
            filepath = os.path.join(DOWNLOAD_DIR, all_files[0])
            filename = all_files[0]

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
