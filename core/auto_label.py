"""
auto_label.py — IR 辅助自动标点，自动生成 food_labels.json

原理：
  1. 跳过视频前 N 秒（画面不稳定期）
  2. 从稳定帧开始，在 wok_region 椭圆内分析 IR 温度分布
  3. 高温区（>80%分位）= 锅壁 → 背景点
     中温区（30%~70%分位）= 菜 → 前景点
  4. 用 homography 反投影 IR 坐标 → RGB 坐标
  5. 写入 food_labels.json，可直接供 TrackFood.py 使用

用法：
  python core/auto_label.py
  python core/auto_label.py --skip 8        # 跳过前 8 秒
  python core/auto_label.py --preview       # 预览标点结果（不保存）
  python core/auto_label.py --video path/to/rgb.mp4 --npy path/to/temp.npy
"""

import os
import sys
import json
import argparse
import glob
import re

import cv2
import numpy as np

# ── 路径基准 ─────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))

# ── 默认配置 ─────────────────────────────────────────────────────────────────
LABELS_JSON     = os.path.join(_HERE, "food_labels.json")
HOMOGRAPHY_PATH = os.path.join(_HERE, "..", "data", "homography.npy")
WOK_CFG_PATH    = os.path.join(_HERE, "..", "data", "wok_region.json")

SKIP_SECONDS    = 5      # 跳过前 N 秒
STABLE_WINDOW   = 3      # 连续检查 N 秒，都满足条件才认为稳定
WOK_MIN_TEMP    = 80.0   # 锅内最高温 > 此值才认为锅已加热（画面稳定）

# 温度分层阈值（百分位）
# 菜在锅内温度最低的区域（锅壁 200°C+，菜 44~122°C）
FG_LOW_PCT  = 0    # 前景点（菜）：温度在 [FG_LOW_PCT, FG_HIGH_PCT] 分位之间
FG_HIGH_PCT = 20   # 锅内最低 20% 温度 = 菜
BG_LOW_PCT  = 75   # 背景点（锅壁）：温度 > BG_LOW_PCT 分位

# 采样点数量
N_FG_POINTS = 12   # 前景点数量
N_BG_POINTS = 20   # 背景点数量（锅壁 + 锅外）
N_OUTER_BG  = 8    # 锅外背景点数量（在 wok_region 外均匀采样）


# ── 工具函数 ─────────────────────────────────────────────────────────────────

def find_video_and_npy(video_path=None, npy_path=None):
    """自动在 test_data/ 下找最新的 rgb_*.mp4 和对应 temp_*.npy"""
    if video_path and npy_path:
        return video_path, npy_path
    search_dirs = [
        os.path.join(_HERE, "..", "test_data"),
        os.path.join(_HERE, ".."),
    ]
    candidates = []
    for d in search_dirs:
        candidates += glob.glob(os.path.join(d, "**", "rgb_*.mp4"), recursive=True)
    if not candidates:
        return video_path, npy_path
    candidates.sort(key=os.path.getmtime, reverse=True)
    vid = candidates[0]
    npy_candidate = os.path.join(
        os.path.dirname(vid),
        os.path.splitext(os.path.basename(vid))[0].replace("rgb_", "temp_") + ".npy"
    )
    if os.path.exists(npy_candidate):
        return vid, npy_candidate
    return vid, npy_path


def load_wok_cfg():
    if not os.path.exists(WOK_CFG_PATH):
        print(f"[错误] 找不到 wok_region.json: {WOK_CFG_PATH}")
        print("  请先运行: python core/ir_mask_viz.py --setup")
        sys.exit(1)
    with open(WOK_CFG_PATH) as f:
        return json.load(f)


def build_wok_mask(wok_cfg, ir_h, ir_w):
    mask = np.zeros((ir_h, ir_w), dtype=np.uint8)
    cv2.ellipse(mask,
                (int(wok_cfg["cx"]), int(wok_cfg["cy"])),
                (int(wok_cfg["rx"]), int(wok_cfg["ry"])),
                0, 0, 360, 255, -1)
    return mask > 0


def find_stable_frame(temp_data, fps_ir, skip_s, stable_window_s, wok_mask):
    """从 skip_s 秒开始找第一个稳定帧（锅内最高温 > WOK_MIN_TEMP 持续 stable_window_s 秒）"""
    start_ir = int(skip_s * fps_ir)
    window   = max(1, int(stable_window_s * fps_ir))
    n_frames = temp_data.shape[0]
    print(f"[稳定帧] 从 IR 帧 {start_ir}（{skip_s}s）开始搜索...")
    consecutive = 0
    for i in range(start_ir, n_frames):
        wok_temps = temp_data[i][wok_mask]
        if len(wok_temps) and float(np.max(wok_temps)) > WOK_MIN_TEMP:
            consecutive += 1
            if consecutive >= window:
                stable_ir = i - window + 1
                print(f"[稳定帧] IR帧 {stable_ir} ({stable_ir/fps_ir:.1f}s)"
                      f"  锅内最高温={float(np.max(temp_data[stable_ir][wok_mask])):.1f}C")
                return stable_ir
        else:
            consecutive = 0
    # clamp：不能超过最后一帧
    start_ir = min(start_ir, n_frames - 1)
    print(f"[稳定帧] 未找到满足条件的帧，使用 skip 帧: {start_ir}")
    return start_ir


def sample_points_from_mask(bool_mask, n, rng):
    """从 bool_mask 中随机采样 n 个坐标，返回 [[x,y], ...]（IR 坐标）"""
    ys, xs = np.where(bool_mask)
    if len(xs) == 0:
        return []
    idx = rng.choice(len(xs), size=min(n, len(xs)), replace=False)
    return [[int(xs[i]), int(ys[i])] for i in idx]


# 背景点距离前景点的最小距离（RGB 像素）
BG_MIN_DIST_FROM_FG = 80   # 背景点必须距所有前景点至少 80px

# 旋转轴排除半径（相对于 wok 半径的比例）
# 中心旋转轴金属温度低，容易被误判为菜前景，需要排除
AXIS_EXCLUDE_RATIO = 0.18   # 排除锅中心 18% 半径内的点


def project_wok_to_rgb(wok_cfg_ir, H_inv, rim_expand_px=20):
    """
    将 IR 坐标系的锅椭圆用 homography 逆矩阵投影到 RGB 坐标系。
    rim_expand_px: 在锅边缘外扩展若干像素，让背景点落在锅壁上而非锅内。
    返回 dict: {cx, cy, rx, ry}（RGB 坐标系）
    """
    cx_ir, cy_ir = wok_cfg_ir["cx"], wok_cfg_ir["cy"]
    rx_ir, ry_ir = wok_cfg_ir["rx"], wok_cfg_ir["ry"]
    # 用中心+四个轴端点投影，估算 RGB 椭圆
    pts = np.array([[[float(cx_ir),        float(cy_ir)],
                      [float(cx_ir + rx_ir), float(cy_ir)],
                      [float(cx_ir - rx_ir), float(cy_ir)],
                      [float(cx_ir),         float(cy_ir + ry_ir)],
                      [float(cx_ir),         float(cy_ir - ry_ir)]]], dtype=np.float32)
    rp = cv2.perspectiveTransform(pts, H_inv)[0]
    cx_rgb = int(round(rp[0][0]))
    cy_rgb = int(round(rp[0][1]))
    rx_rgb = int(round((abs(rp[1][0] - rp[0][0]) + abs(rp[2][0] - rp[0][0])) / 2)) + rim_expand_px
    ry_rgb = int(round((abs(rp[3][1] - rp[0][1]) + abs(rp[4][1] - rp[0][1])) / 2)) + rim_expand_px
    print(f"[RGB锅投影] homography: cx={cx_rgb} cy={cy_rgb} rx={rx_rgb} ry={ry_rgb}")
    return {"cx": cx_rgb, "cy": cy_rgb, "rx": rx_rgb, "ry": ry_rgb}


def rgb_wok_rim_bg_points(wok_rgb, n_rim, n_outer, rgb_w, rgb_h):
    """
    直接在 RGB 坐标系里沿锅椭圆生成背景点（不依赖 homography）。
    n_rim:   锅壁边缘背景点数量（略在锅边内侧和外侧交替）
    n_outer: 锅外背景点数量（距锅边缘一定距离）
    """
    cx, cy = wok_rgb["cx"], wok_rgb["cy"]
    rx, ry = wok_rgb["rx"], wok_rgb["ry"]
    pts = []

    # 锅壁边缘点：沿椭圆均匀采样，放在可见锅壁上（+20%半径）
    # IR wok_cfg 是炒菜内区，实际锅壁在 RGB 里比投影椭圆大 ~20%
    for i in range(n_rim):
        angle = 2 * np.pi * i / n_rim
        x = int(round(cx + rx * 1.20 * np.cos(angle)))
        y = int(round(cy + ry * 1.20 * np.sin(angle)))
        x = max(0, min(rgb_w - 1, x))
        y = max(0, min(rgb_h - 1, y))
        pts.append([float(x), float(y)])

    # 锅外背景点：明确在锅外机器设备上（+40%半径处）
    for i in range(n_outer):
        angle = 2 * np.pi * i / n_outer
        x = int(round(cx + rx * 1.40 * np.cos(angle)))
        y = int(round(cy + ry * 1.40 * np.sin(angle)))
        x = max(0, min(rgb_w - 1, x))
        y = max(0, min(rgb_h - 1, y))
        pts.append([float(x), float(y)])

    return pts


def ir_to_rgb(ir_pts, homography_inv, rgb_w, rgb_h):
    """
    用 homography 逆矩阵将 IR 坐标反投影到 RGB 坐标。
    homography_inv: IR→RGB 的变换矩阵（homography 的逆）
    """
    if not ir_pts:
        return []
    pts = np.array([[p[0], p[1]] for p in ir_pts], dtype=np.float32).reshape(-1, 1, 2)
    rgb_pts = cv2.perspectiveTransform(pts, homography_inv).reshape(-1, 2)
    result = []
    for p in rgb_pts:
        x, y = float(p[0]), float(p[1])
        if 0 <= x < rgb_w and 0 <= y < rgb_h:
            result.append([round(x, 1), round(y, 1)])
    return result


def build_rgb_wok_mask(wok_cfg, H_inv, ir_h, ir_w, rgb_w, rgb_h, dilate_px=40):
    """
    把 IR 坐标系的 wok_mask warp 到 RGB 坐标系，生成 RGB 锅区域 mask。
    dilate_px: 对 mask 做膨胀（像素），给锅边缘留安全余量，
               避免背景点落在锅壁边缘模糊区域。
    """
    ir_mask = np.zeros((ir_h, ir_w), dtype=np.uint8)
    cv2.ellipse(ir_mask,
                (int(wok_cfg["cx"]), int(wok_cfg["cy"])),
                (int(wok_cfg["rx"]), int(wok_cfg["ry"])),
                0, 0, 360, 255, -1)
    rgb_mask = cv2.warpPerspective(ir_mask, H_inv, (rgb_w, rgb_h))
    rgb_mask = (rgb_mask > 64).astype(np.uint8) * 255  # 降低阈值，捕获边缘模糊区域
    # 膨胀：扩大锅区域，给背景点留安全距离
    if dilate_px > 0:
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (dilate_px * 2 + 1, dilate_px * 2 + 1))
        rgb_mask = cv2.dilate(rgb_mask, kernel)
    return rgb_mask > 128


def filter_bg_points(bg_rgb, fg_rgb, rgb_wok_mask, min_dist):
    """
    双重过滤背景点：
    1. 移除落在 RGB 锅区域内的背景点（homography 偏差导致的误投影）
    2. 移除距任意前景点小于 min_dist 像素的背景点
    """
    if not bg_rgb:
        return bg_rgb

    fg_arr = np.array(fg_rgb, dtype=np.float32) if fg_rgb else None
    kept = []
    removed_in_wok = 0
    removed_too_close = 0

    for bp in bg_rgb:
        bx, by = int(round(bp[0])), int(round(bp[1]))

        # 条件 1：不能在 RGB 锅区域内
        if (0 <= bx < rgb_wok_mask.shape[1] and
                0 <= by < rgb_wok_mask.shape[0] and
                rgb_wok_mask[by, bx]):
            removed_in_wok += 1
            continue

        # 条件 2：距所有前景点至少 min_dist 像素
        if fg_arr is not None:
            dists = np.sqrt((fg_arr[:, 0] - bp[0])**2 + (fg_arr[:, 1] - bp[1])**2)
            if np.min(dists) < min_dist:
                removed_too_close += 1
                continue

        kept.append(bp)

    if removed_in_wok:
        print(f"[过滤] 移除 {removed_in_wok} 个落在锅内的背景点")
    if removed_too_close:
        print(f"[过滤] 移除 {removed_too_close} 个距前景点 <{min_dist}px 的背景点")
    print(f"[过滤] 剩余背景点: {len(kept)} 个")
    return kept


def wok_rim_bg_points(wok_cfg, n_rim, ir_h, ir_w):
    """
    在 wok_region 椭圆边缘环形区域采样背景点（锅壁边缘）。
    策略：沿椭圆边缘均匀取 n_rim 个角度，向内缩 rim_inner 像素作为内边界，
    在 [内边界, 外边界] 之间均匀分布点。
    """
    cx, cy = wok_cfg["cx"], wok_cfg["cy"]
    rx, ry = wok_cfg["rx"], wok_cfg["ry"]
    rim_inner = 6   # 边缘环形宽度（像素），只取最外圈
    pts = []
    for i in range(n_rim):
        angle = 2 * np.pi * i / n_rim
        # 在 [rim_inner, 0] 范围内取点（从边缘往内 rim_inner 像素）
        for frac in [0.0, 0.5, 1.0]:
            r_frac = 1.0 - frac * rim_inner / min(rx, ry)
            r_frac = max(0.85, r_frac)   # 不超过 85% 半径
            x = int(round(cx + rx * r_frac * np.cos(angle)))
            y = int(round(cy + ry * r_frac * np.sin(angle)))
            if 0 <= x < ir_w and 0 <= y < ir_h:
                pts.append([x, y])
    # 去重
    seen = set()
    unique = []
    for p in pts:
        k = (p[0], p[1])
        if k not in seen:
            seen.add(k)
            unique.append(p)
    return unique[:n_rim]


def outer_bg_points_uniform(wok_cfg, n, ir_h, ir_w):
    """
    在 wok_region 外按上/下/左/右/四角均匀分布背景点（锅外区域，IR 坐标）。
    """
    cx, cy = wok_cfg["cx"], wok_cfg["cy"]
    rx, ry = wok_cfg["rx"], wok_cfg["ry"]
    margin = 8
    angles = [0, np.pi/4, np.pi/2, 3*np.pi/4,
              np.pi, 5*np.pi/4, 3*np.pi/2, 7*np.pi/4]
    pts = []
    for angle in angles[:n]:
        x = int(round(cx + (rx + margin) * np.cos(angle)))
        y = int(round(cy + (ry + margin) * np.sin(angle)))
        x = max(0, min(ir_w - 1, x))
        y = max(0, min(ir_h - 1, y))
        pts.append([x, y])
    return pts


def rgb_outer_bg_points(rgb_wok_mask, n_total, rgb_w, rgb_h):
    """
    直接在 RGB 坐标系里生成锅外背景点（不依赖 homography）。
    找到 RGB wok mask 的边界框，在锅外按 8 个方向均匀放置背景点。
    """
    # 找 wok mask 的边界
    ys, xs = np.where(rgb_wok_mask)
    if len(xs) == 0:
        return []
    cx = int((xs.min() + xs.max()) / 2)
    cy = int((ys.min() + ys.max()) / 2)
    rx = int((xs.max() - xs.min()) / 2)
    ry = int((ys.max() - ys.min()) / 2)
    margin = max(30, int(min(rx, ry) * 0.15))  # 距锅边缘至少 15% 半径

    angles = np.linspace(0, 2 * np.pi, n_total, endpoint=False)
    pts = []
    for angle in angles:
        x = int(round(cx + (rx + margin) * np.cos(angle)))
        y = int(round(cy + (ry + margin) * np.sin(angle)))
        x = max(0, min(rgb_w - 1, x))
        y = max(0, min(rgb_h - 1, y))
        # 确保不在锅内
        if not rgb_wok_mask[y, x]:
            pts.append([float(x), float(y)])
    return pts


def generate_fg_points_ir_warp(rgb_frame, ir_frame, wok_mask,
                                wok_cfg, ir_h, ir_w, H_inv, rgb_w, rgb_h, rng):
    """
    IR 温度分层 + warpPerspective 投影到 RGB，再用 RGB 非黑像素过滤。

    解决时间差问题的策略：
      1. 用 IR 温度找出食物区域（低温 mask）
      2. 用 warpPerspective 把整个 IR food mask 投影到 RGB 坐标系
         （比逐点投影更平滑，边缘噪声更少）
      3. 在投影后的 RGB mask 内，进一步过滤：只保留 RGB 图里非黑色的像素
         （黑色 = 锅底，说明食物已经离开了这个位置）
      4. 从过滤后的区域采样前景点
      5. 如果这样还不够，直接从 RGB 锅内非黑区域采样（纯 RGB 备用）
    """
    # 1. IR 温度分层找食物区域，排除中心旋转轴
    wok_temps = ir_frame[wok_mask]
    if len(wok_temps) == 0:
        return [], "failed"

    t_fg_lo = np.percentile(wok_temps, FG_LOW_PCT)
    t_fg_hi = np.percentile(wok_temps, FG_HIGH_PCT)
    fg_ir_mask = wok_mask & (ir_frame >= t_fg_lo) & (ir_frame <= t_fg_hi)

    # 排除中心旋转轴（IR 坐标）
    cx_ir, cy_ir = wok_cfg["cx"], wok_cfg["cy"]
    rx_ir, ry_ir = wok_cfg["rx"], wok_cfg["ry"]
    ax_ir = int(rx_ir * AXIS_EXCLUDE_RATIO)
    ay_ir = int(ry_ir * AXIS_EXCLUDE_RATIO)
    axis_mask_ir = np.zeros((ir_h, ir_w), dtype=np.uint8)
    cv2.ellipse(axis_mask_ir, (cx_ir, cy_ir), (ax_ir, ay_ir), 0, 0, 360, 255, -1)
    fg_ir_mask = fg_ir_mask & (axis_mask_ir == 0)

    print(f"[标点] IR温度分层: FG=[{t_fg_lo:.1f},{t_fg_hi:.1f}]C")

    # 2. 在 RGB 锅内区域用形态学开运算分离食物团块 vs 细长金属臂
    #    原理：腐蚀消除细线（金属臂宽度 < erosion 核），膨胀恢复团块大小

    # 先把 IR wok_mask 整体投影到 RGB 坐标系，得到锅内搜索区域
    wok_ir_img = wok_mask.astype(np.uint8) * 255
    wok_rgb_proj = cv2.warpPerspective(wok_ir_img, H_inv, (rgb_w, rgb_h))
    wok_rgb_bool = wok_rgb_proj > 64

    # ── IR food mask warp 到 RGB（交叉验证：只在 IR 认为是食物的区域里找团块）──
    fg_ir_u8 = fg_ir_mask.astype(np.uint8) * 255
    # 先做形态学膨胀再 warp，弥补 IR 分辨率低导致的边缘漏洞
    dilate_ir = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    fg_ir_dilated = cv2.dilate(fg_ir_u8, dilate_ir)
    fg_rgb_proj = cv2.warpPerspective(fg_ir_dilated, H_inv, (rgb_w, rgb_h))
    fg_rgb_hint = fg_rgb_proj > 64   # IR 认为是食物的 RGB 区域

    # RGB 亮色像素（动态阈值：用锅内区域中位亮度的 40%，适应不同曝光）
    gray = cv2.cvtColor(rgb_frame, cv2.COLOR_BGR2GRAY)
    wok_px = gray[wok_rgb_bool]
    if len(wok_px) > 0:
        bright_thresh = max(30, int(np.median(wok_px) * 0.40))
    else:
        bright_thresh = 65
    bright = (gray > bright_thresh).astype(np.uint8) * 255
    print(f"[标点] 动态亮度阈值: {bright_thresh}  (锅内中位亮度={np.median(wok_px):.0f})")

    # 只保留锅内亮色，并优先保留 IR food hint 区域
    in_wok_bright = cv2.bitwise_and(bright, bright,
                                    mask=wok_rgb_bool.astype(np.uint8))
    # 与 IR food hint 做 OR，补充 IR 认为是食物但 RGB 亮度略低的区域
    # 同时与锅内 mask 约束，避免锅外误扩展
    ir_hint_in_wok = cv2.bitwise_and(
        fg_rgb_proj, fg_rgb_proj,
        mask=wok_rgb_bool.astype(np.uint8)
    )
    in_wok_bright = cv2.bitwise_or(in_wok_bright, ir_hint_in_wok)

    # 形态学开运算（先腐蚀再膨胀）：腐蚀核 15px 能消除宽度 < 30px 的细线（金属臂）
    # 食物团块通常直径 > 60px，会缩小但不消失
    erode_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    dilate_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (17, 17))
    eroded = cv2.erode(in_wok_bright, erode_k)
    food_only = cv2.dilate(eroded, dilate_k)

    # 叠加两层限制，排除假阳性区域：
    # 限制1：只保留锅内 75% 半径以内（排除靠近锅壁的边缘亮区）
    wok_inner = np.zeros((rgb_h, rgb_w), dtype=np.uint8)
    # 用 wok_rgb_proj 的边界框估算锅中心和半径（RGB 坐标系）
    wok_ys, wok_xs = np.where(wok_rgb_bool)
    if len(wok_xs) > 0:
        cx_wok = int((wok_xs.min() + wok_xs.max()) / 2)
        cy_wok = int((wok_ys.min() + wok_ys.max()) / 2)
        rx_wok = int((wok_xs.max() - wok_xs.min()) / 2)
        ry_wok = int((wok_ys.max() - wok_ys.min()) / 2)
        cv2.ellipse(wok_inner, (cx_wok, cy_wok),
                    (int(rx_wok * 0.75), int(ry_wok * 0.75)),
                    0, 0, 360, 255, -1)
        food_only = cv2.bitwise_and(food_only, food_only, mask=wok_inner)

        # 限制2：排除中心轴区域（30% 半径），覆盖旋转臂金属件
        cv2.ellipse(food_only, (cx_wok, cy_wok),
                    (int(rx_wok * 0.30), int(ry_wok * 0.30)),
                    0, 0, 360, 0, -1)

    n_food_px = int(np.sum(food_only > 0))
    print(f"[标点] 形态学+区域限制后食物像素: {n_food_px}px")

    if n_food_px >= N_FG_POINTS * 10:
        # 从食物团块区域随机采样
        ys, xs = np.where(food_only > 0)
        idx = rng.choice(len(xs), size=N_FG_POINTS, replace=False)
        pts = [[float(xs[i]), float(ys[i])] for i in idx]
        print(f"[标点] 形态学食物团块采样: FG={len(pts)}个")
        return pts, "morphology_blob"

    # 3. 备用：开运算 + findContours，只从紧凑度高的轮廓采样
    #    用紧凑度 = 4π×面积/周长² 过滤细长金属臂（紧凑度 << 1）
    contours, _ = cv2.findContours(in_wok_bright, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    compact = []
    for c in contours:
        area = cv2.contourArea(c)
        peri = cv2.arcLength(c, True)
        if area < 300 or peri < 1:
            continue
        circularity = 4 * np.pi * area / (peri * peri)
        # 圆形/椭圆形食物团块：circularity > 0.3
        # 细长金属臂：circularity < 0.1
        if circularity > 0.25:
            compact.append((c, area, circularity))
    compact.sort(key=lambda x: x[1], reverse=True)
    print(f"[标点] 紧凑轮廓(circularity>0.25): {len(compact)}个")

    if compact:
        food_mask2 = np.zeros((rgb_h, rgb_w), dtype=np.uint8)
        for c, _, _ in compact[:5]:
            cv2.drawContours(food_mask2, [c], -1, 255, -1)
        ys, xs = np.where(food_mask2 > 0)
        if len(xs) >= N_FG_POINTS:
            idx = rng.choice(len(xs), size=N_FG_POINTS, replace=False)
            pts = [[float(xs[i]), float(ys[i])] for i in idx]
            print(f"[标点] 紧凑轮廓采样: FG={len(pts)}个")
            return pts, "compact_contour"

    # 4. 最终备用：IR 逐点投影
    fg_ir_pts = sample_points_from_mask(fg_ir_mask, N_FG_POINTS, rng)
    pts = ir_to_rgb(fg_ir_pts, H_inv, rgb_w, rgb_h)
    print(f"[标点] IR逐点投影备用: FG={len(pts)}个")
    return pts, "ir_pointwise"


def find_wok_edge_by_ray(rgb_frame, cx, cy, angle, r_start, r_max,
                          dark_thresh=60, bright_thresh=90):
    """
    从锅中心 (cx,cy) 沿 angle 方向发射射线，寻找锅边缘。

    策略：
      - 锅内壁是深黑色（V < dark_thresh）
      - 锅边缘/机器是较亮的颜色（V > bright_thresh）
      - 找到第一个从暗到亮的过渡点 = 锅边缘

    返回：锅边缘到中心的距离（像素），找不到则返回 r_max
    """
    gray = cv2.cvtColor(rgb_frame, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    cos_a, sin_a = np.cos(angle), np.sin(angle)

    was_dark = False
    bright_count = 0
    BRIGHT_CONFIRM = 4   # 需要连续 4 像素亮才确认是锅边缘（避免食物亮斑误判）
    for r in range(r_start, r_max):
        x = int(round(cx + r * cos_a))
        y = int(round(cy + r * sin_a))
        if x < 0 or x >= w or y < 0 or y >= h:
            return r
        v = int(gray[y, x])
        if v < dark_thresh:
            was_dark = True
            bright_count = 0
        elif was_dark and v > bright_thresh:
            bright_count += 1
            if bright_count >= BRIGHT_CONFIRM:
                # 连续 4 像素都亮 = 真正的锅边缘金属壁
                return r - BRIGHT_CONFIRM + 1
        else:
            bright_count = 0
    return r_max


def find_wok_bg_points_by_ray(rgb_frame, wok_rgb, n_total, rgb_w, rgb_h,
                               outer_offset=50, fallback_mult=1.25):
    """
    用射线法找实际锅边缘，在锅边缘外 outer_offset 像素处放置背景点。

    每个方向：
      1. 从锅中心向外发射射线
      2. 找到从暗（锅内壁）到亮（锅壁金属）的过渡点 = 真实锅边缘
      3. 在该点外侧 outer_offset 像素处放背景点

    如果某方向找不到边缘，用固定倍数 fallback_mult 作为备用。
    """
    cx, cy = wok_rgb["cx"], wok_rgb["cy"]
    rx, ry = wok_rgb["rx"], wok_rgb["ry"]
    r_search_min = int(min(rx, ry) * 0.85)  # 从 85% 处开始，跳过锅内食物区域
    r_search_max = int(max(rx, ry) * 2.0)   # 最远搜索到投影半径 200% 处

    angles = np.linspace(0, 2 * np.pi, n_total, endpoint=False)
    pts = []
    found_by_ray = 0

    for angle in angles:
        edge_r = find_wok_edge_by_ray(
            rgb_frame, cx, cy, angle,
            r_start=r_search_min, r_max=r_search_max
        )
        # 背景点放在锅边缘外侧
        bg_r = edge_r + outer_offset
        x = int(round(cx + bg_r * np.cos(angle)))
        y = int(round(cy + bg_r * np.sin(angle)))
        x = max(0, min(rgb_w - 1, x))
        y = max(0, min(rgb_h - 1, y))

        # 验证：背景点不应该在锅内（V 应该 > 60）
        gray_val = int(cv2.cvtColor(
            rgb_frame[y:y+1, x:x+1], cv2.COLOR_BGR2GRAY)[0, 0])
        if gray_val < 40:
            # 仍在锅内黑色区域，再往外推一点
            bg_r = edge_r + outer_offset * 2
            x = int(round(cx + bg_r * np.cos(angle)))
            y = int(round(cy + bg_r * np.sin(angle)))
            x = max(0, min(rgb_w - 1, x))
            y = max(0, min(rgb_h - 1, y))

        if edge_r < r_search_max:
            found_by_ray += 1
        pts.append([float(x), float(y)])

    print(f"[背景点] 射线法: {found_by_ray}/{n_total}个方向找到真实锅边")
    return pts


def preview_result(rgb_frame, fg_rgb, bg_rgb, save_path=None):
    """在 RGB 帧上绘制标点结果并显示/保存"""
    vis = rgb_frame.copy()
    for p in fg_rgb:
        cv2.circle(vis, (int(p[0]), int(p[1])), 8, (0, 255, 80), -1)
        cv2.circle(vis, (int(p[0]), int(p[1])), 9, (255, 255, 255), 1)
    for p in bg_rgb:
        cv2.circle(vis, (int(p[0]), int(p[1])), 8, (0, 0, 255), -1)
        cv2.circle(vis, (int(p[0]), int(p[1])), 9, (255, 255, 255), 1)
    cv2.putText(vis, f"FG(green):{len(fg_rgb)}  BG(red):{len(bg_rgb)}",
                (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 0), 2)
    cv2.putText(vis, "Auto-Label Preview", (20, 80),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 0), 2)
    if save_path:
        cv2.imwrite(save_path, vis)
        print(f"[预览] 已保存: {save_path}")
    # 缩小显示（原图 1600x1200 太大）
    h, w = vis.shape[:2]
    disp = cv2.resize(vis, (w // 2, h // 2))
    cv2.imshow("Auto-Label Preview (press any key to close)", disp)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


# ── 主程序 ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="IR 辅助自动标点")
    parser.add_argument("--video",   default=None, help="RGB 视频路径")
    parser.add_argument("--npy",     default=None, help="温度 npy 路径")
    parser.add_argument("--skip",    type=float, default=SKIP_SECONDS,
                        help=f"跳过前 N 秒（默认 {SKIP_SECONDS}）")
    parser.add_argument("--preview", action="store_true",
                        help="预览标点结果（不保存 food_labels.json）")
    parser.add_argument("--append",  action="store_true",
                        help="追加关键帧到现有 food_labels.json（而非覆盖）")
    parser.add_argument("--list",    action="store_true",
                        help="列出现有 food_labels.json 中的所有关键帧，然后退出")
    parser.add_argument("--seed",    type=int, default=42, help="随机种子")
    args = parser.parse_args()

    # ── --list：只打印现有关键帧 ──────────────────────────────────────────────
    if args.list:
        if not os.path.exists(LABELS_JSON):
            print(f"[列表] food_labels.json 不存在: {LABELS_JSON}")
            return
        with open(LABELS_JSON, encoding="utf-8") as f:
            data = json.load(f)
        kfs = data.get("keyframes", [])
        print(f"[列表] 视频: {data.get('video_path','')}")
        print(f"[列表] 共 {len(kfs)} 个关键帧：")
        for i, kf in enumerate(kfs):
            print(f"  [{i}] 帧={kf['frame']:6d}  t={kf.get('time_s',0):.1f}s"
                  f"  标签={kf.get('label','')}  FG={len(kf.get('fg_points',[]))}"
                  f"  BG={len(kf.get('bg_points',[]))}")
        return

    rng = np.random.default_rng(args.seed)

    # ── --append 模式：优先从现有 json 读取视频路径 ───────────────────────────
    if args.append and args.video is None and os.path.exists(LABELS_JSON):
        with open(LABELS_JSON, encoding="utf-8") as _f:
            _existing = json.load(_f)
        _vp = _existing.get("video_path", "")
        if _vp and os.path.exists(_vp):
            args.video = _vp
            print(f"[追加] 使用现有 json 中的视频: {args.video}")
        # npy 同理：按视频路径自动匹配
        if args.npy is None and args.video:
            _npy_c = os.path.join(
                os.path.dirname(args.video),
                os.path.splitext(os.path.basename(args.video))[0].replace("rgb_", "temp_") + ".npy"
            )
            if os.path.exists(_npy_c):
                args.npy = _npy_c
                print(f"[追加] 使用匹配温度文件: {args.npy}")

    # ── 找视频和温度文件 ──────────────────────────────────────────────────────
    video_path, npy_path = find_video_and_npy(args.video, args.npy)
    if not video_path or not os.path.exists(video_path):
        print(f"[错误] 找不到 RGB 视频，请用 --video 指定")
        sys.exit(1)
    if not npy_path or not os.path.exists(npy_path):
        print(f"[错误] 找不到温度 npy，请用 --npy 指定")
        sys.exit(1)
    print(f"[视频] {video_path}")
    print(f"[温度] {npy_path}")

    # ── 加载数据 ──────────────────────────────────────────────────────────────
    temp_data = np.load(npy_path)
    if temp_data.ndim == 2:
        temp_data = temp_data[np.newaxis]
    ir_n, ir_h, ir_w = temp_data.shape
    print(f"[温度] shape={temp_data.shape}  范围: {temp_data.min():.1f}~{temp_data.max():.1f}C")

    cap = cv2.VideoCapture(video_path)
    rgb_fps    = cap.get(cv2.CAP_PROP_FPS)
    rgb_total  = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    rgb_w      = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    rgb_h      = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    ir_fps     = ir_n / (rgb_total / rgb_fps)   # 估算 IR 帧率
    ir_rgb_ratio = ir_n / rgb_total
    print(f"[视频] {rgb_w}x{rgb_h}  {rgb_fps:.1f}fps  {rgb_total}帧")
    print(f"[IR]   {ir_w}x{ir_h}  ~{ir_fps:.1f}fps  {ir_n}帧  比例={ir_rgb_ratio:.4f}")

    # ── 加载 homography ───────────────────────────────────────────────────────
    if not os.path.exists(HOMOGRAPHY_PATH):
        print(f"[错误] 找不到 homography.npy: {HOMOGRAPHY_PATH}")
        sys.exit(1)
    H = np.load(HOMOGRAPHY_PATH)          # RGB→IR
    H_inv = np.linalg.inv(H)              # IR→RGB
    print(f"[单应矩阵] 已加载 (RGB→IR)，已计算逆矩阵 (IR→RGB)")

    # ── 加载锅区域 ────────────────────────────────────────────────────────────
    wok_cfg  = load_wok_cfg()
    wok_mask = build_wok_mask(wok_cfg, ir_h, ir_w)
    print(f"[锅区域] cx={wok_cfg['cx']} cy={wok_cfg['cy']} "
          f"rx={wok_cfg['rx']} ry={wok_cfg['ry']}  覆盖 {wok_mask.sum()} 像素")

    # ── 找稳定帧 ──────────────────────────────────────────────────────────────
    stable_ir = find_stable_frame(temp_data, ir_fps, args.skip, STABLE_WINDOW, wok_mask)
    stable_rgb = int(stable_ir / ir_rgb_ratio)
    stable_rgb = min(stable_rgb, rgb_total - 1)
    print(f"[对齐] 稳定帧: IR帧{stable_ir} → RGB帧{stable_rgb} ({stable_rgb/rgb_fps:.1f}s)")

    # ── 读取对应 RGB 帧（先读，用于检测锅轮廓）──────────────────────────────
    cap.set(cv2.CAP_PROP_POS_FRAMES, stable_rgb)
    ret, rgb_frame = cap.read()
    cap.release()
    if not ret:
        print(f"[错误] 无法读取 RGB 帧 {stable_rgb}")
        sys.exit(1)

    # ── 前景点：RGB 颜色分析（备用：IR 温度分层）────────────────────────────
    ir_frame = temp_data[stable_ir]
    wok_rgb  = project_wok_to_rgb(wok_cfg, H_inv, rim_expand_px=0)

    fg_rgb, fg_method = generate_fg_points_ir_warp(
        rgb_frame, ir_frame, wok_mask,
        wok_cfg, ir_h, ir_w, H_inv, rgb_w, rgb_h, rng
    )

    if not fg_rgb:
        print("[错误] 未能生成前景点，请检查 wok_region.json 或降低 WOK_MIN_TEMP")
        sys.exit(1)

    print(f"[RGB前景] FG={len(fg_rgb)}个  (方法={fg_method})")

    # ── 背景点：射线法找实际锅边缘，在边缘外侧放置 ───────────────────────────
    bg_rgb = find_wok_bg_points_by_ray(
        rgb_frame, wok_rgb, N_BG_POINTS, rgb_w, rgb_h, outer_offset=50
    )
    print(f"[RGB背景] BG={len(bg_rgb)}个 (射线法，锅边缘外50px)")

    # ── 预览 ──────────────────────────────────────────────────────────────────
    preview_path = os.path.join(_HERE, "..", "output", "auto_label_preview.jpg")
    os.makedirs(os.path.dirname(preview_path), exist_ok=True)
    if args.preview:
        preview_result(rgb_frame, fg_rgb, bg_rgb, save_path=preview_path)
        print("[预览模式] 未保存 food_labels.json")
        return

    # 非预览模式也保存预览图（方便检查）
    vis = rgb_frame.copy()
    for p in fg_rgb:
        cv2.circle(vis, (int(p[0]), int(p[1])), 8, (0, 255, 80), -1)
    for p in bg_rgb:
        cv2.circle(vis, (int(p[0]), int(p[1])), 8, (0, 0, 255), -1)
    cv2.imwrite(preview_path, vis)
    print(f"[预览图] 已保存: {preview_path}")

    # ── 写入 food_labels.json ─────────────────────────────────────────────────
    new_kf = {
        "frame":     stable_rgb,
        "time_s":    round(stable_rgb / rgb_fps, 3),
        "label":     f"auto@{stable_rgb/rgb_fps:.0f}s",
        "fg_points": fg_rgb,
        "bg_points": bg_rgb,
    }

    if args.append and os.path.exists(LABELS_JSON):
        # ── 追加模式：读取现有 json，插入新关键帧并按帧号排序 ─────────────────
        with open(LABELS_JSON, encoding="utf-8") as f:
            label_data = json.load(f)

        existing_kfs = label_data.get("keyframes", [])
        # 检查是否已有相近帧（±10帧内视为重复，直接替换）
        dup_idx = None
        for i, kf in enumerate(existing_kfs):
            if abs(kf["frame"] - stable_rgb) <= 10:
                dup_idx = i
                break
        if dup_idx is not None:
            print(f"[追加] 检测到相近关键帧（帧差≤10），替换第 {dup_idx} 个")
            existing_kfs[dup_idx] = new_kf
        else:
            existing_kfs.append(new_kf)

        # 按帧号排序
        existing_kfs.sort(key=lambda k: k["frame"])
        label_data["keyframes"] = existing_kfs
        print(f"[追加] 当前共 {len(existing_kfs)} 个关键帧：")
        for kf in existing_kfs:
            print(f"  帧={kf['frame']:6d}  t={kf.get('time_s',0):.1f}s  "
                  f"标签={kf.get('label','')}  FG={len(kf.get('fg_points',[]))}")
    else:
        # ── 覆盖模式（默认）──────────────────────────────────────────────────
        new_kf["label"] = "auto"   # 第一帧用简洁标签
        label_data = {
            "video_path": os.path.abspath(video_path).replace("\\", "/"),
            "fps":        rgb_fps,
            "keyframes":  [new_kf],
        }

    with open(LABELS_JSON, "w", encoding="utf-8") as f:
        json.dump(label_data, f, indent=2, ensure_ascii=False)
    mode_str = "追加" if args.append else "新建"
    print(f"\n[完成({mode_str})] food_labels.json 已写入: {LABELS_JSON}")
    print(f"  起始帧: {stable_rgb}  ({stable_rgb/rgb_fps:.1f}s)")
    print(f"  FG: {len(fg_rgb)} 个点  BG: {len(bg_rgb)} 个点")
    print(f"  下一步: python core/TrackFood.py")


def generate_ir_mask_and_points(rgb_frame, ir_frame, wok_mask,
                                  wok_cfg, ir_h, ir_w, H_inv,
                                  rgb_w, rgb_h, rng,
                                  n_fg_confirm=6, n_bg=20,
                                  ir_frames_nearby=None):
    """
    生成用于 SAM2 散点初始化的精准前景点 + 背景点。

    改进策略（方案B+A）：
      - IR mask warp 到 RGB 后做腐蚀，去掉粗糙外圈，只在内部可靠区域采点
      - 可选 ir_frames_nearby：传入前后各 N 帧 IR 取均值，减少时间抖动
      - 返回散点（不再用 add_new_mask），让 SAM2 自由找精确轮廓

    返回：
      ir_rgb_mask  : (rgb_h, rgb_w) bool — IR food mask 腐蚀后内部区域（仅供可视化）
      fg_pts       : [[x,y], ...]        — 在腐蚀内部区域采样的精准前景点
      bg_pts       : [[x,y], ...]        — 背景点（射线法）
      is_stable    : bool                — IR 温度分布是否稳定

    稳定性判断：
      - 锅内温度方差 < WOK_VAR_MIN   → 温度均匀，不稳定
      - K-means 两类中心差距 < 40°C  → 高低温分不开，不稳定
    """
    WOK_VAR_MIN = 200.0

    # ── 时间平滑：对前后帧 IR 取均值，减少单帧噪声和时间偏差 ──────────────
    if ir_frames_nearby and len(ir_frames_nearby) > 0:
        frames_to_avg = [ir_frame] + list(ir_frames_nearby)
        ir_avg = np.mean(np.stack(frames_to_avg, axis=0), axis=0).astype(np.float32)
    else:
        ir_avg = ir_frame

    wok_temps = ir_avg[wok_mask]
    if len(wok_temps) == 0:
        return None, [], [], False

    # ── 稳定性检查 ───────────────────────────────────────────────────────────
    var = float(np.var(wok_temps))
    if var < WOK_VAR_MIN:
        print(f"[稳定性] 锅内温度方差={var:.1f}C^2  < {WOK_VAR_MIN}，跳过重标")
        return None, [], [], False

    # K-means 双峰检查
    c_low  = float(np.percentile(wok_temps, 10))
    c_high = float(np.percentile(wok_temps, 90))
    for _ in range(20):
        dl = np.abs(wok_temps - c_low)
        dh = np.abs(wok_temps - c_high)
        ll = dl <= dh
        nl = float(np.mean(wok_temps[ll]))  if ll.any()  else c_low
        nh = float(np.mean(wok_temps[~ll])) if (~ll).any() else c_high
        if abs(nl - c_low) < 0.1 and abs(nh - c_high) < 0.1:
            break
        c_low, c_high = nl, nh
    if (c_high - c_low) < 40.0:
        print(f"[稳定性] K-means 双峰差={c_high-c_low:.1f}C < 40C，跳过重标")
        return None, [], [], False

    # ── 生成 IR food mask（低温类，用均值帧）──────────────────────────────
    t_fg_hi = np.percentile(wok_temps, FG_HIGH_PCT)
    fg_ir_mask = wok_mask & (ir_avg <= t_fg_hi)

    # 排除中心旋转轴
    cx_ir, cy_ir = wok_cfg["cx"], wok_cfg["cy"]
    rx_ir, ry_ir = wok_cfg["rx"], wok_cfg["ry"]
    ax_ir = int(rx_ir * AXIS_EXCLUDE_RATIO)
    ay_ir = int(ry_ir * AXIS_EXCLUDE_RATIO)
    axis_mask = np.zeros((ir_h, ir_w), dtype=np.uint8)
    cv2.ellipse(axis_mask, (cx_ir, cy_ir), (ax_ir, ay_ir), 0, 0, 360, 255, -1)
    fg_ir_mask = fg_ir_mask & (axis_mask == 0)

    # ── IR food mask warp 到 RGB ─────────────────────────────────────────────
    fg_u8 = fg_ir_mask.astype(np.uint8) * 255
    fg_rgb_proj = cv2.warpPerspective(fg_u8, H_inv, (rgb_w, rgb_h))
    # 闭运算填补空洞
    close_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25))
    fg_rgb_closed = cv2.morphologyEx(fg_rgb_proj, cv2.MORPH_CLOSE, close_k)
    ir_rgb_mask_raw = fg_rgb_closed > 64   # 原始（粗糙边缘）

    # ── 腐蚀内部区域：去掉粗糙外圈，只保留中心可靠部分 ────────────────────
    # 腐蚀半径约为 warp 后边缘不确定性的估算（IR 低分辨率 → 约 50px 边缘误差）
    erode_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (60, 60))
    ir_rgb_inner = cv2.erode(ir_rgb_mask_raw.astype(np.uint8) * 255, erode_k)
    ir_rgb_mask = ir_rgb_inner > 0   # 腐蚀后内部区域（用于采点）

    n_inner_px = int(ir_rgb_mask.sum())
    n_raw_px   = int(ir_rgb_mask_raw.sum())
    print(f"[IR mask warp] 原始={n_raw_px}px  腐蚀后内部={n_inner_px}px  "
          f"(≤{t_fg_hi:.1f}C)")

    # ── 在腐蚀后内部区域采样精准前景点 ─────────────────────────────────────
    ys, xs = np.where(ir_rgb_mask)
    if len(xs) >= n_fg_confirm:
        idx = rng.choice(len(xs), size=n_fg_confirm, replace=False)
        fg_pts = [[float(xs[i]), float(ys[i])] for i in idx]
    elif len(xs) > 0:
        # 腐蚀后内部太小，退回用原始 mask 中心 50% 区域
        ys2, xs2 = np.where(ir_rgb_mask_raw)
        if len(xs2) >= n_fg_confirm:
            # 只取靠近质心的点
            cx_m = float(np.mean(xs2))
            cy_m = float(np.mean(ys2))
            dists = np.sqrt((xs2 - cx_m)**2 + (ys2 - cy_m)**2)
            thresh = np.percentile(dists, 50)
            inner_idx = np.where(dists <= thresh)[0]
            if len(inner_idx) >= n_fg_confirm:
                sel = rng.choice(inner_idx, size=n_fg_confirm, replace=False)
            else:
                sel = rng.choice(len(xs2), size=min(n_fg_confirm, len(xs2)), replace=False)
            fg_pts = [[float(xs2[i]), float(ys2[i])] for i in sel]
            print(f"[IR mask warp] 腐蚀后太小，用原始mask中心50%采点: {len(fg_pts)}个")
        else:
            fg_pts = [[float(xs[i]), float(ys[i])] for i in range(len(xs))]
    else:
        fg_pts = []

    # ── 背景点：射线法 ────────────────────────────────────────────────────────
    wok_rgb = project_wok_to_rgb(wok_cfg, H_inv, rim_expand_px=0)
    bg_pts  = find_wok_bg_points_by_ray(rgb_frame, wok_rgb, n_bg, rgb_w, rgb_h,
                                         outer_offset=50)

    smooth_str = f"(时间平滑={len(ir_frames_nearby)+1}帧)" if ir_frames_nearby else ""
    print(f"[IR mask warp] 稳定{smooth_str}  var={var:.0f}  "
          f"FG={len(fg_pts)}  BG={len(bg_pts)}")
    # 返回腐蚀后内部 mask（供可视化），精准散点（供 SAM2 add_new_points）
    return ir_rgb_mask, fg_pts, bg_pts, True


if __name__ == "__main__":
    main()
