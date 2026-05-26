"""检查 IR 和 RGB 的时间对齐"""
import numpy as np, cv2

temp = np.load("test_data/temp_20260519_155641.npy")
cap = cv2.VideoCapture("test_data/rgb_20260519_154927.mp4")
rgb_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
fps = cap.get(cv2.CAP_PROP_FPS)
cap.release()

ir_frames = temp.shape[0]
ir_fps = ir_frames / (rgb_frames / fps)

print(f"RGB: {rgb_frames}帧 @{fps}fps = {rgb_frames/fps:.1f}s")
print(f"IR:  {ir_frames}帧 @{ir_fps:.2f}fps = {ir_frames/ir_fps:.1f}s")

# 计算每帧 IR 均值，找高温区域
print("\n每隔500帧的IR均值温度：")
for i in range(0, ir_frames, 500):
    mean_t = float(temp[i].mean())
    max_t  = float(temp[i].max())
    print(f"  IR帧 {i:5d}  t={i/ir_fps:6.1f}s  均值={mean_t:.1f}°C  最大={max_t:.1f}°C")

# 找第一个均值超过 30°C 的 IR 帧（锅开始热了）
print("\n寻找IR温度上升点（均值>30°C）：")
for i in range(0, ir_frames, 10):
    if float(temp[i].mean()) > 30:
        print(f"  IR帧 {i}  t={i/ir_fps:.1f}s  均值={float(temp[i].mean()):.1f}°C")
        break

# RGB 视频里 start_frame=1410，对应 56.4s
# 如果 IR 从 0 开始对齐，IR 帧 1410*1.6986 = 2395 对应 56.4s
rgb_start = 1410
ir_at_rgb_start = int(rgb_start * ir_fps / fps)
print(f"\nRGB start_frame={rgb_start} (t={rgb_start/fps:.1f}s)")
print(f"对应 IR 帧: {ir_at_rgb_start}  IR均值={float(temp[ir_at_rgb_start].mean()):.1f}°C")
