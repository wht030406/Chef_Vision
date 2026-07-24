"""
数据清洗脚本
1. 过滤损坏/无法打开的图片
2. 过滤分辨率过小的图片（< 100×100）
3. 基于 pHash 去重（感知哈希，过滤几乎一样的图）
4. 按 8:2 比例划分训练集/验证集

用法：
  python classify/filter_data.py

输出：
  classify/data/raw|done|burnt/       ← 清洗后的训练集
  classify/data_val/raw|done|burnt/   ← 验证集（从训练集中划出）
"""

import os
import shutil
import hashlib
import random
from pathlib import Path

import cv2
import numpy as np

# ── 配置 ──────────────────────────────────────────────────────────────────────
_HERE     = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.path.join(_HERE, "data")
VAL_DIR   = os.path.join(_HERE, "data_val")
CLASSES   = ["raw", "done", "burnt"]

MIN_W, MIN_H = 100, 100    # 最小分辨率
VAL_RATIO    = 0.2          # 验证集比例
PHASH_THRESH = 8            # pHash 汉明距离阈值（<=8 认为重复）

random.seed(42)


def phash(img_bgr, hash_size=8):
    """计算图片的感知哈希（pHash），返回 64 bit 整数"""
    gray  = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (hash_size * 4, hash_size * 4))
    # DCT
    dct   = cv2.dct(small.astype(np.float32))
    dct_low = dct[:hash_size, :hash_size]
    med   = np.median(dct_low)
    bits  = (dct_low > med).flatten()
    val   = 0
    for b in bits:
        val = (val << 1) | int(b)
    return val


def hamming(a, b):
    """两个 pHash 值的汉明距离"""
    xor = a ^ b
    count = 0
    while xor:
        count += xor & 1
        xor >>= 1
    return count


def filter_class(cls_name):
    src_dir = os.path.join(DATA_DIR, cls_name)
    val_dir = os.path.join(VAL_DIR,  cls_name)
    os.makedirs(val_dir, exist_ok=True)

    all_files = sorted([
        f for f in os.listdir(src_dir)
        if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
    ])
    print(f"\n[{cls_name}] 原始: {len(all_files)} 张")

    valid   = []
    hashes  = []
    removed_corrupt = 0
    removed_small   = 0
    removed_dup     = 0

    for fname in all_files:
        fpath = os.path.join(src_dir, fname)
        # 1. 读取检查
        img = cv2.imread(fpath)
        if img is None:
            os.remove(fpath)
            removed_corrupt += 1
            continue
        h, w = img.shape[:2]
        # 2. 分辨率检查
        if w < MIN_W or h < MIN_H:
            os.remove(fpath)
            removed_small += 1
            continue
        # 3. pHash 去重
        ph = phash(img)
        is_dup = False
        for existing_ph in hashes:
            if hamming(ph, existing_ph) <= PHASH_THRESH:
                is_dup = True
                break
        if is_dup:
            os.remove(fpath)
            removed_dup += 1
            continue
        hashes.append(ph)
        valid.append(fname)

    print(f"  删除损坏: {removed_corrupt}  过小: {removed_small}  重复: {removed_dup}")
    print(f"  保留: {len(valid)} 张")

    # 4. 划分验证集
    random.shuffle(valid)
    n_val   = max(1, int(len(valid) * VAL_RATIO))
    val_set = valid[:n_val]
    trn_set = valid[n_val:]

    for fname in val_set:
        src = os.path.join(src_dir, fname)
        dst = os.path.join(val_dir,  fname)
        shutil.move(src, dst)

    print(f"  训练集: {len(trn_set)}  验证集: {len(val_set)}")
    return len(trn_set), len(val_set)


def main():
    print("=" * 60)
    print("  Chef Vision — 数据清洗 + 训练/验证集划分")
    print("=" * 60)

    total_trn = total_val = 0
    for cls in CLASSES:
        t, v = filter_class(cls)
        total_trn += t
        total_val += v

    print(f"\n{'='*60}")
    print(f"  清洗完成！训练集共 {total_trn} 张，验证集共 {total_val} 张")
    print(f"  下一步：运行 classify/train.py 开始训练")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
