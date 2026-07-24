"""
第二版数据采集脚本
策略：
  1. Bing Images（精准英文关键词）
  2. YouTube 视频下载 + 抽帧（真实锅内视角）

用法：
  python classify/crawl_data2.py
"""

import os
import time
import cv2
import glob
import tempfile

_HERE    = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_HERE, "data")

# ── Part 1：Bing Images ───────────────────────────────────────────────────────
from icrawler.builtin import BingImageCrawler

TARGET_PER_QUERY = 100

BING_PLAN = [
    (
        "raw",
        [
            "scrambled eggs raw liquid pan cooking",
            "runny scrambled eggs undercooked liquid pan",
            "egg cracked into hot pan raw liquid",
            "soft raw scrambled eggs not cooked yet pan",
            "scrambled eggs very runny pan stove",
        ]
    ),
    (
        "done",
        [
            "perfect fluffy scrambled eggs golden yellow done pan",
            "scrambled eggs cooked fluffy plate",
            "chinese stir fry egg done wok golden",
            "scrambled eggs just cooked golden yellow pan",
            "homemade scrambled eggs finished golden fluffy plate",
        ]
    ),
    (
        "burnt",
        [
            "scrambled eggs burnt pan brown crispy overcooked",
            "overcooked scrambled eggs dark brown dry pan",
            "burnt eggs pan black bottom charred",
            "egg burnt wok dark brown overcooked dry",
            "fried egg burnt black crispy pan overdone",
        ]
    ),
]


def crawl_bing(keyword, save_dir, max_num):
    """用 Bing 爬取图片"""
    crawler = BingImageCrawler(
        storage={"root_dir": save_dir},
        downloader_threads=4,
        parser_threads=2,
    )
    crawler.crawl(
        keyword=keyword,
        max_num=max_num,
        min_size=(150, 150),
        file_idx_offset="auto",
    )


# ── Part 2：YouTube 视频下载 + 抽帧 ──────────────────────────────────────────
YOUTUBE_SEARCHES = [
    # burnt 类（焦糊炒蛋）
    ("burnt", "scrambled eggs overcooked burnt crispy pan cooking mistake", 20),
    ("burnt", "how to overcook scrambled eggs burnt tutorial",              20),
    ("burnt", "egg stir fry overcooked burnt wok chinese recipe",           20),
    # done 类（正常熟炒蛋）
    ("done",  "perfect scrambled eggs wok pan cooking full process",        12),
    ("done",  "chinese tomato egg stir fry recipe wok cooking",             12),
    ("done",  "scrambled eggs recipe fluffy golden pan step by step",       12),
    # raw 类（生蛋/过程）
    ("raw",   "scrambled eggs cooking from raw start to finish wok",        12),
    ("raw",   "egg cracked into hot pan cooking process raw to done",       12),
]

MAX_FRAMES_PER_VIDEO = 200


def download_and_extract(cls_name, search_term, frame_interval=15):
    """用 yt-dlp 搜索下载视频并抽帧"""
    import yt_dlp

    save_dir = os.path.join(DATA_DIR, cls_name)
    os.makedirs(save_dir, exist_ok=True)

    existing = [f for f in os.listdir(save_dir)
                if f.lower().endswith((".jpg", ".jpeg", ".png"))]
    start_idx = len(existing)

    with tempfile.TemporaryDirectory() as tmp_dir:
        video_path = os.path.join(tmp_dir, "video.%(ext)s")

        ydl_opts = {
            # 优先直接下载已合并的 mp4，回退到最佳单流
            "format": "bestvideo[ext=mp4][height<=480]+bestaudio[ext=m4a]/mp4/best[height<=480]/best",
            "outtmpl": video_path,
            "quiet":   True,
            "no_warnings": True,
            "noplaylist": True,
            "default_search": "ytsearch1",
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

        video_file = video_files[0]
        cap   = cv2.VideoCapture(video_file)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        print(f"  [抽帧] 总帧数={total}，间隔={frame_interval}")

        saved = 0
        img_idx = start_idx
        fi = 0
        while saved < MAX_FRAMES_PER_VIDEO and fi < total:
            cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
            ret, frame = cap.read()
            if not ret:
                break
            if frame.mean() > 10:   # 过滤纯黑帧
                out = os.path.join(save_dir, f"yt_{img_idx:06d}.jpg")
                cv2.imwrite(out, frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
                img_idx += 1
                saved   += 1
            fi += frame_interval

        cap.release()
        print(f"  [抽帧] 保存 {saved} 张 → {cls_name}/")
        return saved


# ── 主程序 ────────────────────────────────────────────────────────────────────
def main():
    print("=" * 65)
    print("  Chef Vision — 第二轮数据采集（Bing + YouTube 视频抽帧）")
    print("=" * 65)

    # Part 1: Bing
    print("\n── Part 1: Bing Images ────────────────────────────────────────")
    for cls_name, keywords in BING_PLAN:
        cls_dir = os.path.join(DATA_DIR, cls_name)
        os.makedirs(cls_dir, exist_ok=True)
        print(f"\n  [{cls_name}]")
        for kw in keywords:
            print(f"    Bing: {kw}")
            try:
                crawl_bing(kw, cls_dir, TARGET_PER_QUERY)
                time.sleep(2)
            except Exception as e:
                print(f"    [警告] {e}")
        n = len([f for f in os.listdir(cls_dir)
                 if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))])
        print(f"  [{cls_name}] Bing 完成: {n} 张")

    # Part 2: YouTube
    print("\n── Part 2: YouTube 视频抽帧 ───────────────────────────────────")
    for cls_name, search, interval in YOUTUBE_SEARCHES:
        print(f"\n  [{cls_name}]")
        download_and_extract(cls_name, search, frame_interval=interval)
        time.sleep(3)

    # 统计
    print("\n" + "=" * 65)
    print("  采集完成！各类别统计：")
    for cls in ["raw", "done", "burnt"]:
        d = os.path.join(DATA_DIR, cls)
        n = len([f for f in os.listdir(d)
                 if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))])
        print(f"    {cls}: {n} 张")
    print("  下一步: python classify/filter_data.py")
    print("=" * 65)


if __name__ == "__main__":
    main()
