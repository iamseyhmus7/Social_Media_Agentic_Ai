"""Export the four user-requested, account-verified videos as an explicit public showcase.

Original media and production/approval records are never modified.
Docker is used only to read/decode these exact video paths with its existing FFmpeg.
"""
from pathlib import Path
import json
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "data" / "media"
PUBLIC = ROOT / "frontend" / "public" / "showcase"
CONTENT = ROOT / "frontend" / "src" / "content"
REPORT = ROOT / "output" / "design-audit-2026-10-30"
VIDEOS = [
    ("brain-myth", "Beynimizin Sadece %10’unu mu Kullanıyoruz? Yaygın Yanlış İnanış", "Bilim",
     "e5adfd32-5db0-435a-9012-f37e3eb87372/ad8ece23-2357-4644-87e5-8abdfa3f5f68/video.mp4"),
    ("great-wall-myth", "Çin Seddi Ay’dan Görünür mü? Efsaneyi 45 Saniyede Çürütüyoruz", "Merak",
     "8ee1c5b7-6c9b-4178-b74c-69f14170249a/ffe3cceb-7c4c-4b45-8a6f-9f491ae2aebc/video.mp4"),
    ("napoleon", "Napolyon Kısa Değildi: İnçlerin Oyunu", "Tarih",
     "a5919ea2-363c-4a91-8cc5-c7038aa190c7/2cc797e0-c91d-4f68-a00b-79ed5b76946e/video.mp4"),
    ("adana-bridge", "Adana’nın Taş Köprüsü: Seyhan Üzerindeki Zaman Yolculuğu", "Keşif",
     "9a06e454-caba-4ec3-9398-af605ec2e2d1/0b3411f1-2ea4-41c5-91d3-19ea1accf957/video.mp4"),
]

def worker(*args, timeout=180):
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "worker", *args],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace")[-3000:])
    return result

def main():
    PUBLIC.mkdir(parents=True, exist_ok=True)
    CONTENT.mkdir(parents=True, exist_ok=True)
    REPORT.mkdir(parents=True, exist_ok=True)
    entries = []
    checks = []
    for slug, title, category, relative in VIDEOS:
        source = (MEDIA / relative).resolve()
        if not source.is_relative_to(MEDIA.resolve()) or not source.is_file():
            raise RuntimeError(f"Missing authorized media: {slug}")
        container_path = "/app/data/media/" + relative
        probe = json.loads(worker(
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height",
            "-of", "json", container_path,
        ).stdout)
        video = next(s for s in probe["streams"] if s["codec_type"] == "video")
        duration = float(probe["format"]["duration"])
        audio = any(s["codec_type"] == "audio" for s in probe["streams"])
        if duration <= 0 or video["width"] <= 0 or not audio:
            raise RuntimeError(f"Incomplete final video: {slug}")
        # Decode the whole export, including narration, rather than trusting a file extension.
        decoded = worker("ffmpeg", "-v", "error", "-threads", "2", "-i", container_path,
                         "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-")
        if decoded.stderr.strip():
            raise RuntimeError(f"Decode errors for {slug}: {decoded.stderr.decode('utf-8', errors='replace')[-2000:]}")
        poster = worker(
            "ffmpeg", "-v", "error", "-ss", str(min(3, duration / 5)), "-i", container_path,
            "-frames:v", "1", "-vf", "scale=540:-2", "-q:v", "3",
            "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
        ).stdout
        if not poster.startswith(bytes.fromhex("ffd8")):
            raise RuntimeError(f"Invalid poster for {slug}")
        shutil.copy2(source, PUBLIC / f"{slug}.mp4")
        (PUBLIC / f"{slug}.jpg").write_bytes(poster)
        entries.append({
            "id": slug, "title": title, "category": category,
            "src": f"/showcase/{slug}.mp4", "poster": f"/showcase/{slug}.jpg",
            "duration": round(duration, 2),
            "width": video["width"], "height": video["height"],
        })
        checks.append({
            "id": slug, "title": title, "source": relative,
            "duration": duration, "hasAudio": audio,
            "codec": video["codec_name"], "decoded": True,
            "bytes": source.stat().st_size,
        })
        print(f"Verified {slug}: {duration:.2f}s, {video['width']}x{video['height']}, audio, full decode", flush=True)
    (CONTENT / "showcase.json").write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (REPORT / "showcase-verification.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

if __name__ == "__main__":
    main()

