#!/usr/bin/env python3
"""
v4_web_control.py

Gradio web interface for the V1 YouTube Shorts bot.
All settings are adjustable via the UI, and the bot runs with live logs.
"""

import json
import os
import sys
import random
import glob
import logging
import re
import pickle
import time
import warnings
from datetime import datetime, timedelta
import io
import traceback

os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["ALSA_CARD"] = "dummy"
warnings.filterwarnings("ignore", category=SyntaxWarning)

from PIL import Image, ImageDraw, ImageFont
import numpy as np
from moviepy.editor import ImageClip, AudioFileClip

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

import gradio as gr

# ----------------------------------------------------------------------
# Default Configuration (will be overridden by UI inputs)
# ----------------------------------------------------------------------
QUOTE_FILE = "quote.txt"
PROCESSED_FILE = "processed.txt"
IMAGE_DIR = "image"
MUSIC_DIR = "music"
OUTPUT_PREFIX = "output"
OUTPUT_EXT = ".mp4"
THUMB_EXT = ".jpg"

VIDEO_SIZE = (1080, 1920)
FPS = 30

# Adjustable settings (default values)
DEFAULT_TOTAL_DURATION = 7
DEFAULT_FADE_DURATION = 2
DEFAULT_MAX_QUOTE_LEN = 50

FONT_FILE = "Garamond.ttf"
TEXT_COLOR = (255, 255, 255)
STROKE_COLOR = (0, 0, 0)
STROKE_WIDTH = 4
MARGIN = 100
QUOTE_Y = 700
WRITER_Y = 850
WRITER_FONT_RATIO = 0.6

CLIENT_SECRET_FILE = "client_secret.json"
TOKEN_FILE = "token.pickle"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly"
]
CATEGORY_ID = "22"

DEFAULT_SLOTS = "5,30;11,30;17,30;23,30"   # display format
DEFAULT_TAGS = "shorts, quotes, motivation, wisdom"

# ----------------------------------------------------------------------
# Core V1 functions (unchanged, but parameterised)
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
    max_width = VIDEO_SIZE[0] - 2 * MARGIN
    lines = split_quote_two_lines(quote)
    quote_size = best_font_size(lines, max_width)
    quote_font = load_font(quote_size)
    writer_size = max(int(quote_size * WRITER_FONT_RATIO), 12)
    writer_font = load_font(writer_size)
    line_height = quote_font.getbbox("Ag")[3] - quote_font.getbbox("Ag")[1]
    total_height = line_height * len(lines) + (len(lines)-1)*10
    start_y = QUOTE_Y - total_height // 2
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0,0), line, font=quote_font)
        line_w = bbox[2] - bbox[0]
        line_x = (VIDEO_SIZE[0] - line_w) // 2
        line_y = start_y + i * (line_height + 10)
        draw_text_with_stroke(draw, line, (line_x, line_y),
                              quote_font, TEXT_COLOR, STROKE_COLOR, STROKE_WIDTH)
    writer_text = f"- {writer}"
    writer_bbox = draw.textbbox((0,0), writer_text, font=writer_font)
    writer_w = writer_bbox[2] - writer_bbox[0]
    writer_x = (VIDEO_SIZE[0] - writer_w) // 2
    writer_y = start_y + total_height + 30
    draw_text_with_stroke(draw, writer_text, (writer_x, writer_y),
                          writer_font, TEXT_COLOR, STROKE_COLOR, STROKE_WIDTH)
    return img

def get_authenticated_service():
    credentials = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as token:
            credentials = pickle.load(token)
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            # For the web UI, we cannot interact – just raise an error
            raise RuntimeError("Authentication required. Please run the script manually once to save token.pickle.")
    return build("youtube", "v3", credentials=credentials)

def get_upcoming_scheduled_times():
    youtube = get_authenticated_service()
    channel_response = youtube.channels().list(part="contentDetails", mine=True).execute()
    uploads_playlist_id = channel_response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    video_ids = []
    next_page_token = None
    while True:
        playlist_response = youtube.playlistItems().list(
            part="snippet",
            playlistId=uploads_playlist_id,
            maxResults=50,
            pageToken=next_page_token
        ).execute()
        video_ids.extend([item["snippet"]["resourceId"]["videoId"] for item in playlist_response["items"]])
        next_page_token = playlist_response.get("nextPageToken")
        if not next_page_token:
            break

    if not video_ids:
        return set()

    scheduled_times = set()
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i+50]
        vid_response = youtube.videos().list(part="status", id=",".join(batch)).execute()
        for item in vid_response["items"]:
            status = item["status"]
            if status.get("privacyStatus") == "private" and "publishAt" in status:
                dt_str = status["publishAt"]
                dt = datetime.strptime(dt_str.replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
                if dt > datetime.utcnow():
                    scheduled_times.add(dt)
    return scheduled_times

def next_free_slot(occupied_set, slots):
    now = datetime.utcnow()
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    while True:
        for h, m in slots:
            candidate = day.replace(hour=h, minute=m, second=0, microsecond=0)
            if candidate > now and candidate not in occupied_set:
                return candidate
        day += timedelta(days=1)

def upload_video(video_path, thumbnail_path, title, description, tags, category_id, publish_at):
    youtube = get_authenticated_service()
    privacy_status = "private"

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": category_id
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }
    publish_str = publish_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    body["status"]["publishAt"] = publish_str

    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
    video_id = response["id"]

    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            thumb_media = MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
            youtube.thumbnails().set(videoId=video_id, media_body=thumb_media).execute()
        except Exception:
            pass
    return video_id

def create_video(quote, writer, subject, image_path, music_path, output_video, output_thumb, total_duration, fade_duration):
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
# Main processing function (returns log messages)
# ----------------------------------------------------------------------
def run_bot(total_duration, fade_duration, max_quote_len, slots_str, tags_str, description_extra):
    # Parse slots
    slot_list = []
    for part in slots_str.split(";"):
        part = part.strip()
        if part:
            h, m = map(int, part.split(","))
            slot_list.append((h, m))

    # Parse tags
    tags = [t.strip() for t in tags_str.split(",") if t.strip()]

    # Log messages collector
    log_stream = io.StringIO()
    logger = logging.getLogger("bot_logger")
    logger.setLevel(logging.INFO)
    # Remove existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    ch = logging.StreamHandler(log_stream)
    ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(ch)

    try:
        if not os.path.exists(QUOTE_FILE):
            logger.error(f"Quote file {QUOTE_FILE} not found.")
            return log_stream.getvalue()

        processed = load_processed()
        logger.info(f"Already processed lines: {sorted(processed)}")

        with open(QUOTE_FILE, "r") as f:
            lines = f.readlines()

        to_process = []
        for idx, line in enumerate(lines, start=1):
            if idx in processed:
                continue
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if all(k in data for k in ("qoute", "writer", "subject")):
                    to_process.append((idx, line, data))
            except json.JSONDecodeError:
                logger.error(f"Line {idx}: invalid JSON, skipping.")

        if not to_process:
            logger.info("No unprocessed lines. Exiting.")
            return log_stream.getvalue()

        logger.info("Fetching existing scheduled videos...")
        occupied = get_upcoming_scheduled_times()
        logger.info(f"Found {len(occupied)} already scheduled slots.")
        next_slot = next_free_slot(occupied, slot_list)
        logger.info(f"First free slot: {next_slot.strftime('%Y-%m-%d %H:%M:%S UTC')}")

        for line_idx, line, data in to_process:
            quote = data["qoute"]
            writer = data["writer"]
            subject = data["subject"]

            if len(quote) > max_quote_len:
                logger.info(f"Line {line_idx}: quote too long ({len(quote)} chars), marking processed.")
                mark_processed(line_idx)
                continue

            images = find_images(subject)
            if not images:
                logger.error(f"Line {line_idx}: no images for subject '{subject}'. Skipping.")
                continue

            music_list = find_music(subject)
            if not music_list:
                logger.error(f"Line {line_idx}: no music for subject '{subject}'. Skipping.")
                continue

            image_path = random.choice(images)
            music_path = random.choice(music_list)

            next_idx = get_next_output_index()
            video_name = f"{OUTPUT_PREFIX}_{next_idx:03d}{OUTPUT_EXT}"
            thumb_name = f"{OUTPUT_PREFIX}_{next_idx:03d}_thumb{THUMB_EXT}"
            video_path = os.path.join(os.getcwd(), video_name)
            thumb_path = os.path.join(os.getcwd(), thumb_name)

            try:
                create_video(quote, writer, subject, image_path, music_path, video_path, thumb_path, total_duration, fade_duration)
            except Exception as e:
                logger.error(f"Line {line_idx}: video creation failed – {e}. Skipping.")
                continue

            try:
                title = f"{quote} – {writer}"[:100]
                description = (
                    f"{quote} – {writer}\n\n"
                    f"✨ Topic: {subject}\n"
                    f"{description_extra}\n"
                    f"🔖 #quotes #{subject} #motivation #wisdom\n\n"
                    f"🎵 Music from YouTube Audio Library\n"
                    f"📌 Subscribe for daily quotes"
                )
                all_tags = list(set(tags + [subject, writer]))

                upload_video(video_path, thumb_path, title, description, all_tags, CATEGORY_ID, next_slot)
                logger.info(f"Line {line_idx}: uploaded and scheduled at {next_slot.strftime('%Y-%m-%d %H:%M:%S UTC')}")

                mark_processed(line_idx)
                occupied.add(next_slot)
                next_slot = next_free_slot(occupied, slot_list)

            except Exception as e:
                logger.error(f"Line {line_idx}: upload failed – {e}. Stopping.")
                break

        logger.info("Script finished.")
    except Exception as e:
        logger.error(f"Unexpected error: {traceback.format_exc()}")

    return log_stream.getvalue()

# ----------------------------------------------------------------------
# Gradio Interface
# ----------------------------------------------------------------------
def gradio_interface(total_dur, fade_dur, max_len, slots, tags, desc_extra):
    # Run the bot and return the logs
    logs = run_bot(total_dur, fade_dur, max_len, slots, tags, desc_extra)
    return logs

# Custom CSS for a beautiful look
css = """
.gradio-container {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
}
.gr-button {
    background-color: #ff6b6b !important;
    border: none !important;
    color: white !important;
    font-weight: bold !important;
    padding: 12px 24px !important;
    border-radius: 8px !important;
    cursor: pointer !important;
    transition: 0.3s !important;
}
.gr-button:hover {
    background-color: #ee5a24 !important;
}
.gr-textbox, .gr-number, .gr-slider {
    border-radius: 8px !important;
}
.gr-panel {
    background: rgba(255, 255, 255, 0.9);
    border-radius: 16px;
    padding: 20px;
    box-shadow: 0 8px 32px rgba(0,0,0,0.1);
}
h1 {
    color: white;
    text-align: center;
    font-weight: 300;
    font-size: 2.5em;
}
"""

with gr.Blocks(css=css, title="YouTube Shorts Bot Control Panel") as demo:
    gr.HTML("<h1>⚡ YouTube Shorts Bot V4 ⚡</h1>")
    gr.HTML("<p style='text-align:center; color:white;'>Configure your bot and start creating stunning Shorts with a single click.</p>")

    with gr.Row():
        with gr.Column(scale=1, variant="panel"):
            gr.HTML("<h2 style='color:white;'>⏱️ Timing</h2>")
            total_dur = gr.Slider(5, 15, value=DEFAULT_TOTAL_DURATION, step=1, label="Video Duration (seconds)")
            fade_dur = gr.Slider(0.5, 3.0, value=DEFAULT_FADE_DURATION, step=0.1, label="Fade‑in Duration (seconds)")
            max_len = gr.Slider(30, 100, value=DEFAULT_MAX_QUOTE_LEN, step=1, label="Max Quote Length (characters)")

            gr.HTML("<h2 style='color:white;'>📅 Upload Slots (UTC)</h2>")
            slots_input = gr.Textbox(value=DEFAULT_SLOTS, label="Slots (hour,min;hour,min;...)", lines=1)

            gr.HTML("<h2 style='color:white;'>🏷️ Tags</h2>")
            tags_input = gr.Textbox(value=DEFAULT_TAGS, label="Comma‑separated base tags", lines=1)

            gr.HTML("<h2 style='color:white;'>📝 Description</h2>")
            desc_extra = gr.Textbox(
                value="💡 Quote of the day | Motivational quotes | Motivational speech | Motivational video | Understanding politics",
                label="Extra description line (appears after Topic)",
                lines=2
            )

            run_btn = gr.Button("▶️ Run Bot", variant="primary")

        with gr.Column(scale=2, variant="panel"):
            log_output = gr.Textbox(label="📋 Live Log", lines=25, max_lines=50, autoscroll=True)

    run_btn.click(
        fn=gradio_interface,
        inputs=[total_dur, fade_dur, max_len, slots_input, tags_input, desc_extra],
        outputs=log_output
    )

demo.queue(default_concurrency_limit=1)
demo.launch(share=True, debug=False)
