"""
搜索纯锅内炒菜视频，只列出标题和时长，不下载
用于人工确认后再批量下载
"""
import yt_dlp

FFMPEG_DIR = r"C:\Users\wht\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin"

# 精心设计的关键词，确保纯锅内视角
SEARCHES = [
    # ASMR 类（全程只拍锅，无人脸）
    "ytsearch5:tomato egg stir fry ASMR cooking wok close up",
    "ytsearch5:番茄炒鸡蛋 ASMR 锅内",
    # 延时摄影类
    "ytsearch5:scrambled eggs cooking timelapse overhead wok",
    # 纯过程类
    "ytsearch5:tomato scrambled eggs wok overhead cooking process Chinese",
    "ytsearch5:番茄炒蛋 全程 锅内 no talking",
]

def search_only(query, n=5):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
        "ffmpeg_location": FFMPEG_DIR,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(query, download=False)
            entries = info.get("entries") or [info]
            results = []
            for e in entries[:n]:
                dur = e.get("duration") or 0
                title = e.get("title", "")
                url = e.get("url") or e.get("webpage_url", "")
                results.append((title, url, dur))
            return results
    except Exception as ex:
        return []

def main():
    print("=" * 70)
    print("  番茄炒蛋纯锅内视频搜索结果（只看标题，不下载）")
    print("=" * 70)

    all_results = []
    seen_urls = set()

    for q in SEARCHES:
        label = q.replace("ytsearch5:", "")[:50]
        print(f"\n── 关键词: {label} ──")
        results = search_only(q)
        for title, url, dur in results:
            if url in seen_urls:
                continue
            seen_urls.add(url)
            dur_i = int(dur) if dur else 0
            mins = dur_i // 60
            secs = dur_i % 60
            all_results.append((title, url, dur_i))
            print(f"  [{mins}:{secs:02d}] {title[:60]}")
            print(f"           {url}")

    print(f"\n共找到 {len(all_results)} 个候选视频")
    # 保存到文件方便查看
    with open("classify/video_candidates.txt", "w", encoding="utf-8") as f:
        for title, url, dur in all_results:
            mins = int(dur) // 60
            secs = int(dur) % 60
            f.write(f"[{mins}:{secs:02d}] {title}\n{url}\n\n")
    print("候选列表已保存到 classify/video_candidates.txt")

if __name__ == "__main__":
    main()
