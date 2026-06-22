"""
一次性测试脚本：对比旧/新 wok 椭圆位置
白色椭圆 = 新位置 (cy=115.7)
蓝色椭圆 = 旧位置 (cy=107.7)
"""
import json
import numpy as np
import cv2

NPY  = "D:/Chef_Vision/test_data/test1/temp_20260529_112414.npy"
WOK  = "D:/Chef_Vision/data/wok_region.json"
OUT  = "D:/Chef_Vision/tools/wok_shift_test.jpg"
FRAME_IDX = 200   # 取第 200 帧做测试

data = np.load(NPY)
with open(WOK) as f:
    wok = json.load(f)

print(f"temp shape : {data.shape}")
print(f"wok NEW    : cx={wok['cx']} cy={wok['cy']} rx={wok['rx']} ry={wok['ry']}")

frame = data[FRAME_IDX]
t_min = float(np.min(frame))
t_max = float(np.max(frame))
norm  = ((frame - t_min) / max(t_max - t_min, 0.1) * 255).astype(np.uint8)

# 放大 4× 方便看清（原始 192×256 → 768×1024）
SCALE = 4
img = cv2.resize(cv2.applyColorMap(norm, cv2.COLORMAP_JET),
                 (frame.shape[1] * SCALE, frame.shape[0] * SCALE),
                 interpolation=cv2.INTER_NEAREST)

def draw_ellipse(canvas, cx, cy, rx, ry, color, thickness, label):
    cv2.ellipse(canvas,
                (int(cx * SCALE), int(cy * SCALE)),
                (int(rx * SCALE), int(ry * SCALE)),
                0, 0, 360, color, thickness)
    cv2.putText(canvas, label,
                (int(cx * SCALE) - 80, int(cy * SCALE) - int(ry * SCALE) - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

OLD_CY = 107.7   # 原始值，供对比
# 也标出上次尝试的 +8px 位置
MID_CY = 115.7

# 旧位置 — 蓝色（细线）
draw_ellipse(img, wok["cx"], OLD_CY, wok["rx"], wok["ry"],
             (0, 100, 255), 2, f"OLD cy={OLD_CY}")

# 新位置 — 白色（粗线）
draw_ellipse(img, wok["cx"], wok["cy"], wok["rx"], wok["ry"],
             (255, 255, 255), 3, f"NEW cy={wok['cy']}")

# 标注帧号和温度范围
cv2.putText(img, f"frame={FRAME_IDX}  t_min={t_min:.1f}C  t_max={t_max:.1f}C",
            (10, img.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX,
            0.7, (200, 200, 200), 2)

cv2.imwrite(OUT, img)
print(f"saved: {OUT}")
