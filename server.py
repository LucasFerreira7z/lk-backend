import os
import re
import tempfile
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from pytubefix import YouTube
from pytubefix.cli import on_progress

app = Flask(__name__)
CORS(app)

DOWNLOAD_DIR = tempfile.mkdtemp()


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


def make_yt(vid_id):
    url = f"https://www.youtube.com/watch?v={vid_id}"
    return YouTube(url, on_progress_callback=on_progress, use_oauth=False, allow_oauth_cache=False)


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
        yt = make_yt(vid_id)

        secs = yt.length or 0
        duration = f"{secs // 60}:{secs % 60:02d}" if secs else ""

        views = yt.views or 0
        if views >= 1_000_000:
            views_str = f"{views/1_000_000:.1f}M visualizacoes"
        elif views >= 1_000:
            views_str = f"{views/1_000:.0f}K visualizacoes"
        else:
            views_str = f"{views} visualizacoes"

        return jsonify({
            "title":    yt.title,
            "channel":  yt.author,
            "views":    views_str,
            "duration": duration,
            "thumbUrl": yt.thumbnail_url,
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
        yt     = make_yt(vid_id)
        title  = safe_name(yt.title)

        if fmt == "mp3":
            # Pega só o áudio
            stream = yt.streams.filter(only_audio=True).order_by("abr").last()
            if not stream:
                return jsonify({"error": "Nenhuma stream de audio encontrada"}), 404

            filepath = stream.download(output_path=DOWNLOAD_DIR, filename=title + ".mp4")

            # Renomeia para .mp3
            mp3_path = os.path.join(DOWNLOAD_DIR, title + ".mp3")
            if os.path.exists(mp3_path):
                os.remove(mp3_path)
            os.rename(filepath, mp3_path)

            return send_file(
                mp3_path,
                as_attachment=True,
                download_name=title + ".mp3",
                mimetype="audio/mpeg",
            )

        else:  # mp4
            height_map = {"360": 360, "720": 720, "1080": 1080}
            max_height = height_map.get(quality, 720)

            # Tenta pegar stream progressivo (vídeo + áudio juntos)
            stream = (
                yt.streams
                  .filter(progressive=True, file_extension="mp4")
                  .filter(lambda s: (s.resolution or "0p").replace("p","").isdigit() and
                          int((s.resolution or "0p").replace("p","")) <= max_height)
                  .order_by("resolution")
                  .last()
            )

            # Fallback: qualquer progressivo mp4
            if not stream:
                stream = (
                    yt.streams
                      .filter(progressive=True, file_extension="mp4")
                      .order_by("resolution")
                      .last()
                )

            # Fallback final: qualquer stream
            if not stream:
                stream = yt.streams.get_highest_resolution()

            if not stream:
                return jsonify({"error": "Nenhuma stream de video encontrada"}), 404

            filepath = stream.download(output_path=DOWNLOAD_DIR, filename=title + ".mp4")

            return send_file(
                filepath,
                as_attachment=True,
                download_name=title + ".mp4",
                mimetype="video/mp4",
            )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
