"""
批量下载确认过的纯锅内炒菜视频
下载完自动打开第一个让用户预览
"""
import os
import yt_dlp

FFMPEG_DIR = r"C:\Users\wht\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_videos")
os.makedirs(OUT_DIR, exist_ok=True)

# 精选的纯锅内视频（ASMR/无旁白/纯过程）
SELECTED = [
    ("asmr_tomato_egg_cantonese", "https://www.youtube.com/watch?v=QTy3rnSp9gE"),   # 7:21 广式ASMR番茄炒蛋
    ("tomato_egg_pure_cantonese", "https://www.youtube.com/watch?v=3TuaVXQvc4k"),   # 8:55 粤语纯过程
    ("kenji_tomato_egg",          "https://www.youtube.com/watch?v=FL7u21QGoo0"),   # 12:36 Kenji俯视
    ("chef_wang_asmr",            "https://www.youtube.com/watch?v=jRspAjKVZFo"),   # 5:01 厨师王ASMR
    ("tomato_egg_chinese_comfort","https://www.youtube.com/watch?v=N7G-aETYhu8"),   # 10:25 中式家常
]

def download_one(name, url):
    out = os.path.join(OUT_DIR, name + ".%(ext)s")
    opts = {
        "format": "bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/mp4[height<=720]/best",
        "outtmpl": out,
        "quiet": False,
        "no_warnings": True,
        "ffmpeg_location": FFMPEG_DIR,
        "noplaylist": True,
    }
    print(f"\n下载: {name}")
    print(f"  {url}")
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    # 找到实际文件
    for f in os.listdir(OUT_DIR):
        if f.startswith(name) and f.endswith(".mp4"):
            size = os.path.getsize(os.path.join(OUT_DIR, f)) / 1024 / 1024
            print(f"  ✓ {f}  ({size:.1f} MB)")
            return os.path.join(OUT_DIR, f)
    return None

def main():
    print("=" * 60)
    print("  批量下载纯锅内番茄炒蛋视频")
    print("=" * 60)

    downloaded = []
    for name, url in SELECTED:
        try:
            path = download_one(name, url)
            if path:
                downloaded.append(path)
        except Exception as e:
            print(f"  ✗ 失败: {e}")

    print(f"\n共下载 {len(downloaded)} 个视频:")
    for p in downloaded:
        size = os.path.getsize(p) / 1024 / 1024
        print(f"  {os.path.basename(p)}  ({size:.1f} MB)")

    # 自动打开第一个让用户预览
    if downloaded:
        print(f"\n自动打开第一个视频预览: {os.path.basename(downloaded[0])}")
        os.startfile(downloaded[0])

if __name__ == "__main__":
    main()
