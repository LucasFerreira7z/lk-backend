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

# Caminho do cookies.txt (na mesma pasta do server.py)
COOKIES = os.path.join(os.path.dirname(__file__), "cookies.txt")

def ydl_base_opts():
    """Configurações base do yt-dlp com suporte a EJS"""
    opts = {
        "quiet": True,
        "no_warnings": False,
        # Formato correto: dicionário com configuração do runtime
        "js_runtimes": {
            "node": {
                "path": "node",
                "flags": []
            }
        },
        # Extratores alternativos para contornar restrições
        "extractor_args": "youtube:player_client=android,web,ios",
        # Ignora erros de formato
        "ignoreerrors": True,
    }
    if os.path.exists(COOKIES):
        opts["cookiefile"] = COOKIES
    return opts

def extract_video_id(url_or_id):
    """Extrai o ID do vídeo de várias URLs do YouTube"""
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
    """Remove caracteres inválidos para nome de arquivo"""
    if not title:
        return "video"
    return re.sub(r'[\\/*?:"<>|]', "-", title)[:60].strip()

@app.route("/")
def health():
    """Endpoint de saúde"""
    return jsonify({
        "status": "ok",
        "service": "VLTX Backend",
        "version": "2.1",
        "features": ["youtube", "ejs-enabled"]
    })

@app.route("/api/info")
def info():
    """Obtém informações do vídeo"""
    video_id = request.args.get("v", "").strip()
    if not video_id:
        return jsonify({"error": "Parametro v obrigatorio"}), 400

    try:
        vid_id = extract_video_id(video_id)
        url = f"https://www.youtube.com/watch?v={vid_id}"

        opts = {**ydl_base_opts(), "skip_download": True}

        with yt_dlp.YoutubeDL(opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
            except Exception as e:
                # Fallback: tenta sem js_runtimes
                opts_simple = {
                    "quiet": True,
                    "skip_download": True,
                    "extractor_args": "youtube:player_client=android",
                }
                with yt_dlp.YoutubeDL(opts_simple) as ydl2:
                    info = ydl2.extract_info(url, download=False)

        if not info:
            return jsonify({"error": "Não foi possível obter informações do vídeo"}), 500

        secs = info.get("duration", 0) or 0
        duration = f"{secs // 60}:{secs % 60:02d}" if secs else ""

        views = info.get("view_count", 0) or 0
        if views >= 1_000_000:
            views_str = f"{views/1_000_000:.1f}M visualizacoes"
        elif views >= 1_000:
            views_str = f"{views/1_000:.0f}K visualizacoes"
        else:
            views_str = f"{views} visualizacoes"

        return jsonify({
            "title": info.get("title", "Sem título"),
            "channel": info.get("uploader", "Desconhecido"),
            "views": views_str,
            "duration": duration,
            "thumbUrl": info.get("thumbnail", f"https://img.youtube.com/vi/{vid_id}/mqdefault.jpg"),
        })
    except Exception as e:
        return jsonify({"error": f"Erro ao obter info: {str(e)}"}), 500

@app.route("/api/download")
def download():
    """Faz o download do vídeo/áudio"""
    video_id = request.args.get("v", "").strip()
    fmt = request.args.get("fmt", "mp3").strip().lower()
    quality = request.args.get("q", "128").strip()

    if not video_id:
        return jsonify({"error": "Parametro v obrigatorio"}), 400

    try:
        vid_id = extract_video_id(video_id)
        url = f"https://www.youtube.com/watch?v={vid_id}"

        # Configuração base para download
        if fmt == "mp3":
            audio_quality = quality if quality in ("128", "192", "320") else "192"
            opts = {
                **ydl_base_opts(),
                "format": "bestaudio/best",
                "outtmpl": os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"),
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": audio_quality,
                }],
            }
        else:
            quality_formats = {
                "360": "best[height<=360][ext=mp4]/best[height<=360]/best[ext=mp4]/best",
                "720": "best[height<=720][ext=mp4]/best[height<=720]/best[ext=mp4]/best",
                "1080": "best[height<=1080][ext=mp4]/best[height<=1080]/best[ext=mp4]/best",
            }
            format_str = quality_formats.get(quality, "best[ext=mp4]/best")

            opts = {
                **ydl_base_opts(),
                "format": format_str,
                "outtmpl": os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"),
                "merge_output_format": "mp4",
            }

        # Tentativa de download com fallback
        info = None
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except Exception as e:
            print(f"Erro na primeira tentativa: {str(e)}")

            # Fallback: tenta com configurações mais simples
            opts_simple = {
                "quiet": True,
                "format": "bestaudio/best" if fmt == "mp3" else "best",
                "outtmpl": os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"),
                "ignoreerrors": True,
                "extractor_args": "youtube:player_client=android",
            }

            if fmt == "mp3":
                opts_simple["postprocessors"] = [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }]

            try:
                with yt_dlp.YoutubeDL(opts_simple) as ydl:
                    info = ydl.extract_info(url, download=True)
            except Exception as e2:
                return jsonify({"error": f"Falha no download: {str(e2)}"}), 500

        if not info:
            return jsonify({"error": "Não foi possível processar o vídeo"}), 500

        title = safe_name(info.get("title", vid_id) if info else vid_id)

        # Localizar arquivo baixado
        ext = "mp3" if fmt == "mp3" else "mp4"
        filepath = os.path.join(DOWNLOAD_DIR, title + f".{ext}")

        if not os.path.exists(filepath):
            # Procura pelo arquivo mais recente
            files = sorted(
                [f for f in os.listdir(DOWNLOAD_DIR) if f.endswith(f".{ext}")],
                key=lambda f: os.path.getmtime(os.path.join(DOWNLOAD_DIR, f)),
                reverse=True,
            )

            if not files and ext == "mp4":
                # Procura outros formatos de vídeo
                for alt_ext in [".mkv", ".webm"]:
                    files = sorted(
                        [f for f in os.listdir(DOWNLOAD_DIR) if f.endswith(alt_ext)],
                        key=lambda f: os.path.getmtime(os.path.join(DOWNLOAD_DIR, f)),
                        reverse=True,
                    )
                    if files:
                        filepath = os.path.join(DOWNLOAD_DIR, files[0])
                        ext = alt_ext[1:]
                        break

            if not files:
                return jsonify({"error": "Arquivo não encontrado após download"}), 500

            if not os.path.exists(filepath):
                filepath = os.path.join(DOWNLOAD_DIR, files[0])

        # Verificar se arquivo existe e tem tamanho
        if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
            return jsonify({"error": "Arquivo corrompido ou vazio"}), 500

        # Enviar arquivo
        mimetypes = {
            "mp3": "audio/mpeg",
            "mp4": "video/mp4",
            "mkv": "video/x-matroska",
            "webm": "video/webm"
        }
        mimetype = mimetypes.get(ext, "application/octet-stream")

        return send_file(
            filepath,
            as_attachment=True,
            download_name=title + f".{ext}",
            mimetype=mimetype
        )

    except Exception as e:
        return jsonify({"error": f"Erro no download: {str(e)}"}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
