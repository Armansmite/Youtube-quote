#!/usr/bin/env python3
"""
v4_advanced_web.py

Full-featured web dashboard for the YouTube Shorts bot.
No terminal needed – everything is controlled via the UI.
Includes OAuth authentication, exportable settings, live logs.
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
import base64
import io
import traceback
from datetime import datetime, timedelta

# Environment fixes
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["ALSA_CARD"] = "dummy"
warnings.filterwarnings("ignore", category=SyntaxWarning)

from PIL import Image, ImageDraw, ImageFont
import numpy as np
from moviepy.editor import ImageClip, AudioFileClip

# Google Auth
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

import gradio as gr

# ----------------------------------------------------------------------
# Default settings
# ----------------------------------------------------------------------
DEFAULT_SETTINGS = {
    "total_duration": 7,
    "fade_duration": 2,
    "max_quote_len": 50,
    "slots": "5,30;11,30;17,30;23,30",      # 05:30, 11:30, 17:30, 23:30 UTC
    "base_tags": "shorts, quotes, motivation, wisdom",
    "description_extra": "💡 Quote of the day | Motivational quotes | Motivational speech | Motivational video | Understanding politics",
    "category_id": "22"
}

# Paths (can be changed, but usually fixed)
QUOTE_FILE = "quote.txt"
PROCESSED_FILE = "processed.txt"
IMAGE_DIR = "image"
MUSIC_DIR = "music"
OUTPUT_PREFIX = "output"
OUTPUT_EXT = ".mp4"
THUMB_EXT = ".jpg"
VIDEO_SIZE = (1080, 1920)
FPS = 30

# Font settings (unchanged)
FONT_FILE = "Garamond.ttf"
TEXT_COLOR = (255, 255, 255)
STROKE_COLOR = (0, 0, 0)
STROKE_WIDTH = 4
MARGIN = 100
QUOTE_Y = 700
WRITER_Y = 850
WRITER_FONT_RATIO = 0.6

# ----------------------------------------------------------------------
# Helper functions (same as before, reused)
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
# Authentication helpers
# ----------------------------------------------------------------------
def get_youtube_service(credentials):
    """Build a YouTube service from a Credentials object."""
    return build("youtube", "v3", credentials=credentials)

def get_upcoming_scheduled_times(service):
    """Return set of future scheduled publish datetimes."""
    channel_response = service.channels().list(part="contentDetails", mine=True).execute()
    uploads_playlist_id = channel_response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    video_ids = []
    next_page_token = None
    while True:
        playlist_response = service.playlistItems().list(
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
        vid_response = service.videos().list(part="status", id=",".join(batch)).execute()
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

def upload_video(service, video_path, thumbnail_path, title, description, tags, category_id, publish_at):
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
    request = service.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
    video_id = response["id"]

    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            thumb_media = MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
            service.thumbnails().set(videoId=video_id, media_body=thumb_media).execute()
        except Exception:
            pass
    return video_id

# ----------------------------------------------------------------------
# State management
# ----------------------------------------------------------------------
def save_state_to_file(settings, creds_bytes, filename="bot_settings.json"):
    """Save all settings + pickled credentials (base64) to a JSON file."""
    state = {
        "settings": settings,
        "credentials_b64": base64.b64encode(creds_bytes).decode("utf-8") if creds_bytes else None
    }
    with open(filename, "w") as f:
        json.dump(state, f, indent=2)
    return filename

def load_state_from_file(file_path):
    """Load state from a JSON file. Returns (settings, credentials)."""
    with open(file_path, "r") as f:
        state = json.load(f)
    settings = state.get("settings", DEFAULT_SETTINGS.copy())
    creds_b64 = state.get("credentials_b64")
    credentials = None
    if creds_b64:
        creds_bytes = base64.b64decode(creds_b64)
        credentials = pickle.loads(creds_bytes)
    return settings, credentials

# ----------------------------------------------------------------------
# Main bot runner (used by the UI)
# ----------------------------------------------------------------------
def run_bot(settings, credentials, log_callback=None):
    """
    Process quotes using the given settings and credentials.
    log_callback is a function that receives log lines (for live UI).
    Returns the full log text.
    """
    log_stream = io.StringIO()
    logger = logging.getLogger("bot_runner")
    logger.setLevel(logging.INFO)
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    ch = logging.StreamHandler(log_stream)
    ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(ch)

    def log(msg):
        logger.info(msg)
        if log_callback:
            log_callback(msg)

    try:
        # Parse slots
        slots_str = settings.get("slots", DEFAULT_SETTINGS["slots"])
        slot_list = []
        for part in slots_str.split(";"):
            part = part.strip()
            if part:
                h, m = map(int, part.split(","))
                slot_list.append((h, m))

        base_tags = [t.strip() for t in settings.get("base_tags", DEFAULT_SETTINGS["base_tags"]).split(",") if t.strip()]
        total_duration = settings.get("total_duration", DEFAULT_SETTINGS["total_duration"])
        fade_duration = settings.get("fade_duration", DEFAULT_SETTINGS["fade_duration"])
        max_quote_len = settings.get("max_quote_len", DEFAULT_SETTINGS["max_quote_len"])
        description_extra = settings.get("description_extra", DEFAULT_SETTINGS["description_extra"])
        category_id = settings.get("category_id", DEFAULT_SETTINGS["category_id"])

        if not os.path.exists(QUOTE_FILE):
            log(f"ERROR: Quote file {QUOTE_FILE} not found.")
            return log_stream.getvalue()

        processed = load_processed()
        log(f"Already processed lines: {sorted(processed)}")

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
                log(f"Line {idx}: invalid JSON, skipping.")

        if not to_process:
            log("No unprocessed lines. Exiting.")
            return log_stream.getvalue()

        # Build YouTube service
        if not credentials or not credentials.valid:
            log("ERROR: No valid credentials. Please authenticate first.")
            return log_stream.getvalue()

        service = get_youtube_service(credentials)

        log("Fetching existing scheduled videos...")
        occupied = get_upcoming_scheduled_times(service)
        log(f"Found {len(occupied)} already scheduled slots.")
        next_slot = next_free_slot(occupied, slot_list)
        log(f"First free slot: {next_slot.strftime('%Y-%m-%d %H:%M:%S UTC')}")

        for line_idx, line, data in to_process:
            quote = data["qoute"]
            writer = data["writer"]
            subject = data["subject"]

            if len(quote) > max_quote_len:
                log(f"Line {line_idx}: quote too long ({len(quote)} chars), marking processed.")
                mark_processed(line_idx)
                continue

            images = find_images(subject)
            if not images:
                log(f"Line {line_idx}: no images for subject '{subject}'. Skipping.")
                continue

            music_list = find_music(subject)
            if not music_list:
                log(f"Line {line_idx}: no music for subject '{subject}'. Skipping.")
                continue

            image_path = random.choice(images)
            music_path = random.choice(music_list)

            next_idx = get_next_output_index()
            video_name = f"{OUTPUT_PREFIX}_{next_idx:03d}{OUTPUT_EXT}"
            thumb_name = f"{OUTPUT_PREFIX}_{next_idx:03d}_thumb{THUMB_EXT}"
            video_path = os.path.join(os.getcwd(), video_name)
            thumb_path = os.path.join(os.getcwd(), thumb_name)

            try:
                create_video(quote, writer, subject, image_path, music_path,
                             video_path, thumb_path, total_duration, fade_duration)
                log(f"Created {video_name}")
            except Exception as e:
                log(f"Line {line_idx}: video creation failed – {e}. Skipping.")
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
                tags = list(set(base_tags + [subject, writer]))

                upload_video(service, video_path, thumb_path, title, description,
                             tags, category_id, next_slot)
                log(f"Uploaded & scheduled at {next_slot.strftime('%Y-%m-%d %H:%M:%S UTC')}")

                mark_processed(line_idx)
                occupied.add(next_slot)
                next_slot = next_free_slot(occupied, slot_list)

            except Exception as e:
                log(f"Line {line_idx}: upload failed – {e}. Stopping.")
                break

        log("Script finished.")
    except Exception as e:
        log(f"Unexpected error: {traceback.format_exc()}")

    return log_stream.getvalue()

# ----------------------------------------------------------------------
# Gradio Interface with advanced features
# ----------------------------------------------------------------------
css = """
:root {
    --primary: #6C63FF;
    --secondary: #F50057;
    --bg-dark: #1E1E2F;
    --card-bg: #2A2A3C;
    --text: #EEEEEE;
}
body, .gradio-container {
    background: var(--bg-dark) !important;
    font-family: 'Inter', 'Segoe UI', sans-serif;
    color: var(--text) !important;
}
.gr-button {
    border-radius: 8px !important;
    font-weight: 600 !important;
    transition: 0.2s !important;
    border: none !important;
    padding: 10px 20px !important;
}
.gr-button.primary {
    background: var(--primary) !important;
    color: white !important;
}
.gr-button.secondary {
    background: var(--secondary) !important;
    color: white !important;
}
.gr-button:hover {
    opacity: 0.9 !important;
    transform: translateY(-1px);
}
.gr-box, .gr-form, .gr-panel {
    background: var(--card-bg) !important;
    border-radius: 12px !important;
    padding: 20px !important;
    box-shadow: 0 4px 6px rgba(0,0,0,0.2) !important;
}
.gr-textbox, .gr-number, .gr-slider, .gr-dropdown {
    background: #3A3A4C !important;
    border: 1px solid #4A4A5E !important;
    color: white !important;
    border-radius: 6px !important;
}
h1, h2, h3 {
    color: white !important;
}
.tab-nav {
    background: var(--card-bg) !important;
    border-radius: 12px !important;
    padding: 5px !important;
}
.gr-tab {
    color: #AAAAAA !important;
}
.gr-tab.selected {
    color: white !important;
    background: var(--primary) !important;
    border-radius: 8px !important;
}
"""

def build_interface():
    with gr.Blocks(css=css, title="YouTube Shorts Bot – Advanced Dashboard") as demo:
        # State variables
        settings_state = gr.State(DEFAULT_SETTINGS.copy())
        credentials_state = gr.State(None)  # Will hold a Credentials object or None
        oauth_flow_state = gr.State(None)

        gr.HTML("""
        <div style="text-align: center; padding: 20px 0;">
            <h1 style="font-size: 2.5rem; margin-bottom: 5px;">🎬 YouTube Shorts Bot</h1>
            <p style="font-size: 1.1rem; opacity: 0.8;">Automated creation & scheduling – all in your browser</p>
        </div>
        """)

        with gr.Tabs():
            # ──── Settings Tab ────
            with gr.TabItem("⚙️ Settings"):
                with gr.Row():
                    with gr.Column(scale=1):
                        gr.HTML("<h2>⏱️ Video</h2>")
                        total_dur = gr.Slider(5, 15, value=DEFAULT_SETTINGS["total_duration"],
                                              step=1, label="Duration (seconds)")
                        fade_dur = gr.Slider(0.5, 3.0, value=DEFAULT_SETTINGS["fade_duration"],
                                             step=0.1, label="Fade‑in (seconds)")
                        max_len = gr.Slider(30, 100, value=DEFAULT_SETTINGS["max_quote_len"],
                                            step=1, label="Max quote length")

                    with gr.Column(scale=1):
                        gr.HTML("<h2>📅 Upload Schedule (UTC)</h2>")
                        slots_input = gr.Textbox(value=DEFAULT_SETTINGS["slots"],
                                                 label="Slots (hour,min;hour,min;...)")
                        category = gr.Textbox(value=DEFAULT_SETTINGS["category_id"],
                                              label="Category ID")

                with gr.Row():
                    gr.HTML("<h2>🏷️ Tags & Description</h2>")
                base_tags = gr.Textbox(value=DEFAULT_SETTINGS["base_tags"],
                                       label="Base tags (comma separated)")
                desc_extra = gr.Textbox(value=DEFAULT_SETTINGS["description_extra"],
                                        label="Extra description line", lines=2)

                save_settings_btn = gr.Button("💾 Save Settings", variant="primary")

            # ──── Authentication Tab ────
            with gr.TabItem("🔐 Authentication"):
                gr.HTML("<h2>1. Upload client_secret.json</h2>")
                client_secret_file = gr.File(label="client_secret.json", file_types=[".json"])
                upload_msg = gr.Textbox(label="Status", interactive=False)

                gr.HTML("<h2>2. Authorize</h2>")
                auth_url_box = gr.Textbox(label="Authorization URL", interactive=False)
                code_input = gr.Textbox(label="Paste the code here")
                auth_btn = gr.Button("🔑 Authenticate", variant="primary")
                auth_status = gr.Textbox(label="Auth Status", interactive=False)

                gr.HTML("<h2>3. Current Token</h2>")
                token_status = gr.Textbox(label="Token status", interactive=False, value="No token loaded")

            # ──── Run Tab ────
            with gr.TabItem("🚀 Run Bot"):
                log_output = gr.Textbox(label="Live Log", lines=20, max_lines=30, autoscroll=True)
                run_btn = gr.Button("▶️ Start Processing", variant="primary")
                stop_btn = gr.Button("⏹️ Stop")

            # ──── Export / Import Tab ────
            with gr.TabItem("📦 Export / Import"):
                gr.HTML("<h2>Download your full configuration (settings + token)</h2>")
                export_btn = gr.Button("📥 Download Config File")
                export_file = gr.File(label="Download")

                gr.HTML("<h2>Upload a saved config file to restore everything</h2>")
                import_file = gr.File(label="Upload Config File")
                import_btn = gr.Button("📤 Restore Config")
                import_status = gr.Textbox(label="Import Status", interactive=False)

        # ------------------------------------------------------------------
        # Event handlers
        # ------------------------------------------------------------------

        # Save settings to state
        def save_settings(total_dur, fade_dur, max_len, slots, cat, tags, desc):
            new_settings = {
                "total_duration": total_dur,
                "fade_duration": fade_dur,
                "max_quote_len": max_len,
                "slots": slots,
                "category_id": cat,
                "base_tags": tags,
                "description_extra": desc
            }
            return gr.State(new_settings), gr.State(new_settings)

        save_settings_btn.click(
            fn=lambda td, fd, ml, sl, cat, bt, de: (td, fd, ml, sl, cat, bt, de),
            inputs=[total_dur, fade_dur, max_len, slots_input, category, base_tags, desc_extra],
            outputs=[settings_state, settings_state],
            queue=False
        )

        # Upload client_secret and create OAuth flow
        def handle_client_secret(file):
            if not file:
                return "No file uploaded", None, ""
            try:
                with open(file.name, "r") as f:
                    secret = json.load(f)
                # Basic validation
                if "installed" not in secret and "web" not in secret:
                    return "Invalid client_secret.json", None, ""
                flow = InstalledAppFlow.from_client_secrets_file(file.name, [
                    "https://www.googleapis.com/auth/youtube.upload",
                    "https://www.googleapis.com/auth/youtube.readonly"
                ])
                flow.redirect_uri = "http://localhost:8080"
                auth_url, _ = flow.authorization_url(prompt="consent")
                return "✅ client_secret loaded. Proceed to authorize.", flow, auth_url
            except Exception as e:
                return f"Error: {e}", None, ""

        client_secret_file.change(
            fn=handle_client_secret,
            inputs=client_secret_file,
            outputs=[upload_msg, oauth_flow_state, auth_url_box],
            queue=False
        )

        # Authenticate with code
        def authenticate(flow, code):
            if flow is None:
                return "❌ No client_secret loaded.", "", None
            if not code or not code.strip():
                return "❌ Please paste the code.", "", None
            try:
                flow.fetch_token(code=code)
                creds = flow.credentials
                # Test if valid
                service = build("youtube", "v3", credentials=creds)
                service.channels().list(part="id", mine=True).execute()
                return "✅ Successfully authenticated!", "Token valid", creds
            except Exception as e:
                return f"❌ Authentication failed: {e}", "", None

        auth_btn.click(
            fn=authenticate,
            inputs=[oauth_flow_state, code_input],
            outputs=[auth_status, token_status, credentials_state],
            queue=False
        )

        # Token status refresh
        def update_token_status(creds):
            if creds is None:
                return "No token loaded"
            if creds.valid:
                return "✅ Token is valid"
            elif creds.expired and creds.refresh_token:
                return "⏳ Token expired but can be refreshed"
            else:
                return "❌ Token invalid"

        credentials_state.change(
            fn=update_token_status,
            inputs=credentials_state,
            outputs=token_status,
            queue=False
        )

        # Run bot
        def run_bot_ui(settings, creds, log_history=""):
            # Create a log callback that appends to a string
            logs = []
            def log_callback(msg):
                logs.append(msg)
            full_log = run_bot(settings, creds, log_callback=log_callback)
            # For live update, we need to yield intermediate logs. Simpler: return final log.
            return full_log

        run_btn.click(
            fn=run_bot_ui,
            inputs=[settings_state, credentials_state],
            outputs=log_output,
            queue=True
        )

        # Export
        def export_config(settings, creds):
            if creds is None:
                return "No token to export. Authenticate first.", None
            # Serialize credentials
            creds_bytes = pickle.dumps(creds)
            filename = save_state_to_file(settings, creds_bytes)
            return "Config exported successfully!", filename

        export_btn.click(
            fn=export_config,
            inputs=[settings_state, credentials_state],
            outputs=[gr.Textbox(visible=False), export_file],
            queue=False
        )

        # Import
        def import_config(file, existing_settings):
            if not file:
                return "No file uploaded", existing_settings, None
            try:
                settings, creds = load_state_from_file(file.name)
                return f"✅ Config imported. {len(settings)} settings loaded.", settings, creds
            except Exception as e:
                return f"❌ Import failed: {e}", existing_settings, None

        import_btn.click(
            fn=import_config,
            inputs=[import_file, settings_state],
            outputs=[import_status, settings_state, credentials_state],
            queue=False
        )

    return demo

# Run the app
if __name__ == "__main__":
    app = build_interface()
    app.queue(default_concurrency_limit=1)
    app.launch(share=True, debug=False)
