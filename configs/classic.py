import os
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy import ImageClip, AudioFileClip, vfx

def create_video(quote, writer, subject, image_path, music_path, output_path,
                 total_duration=7, fade_duration=2):
    # --- Image preparation ---
    pil_img = Image.open(image_path).convert("RGB")
    target_w, target_h = 1080, 1920
    img_w, img_h = pil_img.size
    scale = max(target_w / img_w, target_h / img_h)
    new_w = int(img_w * scale)
    new_h = int(img_h * scale)
    pil_img = pil_img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    pil_img = pil_img.crop((left, top, left + target_w, top + target_h))

    draw = ImageDraw.Draw(pil_img)
    max_width = target_w - 200

    # --- Font loading (same fallback as before) ---
    font = None
    if os.path.exists("Garamond.ttf"):
        try:
            font = ImageFont.truetype("Garamond.ttf", 1)
        except:
            pass
    if font is None:
        for path in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
            "C:/Windows/Fonts/times.ttf",
            "C:/Windows/Fonts/georgia.ttf",
            "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
            "/System/Library/Fonts/Georgia.ttf",
        ]:
            if os.path.isfile(path):
                try:
                    font = ImageFont.truetype(path, 1)
                    break
                except:
                    continue
    if font is None:
        font = ImageFont.load_default()

    # --- Auto‑size helper ---
    def best_size(text_lines, max_w):
        low, high = 10, 200
        best = low
        while low <= high:
            mid = (low + high) // 2
            f = font.font_variant(size=mid)
            fits = True
            for line in text_lines:
                bbox = draw.textbbox((0, 0), line, font=f)
                if (bbox[2] - bbox[0]) > max_w:
                    fits = False
                    break
            if fits:
                best = mid
                low = mid + 1
            else:
                high = mid - 1
        return best

    # --- Split quote into two lines ---
    words = quote.split()
    if len(words) <= 1:
        lines = [quote]
    else:
        best_split = None
        for i in range(len(words) - 1, 0, -1):
            first = " ".join(words[:i])
            second = " ".join(words[i:])
            if len(first) >= len(second):
                if best_split is None or (len(first) > len(second)):
                    best_split = (first, second)
                    if len(first) > len(second):
                        break
        lines = list(best_split) if best_split else [quote]

    quote_size = best_size(lines, max_width)
    quote_font = font.font_variant(size=quote_size)
    writer_size = max(int(quote_size * 0.6), 12)
    writer_font = font.font_variant(size=writer_size)

    # --- Stroke helper ---
    def draw_text_with_stroke(text, xy, f, text_color, stroke_color, stroke_width):
        x, y = xy
        for dx in range(-stroke_width, stroke_width + 1):
            for dy in range(-stroke_width, stroke_width + 1):
                if dx != 0 or dy != 0:
                    draw.text((x + dx, y + dy), text, font=f, fill=stroke_color)
        draw.text((x, y), text, font=f, fill=text_color)

    line_height = quote_font.getbbox("Ag")[3] - quote_font.getbbox("Ag")[1]
    total_text_height = line_height * len(lines) + (len(lines) - 1) * 10
    start_y = 700 - total_text_height // 2

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=quote_font)
        line_w = bbox[2] - bbox[0]
        line_x = (target_w - line_w) // 2
        line_y = start_y + i * (line_height + 10)
        draw_text_with_stroke(line, (line_x, line_y), quote_font,
                              (255, 255, 255), (0, 0, 0), 4)

    writer_text = f"- {writer}"
    writer_bbox = draw.textbbox((0, 0), writer_text, font=writer_font)
    writer_w = writer_bbox[2] - writer_bbox[0]
    writer_x = (target_w - writer_w) // 2
    writer_y = start_y + total_text_height + 30
    draw_text_with_stroke(writer_text, (writer_x, writer_y), writer_font,
                          (255, 255, 255), (0, 0, 0), 4)

    # --- MoviePy v2 clip creation ---
    img_array = np.array(pil_img)
    clip = ImageClip(img_array).with_duration(total_duration)
    if fade_duration > 0:
        clip = clip.with_effects([vfx.FadeIn(fade_duration)])

    audio = AudioFileClip(music_path)
    if audio.duration > total_duration:
        audio = audio.subclipped(0, total_duration)
    clip = clip.with_audio(audio)

    # REMOVED verbose=False and logger=None
    clip.write_videofile(
        output_path,
        fps=30,
        codec="libx264",
        audio_codec="aac",
        temp_audiofile="temp-audio.m4a",
        remove_temp=True,
    )
    clip.close()
    audio.close()
