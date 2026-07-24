"""检查单应矩阵是否与当前视频匹配"""
import numpy as np, cv2

H = np.load("data/homography.npy")
print(f"单应矩阵:\n{H}")

# 取 RGB 视频中间帧的几个点，映射到 IR 坐标
cap = cv2.VideoCapture("test_data/rgb_20260519_154927.mp4")
VW = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
VH = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
cap.release()

IR_W, IR_H = 256, 192
print(f"\nRGB 分辨率: {VW}x{VH}")
print(f"IR  分辨率: {IR_W}x{IR_H}")

# 测试 RGB 图像四个角和中心点映射到 IR 的位置
test_pts = [
    (0, 0, "左上角"),
    (VW-1, 0, "右上角"),
    (0, VH-1, "左下角"),
    (VW-1, VH-1, "右下角"),
    (VW//2, VH//2, "中心"),
    (800, 600, "中心附近"),
]

print("\nRGB → IR 坐标映射：")
for x, y, name in test_pts:
    pt = np.array([[[x, y]]], dtype=np.float32)
    dst = cv2.perspectiveTransform(pt, H)
    ix, iy = dst[0][0]
    in_bounds = 0 <= ix < IR_W and 0 <= iy < IR_H
    print(f"  {name} ({x},{y}) → IR ({ix:.1f},{iy:.1f})  {'✅ 在范围内' if in_bounds else '❌ 越界'}")

# 加载 food_labels.json 里的标注点，看它们映射到哪里
import json
with open("core/food_labels.json") as f:
    labels = json.load(f)
kf = labels.get("keyframes", [labels])[0]
fg = kf.get("fg_points", labels.get("fg_points", []))
print(f"\n标注点 FG 映射到 IR：")
for pt in fg[:5]:
    x, y = pt
    src = np.array([[[x, y]]], dtype=np.float32)
    dst = cv2.perspectiveTransform(src, H)
    ix, iy = dst[0][0]
    in_bounds = 0 <= ix < IR_W and 0 <= iy < IR_H
    print(f"  RGB ({x:.0f},{y:.0f}) → IR ({ix:.1f},{iy:.1f})  {'✅' if in_bounds else '❌ 越界'}")
