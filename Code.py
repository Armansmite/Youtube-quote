#!/usr/bin/env python3
"""
automated_youtube_shorts.py

Creates 10-second YouTube Shorts (9:16 vertical) from quotes.
Uses Pillow for text – NO ImageMagick required.
Text auto-sizes to fill the screen width. Fallback serif fonts if Garamond missing.
"""

import json
import os
import sys
import random
import glob
import logging
import re
from PIL import Image, ImageDraw, ImageFont
import numpy as np
from moviepy.editor import ImageClip, AudioFileClip

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

# Preferred font file (if placed next to script)
FONT_FILE = "Garamond.ttf"

# Text styling
TEXT_COLOR = (255, 255, 255)
STROKE_COLOR = (0, 0, 0)
STROKE_WIDTH = 4
MARGIN = 100                    # px left/right margin

# Layout (Y positions from top, text auto‑centred horizontally)
QUOTE_Y = 700
WRITER_Y = 850

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
# Processed lines tracking (unchanged)
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
# Media file discovery (unchanged)
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
# Font helper – tries Garamond, then system serif fonts, then default
# ----------------------------------------------------------------------
def load_font(size):
    """Return a font object at the given size, falling back to available serif fonts."""
    # 1. Local Garamond.ttf
    if os.path.isfile(FONT_FILE):
        try:
            return ImageFont.truetype(FONT_FILE, size)
        except Exception:
            pass

    # 2. Common system serif fonts (cross‑platform)
    system_fonts = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
        "C:/Windows/Fonts/times.ttf",                 # Times New Roman
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

    # 3. Pillow default (ugly, but always works)
    logger.warning("No serif font found, using Pillow default.")
    return ImageFont.load_default()

# ----------------------------------------------------------------------
# Auto‑size text to fit width
# ----------------------------------------------------------------------
def fit_text(text, font_path_or_none, max_width, max_height=None):
    """Find the largest font size (int) so that the text fits within max_width."""
    low, high = 10, 200
    best_size = low

    # If no proper font, just use a reasonable size
    if font_path_or_none is None:
        return 50

    while low <= high:
        mid = (low + high) // 2
        try:
            font = ImageFont.truetype(font_path_or_none, mid) if isinstance(font_path_or_none, str) else load_font(mid)
        except Exception:
            # Fallback to default if truetype fails
            font = load_font(mid)
        bbox = ImageDraw.Draw(Image.new("RGB", (1,1))).textbbox((0,0), text, font=font)
        w = bbox[2] - bbox[0]
        if w <= max_width:
            best_size = mid
            low = mid + 1
        else:
            high = mid - 1
    return best_size

# ----------------------------------------------------------------------
# Draw text with stroke effect (unchanged logic)
# ----------------------------------------------------------------------
def draw_text_with_stroke(draw, text, xy, font, text_color, stroke_color, stroke_width):
    x, y = xy
    for dx in range(-stroke_width, stroke_width + 1):
        for dy in range(-stroke_width, stroke_width + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=stroke_color)
    draw.text((x, y), text, font=font, fill=text_color)

# ----------------------------------------------------------------------
# Build composite frame (now with auto‑sized fonts)
# ----------------------------------------------------------------------
def build_text_frame(image, quote, writer):
    """Return PIL image with quote and writer text auto‑sized."""
    img = image.copy()
    draw = ImageDraw.Draw(img)
    max_width = VIDEO_SIZE[0] - 2 * MARGIN

    # Determine the font file that will actually be used
    font_path = None
    if os.path.isfile(FONT_FILE):
        font_path = FONT_FILE
    else:
        # Pick the first available system font for truetype sizing
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

    # Auto‑size quote
    quote_size = fit_text(quote, font_path, max_width)
    quote_font = load_font(quote_size)

    # Auto‑size writer (usually shorter, but we still fit it)
    writer_text = f"– {writer}"
    writer_size = fit_text(writer_text, font_path, max_width)
    writer_font = load_font(writer_size)

    # Draw quote centred
    quote_bbox = draw.textbbox((0,0), quote, font=quote_font)
    quote_w = quote_bbox[2] - quote_bbox[0]
    quote_x = (VIDEO_SIZE[0] - quote_w) // 2
    draw_text_with_stroke(draw, quote, (quote_x, QUOTE_Y),
                          quote_font, TEXT_COLOR, STROKE_COLOR, STROKE_WIDTH)

    # Draw writer centred
    writer_bbox = draw.textbbox((0,0), writer_text, font=writer_font)
    writer_w = writer_bbox[2] - writer_bbox[0]
    writer_x = (VIDEO_SIZE[0] - writer_w) // 2
    draw_text_with_stroke(draw, writer_text, (writer_x, WRITER_Y),
                          writer_font, TEXT_COLOR, STROKE_COLOR, STROKE_WIDTH)

    return img

# ----------------------------------------------------------------------
# Video creation (unchanged except calling build_text_frame without sizes)
# ----------------------------------------------------------------------
def create_video(quote, writer, subject, image_path, music_path, output_path):
    # Background image
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

    # Build frame with auto‑sized text
    final_frame = build_text_frame(pil_img, quote, writer)
    img_array = np.array(final_frame)

    # Video clip with fade
    img_clip = ImageClip(img_array).set_duration(TOTAL_DURATION).fadein(FADE_DURATION)

    # Audio
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
# Main loop (unchanged)
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

        try:
            create_video(quote, writer, subject, image_path, music_path, output_path)
        except Exception as e:
            logger.error(f"Line {line_idx}: video creation failed – {e}. Skipping.")
            continue

        mark_processed(line_idx)
        logger.info(f"Line {line_idx}: successfully created {output_name}")

    logger.info("All unprocessed lines handled.")

if __name__ == "__main__":
    main()
