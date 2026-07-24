"""
专门搜索包含焦糊炒蛋片段的视频
策略：搜"失败/错误/过熟"类视频，这类视频会演示焦糊效果
"""
import yt_dlp

FFMPEG_DIR = r"C:\Users\wht\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin"

SEARCHES = [
    # 教训/失败类
    "ytsearch5:eggs overcooked burnt pan cooking mistake close up",
    "ytsearch5:how not to cook scrambled eggs overcooked demonstration",
    "ytsearch5:番茄炒蛋 失败 炒焦 过火",
    # 对比类
    "ytsearch5:perfect vs overcooked eggs comparison wok",
    "ytsearch5:炒蛋 火候 过熟 焦 锅内",
    # 直接搜焦糊
    "ytsearch5:burnt eggs wok Chinese cooking overcooked dark",
]

def main():
    seen = set()
    candidates = []

    for q in SEARCHES:
        opts = {"quiet": True, "no_warnings": True, "skip_download": True,
                "extract_flat": True, "ffmpeg_location": FFMPEG_DIR}
        label = q.replace("ytsearch5:", "")[:45]
        print(f"\n── {label} ──")
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(q, download=False)
                for e in (info.get("entries") or [info])[:5]:
                    url = e.get("url") or e.get("webpage_url", "")
                    if url in seen:
                        continue
                    seen.add(url)
                    dur = int(e.get("duration") or 0)
                    title = e.get("title", "")
                    candidates.append((title, url, dur))
                    print(f"  [{dur//60}:{dur%60:02d}] {title[:60]}")
                    print(f"           {url}")
        except Exception as ex:
            print(f"  失败: {ex}")

    with open("classify/burnt_video_candidates.txt", "w", encoding="utf-8") as f:
        for title, url, dur in candidates:
            f.write(f"[{dur//60}:{dur%60:02d}] {title}\n{url}\n\n")
    print(f"\n共 {len(candidates)} 个候选，已保存到 classify/burnt_video_candidates.txt")

if __name__ == "__main__":
    main()
