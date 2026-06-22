"""
从视频的指定时间段抽帧，生成预览网格图，方便人工标注各段熟度
用法: python classify/extract_segment.py
"""
import cv2
import os
import numpy as np
from PIL import Image, ImageDraw, ImageFont

VIDEO = r"D:\Chef_Vision\classify\test_videos\asmr_tomato_egg.mp4"
OUT_DIR = r"D:\Chef_Vision\classify\frames_preview"
os.makedirs(OUT_DIR, exist_ok=True)

# 有效时间段（秒）
START_SEC = 148   # 2:28
END_SEC   = 350   # 5:50

# 抽帧间隔（秒）
INTERVAL_SEC = 2  # 每2秒1帧，共约100帧


def has_egg(frame):
    """简单判断帧里是否有鸡蛋（黄色区域）"""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    # 黄色范围
    yellow_mask = cv2.inRange(hsv, (15, 50, 80), (35, 255, 255))
    yellow_ratio = yellow_mask.sum() / (frame.shape[0] * frame.shape[1] * 255)
    return yellow_ratio > 0.02  # 黄色超过2%才认为有蛋


def extract_frames():
    cap = cv2.VideoCapture(VIDEO)
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps
    print(f"视频时长: {int(duration//60)}:{int(duration%60):02d}, FPS: {fps:.1f}")

    frames_data = []  # (timestamp_str, frame_img, has_egg_bool)

    cap.set(cv2.CAP_PROP_POS_MSEC, START_SEC * 1000)
    t = START_SEC
    while t <= END_SEC:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ret, frame = cap.read()
        if not ret:
            break
        egg = has_egg(frame)
        ts = f"{int(t//60)}:{int(t%60):02d}"
        frames_data.append((ts, frame.copy(), egg))
        # 保存每一帧
        fname = f"frame_{int(t):04d}s.jpg"
        cv2.imwrite(os.path.join(OUT_DIR, fname), frame)
        t += INTERVAL_SEC

    cap.release()
    print(f"共抽取 {len(frames_data)} 帧，保存到 {OUT_DIR}")

    # 生成预览网格图（4列）
    cols = 4
    rows = (len(frames_data) + cols - 1) // cols
    thumb_w, thumb_h = 320, 240
    grid_w = cols * thumb_w
    grid_h = rows * (thumb_h + 30)
    grid = Image.new("RGB", (grid_w, grid_h), (30, 30, 30))

    for i, (ts, frame, egg) in enumerate(frames_data):
        r, c = divmod(i, cols)
        thumb = cv2.resize(frame, (thumb_w, thumb_h))
        thumb_rgb = cv2.cvtColor(thumb, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(thumb_rgb)
        # 有蛋绿框，无蛋红框
        draw = ImageDraw.Draw(img)
        color = (0, 255, 0) if egg else (255, 80, 80)
        for bw in range(3):
            draw.rectangle([bw, bw, thumb_w-1-bw, thumb_h-1-bw], outline=color)
        grid.paste(img, (c * thumb_w, r * (thumb_h + 30)))
        # 时间戳标签
        label_img = Image.new("RGB", (thumb_w, 30), (30, 30, 30))
        ld = ImageDraw.Draw(label_img)
        status = "🥚有蛋" if egg else "🍅无蛋"
        ld.text((5, 5), f"{ts}  {status}", fill=(200, 200, 200))
        grid.paste(label_img, (c * thumb_w, r * (thumb_h + 30) + thumb_h))

    grid_path = os.path.join(OUT_DIR, "preview_grid.jpg")
    grid.save(grid_path, quality=85)
    print(f"预览网格图: {grid_path}")
    os.startfile(grid_path)

    # 统计
    with_egg = sum(1 for _, _, e in frames_data if e)
    print(f"\n有蛋帧: {with_egg}/{len(frames_data)}")
    print("\n请根据预览图告诉我各段的标注：")
    print("  raw  = 哪几秒到哪几秒（蛋液流动状态）")
    print("  done = 哪几秒到哪几秒（蛋凝固/番茄出锅状态）")


if __name__ == "__main__":
    extract_frames()
