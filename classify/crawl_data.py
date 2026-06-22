"""
炒鸡蛋训练数据爬取脚本
分三类爬取：raw（未熟）、done（熟）、burnt（焦糊）
数据源：Bing（国内可访问，效果好）+ 百度图片备用

用法：
  python classify/crawl_data.py

输出：
  classify/data/raw/     ← 未熟/生蛋液图片
  classify/data/done/    ← 熟炒蛋图片
  classify/data/burnt/   ← 焦糊炒蛋图片
"""

import os
import time
from icrawler.builtin import BingImageCrawler, BaiduImageCrawler, GoogleImageCrawler

# 输出目录（相对于本脚本）
_HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_HERE, "data")

# 每类目标数量（Bing 国内可访问，作为主力）
TARGET_PER_QUERY = 120   # 每个关键词爬 120 张，多关键词叠加后筛选

# ── 爬取配置 ──────────────────────────────────────────────────────────────────
# 格式：(类别目录, [(搜索引擎, 关键词列表), ...])
CRAWL_PLAN = [
    (
        "raw",   # 未熟/蛋液状态
        [
            ("bing",   ["炒蛋 未熟", "炒蛋 生", "半熟炒蛋", "嫩炒蛋 蛋液"]),
            ("bing",   ["scrambled eggs undercooked", "runny scrambled eggs",
                        "soft scrambled eggs raw", "underdone scrambled eggs"]),
            ("baidu",  ["炒蛋 未熟", "炒蛋 嫩 蛋液", "半熟蛋液"]),
        ]
    ),
    (
        "done",  # 熟透/正常炒蛋
        [
            ("bing",   ["嫩滑炒蛋", "黄金炒蛋", "炒蛋 熟", "家常炒鸡蛋"]),
            ("bing",   ["scrambled eggs done", "fluffy scrambled eggs",
                        "perfect scrambled eggs", "cooked scrambled eggs"]),
            ("baidu",  ["嫩滑炒蛋", "炒鸡蛋 熟", "黄金炒蛋"]),
        ]
    ),
    (
        "burnt", # 焦糊/过熟
        [
            ("bing",   ["炒蛋 焦", "鸡蛋炒糊了", "炒焦的鸡蛋", "焦黑炒蛋"]),
            ("bing",   ["burnt scrambled eggs", "overcooked scrambled eggs",
                        "burnt eggs pan", "charred scrambled eggs"]),
            ("baidu",  ["炒蛋 焦糊", "炒蛋 焦黑", "鸡蛋炒糊"]),
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
        min_size=(100, 100),    # 过滤太小的图
        max_size=None,
        file_idx_offset="auto", # 自动续号，不覆盖已有文件
    )


def crawl_baidu(keyword, save_dir, max_num):
    """用百度爬取图片（备用）"""
    crawler = BaiduImageCrawler(
        storage={"root_dir": save_dir},
        downloader_threads=4,
        parser_threads=2,
    )
    crawler.crawl(
        keyword=keyword,
        max_num=max_num,
        min_size=(100, 100),
        file_idx_offset="auto",
    )


def main():
    print("=" * 60)
    print("  Chef Vision — 炒鸡蛋训练数据爬取")
    print("=" * 60)

    for cls_name, sources in CRAWL_PLAN:
        cls_dir = os.path.join(DATA_DIR, cls_name)
        os.makedirs(cls_dir, exist_ok=True)
        print(f"\n{'─'*60}")
        print(f"  类别: [{cls_name}]  保存到: {cls_dir}")
        print(f"{'─'*60}")

        for engine, keywords in sources:
            for kw in keywords:
                print(f"\n  [{engine.upper()}] 关键词: {kw}  目标: {TARGET_PER_QUERY} 张")
                try:
                    if engine == "bing":
                        crawl_bing(kw, cls_dir, TARGET_PER_QUERY)
                    elif engine == "baidu":
                        crawl_baidu(kw, cls_dir, TARGET_PER_QUERY)
                    # 爬完一个关键词暂停，避免被限流
                    time.sleep(2)
                except Exception as e:
                    print(f"  [警告] {kw} 爬取失败: {e}，跳过")
                    continue

        # 统计结果
        imgs = [f for f in os.listdir(cls_dir)
                if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))]
        print(f"\n  [{cls_name}] 爬取完成，共 {len(imgs)} 张图片")

    print("\n" + "=" * 60)
    print("  全部爬取完成！")
    print("  下一步：运行 classify/filter_data.py 筛选无效图片")
    print("=" * 60)


if __name__ == "__main__":
    main()
