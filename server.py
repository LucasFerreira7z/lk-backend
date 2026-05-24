import os
import re
import tempfile
import subprocess
import sys
import json
import time
import random
import traceback

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

def safe_get(data, key, default=""):
    """Obtém valor do dicionário com segurança total"""
    try:
        if not isinstance(data, dict):
            return default
        value = data.get(key, default)
        return value if value is not None else default
    except:
        return default

def format_views(views):
    """Formata número de visualizações"""
    try:
        views = int(views) if views else 0
        if views >= 1000000:
            return f"{views/1000000:.1f}M visualizacoes"
        elif views >= 1000:
            return f"{views/1000:.0f}K visualizacoes"
        else:
            return f"{views} visualizacoes"
    except:
        return "0 visualizacoes"

def format_duration(seconds):
    """Formata duração em minutos:segundos"""
    try:
        secs = int(seconds) if seconds else 0
        if secs > 0:
            return f"{secs // 60}:{secs % 60:02d}"
        return ""
    except:
        return ""

@app.route("/")
def health():
    return jsonify({
        "status": "ok",
        "service": "VLTX Backend",
        "cookies_available": os.path.exists(COOKIES_FILE)
    })

@app.route("/api/info")
def info():
    video_id = request.args.get("v", "").strip()
    if not video_id:
        return jsonify({"error": "Parametro v obrigatorio"}), 400

    try:
        # Validar ID
        vid_id = extract_video_id(video_id)
        if not vid_id:
            return jsonify({"error": "ID de video invalido"}), 400

        # URL do vídeo
        url = f"https://www.youtube.com/watch?v={vid_id}"

        # Dados do vídeo
        video_data = None

        # Método 1: yt-dlp Python API
        try:
            opts = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "extractor_args": "youtube:player_client=android",
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                result = ydl.extract_info(url, download=False)
                if isinstance(result, dict):
                    video_data = result
        except Exception as e1:
            print(f"Método 1 falhou: {str(e1)}")

        # Método 2: yt-dlp CLI
        if not video_data:
            try:
                cmd = [
                    "yt-dlp",
                    "-j",
                    "--skip-download",
                    "--no-warnings",
                    "--extractor-args", "youtube:player_client=android",
                    url
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

                if result.returncode == 0 and result.stdout.strip():
                    data = json.loads(result.stdout)
                    if isinstance(data, dict):
                        video_data = data
            except Exception as e2:
                print(f"Método 2 falhou: {str(e2)}")

        # Método 3: oEmbed API (não requer autenticação)
        if not video_data:
            try:
                oembed_url = f"https://www.youtube.com/oembed?url={url}&format=json"
                import urllib.request
                with urllib.request.urlopen(oembed_url, timeout=10) as response:
                    oembed_data = json.loads(response.read().decode())
                    if isinstance(oembed_data, dict):
                        video_data = {
                            "title": oembed_data.get("title", ""),
                            "uploader": oembed_data.get("author_name", ""),
                            "thumbnail": oembed_data.get("thumbnail_url", ""),
                            "duration": 0,
                            "view_count": 0,
                        }
            except Exception as e3:
                print(f"Método 3 falhou: {str(e3)}")

        # Se não conseguiu nenhum dado
        if not isinstance(video_data, dict):
            return jsonify({
                "error": "Não foi possível obter informações do vídeo",
                "hint": "O YouTube pode estar bloqueando. Tente novamente mais tarde."
            }), 500

        # Construir resposta com segurança
        response = {
            "title": str(safe_get(video_data, "title", "Sem título")),
            "channel": str(safe_get(video_data, "uploader", safe_get(video_data, "channel", "Desconhecido"))),
            "views": format_views(safe_get(video_data, "view_count", 0)),
            "duration": format_duration(safe_get(video_data, "duration", 0)),
            "thumbUrl": str(safe_get(video_data, "thumbnail", f"https://img.youtube.com/vi/{vid_id}/mqdefault.jpg")),
        }

        return jsonify(response)

    except Exception as e:
        print(f"Erro crítico: {traceback.format_exc()}")
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

        # Configuração base
        opts = {
            "quiet": True,
            "no_warnings": True,
            "outtmpl": os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"),
            "extractor_args": "youtube:player_client=android",
        }

        # Formato
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

        # Download
        video_data = None
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                result = ydl.extract_info(url, download=True)
                if isinstance(result, dict):
                    video_data = result
        except Exception as e:
            return jsonify({"error": f"Falha no download: {str(e)}"}), 500

        if not isinstance(video_data, dict):
            return jsonify({"error": "Falha ao processar vídeo"}), 500

        # Nome do arquivo
        title = str(safe_get(video_data, "title", vid_id))
        safe_title = re.sub(r'[\\/*?:"<>|]', "-", title)[:60].strip()

        # Extensão
        ext = "mp3" if fmt == "mp3" else "mp4"
        filename = safe_title + "." + ext
        filepath = os.path.join(DOWNLOAD_DIR, filename)

        # Procurar arquivo se não encontrado
        if not os.path.exists(filepath):
            all_files = []
            for f in os.listdir(DOWNLOAD_DIR):
                if f.endswith(ext):
                    all_files.append(f)

            if not all_files and ext == "mp4":
                for alt_ext in ["mkv", "webm"]:
                    for f in os.listdir(DOWNLOAD_DIR):
                        if f.endswith(alt_ext):
                            all_files.append(f)
                    if all_files:
                        ext = alt_ext
                        break

            if not all_files:
                # Listar arquivos disponíveis para debug
                files_in_dir = os.listdir(DOWNLOAD_DIR)
                return jsonify({
                    "error": "Arquivo não encontrado",
                    "files": files_in_dir[:10]  # Mostrar primeiros 10 arquivos
                }), 500

            # Pegar arquivo mais recente
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

        return send_file(
            filepath,
            as_attachment=True,
            download_name=filename,
            mimetype=mime_types.get(ext, "application/octet-stream")
        )

    except Exception as e:
        print(f"Erro no download: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
