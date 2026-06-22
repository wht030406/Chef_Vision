"""
用 icrawler 爬取番茄炒蛋焦糊图片作为 burnt 训练数据
"""
import os
from icrawler.builtin import BingImageCrawler, GoogleImageCrawler

OUT_DIR = r"D:\Chef_Vision\classify\data_tomato\burnt"
os.makedirs(OUT_DIR, exist_ok=True)

QUERIES = [
    "burnt tomato scrambled eggs overcooked wok",
    "overcooked tomato egg stir fry charred",
    "tomato eggs burnt crispy brown wok Chinese",
    "番茄炒蛋 焦糊 过熟",
]

def crawl():
    total_before = len(os.listdir(OUT_DIR))

    for i, q in enumerate(QUERIES):
        print(f"\n[{i+1}/{len(QUERIES)}] 搜索: {q}")
        save_dir = os.path.join(OUT_DIR, f"tmp_{i}")
        os.makedirs(save_dir, exist_ok=True)

        # 用 Bing
        try:
            crawler = BingImageCrawler(
                storage={"root_dir": save_dir},
                downloader_threads=4,
            )
            crawler.crawl(keyword=q, max_num=25, min_size=(100, 100))
        except Exception as e:
            print(f"  Bing 失败: {e}")

        # 把图片移到 burnt 目录
        moved = 0
        for f in os.listdir(save_dir):
            if f.lower().endswith((".jpg", ".jpeg", ".png")):
                src = os.path.join(save_dir, f)
                dst = os.path.join(OUT_DIR, f"burnt_{i:02d}_{f}")
                os.replace(src, dst)
                moved += 1
        try:
            os.rmdir(save_dir)
        except Exception:
            pass
        print(f"  移入 {moved} 张")

    total_after = len([f for f in os.listdir(OUT_DIR) if f.endswith((".jpg", ".jpeg", ".png"))])
    print(f"\n✓ burnt 总计: {total_after} 张（新增 {total_after - total_before} 张）")


if __name__ == "__main__":
    crawl()
