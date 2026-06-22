"""
YouTube 视频抽帧脚本（独立运行）
ffmpeg 路径已硬编码，不依赖系统 PATH

用法：
  python classify/crawl_youtube.py
"""

import os
import cv2
import glob
import tempfile
import time

_HERE    = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_HERE, "data")

FFMPEG_PATH = r"C:\Users\wht\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin\ffmpeg.exe"

YOUTUBE_SEARCHES = [
    # burnt 类
    ("burnt", "scrambled eggs overcooked burnt crispy pan cooking",   20),
    ("burnt", "how to burn scrambled eggs mistake cooking tutorial",  20),
    ("burnt", "stir fry egg burnt wok overcooked chinese cooking",    20),
    # done 类
    ("done",  "perfect scrambled eggs wok pan cooking full process",  12),
    ("done",  "chinese tomato egg stir fry recipe wok cooking",       12),
    ("done",  "scrambled eggs recipe fluffy golden pan tutorial",     12),
    # raw 类
    ("raw",   "scrambled eggs cooking from raw start to finish",      12),
    ("raw",   "egg cracked into hot pan cooking process raw to done", 12),
]

MAX_FRAMES = 200


def download_and_extract(cls_name, search_term, frame_interval=15):
    import yt_dlp

    save_dir = os.path.join(DATA_DIR, cls_name)
    os.makedirs(save_dir, exist_ok=True)

    existing  = [f for f in os.listdir(save_dir)
                 if f.lower().endswith((".jpg", ".jpeg", ".png"))]
    start_idx = len(existing)

    with tempfile.TemporaryDirectory() as tmp_dir:
        ydl_opts = {
            "format": "bestvideo[ext=mp4][height<=480]+bestaudio[ext=m4a]/mp4[height<=480]/best",
            "outtmpl": os.path.join(tmp_dir, "video.%(ext)s"),
            "quiet":        True,
            "no_warnings":  True,
            "noplaylist":   True,
            "default_search": "ytsearch1",
            "ffmpeg_location": os.path.dirname(FFMPEG_PATH),
        }

        print(f"  [YouTube] {search_term[:55]}...")
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([search_term])
        except Exception as e:
            print(f"  [警告] 下载失败: {e}")
            return 0

        video_files = glob.glob(os.path.join(tmp_dir, "video.*"))
        if not video_files:
            print("  [警告] 未找到视频文件")
            return 0

        cap   = cv2.VideoCapture(video_files[0])
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        print(f"  [抽帧] 总帧数={total}，间隔={frame_interval}")

        saved = 0
        img_idx = start_idx
        fi = 0
        while saved < MAX_FRAMES and fi < total:
            cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
            ret, frame = cap.read()
            if not ret:
                break
            if frame.mean() > 10:
                out = os.path.join(save_dir, f"yt_{img_idx:06d}.jpg")
                cv2.imwrite(out, frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
                img_idx += 1
                saved   += 1
            fi += frame_interval

        cap.release()
        print(f"  [抽帧] 保存 {saved} 张 → {cls_name}/")
        return saved


def main():
    print("=" * 60)
    print("  Chef Vision — YouTube 视频抽帧")
    print("=" * 60)

    if not os.path.exists(FFMPEG_PATH):
        print(f"[错误] ffmpeg 未找到: {FFMPEG_PATH}")
        return

    for cls_name, search, interval in YOUTUBE_SEARCHES:
        print(f"\n  [{cls_name}]")
        download_and_extract(cls_name, search, frame_interval=interval)
        time.sleep(2)

    print("\n" + "=" * 60)
    for cls in ["raw", "done", "burnt"]:
        d = os.path.join(DATA_DIR, cls)
        n = len([f for f in os.listdir(d)
                 if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))])
        print(f"  {cls}: {n} 张")
    print("=" * 60)


if __name__ == "__main__":
    main()
