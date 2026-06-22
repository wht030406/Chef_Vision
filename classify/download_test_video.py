"""
下载测试视频（不参与训练，纯测试模型效果）
搜索从生炒到熟到焦的完整过程视频
"""
import os
import yt_dlp

FFMPEG_DIR = r"C:\Users\wht\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_videos")
os.makedirs(OUT_DIR, exist_ok=True)

# 搜索关键词列表，按优先级排列
SEARCHES = [
    "scrambled eggs perfect vs overcooked burnt comparison cooking",
    "how to cook scrambled eggs wrong burnt overcooked tutorial",
    "scrambled eggs raw to overcooked burnt step by step",
    "cooking scrambled eggs from raw to done to burnt",
]

def download_video(search_term, out_path):
    ydl_opts = {
        "format": "bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/mp4[height<=720]/best[height<=720]",
        "outtmpl": out_path,
        "quiet": False,
        "no_warnings": True,
        "noplaylist": True,
        "default_search": "ytsearch1",
        "ffmpeg_location": FFMPEG_DIR,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(search_term, download=True)
        entries = info.get("entries", [info])
        title = entries[0].get("title", "unknown") if entries else "unknown"
        return title

def main():
    print("=" * 60)
    print("  下载测试视频（不参与训练）")
    print("=" * 60)
    
    for i, search in enumerate(SEARCHES):
        out_path = os.path.join(OUT_DIR, f"test_egg_{i+1}.%(ext)s")
        print(f"\n[{i+1}] 搜索: {search[:55]}...")
        try:
            title = download_video(search, out_path)
            print(f"  ✓ 下载成功: {title}")
            # 只下第一个成功的
            break
        except Exception as e:
            print(f"  ✗ 失败: {e}")
            continue

    # 列出下载的文件
    videos = [f for f in os.listdir(OUT_DIR) if f.endswith((".mp4", ".webm", ".mkv"))]
    print(f"\n测试视频目录: {OUT_DIR}")
    for v in videos:
        size = os.path.getsize(os.path.join(OUT_DIR, v)) / 1024 / 1024
        print(f"  {v}  ({size:.1f} MB)")

if __name__ == "__main__":
    main()
