#!/usr/bin/env python3
"""
automated_youtube_shorts.py

Creates 10-second YouTube Shorts (9:16 vertical) from quotes and uploads them to YouTube.
Uses Pillow for text – NO ImageMagick required.
"""

import json
import os
import sys
import random
import glob
import logging
import re
import pickle
from PIL import Image, ImageDraw, ImageFont
import numpy as np
from moviepy.editor import ImageClip, AudioFileClip

# YouTube upload imports
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
QUOTE_FILE = "quote.txt"
PROCESSED_FILE = "processed.txt"
IMAGE_DIR = "image"
MUSIC_DIR = "music"
OUTPUT_PREFIX = "output"
OUTPUT_EXT = ".mp4"

VIDEO_SIZE = (1080, 1920)   # 9:16 vertical
FPS = 30
TOTAL_DURATION = 10
FADE_DURATION = 2
MAX_QUOTE_LEN = 50

# Preferred font file
FONT_FILE = "Garamond.ttf"

# Text styling
TEXT_COLOR = (255, 255, 255)
STROKE_COLOR = (0, 0, 0)
STROKE_WIDTH = 4
MARGIN = 100

QUOTE_Y = 700
WRITER_Y = 850
WRITER_FONT_RATIO = 0.6

# YouTube API settings
CLIENT_SECRET_FILE = "client_secret.json"   # OAuth 2.0 credentials
TOKEN_FILE = "token.pickle"                 # stored authentication token
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
PRIVACY_STATUS = "public"                   # or "private", "unlisted"
CATEGORY_ID = "22"                          # People & Blogs
YOUTUBE_TAGS = ["shorts", "quotes"]         # default tags

# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Processed lines tracking
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

# ----------------------------------------------------------------------
# Media file discovery
# ----------------------------------------------------------------------
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

# ----------------------------------------------------------------------
# Font helper
# ----------------------------------------------------------------------
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
    logger.warning("No serif font found, using Pillow default.")
    return ImageFont.load_default()

# ----------------------------------------------------------------------
# Quote wrapping (unchanged)
# ----------------------------------------------------------------------
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
    font_path = None
    if os.path.isfile(FONT_FILE):
        font_path = FONT_FILE
    else:
        for p in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
            "C:/Windows/Fonts/times.ttf",
            "C:/Windows/Fonts/georgia.ttf",
            "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
            "/System/Library/Fonts/Georgia.ttf",
        ]:
            if os.path.isfile(p):
                font_path = p
                break
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
            w = draw.textbbox((0,0), line, font=font)[2] - draw.textbbox((0,0), line, font=font)[0]
            if w > max_width:
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

# ----------------------------------------------------------------------
# Build composite frame (unchanged)
# ----------------------------------------------------------------------
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
    writer_text = f"– {writer}"
    writer_bbox = draw.textbbox((0,0), writer_text, font=writer_font)
    writer_w = writer_bbox[2] - writer_bbox[0]
    writer_x = (VIDEO_SIZE[0] - writer_w) // 2
    writer_y = start_y + total_height + 30
    draw_text_with_stroke(draw, writer_text, (writer_x, writer_y),
                          writer_font, TEXT_COLOR, STROKE_COLOR, STROKE_WIDTH)
    return img

# ----------------------------------------------------------------------
# YouTube authentication & upload
# ----------------------------------------------------------------------
def get_authenticated_service():
    """
    Handles OAuth 2.0 flow, stores/refreshes token, returns a YouTube API service object.
    """
    credentials = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as token:
            credentials = pickle.load(token)
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
            credentials = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "wb") as token:
            pickle.dump(credentials, token)
    return build("youtube", "v3", credentials=credentials)

def upload_video(file_path, title, description, tags, category_id, privacy_status):
    """
    Uploads a video to YouTube and returns the video ID.
    Raises an exception on failure.
    """
    youtube = get_authenticated_service()
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
    media = MediaFileUpload(file_path, mimetype="video/mp4", resumable=True)
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            logger.info(f"Upload progress: {int(status.progress() * 100)}%")
    logger.info(f"Upload complete. Video ID: {response['id']}")
    return response["id"]

# ----------------------------------------------------------------------
# Video creation (unchanged)
# ----------------------------------------------------------------------
def create_video(quote, writer, subject, image_path, music_path, output_path):
    pil_img = Image.open(image_path).convert("RGB")
    img_w, img_h = pil_img.size
    target_w, target_h = VIDEO_SIZE
    scale = max(target_w / img_w, target_h / img_h)
    new_w = int(img_w * scale)
    new_h = int(img_h * scale)
    pil_img = pil_img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    pil_img = pil_img.crop((left, top, left + target_w, top + target_h))
    final_frame = build_text_frame(pil_img, quote, writer)
    img_array = np.array(final_frame)
    img_clip = ImageClip(img_array).set_duration(TOTAL_DURATION).fadein(FADE_DURATION)
    audio_clip = AudioFileClip(music_path)
    if audio_clip.duration > TOTAL_DURATION:
        audio_clip = audio_clip.subclip(0, TOTAL_DURATION)
    final_video = img_clip.set_audio(audio_clip)
    logger.info(f"Writing video to {output_path} ...")
    final_video.write_videofile(
        output_path,
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        temp_audiofile="temp-audio.m4a",
        remove_temp=True,
        verbose=False,
    )
    final_video.close()
    audio_clip.close()
    img_clip.close()

# ----------------------------------------------------------------------
# Main loop (now with upload)
# ----------------------------------------------------------------------
def main():
    processed = load_processed()
    logger.info(f"Already processed lines: {sorted(processed)}")

    if not os.path.exists(QUOTE_FILE):
        logger.error(f"Quote file {QUOTE_FILE} not found.")
        sys.exit(1)

    with open(QUOTE_FILE, "r") as f:
        lines = f.readlines()

    for line_idx, line in enumerate(lines, start=1):
        if line_idx in processed:
            continue
        line = line.strip()
        if not line:
            continue

        try:
            data = json.loads(line)
        except json.JSONDecodeError as e:
            logger.error(f"Line {line_idx}: invalid JSON – {e}. Skipping.")
            continue

        if not all(k in data for k in ("qoute", "writer", "subject")):
            logger.error(f"Line {line_idx}: missing required keys. Skipping.")
            continue

        quote = data["qoute"]
        writer = data["writer"]
        subject = data["subject"]

        if len(quote) > MAX_QUOTE_LEN:
            logger.info(f"Line {line_idx}: quote too long ({len(quote)} chars), skipping and marking processed.")
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
        output_name = f"{OUTPUT_PREFIX}_{next_idx:03d}{OUTPUT_EXT}"
        output_path = os.path.join(os.getcwd(), output_name)

        # 1. Create the video
        try:
            create_video(quote, writer, subject, image_path, music_path, output_path)
        except Exception as e:
            logger.error(f"Line {line_idx}: video creation failed – {e}. Skipping.")
            continue

        # 2. Upload to YouTube
        try:
            title = f"{quote} – {writer}"[:100]  # YouTube title limit
            description = f'"{quote}"\n\n– {writer}\n\nSubject: {subject}\n#shorts #quotes'
            tags = YOUTUBE_TAGS + [subject, writer, "shorts", "quotes"]
            upload_video(
                file_path=output_path,
                title=title,
                description=description,
                tags=tags,
                category_id=CATEGORY_ID,
                privacy_status=PRIVACY_STATUS
            )
        except Exception as e:
            logger.error(f"Line {line_idx}: upload failed – {e}. Video file kept, line not marked as processed.")
            # Do NOT mark as processed – will retry next time (and create a new video file)
            continue

        # If we get here, both creation and upload succeeded → mark processed
        mark_processed(line_idx)
        logger.info(f"Line {line_idx}: successfully created and uploaded {output_name}")

    logger.info("All unprocessed lines handled.")

if __name__ == "__main__":
    main()
