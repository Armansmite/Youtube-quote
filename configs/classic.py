# configs/classic.py
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy import ImageClip, AudioFileClip

def create_video(quote, writer, subject, image_path, music_path, output_path):
    # Example: a simple image with text (you can paste your full V1 logic here)
    pil_img = Image.open(image_path).convert("RGB")
    pil_img = pil_img.resize((1080, 1920), Image.LANCZOS)

    # Add text (basic, no stroke – you should use your own draw functions)
    draw = ImageDraw.Draw(pil_img)
    font = ImageFont.load_default()
    draw.text((100, 700), quote, fill="white", font=font)
    draw.text((100, 850), f"- {writer}", fill="white", font=font)

    # Write final frame
    final_array = np.array(pil_img)
    clip = ImageClip(final_array).set_duration(7)
    # Music
    audio = AudioFileClip(music_path).subclip(0, 7)
    clip = clip.with_audio(audio)
    clip.write_videofile(output_path, fps=30, codec="libx264", audio_codec="aac",
                         temp_audiofile="temp-audio.m4a", remove_temp=True,
                         verbose=False, logger=None)
    clip.close()
