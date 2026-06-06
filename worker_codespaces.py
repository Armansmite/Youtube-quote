import os, sys, json, time, requests, random, re, glob, warnings, traceback
from datetime import datetime, timedelta
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import ImageClip, AudioFileClip
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

warnings.filterwarnings("ignore")

DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "https://pwa-gqoh.onrender.com/").rstrip("/") + "/"
CODESPACE_NAME = os.environ.get("CODESPACE_NAME")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "Armansmite/Youtube-quote")

# ---------- Log ----------
def send_log(msg):
    print(msg)
    try:
        requests.post(DASHBOARD_URL + "api/log", json={"message": msg}, timeout=5)
    except:
        pass

def download_token():
    send_log("📥 Downloading token from dashboard...")
    r = requests.get(DASHBOARD_URL + "api/token")
    if r.status_code == 200:
        with open("token.json", "w") as f:
            f.write(r.text)
        send_log("✅ token.json saved.")
        return True
    send_log("❌ No token found on dashboard.")
    return False

def get_settings():
    r = requests.get(DASHBOARD_URL + "api/settings")
    if r.status_code != 200:
        raise Exception("Could not fetch settings")
    return r.json()

# ---------- V1 helper functions ----------
def load_processed():
    if not os.path.exists("processed.txt"): return set()
    with open("processed.txt", "r") as f:
        return {int(line) for line in f.read().splitlines() if line.strip().isdigit()}

def mark_processed(line_num):
    with open("processed.txt", "a") as f:
        f.write(f"{line_num}\n")

def get_next_output_index():
    existing = glob.glob("output_*.mp4")
    max_idx = 0
    for fname in existing:
        m = re.match(r"output_(\d+)\.mp4", os.path.basename(fname))
        if m:
            idx = int(m.group(1))
            if idx > max_idx: max_idx = idx
    return max_idx + 1

def find_images(subject):
    folder = "image"
    if not os.path.isdir(folder): return []
    patterns = [
        os.path.join(folder, f"{subject}_*.jpg"),
        os.path.join(folder, f"{subject}_*.JPG"),
        os.path.join(folder, f"{subject}_*.jpeg"),
        os.path.join(folder, f"{subject}_*.JPEG"),
        os.path.join(folder, f"{subject}_*.png"),
        os.path.join(folder, f"{subject}_*.PNG"),
    ]
    images = []
    for pat in patterns: images.extend(glob.glob(pat))
    return images

def find_music(subject):
    folder = "music"
    if not os.path.isdir(folder): return []
    patterns = [
        os.path.join(folder, f"{subject}_*.mp3"),
        os.path.join(folder, f"{subject}_*.MP3"),
        os.path.join(folder, f"{subject}_*.m4a"),
        os.path.join(folder, f"{subject}_*.M4A"),
    ]
    music = []
    for pat in patterns: music.extend(glob.glob(pat))
    return music

def load_font(size):
    if os.path.isfile("Garamond.ttf"):
        try: return ImageFont.truetype("Garamond.ttf", size)
        except: pass
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
            try: return ImageFont.truetype(path, size)
            except: continue
    return ImageFont.load_default()

def split_quote_two_lines(quote):
    words = quote.split()
    if len(words) <= 1: return [quote]
    best_split = None
    for i in range(len(words)-1, 0, -1):
        first = " ".join(words[:i])
        second = " ".join(words[i:])
        if len(first) >= len(second):
            if best_split is None or (len(first) > len(second) and len(best_split[0]) == len(best_split[1])):
                best_split = (first, second)
            if len(first) > len(second): break
    if best_split is None: return [quote]
    return list(best_split)

def best_font_size(lines, max_width):
    font_path = "Garamond.ttf" if os.path.isfile("Garamond.ttf") else None
    low, high = 10, 200
    best = low
    while low <= high:
        mid = (low + high) // 2
        try:
            font = ImageFont.truetype(font_path, mid) if font_path else load_font(mid)
        except: font = load_font(mid)
        draw = ImageDraw.Draw(Image.new("RGB", (1,1)))
        fits = True
        for line in lines:
            bbox = draw.textbbox((0,0), line, font=font)
            if (bbox[2] - bbox[0]) > max_width:
                fits = False
                break
        if fits: best = mid; low = mid + 1
        else: high = mid - 1
    return best

def draw_text_with_stroke(draw, text, xy, font, text_color, stroke_color, stroke_width):
    x, y = xy
    for dx in range(-stroke_width, stroke_width+1):
        for dy in range(-stroke_width, stroke_width+1):
            if dx != 0 or dy != 0:
                draw.text((x+dx, y+dy), text, font=font, fill=stroke_color)
    draw.text((x, y), text, font=font, fill=text_color)

# ---------- Dynamic config import ----------
def get_config_module(active_config):
    sys.path.insert(0, os.getcwd())
    return __import__(f"configs.{active_config}", fromlist=["create_video"])

# ---------- Delete Codespace ----------
def delete_codespace():
    if not CODESPACE_NAME or not GITHUB_TOKEN:
        send_log("⚠️ Missing CODESPACE_NAME or GITHUB_TOKEN, cannot delete Codespace.")
        return
    url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/codespaces/{CODESPACE_NAME}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    try:
        resp = requests.delete(url, headers=headers)
        if resp.status_code == 202:
            send_log("🧹 Codespace deletion initiated.")
        else:
            send_log(f"⚠️ Could not delete codespace: {resp.text}")
    except Exception as e:
        send_log(f"❌ Deletion error: {e}")

# ---------- Main ----------
def main():
    send_log("🚀 Codespace worker started.")
    if not download_token():
        delete_codespace()
        return

    with open("token.json", "r") as f:
        creds = Credentials.from_authorized_user_info(json.load(f))

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            send_log("🔁 Token refreshed.")
        except Exception as e:
            send_log(f"❌ Token refresh failed: {e}")
            delete_codespace()
            return

    if not creds.valid:
        send_log("❌ Invalid token.")
        delete_codespace()
        return

    settings = get_settings()
    active_config = settings.get("active_config", "classic")
    max_videos = settings.get("max_videos", 0) or None
    slots = settings.get("slots", ["05:30", "11:30", "17:30", "23:30"])
    base_tags = settings.get("base_tags", "shorts, quotes, motivation, wisdom").split(",")
    description_extra = settings.get("description_extra", "")
    category_id = settings.get("category_id", "22")
    total_duration = settings.get("total_duration", 7)
    fade_duration = settings.get("fade_duration", 2)
    max_quote_len = settings.get("max_quote_len", 50)

    slot_tuples = [(int(h), int(m)) for h, m in (s.split(":") for s in slots)]

    try:
        config_module = get_config_module(active_config)
        create_video_fn = config_module.create_video
    except Exception as e:
        send_log(f"❌ Failed to import config '{active_config}': {e}")
        delete_codespace()
        return

    processed = load_processed()
    send_log(f"Already processed: {sorted(processed)}")
    if not os.path.exists("quote.txt"):
        send_log("❌ quote.txt not found.")
        delete_codespace()
        return

    with open("quote.txt", "r") as f:
        lines = f.readlines()

    to_process = []
    for idx, line in enumerate(lines, start=1):
        if idx in processed: continue
        line = line.strip()
        if not line: continue
        try:
            data = json.loads(line)
            if all(k in data for k in ("qoute", "writer", "subject")):
                to_process.append((idx, line, data))
        except:
            send_log(f"Line {idx}: invalid JSON, skipping.")

    if not to_process:
        send_log("No unprocessed lines. Exiting.")
        delete_codespace()
        return

    service = build("youtube", "v3", credentials=creds)

    def get_scheduled_times():
        channel_response = service.channels().list(part="contentDetails", mine=True).execute()
        uploads_id = channel_response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        video_ids = []
        next_page_token = None
        while True:
            playlist_response = service.playlistItems().list(
                part="snippet", playlistId=uploads_id, maxResults=50, pageToken=next_page_token
            ).execute()
            video_ids.extend([item["snippet"]["resourceId"]["videoId"] for item in playlist_response["items"]])
            next_page_token = playlist_response.get("nextPageToken")
            if not next_page_token: break
        if not video_ids: return set()
        times = set()
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i:i+50]
            vid_response = service.videos().list(part="status", id=",".join(batch)).execute()
            for item in vid_response["items"]:
                status = item["status"]
                if status.get("privacyStatus") == "private" and "publishAt" in status:
                    dt = datetime.strptime(status["publishAt"].replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
                    if dt > datetime.utcnow():
                        times.add(dt)
        return times

    occupied = get_scheduled_times()
    send_log(f"Found {len(occupied)} already scheduled slots.")

    def next_free_slot(occ, slot_tuples):
        now = datetime.utcnow()
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        while True:
            for h, m in slot_tuples:
                candidate = day.replace(hour=h, minute=m, second=0, microsecond=0)
                if candidate > now and candidate not in occ:
                    return candidate
            day += timedelta(days=1)

    next_slot = next_free_slot(occupied, slot_tuples)
    send_log(f"First free slot: {next_slot.strftime('%Y-%m-%d %H:%M:%S UTC')}")

    videos_processed = 0
    for line_idx, line, data in to_process:
        if max_videos is not None and videos_processed >= max_videos:
            send_log(f"Reached max videos limit ({max_videos}). Stopping.")
            break

        quote = data["qoute"]
        writer = data["writer"]
        subject = data["subject"]

        if len(quote) > max_quote_len:
            send_log(f"Line {line_idx}: quote too long, marking processed.")
            mark_processed(line_idx)
            continue

        imgs = find_images(subject)
        if not imgs:
            send_log(f"Line {line_idx}: no images for subject '{subject}'. Skipping.")
            continue
        musics = find_music(subject)
        if not musics:
            send_log(f"Line {line_idx}: no music for subject '{subject}'. Skipping.")
            continue

        image_path = random.choice(imgs)
        music_path = random.choice(musics)

        next_idx = get_next_output_index()
        video_name = f"output_{next_idx:03d}.mp4"
        thumb_name = f"output_{next_idx:03d}_thumb.jpg"
        video_path = os.path.join(os.getcwd(), video_name)
        thumb_path = os.path.join(os.getcwd(), thumb_name)

        # Use the config's create_video – it must accept (quote, writer, subject, image_path, music_path, output_path)
        try:
            create_video_fn(quote, writer, subject, image_path, music_path, video_path)
            send_log(f"✅ Created {video_name}")
        except Exception as e:
            send_log(f"❌ Line {line_idx}: creation failed – {e}. Skipping.")
            continue

        # Upload
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

            body = {
                "snippet": {
                    "title": title,
                    "description": description,
                    "tags": tags,
                    "categoryId": category_id
                },
                "status": {
                    "privacyStatus": "private",
                    "selfDeclaredMadeForKids": False,
                },
            }
            publish_str = next_slot.strftime("%Y-%m-%dT%H:%M:%SZ")
            body["status"]["publishAt"] = publish_str

            media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
            request_obj = service.videos().insert(part="snippet,status", body=body, media_body=media)
            response = None
            while response is None:
                status, response = request_obj.next_chunk()
            send_log(f"📤 Uploaded & scheduled at {publish_str}")

            mark_processed(line_idx)
            occupied.add(next_slot)
            next_slot = next_free_slot(occupied, slot_tuples)
            videos_processed += 1

        except Exception as e:
            send_log(f"❌ Line {line_idx}: upload failed – {e}. Stopping.")
            break

    send_log("🏁 Finished.")
    delete_codespace()

if __name__ == "__main__":
    main()
