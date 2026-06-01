"""提取关键帧截图，诊断 mask 异常扩张区域"""
import cv2, os, csv
import numpy as np

_HERE      = os.path.dirname(os.path.abspath(__file__))
CSV_PATH   = os.path.join(_HERE, "..", "output", "food_temp_log.csv")
VIDEO_PATH = os.path.join(_HERE, "..", "data",   "rgb_20260428_121157.mp4")
OUT_DIR    = os.path.join(_HERE, "..", "output", "inspect_frames")
os.makedirs(OUT_DIR, exist_ok=True)

# 读取 mask 数据
rows = []
with open(CSV_PATH) as f:
    reader = csv.DictReader(f)
    for row in reader:
        rows.append({
            "frame_abs": int(row["frame_abs"]),
            "frame_rel": int(row["frame_rel"]),
            "time_s":    float(row["time_s"]),
            "mask_ratio": float(row["mask_ratio"]),
        })

# 找关键帧：mask 发生突变的位置
key_frames = []

# 1. 前期正常帧样本（每500帧取一个）
for i in range(0, 1200, 200):
    key_frames.append(("normal", rows[i]))

# 2. mask突变起点附近（frame_rel 1190~1210）
for r in rows[1190:1215]:
    key_frames.append(("jump", r))

# 3. 高mask阶段样本（frame_rel 1400, 1600, 1800）
for i in [1400, 1600, 1800]:
    if i < len(rows):
        key_frames.append(("big", rows[i]))

# 4. 末尾 mask=0 样本
zero_rows = [r for r in rows if r["mask_ratio"] == 0]
if zero_rows:
    key_frames.append(("zero", zero_rows[0]))

cap = cv2.VideoCapture(VIDEO_PATH)
print(f"提取 {len(key_frames)} 帧截图到 {OUT_DIR}/")

for tag, r in key_frames:
    abs_idx = r["frame_abs"]
    cap.set(cv2.CAP_PROP_POS_FRAMES, abs_idx)
    ret, frame = cap.read()
    if not ret:
        continue
    fname = f"{tag}_rel{r['frame_rel']:04d}_t{r['time_s']:.1f}s_mask{r['mask_ratio']:.1f}pct.jpg"
    # 在画面上标注信息
    cv2.putText(frame, f"frame_rel={r['frame_rel']}  t={r['time_s']:.1f}s  mask={r['mask_ratio']:.2f}%",
                (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
    cv2.imwrite(os.path.join(OUT_DIR, fname), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    print(f"  {fname}")

cap.release()
print("完成！请查看 inspect_frames/ 目录中的截图")
