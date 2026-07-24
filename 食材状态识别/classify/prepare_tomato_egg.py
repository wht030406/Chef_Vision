"""
准备番茄炒蛋专用训练数据：
1. 从视频按标注时间段抽帧 → raw / done
2. 从网上爬 burnt 图片（番茄炒蛋焦糊）
"""
import cv2
import os
import shutil
import yt_dlp
import requests
import hashlib
from PIL import Image
import io

VIDEO = r"D:\Chef_Vision\classify\test_videos\asmr_tomato_egg.mp4"
DATA_DIR = r"D:\Chef_Vision\classify\data_tomato"

# 按标注定义的时间段（秒）
SEGMENTS = {
    "raw":  [(148, 166)],        # 2:28~2:46 生蛋液下锅
    "done": [(296, 332)],        # 4:56~5:32 蛋+番茄炒好
}

FFMPEG_DIR = r"C:\Users\wht\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin"


# ── 1. 从视频抽帧 ────────────────────────────────────────────
def extract_from_video():
    cap = cv2.VideoCapture(VIDEO)
    fps = cap.get(cv2.CAP_PROP_FPS)

    for label, segs in SEGMENTS.items():
        out = os.path.join(DATA_DIR, label)
        os.makedirs(out, exist_ok=True)
        count = 0
        for start, end in segs:
            t = start
            while t <= end:
                cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
                ret, frame = cap.read()
                if ret:
                    fname = os.path.join(out, f"video_{int(t):04d}s.jpg")
                    cv2.imwrite(fname, frame)
                    count += 1
                t += 1  # 每秒1帧
        print(f"  {label}: {count} 帧")

    cap.release()


# ── 2. 爬 burnt 图片 ─────────────────────────────────────────
BURNT_QUERIES = [
    "burnt tomato scrambled eggs overcooked",
    "overcooked tomato eggs wok burnt brown",
    "番茄炒蛋 炒焦 焦糊",
    "tomato eggs burnt crispy wok charred",
]

def download_image(url, save_path):
    try:
        r = requests.get(url, timeout=8,
                         headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200 and len(r.content) > 5000:
            img = Image.open(io.BytesIO(r.content)).convert("RGB")
            img = img.resize((224, 224))
            img.save(save_path, "JPEG", quality=90)
            return True
    except Exception:
        pass
    return False

def crawl_burnt():
    out = os.path.join(DATA_DIR, "burnt")
    os.makedirs(out, exist_ok=True)

    total = 0
    for q in BURNT_QUERIES:
        if total >= 60:
            break
        print(f"  搜索: {q}")
        # 用 Bing Images 搜索
        try:
            search_url = f"https://www.bing.com/images/search?q={requests.utils.quote(q)}&form=HDRSC2&first=1&tsc=ImageHoverTitle"
            r = requests.get(search_url, timeout=10,
                             headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
            if r.status_code != 200:
                continue
            import re
            # 从 Bing 图片结果提取图片 URL
            img_urls = re.findall(r'"murl":"(https?://[^"]+\.(?:jpg|jpeg|png))"', r.text)
            for img_url in img_urls[:20]:
                if total >= 60:
                    break
                h = hashlib.md5(img_url.encode()).hexdigest()[:8]
                save = os.path.join(out, f"burnt_{h}.jpg")
                if os.path.exists(save):
                    continue
                if download_image(img_url, save):
                    total += 1
                    if total % 10 == 0:
                        print(f"    已下载 {total} 张")
        except Exception as ex:
            print(f"  搜索失败: {ex}")

    print(f"  burnt: {total} 张图片")


# ── 3. 统计 ──────────────────────────────────────────────────
def summary():
    print("\n── 数据统计 ──")
    for cls in ["raw", "done", "burnt"]:
        d = os.path.join(DATA_DIR, cls)
        n = len([f for f in os.listdir(d) if f.endswith(".jpg")]) if os.path.exists(d) else 0
        print(f"  {cls:8s}: {n:4d} 张")


def main():
    print("=" * 50)
    print("  准备番茄炒蛋训练数据")
    print("=" * 50)

    print("\n[1] 从视频抽帧...")
    extract_from_video()

    print("\n[2] 爬取 burnt 图片...")
    crawl_burnt()

    summary()
    print("\n完成！运行 python classify/train.py 开始训练")


if __name__ == "__main__":
    main()
