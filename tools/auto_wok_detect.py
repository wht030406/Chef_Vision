"""
自动从 IR 温度数据检测锅的椭圆区域，生成 wok_region.json

原理：锅壁是高温圆环，通过温度阈值分割 + 椭圆拟合自动定位

用法：
  python tools/auto_wok_detect.py
  python tools/auto_wok_detect.py --temp test_data/test1/temp_20260529_112414.npy
  python tools/auto_wok_detect.py --temp xxx.npy --start_sec 5 --out data/wok_region.json
"""

import argparse
import json
import os
import sys

import cv2
import numpy as np


# ── 默认路径 ──────────────────────────────────────────────────────────────────
DEFAULT_TEMP = "test_data/test1/temp_20260529_112414.npy"
DEFAULT_OUT  = "data/wok_region.json"
VIZ_OUT      = "tools/auto_wok_detect_result.jpg"

# IR 帧率（估算，用于 start_sec 换算）
# 如果有 _ts.npy 会自动精确计算，否则用这个估算值
IR_FPS_ESTIMATE = 40.0


def load_temp(path):
    """加载温度 npy，返回 (N, H, W) float32"""
    data = np.load(path, allow_pickle=True)
    if data.ndim == 2:
        data = data[np.newaxis]  # 单帧扩维
    print(f"  温度数据: shape={data.shape}  dtype={data.dtype}")
    print(f"  温度范围: {data.min():.1f} ~ {data.max():.1f} °C")
    return data.astype(np.float32)


def estimate_ir_fps(temp_path, n_frames):
    """尝试从同名 _ts.npy 精确计算 IR 帧率，失败则用估算值"""
    ts_path = temp_path.replace(".npy", "_ts.npy")
    if os.path.exists(ts_path):
        ts = np.load(ts_path)
        if len(ts) >= 2:
            fps = (len(ts) - 1) / (ts[-1] - ts[0])
            print(f"  IR 帧率（时间戳）: {fps:.2f} fps")
            return fps
    fps = IR_FPS_ESTIMATE
    print(f"  IR 帧率（估算）: {fps:.2f} fps")
    return fps


def get_avg_frame(data, start_sec, ir_fps, n_avg=30):
    """从 start_sec 开始取 n_avg 帧平均，得到稳定的温度帧"""
    start_idx = int(start_sec * ir_fps)
    start_idx = max(0, min(start_idx, len(data) - n_avg - 1))
    end_idx   = min(start_idx + n_avg, len(data))
    avg = data[start_idx:end_idx].mean(axis=0)
    print(f"  使用帧范围: [{start_idx}, {end_idx})  ({end_idx-start_idx} 帧平均)")
    print(f"  均值帧温度: {avg.min():.1f} ~ {avg.max():.1f} °C  均值={avg.mean():.1f}")
    return avg


def detect_wok_ellipse(avg_frame, percentile_thresh=75, min_area_ratio=0.05):
    """
    从平均温度帧检测锅椭圆
    返回 (cx, cy, rx, ry) 或 None
    """
    H, W = avg_frame.shape

    # 1. 温度阈值：取高温像素（锅壁 + 锅内高温区）
    thresh = np.percentile(avg_frame, percentile_thresh)
    print(f"  温度阈值（{percentile_thresh}百分位）: {thresh:.1f} °C")
    mask = (avg_frame >= thresh).astype(np.uint8) * 255

    # 2. 形态学：填洞 + 去小噪点
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=3)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  kernel, iterations=2)

    # 3. 找轮廓
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        print("  !! 未找到轮廓，尝试降低百分位阈值")
        return None

    # 4. 按面积排序，取最大轮廓（就是锅）
    min_area = H * W * min_area_ratio
    valid = [c for c in contours if cv2.contourArea(c) > min_area]
    if not valid:
        print(f"  !! 没有足够大的轮廓（最小面积要求 {min_area:.0f} px²）")
        return None

    largest = max(valid, key=cv2.contourArea)
    area = cv2.contourArea(largest)
    print(f"  最大轮廓面积: {area:.0f} px²（占图像 {area/(H*W)*100:.1f}%）")

    # 5. 椭圆拟合（至少需要 5 个点）
    if len(largest) < 5:
        print("  !! 轮廓点太少，无法拟合椭圆")
        return None

    ellipse = cv2.fitEllipse(largest)
    (cx, cy), (w, h), angle = ellipse
    # fitEllipse 返回 (width, height) = (长轴全长, 短轴全长)
    # rx = 较大半径，ry = 较小半径，wok_region 用 rx 表示水平方向
    rx = max(w, h) / 2
    ry = min(w, h) / 2

    # 如果椭圆太扁（长短轴比 > 3），可能检测错了
    if rx / max(ry, 1) > 3.0:
        print(f"  !! 椭圆过于细长（rx/ry={rx/ry:.1f}），可能检测有误")

    print(f"  检测结果: cx={cx:.1f}  cy={cy:.1f}  rx={rx:.1f}  ry={ry:.1f}  angle={angle:.1f}°")
    return cx, cy, rx, ry, angle, mask, largest


def save_result(cx, cy, rx, ry, out_path):
    """保存 wok_region.json"""
    result = {
        "cx": round(float(cx), 1),
        "cy": round(float(cy), 1),
        "rx": round(float(rx), 1),
        "ry": round(float(ry), 1),
    }
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"  保存: {out_path}")
    return result


def make_visualization(avg_frame, cx, cy, rx, ry, mask, contour, out_path):
    """生成可视化图：左=IR热力图+椭圆，右=二值mask"""
    H, W = avg_frame.shape

    # 温度图转伪彩色
    norm = cv2.normalize(avg_frame, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    heat = cv2.applyColorMap(norm, cv2.COLORMAP_JET)

    # 画检测到的椭圆（绿色）
    heat_viz = heat.copy()
    cv2.ellipse(heat_viz, (int(cx), int(cy)), (int(rx), int(ry)), 0, 0, 360, (0, 255, 0), 2)
    cv2.circle(heat_viz, (int(cx), int(cy)), 3, (0, 255, 0), -1)

    # 标注数值
    txt = f"cx={cx:.0f} cy={cy:.0f} rx={rx:.0f} ry={ry:.0f}"
    cv2.putText(heat_viz, txt, (4, H - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)

    # mask 图（灰度转BGR）
    mask_bgr = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
    cv2.drawContours(mask_bgr, [contour], -1, (0, 255, 0), 2)

    # 放大到便于查看的尺寸
    scale = max(1, 600 // W)
    heat_big = cv2.resize(heat_viz, (W * scale, H * scale), interpolation=cv2.INTER_NEAREST)
    mask_big = cv2.resize(mask_bgr, (W * scale, H * scale), interpolation=cv2.INTER_NEAREST)

    # 左右拼接
    combo = np.hstack([heat_big, mask_big])

    # 加标题
    title_h = 30
    canvas = np.zeros((combo.shape[0] + title_h, combo.shape[1], 3), dtype=np.uint8)
    canvas[title_h:] = combo
    cv2.putText(canvas, "Left: IR heatmap + detected ellipse    Right: threshold mask",
                (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1, cv2.LINE_AA)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    cv2.imwrite(out_path, canvas)
    print(f"  可视化: {out_path}")
    return out_path


def auto_detect(temp_path, start_sec, out_path, viz_path, rx_scale=1.0, ry_scale=1.0):
    print("=" * 55)
    print("  Chef Vision — 自动锅区域检测")
    print("=" * 55)

    # 加载数据
    data   = load_temp(temp_path)
    ir_fps = estimate_ir_fps(temp_path, len(data))

    # 取起始帧后的均值帧
    avg = get_avg_frame(data, start_sec, ir_fps)

    # 尝试不同百分位阈值直到成功
    result = None
    for pct in [75, 70, 80, 65, 85, 60]:
        r = detect_wok_ellipse(avg, percentile_thresh=pct)
        if r is not None:
            result = r
            break
        print(f"  百分位 {pct} 失败，尝试下一个...")

    if result is None:
        print("\n!! 自动检测失败，请手动编辑 wok_region.json")
        sys.exit(1)

    cx, cy, rx, ry, angle, mask, contour = result

    # 应用缩放系数（让用户微调椭圆大小）
    rx_final = rx * rx_scale
    ry_final = ry * ry_scale
    if rx_scale != 1.0 or ry_scale != 1.0:
        print(f"  缩放后: rx={rx_final:.1f}  ry={ry_final:.1f}  "
              f"(rx×{rx_scale}  ry×{ry_scale})")

    # 保存 JSON
    saved = save_result(cx, cy, rx_final, ry_final, out_path)

    # 可视化（用缩放后的值）
    viz = make_visualization(avg, cx, cy, rx_final, ry_final, mask, contour, viz_path)

    print(f"\n{'='*55}")
    print(f"  检测完成！")
    print(f"  wok_region: cx={saved['cx']} cy={saved['cy']} "
          f"rx={saved['rx']} ry={saved['ry']}")
    print(f"  请查看可视化图确认结果：{viz}")
    print(f"  如结果有误，可调整参数后重试：")
    print(f"    --start_sec  调整起始时间（越晚锅越热越清晰）")
    print(f"    --rx_scale   调整水平半径缩放（如 0.85 收窄左右）")
    print(f"    --ry_scale   调整垂直半径缩放（如 0.85 收窄上下）")
    print(f"{'='*55}")

    # 自动打开可视化图
    try:
        import subprocess
        subprocess.Popen(["start", viz], shell=True)
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="自动检测锅椭圆区域")
    parser.add_argument("--temp",      default=DEFAULT_TEMP,
                        help=f"温度 npy 文件路径（默认: {DEFAULT_TEMP}）")
    parser.add_argument("--start_sec", type=float, default=5.0,
                        help="从第几秒开始取帧（默认: 5.0秒，等锅预热后）")
    parser.add_argument("--out",       default=DEFAULT_OUT,
                        help=f"输出 JSON 路径（默认: {DEFAULT_OUT}）")
    parser.add_argument("--viz",       default=VIZ_OUT,
                        help=f"可视化图输出路径（默认: {VIZ_OUT}）")
    parser.add_argument("--rx_scale",  type=float, default=0.85,
                        help="水平半径缩放系数（默认0.85，收窄左右以适配锅形）")
    parser.add_argument("--ry_scale",  type=float, default=1.0,
                        help="垂直半径缩放系数（默认1.0，如0.85可收窄上下）")
    args = parser.parse_args()

    auto_detect(args.temp, args.start_sec, args.out, args.viz,
                rx_scale=args.rx_scale, ry_scale=args.ry_scale)


if __name__ == "__main__":
    main()
