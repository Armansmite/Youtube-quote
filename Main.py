import os
import json
import pickle
import base64
import io
import logging
import traceback
import threading
import time
import random
import re
import glob
import warnings
from datetime import datetime, timedelta

os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["ALSA_CARD"] = "dummy"
warnings.filterwarnings("ignore")

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import ImageClip, AudioFileClip

from flask import Flask, request, jsonify, send_file

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from pyngrok import ngrok

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
DEFAULT_SETTINGS = {
    "total_duration": 7,
    "fade_duration": 2,
    "max_quote_len": 50,
    "slots": "5,30;11,30;17,30;23,30",
    "base_tags": "shorts, quotes, motivation, wisdom",
    "description_extra": "💡 Quote of the day | Motivational quotes | Motivational speech | Motivational video | Understanding politics",
    "category_id": "22"
}

QUOTE_FILE = "quote.txt"
PROCESSED_FILE = "processed.txt"
IMAGE_DIR = "image"
MUSIC_DIR = "music"
OUTPUT_PREFIX = "output"
OUTPUT_EXT = ".mp4"
VIDEO_SIZE = (1080, 1920)
FPS = 30
FONT_FILE = "Garamond.ttf"

# ----------------------------------------------------------------------
# Helper functions (unchanged)
# ----------------------------------------------------------------------
def load_processed():
    if not os.path.exists(PROCESSED_FILE):
        return set()
    with open(PROCESSED_FILE, "r") as f:
        return {int(line) for line in f.read().splitlines() if line.strip().isdigit()}

def mark_processed(line_num):
    with open(PROCESSED_FILE, "a") as f:
        f.write(f"{line_num}\n")

def get_next_output_index():
    existing = glob.glob(f"{OUTPUT_PREFIX}_*.mp4")
    max_idx = 0
    for fname in existing:
        m = re.match(rf"{OUTPUT_PREFIX}_(\d+){OUTPUT_EXT}", os.path.basename(fname))
        if m:
            idx = int(m.group(1))
            if idx > max_idx:
                max_idx = idx
    return max_idx + 1

def find_images(subject):
    folder = IMAGE_DIR
    if not os.path.isdir(folder):
        return []
    patterns = [
        os.path.join(folder, f"{subject}_*.jpg"),
        os.path.join(folder, f"{subject}_*.JPG"),
        os.path.join(folder, f"{subject}_*.jpeg"),
        os.path.join(folder, f"{subject}_*.JPEG"),
        os.path.join(folder, f"{subject}_*.png"),
        os.path.join(folder, f"{subject}_*.PNG"),
    ]
    images = []
    for pat in patterns:
        images.extend(glob.glob(pat))
    return images

def find_music(subject):
    folder = MUSIC_DIR
    if not os.path.isdir(folder):
        return []
    patterns = [
        os.path.join(folder, f"{subject}_*.mp3"),
        os.path.join(folder, f"{subject}_*.MP3"),
        os.path.join(folder, f"{subject}_*.m4a"),
        os.path.join(folder, f"{subject}_*.M4A"),
    ]
    music = []
    for pat in patterns:
        music.extend(glob.glob(pat))
    return music

def load_font(size):
    if os.path.isfile(FONT_FILE):
        try:
            return ImageFont.truetype(FONT_FILE, size)
        except Exception:
            pass
    system_fonts = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
        "C:/Windows/Fonts/times.ttf",
        "C:/Windows/Fonts/georgia.ttf",
        "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
        "/System/Library/Fonts/Georgia.ttf",
    ]
    for path in system_fonts:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()

def split_quote_two_lines(quote):
    words = quote.split()
    if len(words) <= 1:
        return [quote]
    best_split = None
    for i in range(len(words) - 1, 0, -1):
        first = " ".join(words[:i])
        second = " ".join(words[i:])
        if len(first) >= len(second):
            if best_split is None or (len(first) > len(second) and len(best_split[0]) == len(best_split[1])):
                best_split = (first, second)
            if len(first) > len(second):
                break
    if best_split is None:
        return [quote]
    return list(best_split)

def best_font_size(lines, max_width):
    font_path = FONT_FILE if os.path.isfile(FONT_FILE) else None
    low, high = 10, 200
    best = low
    while low <= high:
        mid = (low + high) // 2
        try:
            font = ImageFont.truetype(font_path, mid) if font_path else load_font(mid)
        except Exception:
            font = load_font(mid)
        draw = ImageDraw.Draw(Image.new("RGB", (1,1)))
        fits = True
        for line in lines:
            bbox = draw.textbbox((0,0), line, font=font)
            if (bbox[2] - bbox[0]) > max_width:
                fits = False
                break
        if fits:
            best = mid
            low = mid + 1
        else:
            high = mid - 1
    return best

def draw_text_with_stroke(draw, text, xy, font, text_color, stroke_color, stroke_width):
    x, y = xy
    for dx in range(-stroke_width, stroke_width + 1):
        for dy in range(-stroke_width, stroke_width + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=stroke_color)
    draw.text((x, y), text, font=font, fill=text_color)

def build_text_frame(image, quote, writer):
    img = image.copy()
    draw = ImageDraw.Draw(img)
    max_width = VIDEO_SIZE[0] - 2 * 100
    lines = split_quote_two_lines(quote)
    quote_size = best_font_size(lines, max_width)
    quote_font = load_font(quote_size)
    writer_size = max(int(quote_size * 0.6), 12)
    writer_font = load_font(writer_size)
    line_height = quote_font.getbbox("Ag")[3] - quote_font.getbbox("Ag")[1]
    total_height = line_height * len(lines) + (len(lines)-1)*10
    start_y = 700 - total_height // 2
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0,0), line, font=quote_font)
        line_w = bbox[2] - bbox[0]
        line_x = (VIDEO_SIZE[0] - line_w) // 2
        line_y = start_y + i * (line_height + 10)
        draw_text_with_stroke(draw, line, (line_x, line_y),
                              quote_font, (255,255,255), (0,0,0), 4)
    writer_text = f"- {writer}"
    writer_bbox = draw.textbbox((0,0), writer_text, font=writer_font)
    writer_w = writer_bbox[2] - writer_bbox[0]
    writer_x = (VIDEO_SIZE[0] - writer_w) // 2
    writer_y = start_y + total_height + 30
    draw_text_with_stroke(draw, writer_text, (writer_x, writer_y),
                          writer_font, (255,255,255), (0,0,0), 4)
    return img

def create_video(quote, writer, subject, image_path, music_path, output_video, output_thumb,
                 total_duration, fade_duration):
    pil_img = Image.open(image_path).convert("RGB")
    target_w, target_h = VIDEO_SIZE
    img_w, img_h = pil_img.size
    scale = max(target_w / img_w, target_h / img_h)
    new_w = int(img_w * scale)
    new_h = int(img_h * scale)
    pil_img = pil_img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    pil_img = pil_img.crop((left, top, left + target_w, top + target_h))

    final_frame = build_text_frame(pil_img, quote, writer)
    final_frame.save(output_thumb, "JPEG", quality=90)

    img_array = np.array(final_frame)
    img_clip = ImageClip(img_array).set_duration(total_duration).fadein(fade_duration)

    audio_clip = AudioFileClip(music_path)
    if audio_clip.duration > total_duration:
        audio_clip = audio_clip.subclip(0, total_duration)

    final_video = img_clip.set_audio(audio_clip)
    final_video.write_videofile(
        output_video,
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        temp_audiofile="temp-audio.m4a",
        remove_temp=True,
        verbose=False,
        logger=None,
    )
    final_video.close()
    audio_clip.close()
    img_clip.close()

# ----------------------------------------------------------------------
# Flask app
# ----------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.urandom(24)

@app.after_request
def add_cors(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    return response

global_state = {
    "settings": DEFAULT_SETTINGS.copy(),
    "credentials": None,
    "flow": None,
    "log": []
}

def add_log(msg):
    global_state["log"].append(msg)
    if len(global_state["log"]) > 200:
        global_state["log"] = global_state["log"][-200:]

@app.route("/")
def index():
    return send_file("index.html")

@app.route("/frontend")
def frontend():
    return HTML_CONTENT

@app.route("/api/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        data = request.get_json()
        global_state["settings"] = data
        return jsonify({"status": "ok"})
    return jsonify(global_state["settings"])

@app.route("/api/auth/upload_client_secret", methods=["POST"])
def upload_client_secret():
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    file = request.files["file"]
    filepath = "/tmp/client_secret.json"
    file.save(filepath)
    try:
        flow = InstalledAppFlow.from_client_secrets_file(filepath, [
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.readonly"
        ])
        flow.redirect_uri = "http://localhost:8080"
        auth_url, _ = flow.authorization_url(prompt="consent")
        global_state["flow"] = flow
        return jsonify({"auth_url": auth_url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/auth/authenticate", methods=["POST"])
def authenticate():
    raw = request.get_json().get("code", "")
    # If the full redirect URL was pasted, extract just the code
    if "code=" in raw:
        raw = raw.split("code=")[1].split("&")[0]
    if not global_state.get("flow"):
        return jsonify({"error": "No client_secret uploaded"}), 400
    try:
        global_state["flow"].fetch_token(code=raw)
        creds = global_state["flow"].credentials
        service = build("youtube", "v3", credentials=creds)
        service.channels().list(part="id", mine=True).execute()
        global_state["credentials"] = creds
        settings = global_state["settings"]
        creds_bytes = pickle.dumps(creds)
        config = {
            "settings": settings,
            "credentials_b64": base64.b64encode(creds_bytes).decode("utf-8")
        }
        return jsonify({"status": "authenticated", "config": config})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/auth/status", methods=["GET"])
def auth_status():
    creds = global_state.get("credentials")
    if not creds:
        return jsonify({"status": "none"})
    if creds.valid:
        return jsonify({"status": "valid"})
    elif creds.expired and creds.refresh_token:
        return jsonify({"status": "expired_refreshable"})
    else:
        return jsonify({"status": "invalid"})

@app.route("/api/export", methods=["GET"])
def export_config():
    settings = global_state["settings"]
    creds = global_state.get("credentials")
    creds_bytes = pickle.dumps(creds) if creds else b""
    payload = {
        "settings": settings,
        "credentials_b64": base64.b64encode(creds_bytes).decode("utf-8")
    }
    return jsonify(payload)

@app.route("/api/import", methods=["POST"])
def import_config():
    data = request.get_json()
    settings = data.get("settings", DEFAULT_SETTINGS.copy())
    global_state["settings"] = settings
    creds_b64 = data.get("credentials_b64")
    if creds_b64:
        creds_bytes = base64.b64decode(creds_b64)
        global_state["credentials"] = pickle.loads(creds_bytes)
    return jsonify({"status": "imported", "settings": settings})

@app.route("/api/run", methods=["POST"])
def run_bot():
    global_state["log"] = []
    add_log("Starting bot...")
    threading.Thread(target=bot_process).start()
    return jsonify({"status": "started"})

@app.route("/api/log", methods=["GET"])
def get_log():
    return jsonify(global_state["log"])

def bot_process():
    # Placeholder – replace with full implementation
    add_log("Bot process placeholder - replace with full code.")
    pass

# ----------------------------------------------------------------------
# HTML Frontend (same as before)
# ----------------------------------------------------------------------
HTML_CONTENT = r""" ... """  # (use the full HTML from the previous answer)

# ----------------------------------------------------------------------
# Start server with ngrok
# ----------------------------------------------------------------------
def start_ngrok():
    ngrok.kill()
    ngrok.set_auth_token("2t2YZZLCmN25PUCkkeimIhlluPI_59QsciAqHfriV4LvvKejQ")
    public_url = ngrok.connect(5000)
    print(f" * ngrok tunnel: {public_url}")
    return public_url

if __name__ == "__main__":
    with open("index.html", "w") as f:
        f.write("<script>window.location.href='/frontend';</script>")
    threading.Thread(target=start_ngrok, daemon=True).start()
    time.sleep(2)
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
