"""搜索并下载B站炒鸡蛋视频"""
import os
import yt_dlp

FFMPEG_DIR = r"C:\Users\wht\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_videos")
os.makedirs(OUT_DIR, exist_ok=True)

# 直接给几个B站炒鸡蛋的经典视频BV号
# 选短视频（2-5分钟），锅内过程视角
BILIBILI_URLS = [
    "https://www.bilibili.com/video/BV1Qs411j7ER",  # 番茄炒鸡蛋
    "https://www.bilibili.com/video/BV1ZT411C74n",  # 炒鸡蛋教程
    "https://www.bilibili.com/video/BV1Pb4y1e7Aq",  # 嫩炒鸡蛋
]

# 也尝试YouTube搜索，关键词更精准
YOUTUBE_SEARCHES = [
    "ytsearch1:scrambled eggs pan close up overhead cooking wok Chinese style",
    "ytsearch1:炒鸡蛋 锅内 全程 从生到熟",
    "ytsearch1:egg stir fry wok top view cooking process close up",
]

def get_info(url):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "ffmpeg_location": FFMPEG_DIR,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)

def download(url, out_name):
    opts = {
        "format": "bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/mp4[height<=720]/best",
        "outtmpl": os.path.join(OUT_DIR, out_name + ".%(ext)s"),
        "quiet": False,
        "no_warnings": True,
        "ffmpeg_location": FFMPEG_DIR,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return info

def main():
    print("=" * 60)
    print("  搜索炒鸡蛋视频（先预览标题，再下载）")
    print("=" * 60)

    candidates = []

    # 先从 YouTube 搜，稳定性更好
    print("\n── YouTube 搜索 ──")
    for url in YOUTUBE_SEARCHES:
        try:
            info = get_info(url)
            entries = info.get("entries") or [info]
            for e in entries[:1]:
                dur = e.get("duration", 0)
                title = e.get("title", "")
                webpage = e.get("webpage_url", url)
                print(f"  [{dur//60}:{dur%60:02d}] {title[:65]}")
                print(f"           {webpage}")
                candidates.append((title, webpage, dur))
        except Exception as ex:
            print(f"  搜索失败: {ex}")

    print("\n── B站 直链 ──")
    for url in BILIBILI_URLS:
        try:
            info = get_info(url)
            dur = info.get("duration", 0)
            title = info.get("title", "")
            print(f"  [{dur//60}:{dur%60:02d}] {title[:65]}")
            print(f"           {url}")
            candidates.append((title, url, dur))
        except Exception as ex:
            print(f"  获取失败: {ex}")

    if not candidates:
        print("\n[错误] 没有找到合适的视频")
        return

    # 自动选第一个 2-6 分钟的候选（不太短也不太长）
    chosen = None
    for title, url, dur in candidates:
        if 60 <= dur <= 600:
            chosen = (title, url)
            break
    if not chosen:
        chosen = (candidates[0][0], candidates[0][1])

    print(f"\n选择下载: {chosen[0][:65]}")
    print(f"链接: {chosen[1]}")
    try:
        download(chosen[1], "test_egg_cooking")
        print("\n下载完成！")
        # 列出下载结果
        for f in os.listdir(OUT_DIR):
            if "test_egg_cooking" in f:
                size = os.path.getsize(os.path.join(OUT_DIR, f)) / 1024 / 1024
                print(f"  {f}  ({size:.1f} MB)")
    except Exception as ex:
        print(f"下载失败: {ex}")

if __name__ == "__main__":
    main()
