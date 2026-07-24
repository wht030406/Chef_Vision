"""
温度过滤算法
功能：
  1. 加载 Homography 矩阵（homography.npy），将 RGB 帧对齐到 IR 坐标系
  2. 在对齐后的 RGB 帧上生成目标区域 mask
  3. 只对 mask 内像素统计温度（排除锅底/搅拌桨等非食物区域）
  4. 输出食物区域的 AVG/MAX/MIN/中位数 温度
  5. 保存叠加可视化图像

Mask 方案（当前：HSV 颜色分割，后续替换 build_mask() 函数即可）：
  - 当前：HSV 颜色分割（临时占位，用于验证流程）
  - 下一步：形状 mask（手动标注锅底/搅拌桨，一次性）
  - 最终：SAM2 自动分割食物区域

用法：
  1. 修改下方 RGB_FILE / NPY_FILE 为实际文件名
  2. 运行：python TempFilter.py
  3. 查看输出的 filter_result.png
"""

import numpy as np
import cv2
import os

# ============================================================
# 配置：修改这里的文件名
# ============================================================
_HERE           = os.path.dirname(os.path.abspath(__file__))
RGB_FILE        = os.path.join(_HERE, "..", "data", "rgb_20260428_121157.mp4")
NPY_FILE        = os.path.join(_HERE, "..", "data", "temp_20260428_121546.npy")
HOMOGRAPHY_FILE = os.path.join(_HERE, "..", "data", "homography.npy")

# HSV 颜色过滤范围（临时占位，后续替换 build_mask() 函数）
# H: 0-179, S: 0-255, V: 0-255
HSV_LOWER  = np.array([0,   20,  60])   # 皮肤/暖色下限
HSV_UPPER  = np.array([25, 255, 255])   # 皮肤/暖色上限
HSV_LOWER2 = np.array([160,  20,  60])  # 红色第二段下限
HSV_UPPER2 = np.array([179, 255, 255])  # 红色第二段上限

# 分析哪一帧
ANALYZE_FRAME = 0

# ============================================================
# 加载 Homography 矩阵
# ============================================================
def load_homography():
    """加载 RGB→IR 对齐矩阵，不存在则返回 None（跳过对齐）"""
    if not os.path.exists(HOMOGRAPHY_FILE):
        print(f"[警告] 未找到 {HOMOGRAPHY_FILE}，跳过对齐（RGB 和 IR 可能有偏移）")
        print(f"       运行 Calibrate.py 完成标定后可获得更精确结果")
        return None
    H = np.load(HOMOGRAPHY_FILE)
    print(f"[OK] 已加载对齐矩阵: {HOMOGRAPHY_FILE}")
    return H

# ============================================================
# 加载数据
# ============================================================
def load_data():
    """加载 RGB 视频帧 和 温度矩阵"""
    if not os.path.exists(NPY_FILE):
        raise FileNotFoundError(f"找不到温度文件: {NPY_FILE}")
    temp_data = np.load(NPY_FILE)  # shape: (N, 192, 256)
    print(f"[OK] 温度矩阵: {temp_data.shape}, 共 {temp_data.shape[0]} 帧")

    if not os.path.exists(RGB_FILE):
        raise FileNotFoundError(f"找不到视频文件: {RGB_FILE}")
    cap = cv2.VideoCapture(RGB_FILE)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"[OK] RGB 视频: 共 {total_frames} 帧")

    frame_idx = ANALYZE_FRAME if ANALYZE_FRAME >= 0 else total_frames + ANALYZE_FRAME
    frame_idx = min(frame_idx, min(total_frames, temp_data.shape[0]) - 1)

    rgb_frame = None
    for i in range(frame_idx + 1):
        ret, frame = cap.read()
        if ret:
            rgb_frame = frame
    cap.release()

    if rgb_frame is None:
        raise RuntimeError("无法读取 RGB 视频帧")

    temp_frame = temp_data[frame_idx]  # shape: (192, 256)
    print(f"[OK] 分析第 {frame_idx} 帧")
    return rgb_frame, temp_frame

# ============================================================
# RGB 对齐到 IR 坐标系
# ============================================================
def align_rgb_to_ir(rgb_frame, ir_shape, H):
    """
    用 Homography 矩阵将 RGB 帧 warp 到 IR 坐标系
    ir_shape: (h, w) = (192, 256)
    返回：对齐后的 RGB 图，尺寸和 IR 相同
    """
    if H is None:
        # 无标定矩阵：直接缩放到 IR 尺寸（有偏移但不影响流程验证）
        h, w = ir_shape
        return cv2.resize(rgb_frame, (w, h))

    h, w = ir_shape
    aligned = cv2.warpPerspective(rgb_frame, H, (w, h))
    return aligned

# ============================================================
# 生成 Mask（当前：HSV 颜色分割，后续替换此函数）
# ============================================================
def build_mask(rgb_aligned):
    """
    在对齐后的 RGB 图（IR 坐标系）上生成目标区域 mask
    rgb_aligned: 已 warp 到 IR 坐标系的 RGB 图，shape=(192, 256, 3)
    返回 mask: shape=(192, 256), uint8, 255=目标区域 0=背景

    ---- 后续替换说明 ----
    将此函数替换为以下任意方案，其余代码不变：
      方案A：形状 mask（加载预存的锅底/搅拌桨排除区域 PNG）
      方案B：SAM2 自动分割食物区域
    """
    # 转 HSV
    hsv = cv2.cvtColor(rgb_aligned, cv2.COLOR_BGR2HSV)

    # 两段红色/暖色范围
    mask1 = cv2.inRange(hsv, HSV_LOWER,  HSV_UPPER)
    mask2 = cv2.inRange(hsv, HSV_LOWER2, HSV_UPPER2)
    mask = cv2.bitwise_or(mask1, mask2)

    # 形态学去噪
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    pixel_count = np.sum(mask > 0)
    total = mask.shape[0] * mask.shape[1]
    print(f"[OK] Mask 像素数: {pixel_count} / {total} ({100*pixel_count/total:.1f}%)")
    return mask

# ============================================================
# 温度统计
# ============================================================
def analyze_temperature(temp_frame, mask):
    """对 mask 内像素统计温度"""
    masked_temps = temp_frame[mask > 0]
    if len(masked_temps) == 0:
        print("[警告] Mask 为空，没有匹配到任何像素！")
        return None

    result = {
        "count":  len(masked_temps),
        "avg":    float(np.mean(masked_temps)),
        "max":    float(np.max(masked_temps)),
        "min":    float(np.min(masked_temps)),
        "std":    float(np.std(masked_temps)),
        "median": float(np.median(masked_temps)),
    }
    print("\n" + "=" * 40)
    print("目标区域温度统计（已对齐 + 过滤背景）")
    print("=" * 40)
    print(f"  像素数量 : {result['count']}")
    print(f"  平均温度 : {result['avg']:.2f} ℃")
    print(f"  最高温度 : {result['max']:.2f} ℃")
    print(f"  最低温度 : {result['min']:.2f} ℃")
    print(f"  中位温度 : {result['median']:.2f} ℃")
    print(f"  标准差   : {result['std']:.2f} ℃")
    print("=" * 40)
    print(f"\n整帧统计（含背景，供对比）:")
    print(f"  平均温度 : {np.mean(temp_frame):.2f} ℃")
    print(f"  最高温度 : {np.max(temp_frame):.2f} ℃")
    print(f"  最低温度 : {np.min(temp_frame):.2f} ℃")
    return result

# ============================================================
# 可视化保存
# ============================================================
def save_visualization(rgb_frame, rgb_aligned, temp_frame, mask, result,
                       out_path=None):
    if out_path is None:
        out_path = os.path.join(_HERE, "..", "output", "filter_result.png")
    """
    保存四联可视化图：
      RGB原图 | RGB对齐后（warp到IR尺寸）| RGB对齐+Mask | 温度热力图+Mask轮廓
    """
    h, w = temp_frame.shape  # 192, 256

    # ---- 各图准备 ----
    # 1. RGB 原图缩放到 IR 尺寸（仅用于显示对比）
    rgb_orig_small = cv2.resize(rgb_frame, (w, h))

    # 2. 对齐后的 RGB（已是 IR 尺寸）
    rgb_align_vis = rgb_aligned.copy()

    # 3. 对齐 RGB + mask 叠加
    rgb_mask_vis = rgb_aligned.copy()
    green = np.zeros_like(rgb_aligned)
    green[:, :] = (0, 200, 0)
    alpha = (mask > 0).astype(np.float32) * 0.4
    for c in range(3):
        rgb_mask_vis[:, :, c] = (
            rgb_aligned[:, :, c] * (1 - alpha) + green[:, :, c] * alpha
        ).astype(np.uint8)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(rgb_mask_vis, contours, -1, (0, 255, 0), 1)

    # 4. 温度热力图 + mask 轮廓
    t_min, t_max = temp_frame.min(), temp_frame.max()
    temp_norm = ((temp_frame - t_min) / max(t_max - t_min, 0.1) * 255).astype(np.uint8)
    temp_vis = cv2.applyColorMap(temp_norm, cv2.COLORMAP_JET)
    cv2.drawContours(temp_vis, contours, -1, (255, 255, 255), 1)

    # ---- 文字标注 ----
    def put_text(img, text, pos, color=(255,255,255), scale=0.38):
        cv2.putText(img, text, pos, cv2.FONT_HERSHEY_SIMPLEX, scale, (0,0,0), 2)
        cv2.putText(img, text, pos, cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1)

    put_text(rgb_orig_small, "RGB Original", (3, 13))
    put_text(rgb_align_vis,  "RGB Aligned (warp->IR)", (3, 13))
    put_text(rgb_mask_vis,   "RGB + Mask", (3, 13))
    put_text(temp_vis, f"Temp {t_min:.1f}~{t_max:.1f}C", (3, 13))
    if result:
        put_text(temp_vis, f"Mask AVG:{result['avg']:.1f} MAX:{result['max']:.1f}C", (3, 26))

    # ---- 拼接四图 ----
    gap = np.zeros((h, 4, 3), dtype=np.uint8)
    combined = np.hstack([rgb_orig_small, gap, rgb_align_vis, gap, rgb_mask_vis, gap, temp_vis])

    # 放大 3x 便于查看
    combined = cv2.resize(combined, (combined.shape[1]*3, combined.shape[0]*3),
                          interpolation=cv2.INTER_NEAREST)

    cv2.imwrite(out_path, combined)
    print(f"\n[OK] 可视化已保存: {out_path}")
    print("      左1: RGB原图  左2: RGB对齐后  左3: RGB+Mask  右: 温度热力图+Mask轮廓")

# ============================================================
# 主流程
# ============================================================
if __name__ == "__main__":
    print("=" * 55)
    print("  Chef Vision - 温度过滤分析")
    print("=" * 55)
    print(f"  RGB 文件 : {RGB_FILE}")
    print(f"  NPY 文件 : {NPY_FILE}")
    print(f"  H   文件 : {HOMOGRAPHY_FILE}")
    print(f"  分析帧号 : {ANALYZE_FRAME}")
    print("-" * 55)

    H = load_homography()
    rgb_frame, temp_frame = load_data()

    # RGB 对齐到 IR 坐标系
    rgb_aligned = align_rgb_to_ir(rgb_frame, temp_frame.shape, H)
    if H is not None:
        print(f"[OK] RGB 已 warp 对齐到 IR 坐标系 ({temp_frame.shape[1]}×{temp_frame.shape[0]})")

    # 生成 mask（在对齐后的 RGB 上操作）
    mask = build_mask(rgb_aligned)

    # 温度统计
    result = analyze_temperature(temp_frame, mask)

    # 保存可视化
    save_visualization(rgb_frame, rgb_aligned, temp_frame, mask, result)

    print("\n完成！查看 filter_result.png")
    print("第2列（RGB Aligned）和第4列（温度热力图）内容应该基本重合。")
    print("如果 mask 不准确，修改顶部 HSV_LOWER/HSV_UPPER 参数后重新运行。")
