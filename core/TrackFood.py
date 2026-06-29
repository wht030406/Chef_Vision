"""
TrackFood.py — SAM2 视频追踪食材 + 温度融合（分批处理版）

流程：
1. 读取 food_labels.json（由 LabelFirstFrame.py 生成）
2. 将视频分批抽帧（每批 CHUNK_SIZE 帧），避免内存溢出
3. 用 SAM2 VideoPredictor 逐批追踪食材，批间传递 mask 状态
4. 每帧输出食材 mask
5. 用 homography.npy 将 mask 映射到红外图像坐标
6. 统计每帧菜区域的温度均值，输出 CSV + 可视化视频

依赖：
  pip install sam2 opencv-python numpy matplotlib
  权重：D:/sam2_checkpoints/sam2.1_hiera_large.pt
"""

import os
import sys
import json
import shutil
import glob
import re
from datetime import datetime

import cv2
import numpy as np
import torch
import matplotlib
matplotlib.use("Agg")   # 无头模式，不弹窗
import matplotlib.pyplot as plt
import ir_wok as _ir_wok
import label_io as _label_io
import output_utils as _output_utils
import track_config as _track_config

# ── 路径基准（本文件所在目录）────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, ".."))

# ── 配置 ─────────────────────────────────────────────────────────────────────
LABELS_JSON     = os.path.join(_HERE, "food_labels.json")
HOMOGRAPHY_PATH = os.path.join(_HERE, "..", "data", "homography.npy")
OUTPUT_VIDEO    = os.path.join(_HERE, "..", "output", "track_result.mp4")
OUTPUT_VIDEO_VIZ = os.path.join(_HERE, "..", "output", "track_result_viz.mp4")
OUTPUT_CSV      = os.path.join(_HERE, "..", "output", "food_temp_log.csv")
OUTPUT_EXCEL    = os.path.join(_HERE, "..", "output", "food_temp_log.xlsx")

# SAM2 配置
# 模型选择：tiny（快，适合实时）/ large（慢，精度高，适合离线）
# MODEL_CFG       = "configs/sam2.1/sam2.1_hiera_t.yaml"
# CHECKPOINT_PATH = os.path.join(_HERE, "..", "models", "sam2.1_hiera_tiny.pt")
# 切换到 large：
MODEL_CFG       = "configs/sam2.1/sam2.1_hiera_l.yaml"
CHECKPOINT_PATH = os.path.join(_HERE, "..", "models", "sam2.1_hiera_large.pt")

# 分批处理参数
OPTICAL_FLOW_INTERVAL = 0    # 0 = 纯 SAM2 模式（推荐）；>1 = SAM2+光流混合

# SAM2 批次大小（帧数）
# 100 帧 = 4 秒批次（@25fps），流水线模式下处理时间(~3.5s) < 录制时间(4s)
CHUNK_SIZE      = 100

# SAM2 推理分辨率缩放
# 缩小分辨率可大幅提升 SAM2 速度，mask 会放大回原始分辨率用于温度计算
# None = 不缩放（使用原始分辨率）；(640, 480) = 缩放到 640×480
SAM2_INFER_SIZE = None   # SAM2 内部会 resize 到 1024p，外部缩放无效

# 提示点数量上限（None = 不限制，使用全部标注点）
MAX_FG_POINTS   = None
MAX_BG_POINTS   = None

# 温度数据（自动推断）
TEMP_NPY_PATH   = None   # None = 自动扫描项目目录

# 可视化参数
MASK_COLOR      = (0, 255, 100)   # BGR 绿色，食材 mask 叠加色
MASK_ALPHA      = 0.45
SHOW_PREVIEW    = False           # 关闭实时预览，减少资源占用

# 底部信息栏（可视化版输出）
INFO_H          = 50              # 文字信息条高度（像素）
CHART_H         = 120             # 温度曲线图高度（像素）
CURVE_WIN_S     = 60              # 曲线滑动窗口（秒），只显示最近 N 秒

# 分段自动重标点（模拟实时流水线）
# 每隔 N 秒自动重新生成前景点并重置 SAM2，解决长时间追踪漂移问题
# 0 = 关闭（使用 food_labels.json 中的关键帧）
RELABEL_INTERVAL_S = 4

# 临时帧目录（放在 core/ 下）
TMP_BASE        = os.path.join(_HERE, "tmp_sam2_frames")
# ── 工具函数 ─────────────────────────────────────────────────────────────────

def find_temp_npy(video_path):
    """
    自动匹配温度 npy 文件。
    策略：
    1. 先找与视频同名的（rgb_ → temp_）
    2. 再扫描目录找所有 temp_*.npy，选时间戳最近的
    """
    base      = os.path.splitext(os.path.basename(video_path))[0]
    video_dir = os.path.dirname(os.path.abspath(video_path))

    # 策略 1：同名替换
    candidate = base.replace("rgb_", "temp_") + ".npy"
    candidate_path = os.path.join(video_dir, candidate)
    if os.path.exists(candidate_path):
        print(f"[温度] 找到同名温度文件: {candidate}")
        return candidate_path

    # 策略 2：提取视频时间戳，找最近的 temp_*.npy
    m = re.search(r"(\d{8}_\d{6})", base)
    if m:
        vid_ts = m.group(1)
        all_npy = glob.glob(os.path.join(video_dir, "temp_*.npy"))
        best_path, best_diff = None, float("inf")
        for p in all_npy:
            mn = re.search(r"(\d{8}_\d{6})", os.path.basename(p))
            if mn:
                diff = abs(int(mn.group(1).replace("_", "")) - int(vid_ts.replace("_", "")))
                if diff < best_diff:
                    best_diff, best_path = diff, p
        if best_path:
            print(f"[温度] 自动匹配到最近温度文件: {os.path.basename(best_path)}"
                  f"  (时间差 {best_diff})")
            return best_path

    print(f"[温度] 未找到匹配的温度文件，跳过温度统计")
    return None


def load_temp_data(npy_path):
    """
    加载完整温度矩阵，不做帧号切片。
    帧对齐由调用方根据 IR/RGB 帧率比例动态计算。
    返回 (data, ir_total_frames)
    """
    if npy_path is None or not os.path.exists(npy_path):
        return None, 0
    data = np.load(npy_path)
    print(f"[温度] 加载 {os.path.basename(npy_path)}，shape: {data.shape}，dtype: {data.dtype}")
    if data.ndim == 2:
        data = data[np.newaxis, ...]
    t_min_val = float(np.min(data))
    t_max_val = float(np.max(data))
    print(f"[温度] 总帧数: {data.shape[0]}  温度范围: {t_min_val:.1f}°C ~ {t_max_val:.1f}°C")
    return data, data.shape[0]


def build_sam2_predictor(device):
    from sam2.build_sam import build_sam2_video_predictor
    print(f"\n[SAM2] 加载模型: {CHECKPOINT_PATH}")
    predictor = build_sam2_video_predictor(MODEL_CFG, CHECKPOINT_PATH, device=device)
    print("[SAM2] 模型加载完成")
    return predictor


def extract_chunk_to_dir(video_path, start_abs, end_abs, infer_size=None):
    """
    将视频 [start_abs, end_abs) 帧抽到临时目录。
    infer_size: (W, H) 缩放尺寸，None 则不缩放。
    返回 (tmp_dir, frame_names, actual_count)
    """
    os.makedirs(TMP_BASE, exist_ok=True)
    import tempfile
    tmp_dir = tempfile.mkdtemp(prefix="chunk_", dir=TMP_BASE)

    cap = cv2.VideoCapture(video_path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_abs)

    frame_names = []
    local_idx   = 0
    for _ in range(end_abs - start_abs):
        ret, frame = cap.read()
        if not ret:
            break
        if infer_size is not None:
            frame = cv2.resize(frame, infer_size, interpolation=cv2.INTER_AREA)
        fname = f"{local_idx:06d}.jpg"
        cv2.imwrite(os.path.join(tmp_dir, fname),
                    frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        frame_names.append(fname)
        local_idx += 1

    cap.release()
    return tmp_dir, frame_names, local_idx


def scale_points(points, src_wh, dst_wh):
    """将标注点从 src_wh 坐标系缩放到 dst_wh 坐标系"""
    if not points or src_wh == dst_wh:
        return points
    sx = dst_wh[0] / src_wh[0]
    sy = dst_wh[1] / src_wh[1]
    return [[p[0] * sx, p[1] * sy] for p in points]


def upscale_mask(mask, dst_wh):
    """将 mask 放大到 dst_wh (W, H) 大小"""
    mh, mw = mask.shape
    if (mw, mh) == dst_wh:
        return mask
    m_u8 = mask.astype(np.uint8) * 255
    m_up = cv2.resize(m_u8, dst_wh, interpolation=cv2.INTER_NEAREST)
    return m_up > 127


def track_chunk(predictor, tmp_dir, frame_names,
                fg_points, bg_points,
                carry_mask=None,
                inject_keyframes=None):
    """
    对一批帧进行 SAM2 追踪，支持在批内指定帧号注入新前景点。

    参数：
      fg_points / bg_points : 第一批（或无 carry_mask 时）使用的标注点
      carry_mask            : 上批末帧 mask (H,W bool)；None 表示第一批
      inject_keyframes      : list[dict]，本批内需要注入的额外关键帧，格式：
                              [{"local_frame": int, "fg_points": [...], "bg_points": [...]}]
                              local_frame 是在本批帧序列中的局部帧号（0-based）

    返回：
      masks    : {local_idx: mask (H,W bool)}
      last_mask: 本批末帧 mask（传给下一批）
    """
    inject_keyframes = inject_keyframes or []

    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
        inference_state = predictor.init_state(video_path=tmp_dir)

        if carry_mask is not None and carry_mask.any():
            # ── 后续批：用上批末帧 mask 传递边界（add_new_mask 与 points 在同帧互斥）
            predictor.add_new_mask(
                inference_state=inference_state,
                frame_idx=0,
                obj_id=1,
                mask=carry_mask,
            )
        else:
            # ── 第一批：用用户标注点 ────────────────────────────────────────
            points = np.array(fg_points + bg_points, dtype=np.float32)
            labels = np.array(
                [1] * len(fg_points) + [0] * len(bg_points),
                dtype=np.int32
            )
            predictor.add_new_points_or_box(
                inference_state=inference_state,
                frame_idx=0,
                obj_id=1,
                points=points,
                labels=labels,
            )

        # ── 注入额外关键帧的前景点 ───────────────────────────────────────────
        # local_frame=0：补强点追加到第0帧（与 carry_mask 同帧，SAM2 会合并两者）
        # local_frame>0：食材入锅等关键帧，在对应帧注入
        for kf_inject in inject_keyframes:
            local_f  = kf_inject["local_frame"]
            kf_fg    = kf_inject["fg_points"]
            kf_bg    = kf_inject.get("bg_points", [])
            if not kf_fg:
                continue
            if 0 <= local_f < len(frame_names):
                pts    = np.array(kf_fg + kf_bg, dtype=np.float32)
                lbls   = np.array([1]*len(kf_fg) + [0]*len(kf_bg), dtype=np.int32)
                predictor.add_new_points_or_box(
                    inference_state=inference_state,
                    frame_idx=local_f,
                    obj_id=1,
                    points=pts,
                    labels=lbls,
                )
                print(f"  [注入] 局部帧 {local_f}：FG={len(kf_fg)} BG={len(kf_bg)}"
                      f"  标签={kf_inject.get('label','')}")

        masks = {}
        for out_frame_idx, out_obj_ids, out_mask_logits in predictor.propagate_in_video(
            inference_state
        ):
            mask = (out_mask_logits[0] > 0.0).cpu().numpy().squeeze().astype(bool)
            masks[out_frame_idx] = mask

        predictor.reset_state(inference_state)
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    last_mask = masks.get(len(frame_names) - 1, None)
    return masks, last_mask


def map_mask_to_ir(rgb_mask, homography, ir_shape):
    """用单应矩阵将 RGB mask 映射到红外图像坐标系"""
    H_ir, W_ir = ir_shape
    ys, xs = np.where(rgb_mask)
    if len(xs) == 0:
        return np.zeros(ir_shape, dtype=bool)

    pts_rgb = np.stack([xs, ys, np.ones(len(xs))], axis=1).T  # (3, N)
    pts_ir  = homography @ pts_rgb
    pts_ir  = pts_ir[:2] / pts_ir[2]

    xi = np.round(pts_ir[0]).astype(int)
    yi = np.round(pts_ir[1]).astype(int)
    valid = (xi >= 0) & (xi < W_ir) & (yi >= 0) & (yi < H_ir)
    xi, yi = xi[valid], yi[valid]

    ir_mask = np.zeros(ir_shape, dtype=bool)
    ir_mask[yi, xi] = True
    return ir_mask


def _measure_rgb_mask_temperature(rgb_mask, temp_data, homography, ir_idx):
    """Map an RGB mask to IR and return mean/min/max temperature."""
    nan_stats = (float("nan"), float("nan"), float("nan"))
    if rgb_mask is None or temp_data is None or homography is None:
        return nan_stats
    if ir_idx < 0 or ir_idx >= temp_data.shape[0]:
        return nan_stats

    ir_h, ir_w = temp_data.shape[1], temp_data.shape[2]
    ir_mask = map_mask_to_ir(rgb_mask, homography, (ir_h, ir_w))
    food_temps = temp_data[ir_idx][ir_mask]
    if len(food_temps) == 0:
        return nan_stats
    return (
        float(np.mean(food_temps)),
        float(np.min(food_temps)),
        float(np.max(food_temps)),
    )


def flow_propagate_mask(prev_gray, cur_gray, prev_mask):
    """
    用 Farneback 稠密光流将上一帧 mask 传播到当前帧。

    原理：
      1. 计算 prev→cur 的稠密光流场 (dx, dy)
      2. 对 prev_mask 中每个前景像素，按光流偏移映射到 cur 坐标
      3. 对结果做形态学闭运算填补空洞

    参数：
      prev_gray : (H,W) uint8 灰度图（上一帧）
      cur_gray  : (H,W) uint8 灰度图（当前帧）
      prev_mask : (H,W) bool  上一帧 mask

    返回：
      cur_mask  : (H,W) bool  传播后的 mask
    """
    if not prev_mask.any():
        return prev_mask.copy()

    # Farneback 光流（CPU，速度快）
    flow = cv2.calcOpticalFlowFarneback(
        prev_gray, cur_gray,
        None,
        pyr_scale=0.5, levels=3, winsize=15,
        iterations=3, poly_n=5, poly_sigma=1.2,
        flags=0
    )  # shape: (H, W, 2)

    H, W = prev_mask.shape
    ys, xs = np.where(prev_mask)

    # 按光流偏移计算新坐标
    dx = flow[ys, xs, 0]
    dy = flow[ys, xs, 1]
    new_xs = np.round(xs + dx).astype(int)
    new_ys = np.round(ys + dy).astype(int)

    # 过滤越界坐标
    valid = (new_xs >= 0) & (new_xs < W) & (new_ys >= 0) & (new_ys < H)
    new_xs = new_xs[valid]
    new_ys = new_ys[valid]

    cur_mask = np.zeros((H, W), dtype=np.uint8)
    cur_mask[new_ys, new_xs] = 255

    # 形态学闭运算：填补光流稀疏导致的空洞
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    cur_mask = cv2.morphologyEx(cur_mask, cv2.MORPH_CLOSE, kernel)

    return cur_mask.astype(bool)


def render_overlay(frame_bgr, mask, color_bgr, alpha):
    """在帧上叠加半透明 mask + 轮廓"""
    vis = frame_bgr.copy()
    c   = np.array(color_bgr, dtype=np.uint8)
    vis[mask] = (vis[mask].astype(float) * (1 - alpha) + c * alpha).astype(np.uint8)
    mask_u8 = mask.astype(np.uint8) * 255
    contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(vis, contours, -1, (255, 255, 255), 1)
    return vis


def _kmeans_food_temp(wok_temps, min_cluster_gap=30.0):
    """
    用 K-means 把锅内温度分成两类（高温=锅壁/锅底，低温=食物），
    返回低温类的均值作为食物温度。

    参数：
      wok_temps       : 1D float array，锅内所有像素温度
      min_cluster_gap : 两个聚类中心差距的最小值（°C）。
                        若两类中心差距 < 此值，说明锅内温度分布均匀
                        （锅倾斜/空锅/翻炒过渡期），返回 nan 表示帧不可靠。

    返回：
      float，食物温度均值；或 nan（帧不可靠）
    """
    vals = wok_temps.astype(np.float32).flatten()
    if len(vals) < 10:
        return float("nan")

    # 初始化：用最小值和最大值作为两个初始中心
    c_low  = float(np.percentile(vals, 10))
    c_high = float(np.percentile(vals, 90))

    # 迭代 K-means（最多 20 次，收敛即停）
    for _ in range(20):
        # 分配：每个像素归入更近的中心
        dist_low  = np.abs(vals - c_low)
        dist_high = np.abs(vals - c_high)
        label_low = dist_low <= dist_high   # True = 低温类（食物）

        new_low  = float(np.mean(vals[label_low]))  if label_low.any()  else c_low
        new_high = float(np.mean(vals[~label_low])) if (~label_low).any() else c_high

        if abs(new_low - c_low) < 0.1 and abs(new_high - c_high) < 0.1:
            break
        c_low, c_high = new_low, new_high

    # 可靠性检查：两类中心差距太小 → 帧不可靠（翻炒/倾斜/空锅）
    if (c_high - c_low) < min_cluster_gap:
        return float("nan")

    # 返回低温类（食物）的均值
    dist_low  = np.abs(vals - c_low)
    dist_high = np.abs(vals - c_high)
    food_mask = dist_low <= dist_high
    return float(np.mean(vals[food_mask])) if food_mask.any() else float("nan")


def _build_ir_food_mask_by_temperature(ir_frame, wok_mask_ir, min_cluster_gap=30.0):
    """Build an IR food mask from the low-temperature cluster inside the wok."""
    if ir_frame is None or wok_mask_ir is None:
        return None

    wok_temps = ir_frame[wok_mask_ir]
    if len(wok_temps) < 10:
        return None

    c_low = float(np.percentile(wok_temps, 10))
    c_high = float(np.percentile(wok_temps, 90))
    for _ in range(20):
        food_sel = np.abs(wok_temps - c_low) <= np.abs(wok_temps - c_high)
        new_low = float(np.mean(wok_temps[food_sel])) if food_sel.any() else c_low
        new_high = float(np.mean(wok_temps[~food_sel])) if (~food_sel).any() else c_high
        if abs(new_low - c_low) < 0.1 and abs(new_high - c_high) < 0.1:
            break
        c_low, c_high = new_low, new_high

    if (c_high - c_low) < min_cluster_gap:
        return None

    ys_wok, xs_wok = np.where(wok_mask_ir)
    food_sel = np.abs(ir_frame[wok_mask_ir] - c_low) <= np.abs(ir_frame[wok_mask_ir] - c_high)
    food_ir = np.zeros(ir_frame.shape, dtype=np.uint8)
    food_ir[ys_wok[food_sel], xs_wok[food_sel]] = 255
    return food_ir


def _estimate_ir_wok_food_temp(temp_data, ir_idx, wok_mask_ir):
    """Estimate food temperature inside the current IR wok mask."""
    if temp_data is None or wok_mask_ir is None:
        return float("nan")
    if ir_idx < 0 or ir_idx >= temp_data.shape[0]:
        return float("nan")

    t_frame = temp_data[ir_idx]
    wok_temps = t_frame[wok_mask_ir]
    if len(wok_temps) < 10:
        return float("nan")
    return _kmeans_food_temp(wok_temps)


def _estimate_wok_center_from_ir_edge(ir_frame, cx, cy, rx, ry,
                                      n_angles=160,
                                      r_min=0.72, r_max=1.32,
                                      min_sectors=7,
                                      min_points=35):
    """
    Track the IR wok by the stable temperature cliff at the wok/outside border.

    The search is centered on the previous estimate, not the original label.
    Low-temperature food inside the wok is rejected by only looking near the
    expected rim and requiring the samples outside the candidate edge to stay
    cooler than the samples inside it.
    """
    if ir_frame is None or rx <= 1 or ry <= 1:
        return None

    h, w = ir_frame.shape[:2]
    vals = ir_frame[np.isfinite(ir_frame)]
    if vals.size < 100:
        return None

    temp_span = float(np.percentile(vals, 95) - np.percentile(vals, 5))
    min_drop = max(2.5, temp_span * 0.06)
    rs = np.linspace(r_min, r_max, 64)
    angles = np.linspace(0.0, 2.0 * np.pi, n_angles, endpoint=False)

    points = []
    sectors = set()
    kernel = np.ones(5, dtype=np.float32) / 5.0

    for ai, th in enumerate(angles):
        cos_t = np.cos(th)
        sin_t = np.sin(th)
        xs = np.rint(cx + rs * rx * cos_t).astype(np.int32)
        ys = np.rint(cy + rs * ry * sin_t).astype(np.int32)
        valid = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
        if valid.sum() < 12:
            continue

        xs_v = xs[valid]
        ys_v = ys[valid]
        rs_v = rs[valid]
        ts = ir_frame[ys_v, xs_v].astype(np.float32)
        if ts.size < 12 or not np.isfinite(ts).all():
            continue

        ts_s = np.convolve(ts, kernel, mode="same")
        # Positive value means temperature drops when moving outward.
        drop = ts_s[:-1] - ts_s[1:]
        if drop.size == 0:
            continue

        bi = int(np.argmax(drop))
        best_drop = float(drop[bi])
        r_edge = float(rs_v[bi])
        if best_drop < min_drop or r_edge < 0.82 or r_edge > 1.22:
            continue

        inner0 = max(0, bi - 6)
        inner1 = max(inner0 + 1, bi - 1)
        outer0 = min(ts_s.size - 1, bi + 2)
        outer1 = min(ts_s.size, bi + 9)
        if outer1 <= outer0 or inner1 <= inner0:
            continue

        inner_med = float(np.median(ts_s[inner0:inner1]))
        outer_med = float(np.median(ts_s[outer0:outer1]))
        if (inner_med - outer_med) < min_drop:
            continue

        _sector = ai * 16 // n_angles
        points.append((
            float(xs_v[bi]), float(ys_v[bi]), r_edge, th,
            best_drop, inner_med, outer_med, _sector
        ))
        sectors.add(_sector)

    if len(points) < min_points or len(sectors) < min_sectors:
        return {
            "ok": False,
            "reason": f"edge points {len(points)}, sectors {len(sectors)}",
        }

    pts_arr = np.array([[p[0], p[1]] for p in points], dtype=np.float32)
    r_arr = np.array([p[2] for p in points], dtype=np.float32)
    drop_arr = np.array([p[4] for p in points], dtype=np.float32)
    inner_arr = np.array([p[5] for p in points], dtype=np.float32)
    sector_arr = np.array([p[7] for p in points], dtype=np.int32)
    med_r = float(np.median(r_arr))
    keep_radius = np.abs(r_arr - med_r) <= 0.16
    if keep_radius.sum() < min_points:
        return {
            "ok": False,
            "reason": f"rim radius unstable ({int(keep_radius.sum())}/{len(points)})",
        }

    # Prefer the clearest visible rim arc instead of trusting every weak edge.
    _drop_thr = float(np.percentile(drop_arr[keep_radius], 65))
    _inner_thr = float(np.percentile(inner_arr[keep_radius], 55))
    keep_strong = keep_radius & (drop_arr >= _drop_thr) & (inner_arr >= _inner_thr)
    strong_points_min = max(18, min_points // 2)
    strong_sectors = set(sector_arr[keep_strong].tolist())
    if keep_strong.sum() >= strong_points_min and len(strong_sectors) >= max(5, min_sectors - 1):
        keep = keep_strong
        fit_mode = "strong-rim"
    else:
        keep = keep_radius
        fit_mode = "radius-rim"

    pts_keep = pts_arr[keep]
    if len(pts_keep) < 5:
        return {"ok": False, "reason": "not enough fit points"}

    try:
        ellipse = cv2.fitEllipse(pts_keep)
        (fit_cx, fit_cy), (ew, eh), _ = ellipse
    except Exception as exc:
        return {"ok": False, "reason": f"fit failed: {exc}"}

    fit_rx = max(float(ew), float(eh)) / 2.0
    fit_ry = min(float(ew), float(eh)) / 2.0
    rx_ratio = fit_rx / max(float(rx), 1.0)
    ry_ratio = fit_ry / max(float(ry), 1.0)
    radius_ratio = max(fit_rx, fit_ry) / max(max(float(rx), float(ry)), 1.0)
    if radius_ratio < 0.65 or radius_ratio > 1.45 or rx_ratio < 0.70 or rx_ratio > 1.30 or ry_ratio < 0.70 or ry_ratio > 1.30:
        return {
            "ok": False,
            "reason": f"bad fit radius ratio {radius_ratio:.2f}",
        }

    return {
        "ok": True,
        "cx": float(fit_cx),
        "cy": float(fit_cy),
        "rx": float(fit_rx),
        "ry": float(fit_ry),
        "points": int(len(pts_keep)),
        "sectors": int(len(set(sector_arr[keep].tolist()))),
        "drop": float(np.median(drop_arr[keep])),
        "fit_mode": fit_mode,
        "radius_ratio": float(radius_ratio),
        "rx_ratio": float(rx_ratio),
        "ry_ratio": float(ry_ratio),
    }


def _estimate_wok_from_ir_hot_ring(ir_frame, cx, cy, rx, ry,
                                   n_angles=160,
                                   r_min=0.58, r_max=1.08,
                                   min_sectors=7,
                                   min_points=28):
    """
    Track the visible hot wok rim directly, then let the caller map it back to
    the larger business ROI.
    """
    if ir_frame is None or rx <= 1 or ry <= 1:
        return None

    h, w = ir_frame.shape[:2]
    vals = ir_frame[np.isfinite(ir_frame)]
    if vals.size < 100:
        return None

    rs = np.linspace(r_min, r_max, 72)
    angles = np.linspace(0.0, 2.0 * np.pi, n_angles, endpoint=False)
    band_tops = []
    points = []
    sectors = set()

    for ai, th in enumerate(angles):
        cos_t = np.cos(th)
        sin_t = np.sin(th)
        xs = np.rint(cx + rs * rx * cos_t).astype(np.int32)
        ys = np.rint(cy + rs * ry * sin_t).astype(np.int32)
        valid = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
        if valid.sum() < 15:
            continue

        xs_v = xs[valid]
        ys_v = ys[valid]
        rs_v = rs[valid]
        ts = ir_frame[ys_v, xs_v].astype(np.float32)
        if ts.size < 15 or not np.isfinite(ts).all():
            continue

        peak_i = int(np.argmax(ts))
        peak_t = float(ts[peak_i])
        peak_r = float(rs_v[peak_i])
        if peak_r < 0.64 or peak_r > 1.02:
            continue

        inner0 = max(0, peak_i - 7)
        inner1 = max(inner0 + 1, peak_i - 2)
        outer0 = min(ts.size - 1, peak_i + 2)
        outer1 = min(ts.size, peak_i + 8)
        if outer1 <= outer0 or inner1 <= inner0:
            continue

        inner_med = float(np.median(ts[inner0:inner1]))
        outer_med = float(np.median(ts[outer0:outer1]))
        if peak_t < inner_med or peak_t < outer_med + 1.0:
            continue

        band_tops.append(peak_t)
        points.append((
            float(xs_v[peak_i]), float(ys_v[peak_i]), peak_r, th,
            peak_t, inner_med, outer_med, ai * 16 // n_angles
        ))
        sectors.add(ai * 16 // n_angles)

    if len(points) < min_points or len(sectors) < min_sectors:
        return {
            "ok": False,
            "reason": f"hot-ring points {len(points)}, sectors {len(sectors)}",
        }

    top_thr = float(np.percentile(np.array(band_tops, dtype=np.float32), 60))
    pts_arr = np.array([[p[0], p[1]] for p in points], dtype=np.float32)
    r_arr = np.array([p[2] for p in points], dtype=np.float32)
    t_arr = np.array([p[4] for p in points], dtype=np.float32)
    sector_arr = np.array([p[7] for p in points], dtype=np.int32)

    med_r = float(np.median(r_arr))
    keep_radius = np.abs(r_arr - med_r) <= 0.14
    keep_hot = keep_radius & (t_arr >= top_thr)
    hot_sectors = set(sector_arr[keep_hot].tolist())
    if keep_hot.sum() >= max(18, min_points // 2) and len(hot_sectors) >= max(5, min_sectors - 1):
        keep = keep_hot
        fit_mode = "hot-ring"
    else:
        keep = keep_radius
        fit_mode = "hot-radius"

    pts_keep = pts_arr[keep]
    if len(pts_keep) < 5:
        return {"ok": False, "reason": "not enough hot rim points"}

    try:
        ellipse = cv2.fitEllipse(pts_keep)
        (fit_cx, fit_cy), (ew, eh), _ = ellipse
    except Exception as exc:
        return {"ok": False, "reason": f"hot fit failed: {exc}"}

    fit_rx = max(float(ew), float(eh)) / 2.0
    fit_ry = min(float(ew), float(eh)) / 2.0
    rx_ratio = fit_rx / max(float(rx), 1.0)
    ry_ratio = fit_ry / max(float(ry), 1.0)
    if rx_ratio < 0.45 or rx_ratio > 1.10 or ry_ratio < 0.45 or ry_ratio > 1.10:
        return {
            "ok": False,
            "reason": f"hot fit radius rx={rx_ratio:.2f} ry={ry_ratio:.2f}",
        }

    return {
        "ok": True,
        "cx": float(fit_cx),
        "cy": float(fit_cy),
        "rx": float(fit_rx),
        "ry": float(fit_ry),
        "points": int(len(pts_keep)),
        "sectors": int(len(set(sector_arr[keep].tolist()))),
        "peak": float(np.median(t_arr[keep])),
        "fit_mode": fit_mode,
    }


def refine_wok_ellipse_from_rgb(frame_bgr, cx, cy, rx, ry, shrink_px=8):
    """
    从 RGB 帧的锅沿亮环中精化内圆边界椭圆。

    原理：
      1. 在手动标注椭圆的环状区域（外边±20%宽度）内做掩码
      2. 转灰度后 Canny 边缘检测
      3. 对边缘点做 fitEllipse，得到精确锅沿椭圆
      4. 向内收缩 shrink_px 作为实际锅内区域边界

    返回：
      (cx_new, cy_new, rx_new, ry_new) 精化后的椭圆参数
      失败时 fallback 返回原始参数
    """
    try:
        h, w = frame_bgr.shape[:2]
        # 环状搜索区域：外圆 = 标注椭圆 * 1.15，内圆 = 标注椭圆 * 0.80
        outer_mask = np.zeros((h, w), dtype=np.uint8)
        inner_mask = np.zeros((h, w), dtype=np.uint8)
        cv2.ellipse(outer_mask, (int(cx), int(cy)),
                    (int(rx * 1.15), int(ry * 1.15)), 0, 0, 360, 255, -1)
        cv2.ellipse(inner_mask, (int(cx), int(cy)),
                    (int(rx * 0.80), int(ry * 0.80)), 0, 0, 360, 255, -1)
        ring_mask = (outer_mask > 0) & (inner_mask == 0)

        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        # 在环状区域内做自适应亮度归一化后 Canny
        gray_ring = cv2.bitwise_and(gray, gray, mask=ring_mask.astype(np.uint8))
        blurred   = cv2.GaussianBlur(gray_ring, (5, 5), 1.2)
        edges     = cv2.Canny(blurred, 30, 90)
        edges     = cv2.bitwise_and(edges, edges, mask=ring_mask.astype(np.uint8))

        ys, xs = np.where(edges > 0)
        if len(xs) < 20:
            return cx, cy, rx, ry   # 边缘点不足，fallback

        pts = np.column_stack([xs, ys]).astype(np.float32)
        ellipse = cv2.fitEllipse(pts)
        (ecx, ecy), (ew, eh), angle = ellipse
        # 拟合结果合理性检查：圆心偏移不超过标注值 15%，半径比例合理
        if (abs(ecx - cx) > rx * 0.3 or abs(ecy - cy) > ry * 0.3):
            return cx, cy, rx, ry
        new_rx = max(ew, eh) / 2.0 - shrink_px
        new_ry = min(ew, eh) / 2.0 - shrink_px
        if new_rx < rx * 0.5 or new_ry < ry * 0.5:
            return cx, cy, rx, ry   # 收缩过度，fallback
        print(f"[锅沿精化] RGB椭圆检测成功: "
              f"cx={ecx:.0f}({cx:.0f}) cy={ecy:.0f}({cy:.0f}) "
              f"rx={new_rx:.0f}({rx:.0f}) ry={new_ry:.0f}({ry:.0f})")
        return float(ecx), float(ecy), float(new_rx), float(new_ry)
    except Exception as _re:
        print(f"[锅沿精化] 失败({_re})，保留原始标注椭圆")
        return cx, cy, rx, ry


def draw_temp_chart(temp_history, cur_time_s, w, h, curve_win_s=60,
                    roi_history=None, ir_mask_history=None, inverse_history=None):
    """
    用纯 numpy/cv2 绘制温度折线图，支持四条曲线：
      SAM2 mask（橙色）、ROI 固定圆圈（蓝色）、IR mask 自动分割（绿色）、
      反向语义（紫色实线）

    参数：
      temp_history     : list of (time_s, temp_mean)，SAM2 mask 温度历史
      cur_time_s       : 当前帧时间（秒）
      w, h             : 图像宽高（像素）
      curve_win_s      : 滑动窗口长度（秒），只显示最近 N 秒
      roi_history      : list of (time_s, temp_mean)，ROI 区域温度历史（可选）
      ir_mask_history  : list of (time_s, temp_mean)，IR mask 温度历史（可选）
      inverse_history  : list of (time_s, temp_mean)，反向语义温度历史（可选）
    """
    bar = np.zeros((h, w, 3), dtype=np.uint8)
    if len(temp_history) < 2:
        cv2.putText(bar, "Mask Avg Temp (waiting for data...)",
                    (10, h // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (160, 160, 160), 1)
        return bar

    # 取滑动窗口内的有效数据
    t0  = max(0.0, cur_time_s - curve_win_s)
    pts = [(t, v) for t, v in temp_history if t >= t0 and not np.isnan(v)]
    if len(pts) < 2:
        pts = temp_history[-2:]

    times = [p[0] for p in pts]
    vals  = [p[1] for p in pts]

    # ROI 数据（同窗口）
    roi_pts = []
    if roi_history:
        roi_pts = [(t, v) for t, v in roi_history if t >= t0 and not np.isnan(v)]

    # 坐标范围（Y 轴留 5°C 余量，兼顾两条曲线）
    all_vals = vals + [v for _, v in roi_pts]
    t_min = t0
    t_max = max(cur_time_s, t0 + 1.0)
    v_min = max(0.0, min(all_vals) - 5.0)
    v_max = max(all_vals) + 5.0
    if v_max <= v_min:
        v_max = v_min + 10.0

    # 绘图边距
    pad_l, pad_r, pad_t, pad_b = 48, 12, 10, 22

    def tx(t):
        return pad_l + int((t - t_min) / (t_max - t_min) * (w - pad_l - pad_r))

    def ty(v):
        return pad_t + int((1.0 - (v - v_min) / (v_max - v_min)) * (h - pad_t - pad_b))

    # 网格线 + Y 轴刻度（3 条）
    for v in np.linspace(v_min, v_max, 3):
        yy = ty(v)
        cv2.line(bar, (pad_l, yy), (w - pad_r, yy), (45, 45, 45), 1)
        cv2.putText(bar, f"{v:.0f}", (2, yy + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (180, 180, 180), 1)

    # 坐标轴
    cv2.line(bar, (pad_l, pad_t), (pad_l, h - pad_b), (160, 160, 160), 1)
    cv2.line(bar, (pad_l, h - pad_b), (w - pad_r, h - pad_b), (160, 160, 160), 1)

    # X 轴时间刻度（起止）
    cv2.putText(bar, f"{t_min:.0f}s", (pad_l, h - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.32, (140, 140, 140), 1)
    cv2.putText(bar, f"{cur_time_s:.1f}s", (w - pad_r - 30, h - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.32, (140, 140, 140), 1)

    # SAM2 mask 折线（橙色）
    screen_pts = [(tx(t), ty(v)) for t, v in zip(times, vals)]
    for i in range(1, len(screen_pts)):
        p1, p2 = screen_pts[i - 1], screen_pts[i]
        if all(0 <= c < dim for c, dim in [(p1[0], w), (p1[1], h), (p2[0], w), (p2[1], h)]):
            cv2.line(bar, p1, p2, (50, 165, 255), 2)

    # ROI 折线（蓝色）
    if len(roi_pts) >= 2:
        roi_screen = [(tx(t), ty(v)) for t, v in roi_pts]
        for i in range(1, len(roi_screen)):
            p1, p2 = roi_screen[i - 1], roi_screen[i]
            if all(0 <= c < dim for c, dim in [(p1[0], w), (p1[1], h), (p2[0], w), (p2[1], h)]):
                cv2.line(bar, p1, p2, (255, 160, 30), 2)
        # ROI 当前值
        rx, ry = roi_screen[-1]
        if 0 <= rx < w and 0 <= ry < h:
            cv2.circle(bar, (rx, ry), 4, (255, 100, 0), -1)
            cv2.putText(bar, f"ROI:{roi_pts[-1][1]:.1f}C", (rx + 6, ry + 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 180, 60), 1)

    # IR mask 折线（绿色）
    ir_pts = []
    if ir_mask_history:
        ir_pts = [(t, v) for t, v in ir_mask_history if t >= t0 and not np.isnan(v)]
    if len(ir_pts) >= 2:
        ir_screen = [(tx(t), ty(v)) for t, v in ir_pts]
        for i in range(1, len(ir_screen)):
            p1, p2 = ir_screen[i - 1], ir_screen[i]
            if all(0 <= c < dim for c, dim in [(p1[0], w), (p1[1], h), (p2[0], w), (p2[1], h)]):
                cv2.line(bar, p1, p2, (0, 220, 80), 2)
        irx, iry = ir_screen[-1]
        if 0 <= irx < w and 0 <= iry < h:
            cv2.circle(bar, (irx, iry), 4, (0, 255, 60), -1)
            cv2.putText(bar, f"IR:{ir_pts[-1][1]:.1f}C", (irx + 6, iry + 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 255, 100), 1)

    # SAM2 当前帧红点
    cx, cy = tx(cur_time_s), ty(vals[-1])
    if 0 <= cx < w and 0 <= cy < h:
        cv2.circle(bar, (cx, cy), 4, (0, 60, 255), -1)
        cv2.putText(bar, f"Mask:{vals[-1]:.1f}C", (cx + 6, cy + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 200, 255), 1)

    # 反向语义折线（紫色实线）
    inv_pts = []
    if inverse_history:
        inv_pts = [(t, v) for t, v in inverse_history if t >= t0 and not np.isnan(v)]
    if len(inv_pts) >= 2:
        inv_screen = [(tx(t), ty(v)) for t, v in inv_pts]
        for i in range(1, len(inv_screen)):
            p1, p2 = inv_screen[i - 1], inv_screen[i]
            if all(0 <= c < dim for c, dim in [(p1[0], w), (p1[1], h), (p2[0], w), (p2[1], h)]):
                cv2.line(bar, p1, p2, (200, 80, 255), 2)
        ivx, ivy = inv_screen[-1]
        if 0 <= ivx < w and 0 <= ivy < h:
            cv2.circle(bar, (ivx, ivy), 4, (200, 80, 255), -1)
            cv2.putText(bar, f"Inv:{inv_pts[-1][1]:.1f}C", (ivx + 6, ivy + 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.38, (200, 80, 255), 1)

    # 图例（全英文，cv2 不支持中文/特殊符号）
    cv2.putText(bar, "[SAM2]", (pad_l + 4, pad_t + 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.38, (50, 165, 255), 1)
    if roi_pts:
        cv2.putText(bar, "[ROI]", (pad_l + 70, pad_t + 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 160, 30), 1)
    if ir_pts:
        cv2.putText(bar, "[IR-Auto]", (pad_l + 120, pad_t + 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 220, 80), 1)
    if inv_pts:
        cv2.putText(bar, "[Inv]", (pad_l + 200, pad_t + 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (200, 80, 255), 1)

    return bar


# ── 主程序 ───────────────────────────────────────────────────────────────────

def generate_inverse_bottom_points_from_ir(rgb_frame, ir_frame, wok_mask_ir,
                                           homography_inv, wok_rgb_constraint,
                                           n_fg=18, n_bg=18, rng=None,
                                           preview_path=None):
    """Generate inverse-SAM2 points from current IR: hot wok/body=FG, cool food=BG."""
    if (rgb_frame is None or ir_frame is None or wok_mask_ir is None
            or homography_inv is None or wok_rgb_constraint is None):
        return [], [], False

    rng = rng or np.random.default_rng(0)
    wok_t = ir_frame[wok_mask_ir]
    if len(wok_t) < 10:
        return [], [], False

    c_low = float(np.percentile(wok_t, 10))
    c_high = float(np.percentile(wok_t, 90))
    for _ in range(20):
        d_low = np.abs(wok_t - c_low)
        d_high = np.abs(wok_t - c_high)
        low_sel = d_low <= d_high
        n_low = float(np.mean(wok_t[low_sel])) if low_sel.any() else c_low
        n_high = float(np.mean(wok_t[~low_sel])) if (~low_sel).any() else c_high
        if abs(n_low - c_low) < 0.1 and abs(n_high - c_high) < 0.1:
            break
        c_low, c_high = n_low, n_high
    if (c_high - c_low) < 25.0:
        return [], [], False

    ys_w, xs_w = np.where(wok_mask_ir)
    vals = ir_frame[wok_mask_ir]
    d_low = np.abs(vals - c_low)
    d_high = np.abs(vals - c_high)
    food_ir = np.zeros_like(wok_mask_ir, dtype=np.uint8)
    hot_ir = np.zeros_like(wok_mask_ir, dtype=np.uint8)
    food_ir[ys_w[d_low <= d_high], xs_w[d_low <= d_high]] = 255
    hot_ir[ys_w[d_high < d_low], xs_w[d_high < d_low]] = 255

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    food_ir = cv2.morphologyEx(food_ir, cv2.MORPH_OPEN, kernel) > 0
    hot_ir = cv2.morphologyEx(hot_ir, cv2.MORPH_OPEN, kernel) > 0

    def _sample_points(mask_ir, n):
        ys, xs = np.where(mask_ir)
        if len(xs) == 0:
            return []
        idx = rng.choice(len(xs), size=min(len(xs), n * 8), replace=False)
        pts_ir = np.array([[[float(xs[i]), float(ys[i])]] for i in idx], dtype=np.float32)
        pts_rgb = cv2.perspectiveTransform(pts_ir, homography_inv).reshape(-1, 2)
        h, w = wok_rgb_constraint.shape
        pts = []
        for x, y in pts_rgb:
            xi, yi = int(round(float(x))), int(round(float(y)))
            if 0 <= xi < w and 0 <= yi < h and wok_rgb_constraint[yi, xi]:
                pts.append([float(xi), float(yi)])
                if len(pts) >= n:
                    break
        return pts

    fg_pts = _sample_points(hot_ir, n_fg)
    bg_pts = _sample_points(food_ir, n_bg)
    ok = len(fg_pts) >= 4 and len(bg_pts) >= 4

    if ok and preview_path:
        vis = rgb_frame.copy()
        shade = np.zeros_like(vis)
        shade[wok_rgb_constraint] = (70, 70, 70)
        vis = cv2.addWeighted(vis, 1.0, shade, 0.25, 0)
        for x, y in fg_pts:
            cv2.circle(vis, (int(x), int(y)), 8, (0, 255, 80), -1)
            cv2.circle(vis, (int(x), int(y)), 9, (0, 0, 0), 1)
        for x, y in bg_pts:
            cv2.circle(vis, (int(x), int(y)), 8, (0, 0, 255), -1)
            cv2.circle(vis, (int(x), int(y)), 9, (0, 0, 0), 1)
        cv2.putText(vis, f"Inverse auto points FG-hot={len(fg_pts)} BG-food={len(bg_pts)}",
                    (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        cv2.putText(vis, f"K-low/high=({c_low:.1f},{c_high:.1f})C",
                    (20, 78), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2)
        cv2.imwrite(preview_path, vis)

    return fg_pts, bg_pts, ok


def main():
    runtime_cfg = _track_config.resolve_runtime_config(
        sys.argv[1:],
        project_root=_PROJECT_ROOT,
        default_labels_json=LABELS_JSON,
        default_homography_path=HOMOGRAPHY_PATH,
        default_wok_cfg_path=os.path.join(_HERE, "..", "data", "wok_region.json"),
        default_output_root=os.path.join(_HERE, "..", "output"),
    )
    labels_json = runtime_cfg.labels_json
    video_override = runtime_cfg.video_override
    homography_path = runtime_cfg.homography_path
    wok_cfg_path = runtime_cfg.wok_cfg_path
    temp_override = runtime_cfg.temp_override
    ir_wok_strategy = runtime_cfg.ir_wok_strategy
    output_root = runtime_cfg.output_root
    max_frames = runtime_cfg.max_frames
    if runtime_cfg.run_config_path:
        print(f"[config] loaded: {os.path.abspath(runtime_cfg.run_config_path)}")
    print(f"[IR Mask] strategy={ir_wok_strategy}")
    # ── 创建时间戳输出子目录 ──────────────────────────────────────────────────
    run_ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir  = os.path.join(output_root, run_ts)
    os.makedirs(out_dir, exist_ok=True)
    out_video_viz = os.path.join(out_dir, "track_result_viz.mp4")
    out_csv       = os.path.join(out_dir, "food_temp_log.csv")      # noqa (reserved)
    out_xlsx      = os.path.join(out_dir, "food_temp_log.xlsx")     # noqa (reserved)
    out_curve     = os.path.join(out_dir, "food_temp_curve.png")
    print(f"[输出] 本次结果目录: {out_dir}")

    # ── 检查依赖文件 ──────────────────────────────────────────────────────────
    if not os.path.exists(labels_json):
        print(f"[error] labels file not found: {labels_json}")
        print("请先运行 LabelFirstFrame.py 完成标注")
        sys.exit(1)

    video_path, start_frame, keyframes, bottom_keyframes = _label_io.load_labels(
        labels_json,
        max_fg_points=MAX_FG_POINTS,
        max_bg_points=MAX_BG_POINTS,
    )
    if video_override:
        print(f"[config] override video path: {video_override}")
        video_path = video_override
    # 第一个关键帧用于初始标注
    first_kf  = keyframes[0]
    fg_points = first_kf["fg_points"]
    bg_points = first_kf["bg_points"]
    # 其余关键帧（index>=1）将在追踪过程中按帧号注入
    extra_kfs = keyframes[1:]
    if extra_kfs:
        print(f"[多关键帧] 将在以下帧注入额外前景标注：")
        for kf in extra_kfs:
            print(f"  帧 {kf['frame']}  标签={kf.get('label','')}  FG={len(kf['fg_points'])}")
    # 锅底关键帧（用于反向追踪）
    has_bottom = len(bottom_keyframes) > 0
    if has_bottom:
        bottom_first_kf  = bottom_keyframes[0]
        bottom_fg_points = bottom_first_kf["fg_points"]
        bottom_bg_points = bottom_first_kf["bg_points"]
        bottom_start_frame = bottom_first_kf["frame"]
        print(f"[锅底反向] 将从帧 {bottom_start_frame} 开始追踪锅底（反向语义）")
    else:
        bottom_fg_points = bottom_bg_points = []
        bottom_start_frame = start_frame

    # ── wok_rgb_region 的读取参数（先存起来，等 VH/VW 初始化后再构建 mask）──
    _wok_rgb_json = {}
    try:
        with open(labels_json, "r", encoding="utf-8") as _f_wok:
            _wok_rgb_json = json.load(_f_wok)
    except Exception:
        pass

    if not os.path.exists(video_path):
        print(f"[错误] 找不到视频: {video_path}")
        sys.exit(1)

    # 获取视频基本信息
    cap_info = cv2.VideoCapture(video_path)
    total_frames = int(cap_info.get(cv2.CAP_PROP_FRAME_COUNT))
    fps          = cap_info.get(cv2.CAP_PROP_FPS)
    VW           = int(cap_info.get(cv2.CAP_PROP_FRAME_WIDTH))
    VH           = int(cap_info.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap_info.release()
    track_end_frame = total_frames
    if max_frames is not None:
        track_end_frame = min(total_frames, start_frame + max(1, int(max_frames)))
        print(f"[config] short run enabled: max_frames={max_frames}")
    track_frames = max(0, track_end_frame - start_frame)
    print(f"[config] effective track range: {start_frame} ~ {track_end_frame} ({track_frames} frames)")
    print(f"\n[视频] {video_path}")
    print(f"[视频] 分辨率: {VW}x{VH}  总帧数: {total_frames}  FPS: {fps:.1f}")
    print(f"[视频] 追踪范围: 第 {start_frame} ~ {track_end_frame} 帧，共 {track_frames} 帧")
    print(f"[分批] 每批 {CHUNK_SIZE} 帧，共需 {(track_frames + CHUNK_SIZE - 1)//CHUNK_SIZE} 批")

    # ── 加载 wok_rgb_region（在 VH/VW 已知后构建静态 mask）───────────────────
    wok_rgb_cx = wok_rgb_cy = wok_rgb_rx = wok_rgb_ry = None
    wok_rgb_rim_rx = wok_rgb_rim_ry = None
    wok_rgb_anchor_cx = wok_rgb_anchor_cy = None
    wok_rgb_mask_static = None
    _wok_rgb_cx_dyn = _wok_rgb_cy_dyn = None
    _WOK_RGB_MAX_DRIFT = 40
    _bottom_carry = None
    _bottom_fail_streak = 0
    _bottom_auto_reset = None
    _bottom_inject_map = {kf["frame"]: kf for kf in bottom_keyframes[1:]}
    if "wok_rgb_region" in _wok_rgb_json:
        _wr = _wok_rgb_json["wok_rgb_region"]
        wok_rgb_cx = float(_wr["cx"])
        wok_rgb_cy = float(_wr["cy"])
        wok_rgb_anchor_cx = float(_wr.get("center_x", _wr.get("initial_cx", wok_rgb_cx)))
        wok_rgb_anchor_cy = float(_wr.get("center_y", _wr.get("initial_cy", wok_rgb_cy)))
        wok_rgb_rim_rx = float(_wr["rx"])
        wok_rgb_rim_ry = float(_wr["ry"])
        wok_rgb_rx = wok_rgb_rim_rx * 0.79   # 反向语义检测区域：锅沿内缩
        wok_rgb_ry = wok_rgb_rim_ry * 0.79
        print(f"[wok_rgb] 已加载 RGB 锅椭圆: "
              f"cx={wok_rgb_cx:.0f} cy={wok_rgb_cy:.0f} "
              f"rim_rx={wok_rgb_rim_rx:.0f} rim_ry={wok_rgb_rim_ry:.0f} "
              f"detect_rx={wok_rgb_rx:.0f} detect_ry={wok_rgb_ry:.0f}")
        print(f"[wok_rgb] 手工锅中心锚点: "
              f"cx={wok_rgb_anchor_cx:.0f} cy={wok_rgb_anchor_cy:.0f}")
        _wm_static = np.zeros((VH, VW), dtype=np.uint8)
        cv2.ellipse(_wm_static,
                    (int(round(wok_rgb_cx)), int(round(wok_rgb_cy))),
                    (int(round(wok_rgb_rx)), int(round(wok_rgb_ry))),
                    0, 0, 360, 255, -1)
        wok_rgb_mask_static = _wm_static > 0
        # 反向语义动态中心由 IR 锅中心反投影驱动；这里仅保存初始人工中心用于偏移校正。
        _wok_rgb_cx_dyn = wok_rgb_anchor_cx
        _wok_rgb_cy_dyn = wok_rgb_anchor_cy
    else:
        print(f"[wok_rgb] 未找到 wok_rgb_region，inverse_mask 将 fallback 到 IR 反投影约束")

    # ── 预构建关键帧注入表：{abs_frame: kf_dict} ──────────────────────────────
    # 只包含 extra_kfs（index>=1），第一个关键帧已经作为初始标注点使用
    inject_map = {kf["frame"]: kf for kf in extra_kfs}

    # ── 加载单应矩阵（可选）──────────────────────────────────────────────────
    homography = None
    if os.path.exists(homography_path):
        homography = np.load(homography_path)
        print(f"[homography] loaded: {homography_path}  shape: {homography.shape}")
        # wok_rgb 动态圆心由 refine_wok_ellipse_from_rgb（首帧RGB精化）或手动标注值初始化
        # 不再用 IR 反投影覆盖（IR→RGB 换算有系统误差，导致圆心偏移）
        if wok_rgb_cx is not None:
            print(f"[wok_rgb初始化] 初始反向语义中心: ({_wok_rgb_cx_dyn:.0f}, {_wok_rgb_cy_dyn:.0f})")
    else:
        print(f"[homography] missing: {homography_path}; skip temperature fusion")

    # ── 自动匹配温度文件 ──────────────────────────────────────────────────────
    global TEMP_NPY_PATH
    if temp_override is not None:
        TEMP_NPY_PATH = temp_override
    if TEMP_NPY_PATH is None:
        TEMP_NPY_PATH = find_temp_npy(video_path)
    temp_data, ir_total_frames = load_temp_data(TEMP_NPY_PATH)

    # ── 加载逐帧时间戳文件（用于精确帧对齐）────────────────────────────────
    # 新录制数据会有 rgb_YYYYMMDD_HHMMSS_ts.npy 和 temp_YYYYMMDD_HHMMSS_ts.npy
    # 老录制数据没有时间戳文件，fallback 到帧率比例估算
    _rgb_ts = None   # shape (N_rgb,) float64 Unix 时间戳
    _ir_ts  = None   # shape (N_ir,)  float64 Unix 时间戳

    if temp_data is not None:
        _ir_ts_path = TEMP_NPY_PATH.replace(".npy", "_ts.npy") if TEMP_NPY_PATH else None
        if _ir_ts_path and os.path.exists(_ir_ts_path):
            _ir_ts = np.load(_ir_ts_path)
            print(f"[时间戳] IR 时间戳已加载: {os.path.basename(_ir_ts_path)}  {len(_ir_ts)} 帧")

    _rgb_ts_path = os.path.splitext(os.path.basename(video_path))[0]
    _rgb_ts_path = _rgb_ts_path.replace("rgb_", "") if _rgb_ts_path.startswith("rgb_") else _rgb_ts_path
    _rgb_ts_file = os.path.join(os.path.dirname(os.path.abspath(video_path)),
                                f"rgb_{_rgb_ts_path}_ts.npy")
    # 也兼容直接以 rgb_YYYYMMDD_HHMMSS_ts.npy 命名的情况
    _rgb_ts_file2 = os.path.splitext(os.path.abspath(video_path))[0] + "_ts.npy"
    for _ts_candidate in [_rgb_ts_file2, _rgb_ts_file]:
        if os.path.exists(_ts_candidate):
            _rgb_ts = np.load(_ts_candidate)
            print(f"[时间戳] RGB 时间戳已加载: {os.path.basename(_ts_candidate)}  {len(_rgb_ts)} 帧")
            break

    if _rgb_ts is not None and _ir_ts is not None:
        print(f"[时间戳] 启用时间戳帧对齐模式（精度 ~40ms）")
    else:
        print(f"[时间戳] 时间戳文件不完整，fallback 到帧率比例估算")

    # 计算 IR/RGB 帧率比例（用于时间对齐，无时间戳时使用）
    ir_fps_ratio = 1.0   # 默认 1:1
    if temp_data is not None and total_frames > 0:
        ir_fps_ratio = ir_total_frames / total_frames
        ir_fps_est   = fps * ir_fps_ratio
        print(f"[帧率对齐] RGB {fps:.1f}fps × {total_frames}帧 | "
              f"IR ~{ir_fps_est:.1f}fps × {ir_total_frames}帧 | "
              f"比例 {ir_fps_ratio:.4f}")

    def _get_ir_idx(rgb_abs_idx: int) -> int:
        """根据 RGB 帧号查找最近邻 IR 帧号（有时间戳用时间戳，无则用帧率比例）"""
        if _rgb_ts is not None and _ir_ts is not None:
            if rgb_abs_idx < len(_rgb_ts):
                t = _rgb_ts[rgb_abs_idx]
                return int(np.argmin(np.abs(_ir_ts - t)))
            # 超出时间戳范围，退化到比例
        return min(int(rgb_abs_idx * ir_fps_ratio), ir_total_frames - 1)

    # ── 设备 ──────────────────────────────────────────────────────────────────
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"\n[设备] 使用: {device}")
    if device.type == "cuda":
        print(f"[设备] GPU: {torch.cuda.get_device_name(0)}")
        # 限制 PyTorch 显存碎片，降低 OOM 风险
        os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

    # ── 加载 SAM2 ─────────────────────────────────────────────────────────────
    predictor = build_sam2_predictor(device)

    # ── 输出视频准备 ──────────────────────────────────────────────────────────
    fourcc      = cv2.VideoWriter_fourcc(*"mp4v")
    OUT_H       = VH + INFO_H + CHART_H          # 原始帧高 + 文字条 + 曲线图
    writer      = cv2.VideoWriter(out_video_viz, fourcc, fps, (VW, OUT_H))
    out_inv_viz = os.path.join(out_dir, "track_result_inv_viz.mp4")
    writer_inv  = cv2.VideoWriter(out_inv_viz, fourcc, fps, (VW, OUT_H)) if has_bottom else None
    # 三策略逐帧数据（各自独立存储，输出为单独表格）
    sam2_rows        = []   # [frame_abs, frame_rel, time_s, mask_pixels, mask_ratio, mean, min, max]
    roi_rows         = []   # [frame_abs, frame_rel, time_s, roi_temp_mean]
    ir_rows          = []   # [frame_abs, frame_rel, time_s, ir_mask_temp]
    inverse_rows     = []   # [frame_abs, frame_rel, time_s, inverse_temp_mean]  锅底反向语义
    temp_history     = []   # list of (time_s, temp_mean)，SAM2 mask 温度历史
    roi_history      = []   # list of (time_s, roi_temp)，ROI 区域温度历史
    ir_mask_history  = []   # list of (time_s, ir_mask_temp)，IR 自动分割温度历史
    inverse_history  = []   # list of (time_s, temp_mean)，锅底反向语义温度历史

    # ── 加载 ROI 配置 ─────────────────────────────────────────────────────────
    roi_cfg = None
    roi_cfg_path = os.path.join(_HERE, "..", "field", "roi_config.json")
    # 也兼容放在 data/ 目录下的情况
    if not os.path.exists(roi_cfg_path):
        roi_cfg_path = os.path.join(_HERE, "..", "data", "roi_config.json")
    if os.path.exists(roi_cfg_path):
        with open(roi_cfg_path, "r") as f:
            roi_cfg = json.load(f)
        print(f"[ROI] 已加载配置: {roi_cfg_path}")
        print(f"  RGB坐标: 圆心=({roi_cfg['rgb_cx']},{roi_cfg['rgb_cy']}) 半径={roi_cfg['rgb_radius']}px")
    else:
        print(f"[ROI] 未找到 roi_config.json，跳过 ROI 温度统计")
        print(f"  提示：在 FieldCapture.py 中按 R 键设置 ROI 后会自动生成")

    # ── 加载 IR 锅区域配置（用于 IR 自动分割温度曲线）────────────────────────
    IR_FOOD_PCT = 40   # 锅内低于此百分位的像素 = 菜
    wok_cfg, wok_mask_ir = _ir_wok.load_ir_wok_region(wok_cfg_path, temp_data)

    # ── 动态 wok 中心跟踪状态（方案B：用温度梯度跟踪锅中心漂移）───────────────
    # 手持拍摄时相机抖动导致 IR 中锅的位置帧间偏移，用高温区质心动态修正 cx/cy
    # rx/ry 保持 wok_region.json 里的固定值不变
    _wok_cx = float(wok_cfg["cx"]) if wok_cfg is not None else 0.0
    _wok_cy = float(wok_cfg["cy"]) if wok_cfg is not None else 0.0
    _wok_rx = float(wok_cfg["rx"]) if wok_cfg is not None else 0.0
    _wok_ry = float(wok_cfg["ry"]) if wok_cfg is not None else 0.0
    _wok_hot_dx = 0.0
    _wok_hot_dy = 0.0
    _wok_hot_sx = 1.0
    _wok_hot_sy = 1.0
    _wok_hot_ref_ready = False
    _WOK_MAX_DRIFT = 25   # 单批允许的最大质心漂移（IR px），防止极端帧跳变
                          # 旋转轴法精度高，可适当放宽（原15→25）
    # 动态 wok 中心历史记录：list of (abs_frame, cx, cy)
    # 拼合视频时按帧号查表，让 IR 椭圆随实际锅位置移动
    _wok_cx_history = [(start_frame, _wok_cx, _wok_cy)]
    _wok_recent_drifts = []   # 最近几批的 drift 值，用于倾斜检测
    _wok_tilting = False      # 当前是否处于锅倾斜/快速移动状态
    _USE_IR_FOR_INV_WOK = True
    _wok_rgb_ir_offset_x = 0.0
    _wok_rgb_ir_offset_y = 0.0
    _wok_rgb_ir_offset_ready = False
    _frame_shift_state = _ir_wok.init_frame_shift_state(
        ir_wok_strategy,
        temp_data,
        wok_mask_ir,
        start_frame,
        _get_ir_idx,
    )

    # ── 分批追踪主循环（SAM2 + 光流混合）────────────────────────────────────
    # 真正的混合模式：
    #   - 纯SAM2模式（OPTICAL_FLOW_INTERVAL<=1）：每批处理 CHUNK_SIZE 帧
    #   - 混合模式（OPTICAL_FLOW_INTERVAL>1）：SAM2 只处理锚点帧（单帧批次），
    #     其余帧完全用光流传播，不再调用 SAM2
    carry_mask     = None   # 上批末帧 SAM2 mask，用于跨批传递
    _next_inject   = None   # IR-fix接管后延迟到下批注入的前景点（让SAM2精细化）
    global_local   = 0      # 全局相对帧计数
    flow_prev_gray = None   # 光流：上一帧灰度图
    flow_prev_mask = None   # 光流：上一帧 mask

    use_flow = (OPTICAL_FLOW_INTERVAL > 1)
    if use_flow:
        print(f"[模式] SAM2+光流混合  SAM2锚点间隔={OPTICAL_FLOW_INTERVAL}帧")
        # 混合模式下：SAM2 每隔 N 帧处理 1 帧，其余帧光流传播
        # 将追踪范围按锚点帧切分
        anchor_frames = list(range(start_frame,
                                   track_end_frame,
                                   OPTICAL_FLOW_INTERVAL))
        print(f"[混合] 共 {len(anchor_frames)} 个SAM2锚点帧，"
              f"其余 {track_frames - len(anchor_frames)} 帧用光流")
    else:
        print(f"[模式] 纯SAM2  CHUNK_SIZE={CHUNK_SIZE}")

    # ── 推理分辨率：计算缩放比例 ─────────────────────────────────────────────
    orig_wh   = (VW, VH)   # 原始分辨率
    infer_wh  = SAM2_INFER_SIZE if SAM2_INFER_SIZE is not None else orig_wh
    do_resize = (infer_wh != orig_wh)

    if do_resize:
        print(f"[缩放] SAM2推理: {infer_wh[0]}×{infer_wh[1]}  "
              f"输出/温度: {orig_wh[0]}×{orig_wh[1]}")
        # 将标注点坐标缩放到推理分辨率
        fg_infer = scale_points(fg_points, orig_wh, infer_wh)
        bg_infer = scale_points(bg_points, orig_wh, infer_wh)
    else:
        fg_infer = fg_points
        bg_infer = bg_points

    # ── 自动重标点：加载 auto_label 的标点函数 ────────────────────────────────
    _auto_label_func = None
    _wok_cfg_al      = None
    _wok_mask_al     = None
    _H_inv_al        = None
    _rng_al          = None
    if RELABEL_INTERVAL_S > 0:
        try:
            import sys as _sys
            if _HERE not in _sys.path:
                _sys.path.insert(0, _HERE)
            from auto_label import (
                load_wok_cfg as _al_load_wok,
                build_wok_mask as _al_build_mask,
                generate_ir_mask_and_points as _al_ir_mask,
            )
            _wok_cfg_al = _al_load_wok()
            if temp_data is not None and homography is not None:
                _ir_h_al = temp_data.shape[1]
                _ir_w_al = temp_data.shape[2]
                _wok_mask_al = _al_build_mask(_wok_cfg_al, _ir_h_al, _ir_w_al)
                _H_inv_al    = np.linalg.inv(homography)
                _rng_al      = np.random.default_rng(42)
                _auto_label_func = _al_ir_mask
                print(f"[自动重标点] 已加载，每 {RELABEL_INTERVAL_S}s 重新标点并重置SAM2")
                # 用 IR 动态锅中心驱动 RGB 反向语义圈，并用首帧人工中心补偿 IR->RGB 系统偏差。
                if _USE_IR_FOR_INV_WOK and _wok_rgb_cx_dyn is not None:
                    _ir_wok0 = np.array([[[_wok_cx, _wok_cy]]], dtype=np.float32)
                    _rgb_wok0 = cv2.perspectiveTransform(_ir_wok0, _H_inv_al)[0][0]
                    _wok_rgb_ir_offset_x = float(_wok_rgb_cx_dyn - _rgb_wok0[0])
                    _wok_rgb_ir_offset_y = float(_wok_rgb_cy_dyn - _rgb_wok0[1])
                    _wok_rgb_ir_offset_ready = True
                    print(f"[wok_rgb-IR] 初始校正偏移: "
                          f"dx={_wok_rgb_ir_offset_x:.1f} dy={_wok_rgb_ir_offset_y:.1f}")
                # ── 旋转轴在 RGB 坐标系中的位置（永久背景点，不得标注为前景）──
                # wok_cfg cx/cy 是 IR 坐标，反投影到 RGB
                try:
                    # 优先使用 wok_region.json 里手动标注的旋转轴坐标
                    if "axis_cx" in _wok_cfg_al and "axis_cy" in _wok_cfg_al:
                        _ir_axis = np.array([[[float(_wok_cfg_al["axis_cx"]),
                                               float(_wok_cfg_al["axis_cy"])]]], dtype=np.float32)
                        _axis_src = "手动标注"
                    else:
                        # 退化：用椭圆中心 cx/cy 反投影
                        _ir_axis = np.array([[[float(_wok_cfg_al["cx"]),
                                               float(_wok_cfg_al["cy"])]]], dtype=np.float32)
                        _axis_src = "椭圆中心(默认)"
                    _rgb_center = cv2.perspectiveTransform(_ir_axis, _H_inv_al)[0][0]
                    _AXIS_CX_RGB = float(_rgb_center[0])
                    _AXIS_CY_RGB = float(_rgb_center[1])
                    _AXIS_EXCL_R = 90   # 旋转轴排除半径（RGB px）
                    print(f"[旋转轴] RGB坐标: ({_AXIS_CX_RGB:.0f}, {_AXIS_CY_RGB:.0f})"
                          f"  排除半径={_AXIS_EXCL_R}px  来源={_axis_src}")
                except Exception as _axe:
                    _AXIS_CX_RGB = _AXIS_CY_RGB = _AXIS_EXCL_R = None
                    print(f"[旋转轴] 坐标计算失败({_axe})，跳过排除")
            else:
                print(f"[自动重标点] 无温度数据或单应矩阵，禁用")
        except ImportError as e:
            print(f"[自动重标点] 导入失败({e})，禁用")

    last_relabel_s = start_frame / fps   # 上次重标点的时间（秒）
    prev_mask_ratio = 0.0                # 上批末帧 mask 面积占比（%），用于异常检测
    last_reinforce_wok_pct = 0.0         # 上次补强时 mask 占 wok 区域的%（骤降检测用）
    _in_recovery = False                 # 重置后进入 recovery 模式，每批强制检查直到恢复

    # ── 预计算 wok RGB mask（用于每帧后处理约束，避免循环内重复计算）────────
    _wok_rgb_constraint = None   # (VH, VW) bool
    if wok_mask_ir is not None and homography is not None:
        try:
            _wok_rgb_constraint = _ir_wok.project_ir_wok_to_rgb_constraint(
                wok_mask_ir, homography, (VH, VW))
            # Inverse mode uses this IR->RGB projected wok mask directly.
            # Disable the RGB ellipse path to avoid extra center/radius correction.
            wok_rgb_mask_static = None
            print(f"[wok约束] 预计算 RGB锅区域 mask  覆盖像素: {_wok_rgb_constraint.sum()}")
        except Exception as _we:

            print(f"[wok约束] 预计算失败({_we})，跳过约束")

    # ── 保存初始关键帧预览图 ──────────────────────────────────────────────────
    if _auto_label_func is not None:
        try:
            _cap_init = cv2.VideoCapture(video_path)
            _cap_init.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
            _ret_init, _rgb_init = _cap_init.read()
            _cap_init.release()
            if _ret_init:
                _vis_init = _rgb_init.copy()
                for _p in fg_points:
                    cv2.circle(_vis_init, (int(_p[0]), int(_p[1])), 8, (0, 255, 80), -1)
                    cv2.circle(_vis_init, (int(_p[0]), int(_p[1])), 9, (255, 255, 255), 1)
                for _p in bg_points:
                    cv2.circle(_vis_init, (int(_p[0]), int(_p[1])), 8, (0, 0, 255), -1)
                    cv2.circle(_vis_init, (int(_p[0]), int(_p[1])), 9, (255, 255, 255), 1)
                cv2.putText(_vis_init,
                            f"Initial-Label t={start_frame/fps:.0f}s  FG(green):{len(fg_points)} BG(red):{len(bg_points)}",
                            (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 200, 255), 2)
                cv2.putText(_vis_init, f"[from food_labels.json]  frame={start_frame}",
                            (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 160, 200), 2)
                _init_name = f"relabel_t{start_frame/fps:.0f}s_f{start_frame}_initial.jpg"
                cv2.imwrite(os.path.join(out_dir, _init_name), _vis_init)
                print(f"[初始标注] 预览图已保存: {_init_name}")
        except Exception as _ei:
            print(f"[初始标注] 预览图保存失败: {_ei}")

    if not use_flow:
        # ── 纯 SAM2 模式 ──────────────────────────────────────────────────────
        n_chunks = (track_frames + CHUNK_SIZE - 1) // CHUNK_SIZE
        for chunk_i in range(n_chunks):
            chunk_start_abs = start_frame + chunk_i * CHUNK_SIZE
            chunk_end_abs   = min(chunk_start_abs + CHUNK_SIZE, track_end_frame)
            chunk_len       = chunk_end_abs - chunk_start_abs
            chunk_start_s   = chunk_start_abs / fps

            _frame_shift_update = _ir_wok.apply_frame_shift_update(
                ir_wok_strategy,
                temp_data,
                wok_mask_ir,
                chunk_start_abs,
                _get_ir_idx,
                _frame_shift_state,
                _wok_cx,
                _wok_cy,
                homography,
                (VH, VW),
            )
            wok_mask_ir = _frame_shift_update.wok_mask_ir
            _wok_cx = _frame_shift_update.wok_cx
            _wok_cy = _frame_shift_update.wok_cy
            if wok_mask_ir is not None:
                _wok_mask_al = wok_mask_ir.copy()
            if _frame_shift_update.wok_rgb_constraint is not None:
                _wok_rgb_constraint = _frame_shift_update.wok_rgb_constraint
            if _frame_shift_update.disable_static_rgb_mask:
                wok_rgb_mask_static = None
            if _frame_shift_update.history_entry is not None:
                _wok_cx_history.append(_frame_shift_update.history_entry)

            print(f"\n{'='*55}")
            print(f"[批次 {chunk_i+1}/{n_chunks}] 帧 {chunk_start_abs} ~ {chunk_end_abs-1}"
                  f"  ({chunk_len} 帧)")

            # ── 动态 wok 中心更新（旋转轴检测法）─────────────────────────────
            # 原理：锅中心有一个固定旋转轴（从锅底凸起），温度偏低（类似食材温度）
            # 被高温锅壁圆环包围。用以下步骤定位旋转轴中心 = 锅的真实几何圆心：
            #   1. 在宽松椭圆内找高温像素（> 85百分位）= 锅壁热环
            #   2. 形态学闭运算填充热环，得到完整锅圈
            #   3. 在锅圈内部找最大低温连通域（< 50百分位）= 旋转轴
            #   4. 旋转轴质心 = 锅的几何圆心
            if (ir_wok_strategy == "legacy"
                    and wok_cfg is not None and temp_data is not None
                    and _wok_mask_al is not None and homography is not None):
                try:
                    _ir_idx_wok_upd = _get_ir_idx(chunk_start_abs)
                    _ir_frm_wok_upd = temp_data[_ir_idx_wok_upd]
                    _ir_h_ud = _ir_frm_wok_upd.shape[0]
                    _ir_w_ud = _ir_frm_wok_upd.shape[1]
                    _hot_fit = _estimate_wok_from_ir_hot_ring(
                        _ir_frm_wok_upd, _wok_cx, _wok_cy, _wok_rx, _wok_ry)
                    _legacy_hot_update = _ir_wok.apply_legacy_hot_ring_update(
                        _hot_fit,
                        wok_cfg,
                        _wok_cx,
                        _wok_cy,
                        _wok_rx,
                        _wok_ry,
                        _wok_hot_ref_ready,
                        _wok_hot_sx,
                        _wok_hot_sy,
                        _WOK_MAX_DRIFT,
                        chunk_start_abs,
                        chunk_start_s,
                        homography,
                        (VH, VW),
                        _wok_recent_drifts,
                        _wok_tilting,
                        (_ir_h_ud, _ir_w_ud),
                    )
                    _wok_cx = _legacy_hot_update.wok_cx
                    _wok_cy = _legacy_hot_update.wok_cy
                    _wok_rx = _legacy_hot_update.wok_rx
                    _wok_ry = _legacy_hot_update.wok_ry
                    _wok_hot_ref_ready = _legacy_hot_update.hot_ref_ready
                    _wok_hot_sx = _legacy_hot_update.hot_sx
                    _wok_hot_sy = _legacy_hot_update.hot_sy
                    _wok_recent_drifts = _legacy_hot_update.recent_drifts
                    _wok_tilting = _legacy_hot_update.tilting
                    if _legacy_hot_update.wok_mask_ir is not None:
                        wok_mask_ir = _legacy_hot_update.wok_mask_ir
                        _wok_mask_al = wok_mask_ir.copy()
                    if _legacy_hot_update.wok_rgb_constraint is not None:
                        _wok_rgb_constraint = _legacy_hot_update.wok_rgb_constraint
                    if _legacy_hot_update.disable_static_rgb_mask:
                        wok_rgb_mask_static = None
                    if _legacy_hot_update.history_entry is not None:
                        _wok_cx_history.append(_legacy_hot_update.history_entry)
                    # 宽松椭圆（1.5×）搜索范围
                    _loose_mask = np.zeros((_ir_h_ud, _ir_w_ud), dtype=np.uint8)
                    cv2.ellipse(_loose_mask,
                                (int(round(_wok_cx)), int(round(_wok_cy))),
                                (int(round(_wok_rx * 1.5)), int(round(_wok_ry * 1.5))),
                                0, 0, 360, 255, -1)
                    _loose_mask = _loose_mask > 0
                    _all_temps_ud = _ir_frm_wok_upd[_loose_mask]
                    if False and len(_all_temps_ud) >= 100:
                        # Step1: 高温热环（> 85百分位）
                        _t85 = float(np.percentile(_all_temps_ud, 85))
                        _hot_ring = (_ir_frm_wok_upd >= _t85) & _loose_mask
                        _hot_u8 = _hot_ring.astype(np.uint8) * 255
                        # Step2: 形态学闭运算填充热环成完整锅圈
                        _kc = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
                        _hot_closed = cv2.morphologyEx(_hot_u8, cv2.MORPH_CLOSE, _kc)
                        # Step3: 对热环像素做最小二乘圆拟合（Kasa法），直接得到锅的几何圆心
                        # 优势：完全不依赖锅内食物分布，食物多少/位置不影响圆心估计
                        # 原理：(xi-cx)^2 + (yi-cy)^2 = r^2
                        #       展开后变为线性方程：2*cx*xi + 2*cy*yi + c = xi^2+yi^2
                        #       其中 c = r^2-cx^2-cy^2，用 numpy.linalg.lstsq 求解
                        _ys_h, _xs_h = np.where(_hot_ring)
                        _cx_new, _cy_new = None, None
                        if len(_xs_h) >= 20:
                            try:
                                _A = np.column_stack([
                                    2.0 * _xs_h.astype(float),
                                    2.0 * _ys_h.astype(float),
                                    np.ones(len(_xs_h))
                                ])
                                _b_vec = (_xs_h.astype(float)**2
                                          + _ys_h.astype(float)**2)
                                _sol, _, _, _ = np.linalg.lstsq(_A, _b_vec, rcond=None)
                                _cx_fit = float(_sol[0])
                                _cy_fit = float(_sol[1])
                                # 检查拟合圆心在宽松椭圆内（防止离群点污染）
                                _dx_fit = _cx_fit - float(wok_cfg["cx"])
                                _dy_fit = _cy_fit - float(wok_cfg["cy"])
                                _loose_r = max(_wok_rx, _wok_ry) * 2.0
                                if (_dx_fit**2 + _dy_fit**2)**0.5 < _loose_r:
                                    _cx_new = _cx_fit
                                    _cy_new = _cy_fit
                            except Exception:
                                pass
                        # 如果圆拟合失败，退化到热环质心
                        if _cx_new is None and len(_xs_h) >= 20:
                            _cx_new = float(np.mean(_xs_h))
                            _cy_new = float(np.mean(_ys_h))
                        if _cx_new is not None:
                            _drift = (((_cx_new - _wok_cx)**2 + (_cy_new - _wok_cy)**2)**0.5)
                            if _drift <= _WOK_MAX_DRIFT:
                                if _drift > 0.5:
                                    _cx_old, _cy_old = _wok_cx, _wok_cy
                                    _wok_cx, _wok_cy = _cx_new, _cy_new
                                    _wm_new = np.zeros((_ir_h_ud, _ir_w_ud), dtype=np.uint8)
                                    cv2.ellipse(_wm_new,
                                                (int(round(_wok_cx)), int(round(_wok_cy))),
                                                (int(round(_wok_rx)), int(round(_wok_ry))),
                                                0, 0, 360, 255, -1)
                                    wok_mask_ir = _wm_new > 0
                                    _wok_mask_al = wok_mask_ir.copy()
                                    _wok_rgb_constraint = _ir_wok.project_ir_wok_to_rgb_constraint(
                                        wok_mask_ir, homography, (VH, VW))
                                    wok_rgb_mask_static = None
                                    _wok_cx_history.append((chunk_start_abs, _wok_cx, _wok_cy))
                                    print(f"[wok更新] t={chunk_start_s:.1f}s  "
                                          f"cx: {_cx_old:.1f}->{_wok_cx:.1f}  "
                                          f"cy: {_cy_old:.1f}->{_wok_cy:.1f}  "
                                          f"drift={_drift:.1f}px (旋转轴法)")
                                    # ── 倾斜检测：记录 drift 历史，判断锅是否快速移动 ──
                                    _wok_recent_drifts.append(_drift)
                                    if len(_wok_recent_drifts) > 3:
                                        _wok_recent_drifts.pop(0)
                                    _cum_drift = sum(_wok_recent_drifts)
                                    _was_tilting = _wok_tilting
                                    _wok_tilting = (len(_wok_recent_drifts) >= 2
                                                    and _cum_drift > 30.0)
                                    if _wok_tilting and not _was_tilting:
                                        print(f"[倾斜] t={chunk_start_s:.1f}s  "
                                              f"检测到锅快速移动(累计drift={_cum_drift:.1f}px)，"
                                              f"降低B-check阈值")
                                    elif _was_tilting and not _wok_tilting:
                                        print(f"[倾斜] t={chunk_start_s:.1f}s  "
                                              f"锅恢复稳定(累计drift={_cum_drift:.1f}px)")
                            else:
                                print(f"[wok更新] t={chunk_start_s:.1f}s  "
                                      f"drift={_drift:.1f}px>{_WOK_MAX_DRIFT}px，跳过（防跳变）")
                except Exception as _wud_e:
                    pass   # 更新失败不影响主流程

            # ── 每批动态更新旋转轴 RGB 坐标（用当前 _wok_cx/_wok_cy 反投影）────────
            # 手持拍摄时锅帧帧移动，不能用启动时算的固定坐标排除旋转轴
            # 每批用最新的 _wok_cx/_wok_cy（IR 坐标）实时反投影到 RGB
            _axis_cx_rgb_dyn = _AXIS_CX_RGB   # 默认 fallback 到初始静态值
            _axis_cy_rgb_dyn = _AXIS_CY_RGB
            if _H_inv_al is not None:
                try:
                    _ir_axis_dyn = np.array([[[_wok_cx, _wok_cy]]], dtype=np.float32)
                    _rgb_axis_dyn = cv2.perspectiveTransform(_ir_axis_dyn, _H_inv_al)[0][0]
                    _axis_cx_rgb_dyn = float(_rgb_axis_dyn[0])
                    _axis_cy_rgb_dyn = float(_rgb_axis_dyn[1])
                    if (_USE_IR_FOR_INV_WOK and _wok_rgb_ir_offset_ready
                            and wok_rgb_cx is not None):
                        _old_inv_cx, _old_inv_cy = _wok_rgb_cx_dyn, _wok_rgb_cy_dyn
                        _wok_rgb_cx_dyn = float(_rgb_axis_dyn[0] + _wok_rgb_ir_offset_x)
                        _wok_rgb_cy_dyn = float(_rgb_axis_dyn[1] + _wok_rgb_ir_offset_y)
                        _inv_drift = ((_wok_rgb_cx_dyn - _old_inv_cx) ** 2
                                      + (_wok_rgb_cy_dyn - _old_inv_cy) ** 2) ** 0.5
                        if _inv_drift > 0.5:
                            print(f"[wok_rgb-IR] t={chunk_start_s:.1f}s  "
                                  f"center: ({_old_inv_cx:.0f},{_old_inv_cy:.0f})->"
                                  f"({_wok_rgb_cx_dyn:.0f},{_wok_rgb_cy_dyn:.0f})  "
                                  f"drift={_inv_drift:.1f}px")
                except Exception:
                    pass   # 失败时保留静态值

            # ── 检查是否需要自动补强（每 N 秒从 carry_mask 内部采点注入第一帧）────
            # 新策略：carry_mask 始终保留（不置 None），只用 SAM2 自己的末帧 mask 定位，
            # IR 只做稳定性检查（决定要不要补强），不再参与任何标注点生成。
            _reinforce_inject = None   # 本批第一帧要注入的补强点

            # ── C：异常场景检测（白烟/空锅/锅直立）→ 冻结 carry_mask，跳过补强 ──
            # 检测锅内 RGB 区域的亮度均值和方差：
            #   白烟：均值 > 150 AND 方差 < 800（整锅均匀偏白）
            #   空锅/锅直立：均值 < 25（整锅极暗，食材不在画面中）
            _scene_frozen = False
            if carry_mask is not None and chunk_i > 0 and _wok_rgb_constraint is not None:
                try:
                    _cap_sc = cv2.VideoCapture(video_path)
                    _cap_sc.set(cv2.CAP_PROP_POS_FRAMES, chunk_start_abs)
                    _ret_sc, _rgb_sc = _cap_sc.read()
                    _cap_sc.release()
                    if _ret_sc:
                        _gray_sc = cv2.cvtColor(_rgb_sc, cv2.COLOR_BGR2GRAY)
                        _wok_px_sc = _gray_sc[_wok_rgb_constraint]
                        if len(_wok_px_sc) > 0:
                            _mean_sc = float(np.mean(_wok_px_sc))
                            _var_sc  = float(np.var(_wok_px_sc))
                            if _mean_sc > 150 and _var_sc < 800:
                                _scene_frozen = True
                                print(f"[冻结] t={chunk_start_s:.1f}s  检测到白烟/均匀高亮"
                                      f"(mean={_mean_sc:.0f}>150, var={_var_sc:.0f}<800)，"
                                      f"冻结carry_mask，跳过补强")
                            elif _mean_sc < 25:
                                _scene_frozen = True
                                print(f"[冻结] t={chunk_start_s:.1f}s  检测到空锅/锅直立"
                                      f"(mean={_mean_sc:.0f}<25)，冻结carry_mask，跳过补强")
                except Exception as _sc_e:
                    pass   # 检测失败不影响主流程

            # recovery 模式下：每批都检查（不等 RELABEL_INTERVAL_S）；正常模式下按间隔检查
            _should_check = (
                not _scene_frozen
                and carry_mask is not None
                and chunk_i > 0
                and (_in_recovery or (chunk_start_s - last_relabel_s) >= RELABEL_INTERVAL_S)
            )
            if _should_check:
                # ── IR 稳定性检查（只判断要不要补强，不采点）─────────────────
                # recovery 模式下强制跳过方差检查，必须尝试 IR 采点
                _do_reinforce = True
                if not _in_recovery and _auto_label_func is not None and temp_data is not None:
                    try:
                        _ir_idx_al = _get_ir_idx(chunk_start_abs)
                        _ir_frame_al = temp_data[_ir_idx_al]
                        from auto_label import load_wok_cfg as _lwc, build_wok_mask as _bwm
                        _wok_temps_chk = _ir_frame_al[_wok_mask_al]
                        _var_chk = float(np.var(_wok_temps_chk)) if len(_wok_temps_chk) > 0 else 0
                        if _var_chk < 200.0:
                            _do_reinforce = False
                            print(f"[补强] t={chunk_start_s:.1f}s  锅倾斜/翻炒(var={_var_chk:.1f})，跳过")
                    except Exception:
                        pass   # 检查失败则默认补强
                if _in_recovery:
                    print(f"[recovery] t={chunk_start_s:.1f}s  recovery模式，强制IR采点（跳过方差检查）")

                if _do_reinforce:
                    # ── 颜色过滤：读取当前批起始帧的灰度图，用于过滤黑色区域补强点 ──
                    _rgb_ref_gray = None
                    try:
                        _cap_ref = cv2.VideoCapture(video_path)
                        _cap_ref.set(cv2.CAP_PROP_POS_FRAMES, chunk_start_abs)
                        _ret_ref, _rgb_ref = _cap_ref.read()
                        _cap_ref.release()
                        if _ret_ref:
                            _rgb_ref_gray = cv2.cvtColor(_rgb_ref, cv2.COLOR_BGR2GRAY)
                    except Exception:
                        pass

                    # ── 检查 carry_mask 是否还在锅内（位置检查，比面积检查更可靠）────
                    # 指标：mask 与锅内区域(wok_rgb_constraint)的交集 / mask 自身面积
                    # < 60% 说明 mask 大部分跑到锅外/搅拌爪/金属部件上 → 强制重置
                    _mask_px = int(carry_mask.sum())
                    _need_reset = False
                    _overlap_pct = 100.0   # 默认100%（无wok约束时不重置）
                    if _wok_rgb_constraint is not None and _mask_px > 0:
                        _overlap_px = int((carry_mask & _wok_rgb_constraint).sum())
                        _overlap_pct = _overlap_px / _mask_px * 100
                        if _overlap_pct < 60.0:
                            _need_reset = True
                            print(f"[补强] t={chunk_start_s:.1f}s  "
                                  f"mask偏离锅内(overlap={_overlap_pct:.0f}%<60%)，"
                                  f"重置SAM2→初始标注点")
                    # 也保留面积检查：mask 超过 wok 区域 35% 同样重置（整锅漂移/锅底漂移）
                    # 食材正常情况下占锅内面积 < 35%，超过说明 SAM2 追踪到了锅底/空白区域
                    _wok_px_chk = int(_wok_rgb_constraint.sum()) if _wok_rgb_constraint is not None else (VW * VH)
                    _mask_vs_wok = _mask_px / max(_wok_px_chk, 1) * 100
                    if not _need_reset:
                        if _mask_vs_wok > 35.0:
                            _need_reset = True
                            print(f"[补强] t={chunk_start_s:.1f}s  "
                                  f"mask过大({_mask_vs_wok:.0f}%>wok35%)，"
                                  f"重置SAM2→IR定位新前景点")
                    # ── 第三级：面积骤降检测（漂移到旋转轴/小碎片）────────────
                    # last_reinforce_wok_pct = 上次补强时 mask 占 wok% （不是批次均值）
                    # 骤降 > 70% 或绝对值 < 2% → 重置
                    if not _need_reset and _wok_px_chk > 0:
                        _drop_pct = (last_reinforce_wok_pct - _mask_vs_wok) / max(last_reinforce_wok_pct, 0.1) * 100
                        if _mask_vs_wok < 2.0:
                            _need_reset = True
                            print(f"[补强] t={chunk_start_s:.1f}s  "
                                  f"mask过小({_mask_vs_wok:.1f}%<2%，可能是旋转轴碎片)，"
                                  f"重置SAM2→初始标注点")
                        elif last_reinforce_wok_pct > 5.0 and _drop_pct > 70.0:
                            _need_reset = True
                            print(f"[补强] t={chunk_start_s:.1f}s  "
                                  f"mask面积骤降({last_reinforce_wok_pct:.0f}%→{_mask_vs_wok:.0f}%，"
                                  f"跌幅{_drop_pct:.0f}%>70%)，重置SAM2→初始标注点")
                    if _need_reset:
                        # ── 记录重置原因（预览图在 IR 采点完成后保存）─────────
                        _rst_reason = "RESET"
                        if _mask_vs_wok < 2.0:
                            _rst_reason = f"RESET: mask过小({_mask_vs_wok:.1f}%<2%)"
                        elif last_reinforce_wok_pct > 5.0 and _drop_pct > 70.0:
                            _rst_reason = f"RESET: 骤降({last_reinforce_wok_pct:.0f}%→{_mask_vs_wok:.0f}%)"
                        elif _mask_vs_wok > 35.0:
                            _rst_reason = f"RESET: mask过大({_mask_vs_wok:.0f}%>wok35%)"
                        elif _overlap_pct < 60.0:
                            _rst_reason = f"RESET: 偏离锅内(overlap={_overlap_pct:.0f}%)"
                        # 保留跑偏时的帧和 mask，供稍后保存预览图
                        _rst_carry_mask = carry_mask   # 跑偏的旧 mask（可能是 None）
                        _rst_rgb_frame  = None
                        try:
                            _cap_rst = cv2.VideoCapture(video_path)
                            _cap_rst.set(cv2.CAP_PROP_POS_FRAMES, chunk_start_abs)
                            _ret_rst, _rgb_rst = _cap_rst.read()
                            _cap_rst.release()
                            if _ret_rst:
                                _rst_rgb_frame = _rgb_rst
                        except Exception:
                            pass

                        carry_mask = None
                        last_relabel_s = chunk_start_s
                        _in_recovery = True   # 进入 recovery 模式，下批立即检查
                        # ── 尝试用 IR 当前帧低温区定位食材，生成新前景点 ────────
                        # 原理：食材温度 < 锅壁温度，取锅内低温像素 → 反投影到 RGB
                        _ir_fg_pts = []
                        if (temp_data is not None and homography is not None
                                and _wok_mask_al is not None and _H_inv_al is not None
                                and _rng_al is not None):
                            try:
                                _ir_idx_rst = _get_ir_idx(chunk_start_abs)
                                _ir_frm_rst = temp_data[_ir_idx_rst]
                                _wok_t_rst  = _ir_frm_rst[_wok_mask_al]
                                if len(_wok_t_rst) >= 10:
                                    # ── K-means 双峰分类，取低温类最大连通域采点 ────
                                    # 代替 P35 固定阈值：K-means 自适应找食材/锅壁分界
                                    # 低温类最大连通域 = 锅内最大食材区域，排除边缘碎片
                                    _km_cl = float(np.percentile(_wok_t_rst, 10))
                                    _km_ch = float(np.percentile(_wok_t_rst, 90))
                                    for _ in range(20):
                                        _km_dl = np.abs(_wok_t_rst - _km_cl)
                                        _km_dh = np.abs(_wok_t_rst - _km_ch)
                                        _km_fl = _km_dl <= _km_dh
                                        _km_nl = float(np.mean(_wok_t_rst[_km_fl]))  if _km_fl.any()  else _km_cl
                                        _km_nh = float(np.mean(_wok_t_rst[~_km_fl])) if (~_km_fl).any() else _km_ch
                                        if abs(_km_nl - _km_cl) < 0.1 and abs(_km_nh - _km_ch) < 0.1:
                                            break
                                        _km_cl, _km_ch = _km_nl, _km_nh
                                    if (_km_ch - _km_cl) < 30.0:
                                        # 锅内温度均匀，无法区分食材和锅壁，跳过采点
                                        pass
                                    else:
                                        # 低温类像素（食材）在 IR 上构建 mask
                                        _km_food_ir = np.zeros_like(_wok_mask_al, dtype=np.uint8)
                                        _ys_wok, _xs_wok = np.where(_wok_mask_al)
                                        _km_dl2 = np.abs(_ir_frm_rst[_wok_mask_al] - _km_cl)
                                        _km_dh2 = np.abs(_ir_frm_rst[_wok_mask_al] - _km_ch)
                                        _km_food_flat = _km_dl2 <= _km_dh2
                                        _km_food_ir[_ys_wok[_km_food_flat], _xs_wok[_km_food_flat]] = 255
                                        # 取最大连通域（排除边缘碎片）
                                        _cc_n2, _cc_lbl2, _cc_st2, _ = cv2.connectedComponentsWithStats(
                                            _km_food_ir, connectivity=8)
                                        if _cc_n2 > 1:
                                            _max_cc = 1 + int(np.argmax(_cc_st2[1:, cv2.CC_STAT_AREA]))
                                            _km_food_ir = (_cc_lbl2 == _max_cc).astype(np.uint8) * 255
                                        _ys_ir, _xs_ir = np.where(_km_food_ir > 0)
                                        if len(_xs_ir) >= 6:
                                            _sel_ir = _rng_al.choice(len(_xs_ir),
                                                                      size=min(8, len(_xs_ir)),
                                                                      replace=False)
                                            _pts_ir_h = np.stack([
                                                _xs_ir[_sel_ir].astype(float),
                                                _ys_ir[_sel_ir].astype(float),
                                                np.ones(len(_sel_ir))
                                            ])  # (3, N)
                                            _pts_rgb_h = _H_inv_al @ _pts_ir_h
                                            _pts_rgb_h = _pts_rgb_h[:2] / _pts_rgb_h[2]
                                            for _xi, _yi in _pts_rgb_h.T:
                                                _xi, _yi = float(_xi), float(_yi)
                                                if _AXIS_CX_RGB is not None:
                                                    _d = ((_xi - _AXIS_CX_RGB)**2 + (_yi - _AXIS_CY_RGB)**2)**0.5
                                                    if _d < _AXIS_EXCL_R:
                                                        continue
                                                if 0 <= _xi < VW and 0 <= _yi < VH:
                                                    if _rgb_ref_gray is not None:
                                                        _bv = int(_rgb_ref_gray[int(_yi), int(_xi)])
                                                        if _bv < 40:
                                                            continue
                                                    _ir_fg_pts.append([_xi, _yi])
                                            if _ir_fg_pts:
                                                print(f"[补强] t={chunk_start_s:.1f}s  "
                                                      f"重置+IR定位新前景点({len(_ir_fg_pts)}个)"
                                                      f"  K-means低温中心={_km_cl:.1f}°C"
                                                      f"  高温中心={_km_ch:.1f}°C")
                            except Exception as _re:
                                print(f"[补强] IR定位失败({_re})，重置后用初始标注点")
                        if _ir_fg_pts:
                            # 旋转轴中心作为固定背景点
                            _axis_bg = []
                            if _AXIS_CX_RGB is not None:
                                _axis_bg = [[_AXIS_CX_RGB, _AXIS_CY_RGB]]
                            _reinforce_inject = {
                                "local_frame": 0,
                                "fg_points":   _ir_fg_pts,
                                "bg_points":   _axis_bg,
                                "label":       "IR-reset",
                            }

                        # ── 保存重置预览图（在 IR 采点完成后，能看到新前景点）──
                        try:
                            if _rst_rgb_frame is not None:
                                _vis_rst = _rst_rgb_frame.copy()
                                # 蓝色半透明显示跑偏的旧 mask（如果有）
                                if _rst_carry_mask is not None and _rst_carry_mask.any():
                                    _vis_rst[_rst_carry_mask] = (
                                        _vis_rst[_rst_carry_mask].astype(float) * 0.5
                                        + np.array([0, 0, 220]) * 0.5
                                    ).astype(np.uint8)
                                # 青色圆点显示 IR 新前景点
                                if _reinforce_inject is not None:
                                    for _p in _reinforce_inject["fg_points"]:
                                        cv2.circle(_vis_rst, (int(_p[0]), int(_p[1])), 10, (0, 255, 255), -1)
                                        cv2.circle(_vis_rst, (int(_p[0]), int(_p[1])), 11, (0, 0, 0), 1)
                                # 信息文字
                                n_new_pts = len(_reinforce_inject["fg_points"]) if _reinforce_inject else 0
                                cv2.putText(_vis_rst, _rst_reason,
                                            (20, 40), cv2.FONT_HERSHEY_SIMPLEX,
                                            1.0, (0, 0, 255), 2)
                                cv2.putText(_vis_rst,
                                            f"t={chunk_start_s:.0f}s  f={chunk_start_abs}"
                                            f"  [blue=old_mask | cyan=new_pts({n_new_pts})]",
                                            (20, 80), cv2.FONT_HERSHEY_SIMPLEX,
                                            0.75, (0, 255, 255), 2)
                                _rst_name = f"reset_t{chunk_start_s:.0f}s_f{chunk_start_abs}.jpg"
                                cv2.imwrite(os.path.join(out_dir, _rst_name), _vis_rst)
                                print(f"[重置] 预览图已保存: {_rst_name}  原因: {_rst_reason}"
                                      f"  新前景点: {n_new_pts}")
                        except Exception as _rpe:
                            print(f"[重置] 预览图保存失败: {_rpe}")

                    else:
                        # ── mask 正常：IR-IoU 检查（语义反转检测）──────────────
                        # 原理：SAM2 mask 与 IR 低温区（真实食材位置）的 IoU
                        # 如果重叠 < 15%，说明 SAM2 追踪到了错误区域（锅壁/旋转轴）
                        # 在这种情况下强制重置，比等待面积检查更快更准
                        _ir_iou_ok = True   # 默认通过（无 IR 数据时不触发）
                        if (temp_data is not None and homography is not None
                                and _wok_mask_al is not None and _H_inv_al is not None
                                and carry_mask is not None and carry_mask.any()):
                            try:
                                _ir_idx_iou = _get_ir_idx(chunk_start_abs)
                                _ir_frm_iou = temp_data[_ir_idx_iou]
                                _wok_t_iou  = _ir_frm_iou[_wok_mask_al]
                                if len(_wok_t_iou) >= 10:
                                    # 用 K-means 双峰分类代替固定 P40 阈值：
                                    # K-means 自适应找食材（低温类）和锅壁（高温类）的分界
                                    # 返回 NaN = 锅内温度均匀（锅直立/无热食材），跳过 IoU 检查
                                    _km_c_low  = float(np.percentile(_wok_t_iou, 10))
                                    _km_c_high = float(np.percentile(_wok_t_iou, 90))
                                    for _ in range(20):
                                        _km_d_low  = np.abs(_wok_t_iou - _km_c_low)
                                        _km_d_high = np.abs(_wok_t_iou - _km_c_high)
                                        _km_food   = _km_d_low <= _km_d_high
                                        _km_nl = float(np.mean(_wok_t_iou[_km_food]))  if _km_food.any()  else _km_c_low
                                        _km_nh = float(np.mean(_wok_t_iou[~_km_food])) if (~_km_food).any() else _km_c_high
                                        if abs(_km_nl - _km_c_low) < 0.1 and abs(_km_nh - _km_c_high) < 0.1:
                                            break
                                        _km_c_low, _km_c_high = _km_nl, _km_nh
                                    if (_km_c_high - _km_c_low) < 30.0:
                                        # 锅内温度均匀，无法区分食材和锅壁，跳过 IoU 检查
                                        _wok_t_iou = None   # 标记跳过
                                    else:
                                        # 用 K-means 低温类像素构建食材 mask
                                        _km_d_low2  = np.abs(_ir_frm_iou[_wok_mask_al] - _km_c_low)
                                        _km_d_high2 = np.abs(_ir_frm_iou[_wok_mask_al] - _km_c_high)
                                        _food_flat  = _km_d_low2 <= _km_d_high2
                                        _food_ir_iou = np.zeros(_ir_frm_iou.shape, dtype=bool)
                                        _food_ir_iou[_wok_mask_al] = _food_flat
                                    if _wok_t_iou is not None:
                                        # 把 IR 低温区反投影到 RGB 坐标系
                                        _ys_iou, _xs_iou = np.where(_food_ir_iou)
                                        if len(_xs_iou) >= 10:
                                            _pts_iou_h = np.stack([
                                                _xs_iou.astype(float),
                                                _ys_iou.astype(float),
                                                np.ones(len(_xs_iou))
                                            ])
                                            _pts_rgb_iou = _H_inv_al @ _pts_iou_h
                                            _pts_rgb_iou = _pts_rgb_iou[:2] / _pts_rgb_iou[2]
                                            # 构建 IR 食材区域 RGB mask
                                            _ir_food_rgb = np.zeros((VH, VW), dtype=bool)
                                            _xi_iou = np.clip(np.round(_pts_rgb_iou[0]).astype(int), 0, VW-1)
                                            _yi_iou = np.clip(np.round(_pts_rgb_iou[1]).astype(int), 0, VH-1)
                                            _ir_food_rgb[_yi_iou, _xi_iou] = True
                                            # 膨胀一下，容忍标定误差（~15px）
                                            _ir_food_rgb_u8 = _ir_food_rgb.astype(np.uint8) * 255
                                            _kd = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31))
                                            _ir_food_rgb_u8 = cv2.dilate(_ir_food_rgb_u8, _kd)
                                            _ir_food_rgb = _ir_food_rgb_u8 > 0
                                            # 计算 IoU：carry_mask 与 IR 低温区的重叠
                                            _inter = int((carry_mask & _ir_food_rgb).sum())
                                            _union = int((carry_mask | _ir_food_rgb).sum())
                                            _iou = _inter / max(_union, 1) * 100
                                            if _iou < 15.0:
                                                _ir_iou_ok = False
                                                print(f"[IR-IoU] t={chunk_start_s:.1f}s  "
                                                      f"IoU={_iou:.1f}%<8%，SAM2 mask 与食材区域严重不符，"
                                                      f"强制重置")
                            except Exception as _iou_e:
                                pass   # IoU 检查失败不影响主流程

                        if not _ir_iou_ok:
                            # 强制重置（复用 _need_reset 路径的逻辑）
                            _rst_reason = f"RESET: IR-IoU语义反转"
                            _rst_carry_mask = carry_mask
                            _rst_rgb_frame  = None
                            try:
                                _cap_iou_rst = cv2.VideoCapture(video_path)
                                _cap_iou_rst.set(cv2.CAP_PROP_POS_FRAMES, chunk_start_abs)
                                _ret_iou_rst, _rgb_iou_rst = _cap_iou_rst.read()
                                _cap_iou_rst.release()
                                if _ret_iou_rst:
                                    _rst_rgb_frame = _rgb_iou_rst
                            except Exception:
                                pass
                            carry_mask = None
                            last_relabel_s = chunk_start_s
                            _in_recovery = True
                            _reinforce_inject = None
                            # 尝试 IR 采点
                            _ir_fg_pts_iou = []
                            if (temp_data is not None and homography is not None
                                    and _wok_mask_al is not None and _H_inv_al is not None
                                    and _rng_al is not None):
                                try:
                                    _ir_idx_r2 = _get_ir_idx(chunk_start_abs)
                                    _ir_frm_r2 = temp_data[_ir_idx_r2]
                                    _wok_t_r2  = _ir_frm_r2[_wok_mask_al]
                                    if len(_wok_t_r2) >= 10:
                                        _t_r2 = float(np.percentile(_wok_t_r2, 35))
                                        _food_r2 = (_ir_frm_r2 < _t_r2) & _wok_mask_al
                                        _ys_r2, _xs_r2 = np.where(_food_r2)
                                        if len(_xs_r2) >= 6:
                                            _sel_r2 = _rng_al.choice(len(_xs_r2), size=min(8, len(_xs_r2)), replace=False)
                                            _pts_r2_h = np.stack([_xs_r2[_sel_r2].astype(float),
                                                                   _ys_r2[_sel_r2].astype(float),
                                                                   np.ones(len(_sel_r2))])
                                            _pts_rgb_r2 = _H_inv_al @ _pts_r2_h
                                            _pts_rgb_r2 = _pts_rgb_r2[:2] / _pts_rgb_r2[2]
                                            for _xi2, _yi2 in _pts_rgb_r2.T:
                                                _xi2, _yi2 = float(_xi2), float(_yi2)
                                                if _AXIS_CX_RGB is not None:
                                                    if ((_xi2-_AXIS_CX_RGB)**2+(_yi2-_AXIS_CY_RGB)**2)**0.5 < _AXIS_EXCL_R:
                                                        continue
                                                if 0 <= _xi2 < VW and 0 <= _yi2 < VH:
                                                    if _rgb_ref_gray is not None and int(_rgb_ref_gray[int(_yi2), int(_xi2)]) < 40:
                                                        continue
                                                    _ir_fg_pts_iou.append([_xi2, _yi2])
                                except Exception:
                                    pass
                            if _ir_fg_pts_iou:
                                _axis_bg_iou = [[_AXIS_CX_RGB, _AXIS_CY_RGB]] if _AXIS_CX_RGB is not None else []
                                _reinforce_inject = {"local_frame": 0, "fg_points": _ir_fg_pts_iou, "bg_points": _axis_bg_iou, "label": "IR-IoU-reset"}
                            # 保存预览图
                            try:
                                if _rst_rgb_frame is not None:
                                    _vis_iou = _rst_rgb_frame.copy()
                                    if _rst_carry_mask is not None and _rst_carry_mask.any():
                                        _vis_iou[_rst_carry_mask] = (_vis_iou[_rst_carry_mask].astype(float) * 0.5 + np.array([0, 0, 220]) * 0.5).astype(np.uint8)
                                    if _reinforce_inject:
                                        for _p in _reinforce_inject["fg_points"]:
                                            cv2.circle(_vis_iou, (int(_p[0]), int(_p[1])), 10, (0, 255, 255), -1)
                                    cv2.putText(_vis_iou, _rst_reason, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
                                    cv2.putText(_vis_iou, f"t={chunk_start_s:.0f}s  [blue=bad_mask | cyan=new_pts]",
                                                (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 255), 2)
                                    _iou_rst_name = f"reset_t{chunk_start_s:.0f}s_f{chunk_start_abs}_iou.jpg"
                                    cv2.imwrite(os.path.join(out_dir, _iou_rst_name), _vis_iou)
                                    print(f"[IR-IoU] 预览图已保存: {_iou_rst_name}")
                            except Exception:
                                pass
                        else:
                            # ── mask 正常且 IoU 通过：SAM2 自主追踪，不注入 IR 采点 ──
                            # IR 只做门控（IoU 检查），通过后让 SAM2 完全靠视觉语义自由追踪
                            # 仅在 SAM2 跑偏（IoU<15%）或面积异常时才强制重置
                            last_relabel_s = chunk_start_s
                            last_reinforce_wok_pct = _mask_vs_wok
                            _in_recovery = False
                            print(f"[补强] t={chunk_start_s:.1f}s  mask正常({_mask_vs_wok:.0f}%)"
                                  f"  SAM2自主追踪(IoU通过，无IR注入)")
                        # 正常路径（IoU通过，SAM2自主追踪）不保存预览图
                        # 预览图只在重置/IoU失败等异常场景下保存，降低输出噪声

            # ── B-check 早检：本批开始前验证上批 carry_mask 可靠性 ──────────────
            # 坏的 carry_mask 若直接喂给 SAM2 会进入死循环，提前拦截
            if carry_mask is not None and _wok_rgb_constraint is not None:
                _cm_u8_pre = carry_mask.astype(np.uint8) * 255
                _cc_n_pre, _cc_lbl_pre, _cc_st_pre, _ = cv2.connectedComponentsWithStats(
                    _cm_u8_pre, connectivity=8)
                _fg_pre = _cc_st_pre[1:]
                _wok_px_pre = int(_wok_rgb_constraint.sum())
                if len(_fg_pre) > 0:
                    _max_cc_pre  = int(_fg_pre[:, cv2.CC_STAT_AREA].max())
                    _max_pct_pre = _max_cc_pre / max(_wok_px_pre, 1) * 100
                    _thr_pre     = 30.0 if _wok_tilting else 50.0
                    _min_px_pre  = max(100, int(_wok_px_pre * 0.005))
                    _valid_pre   = int((_fg_pre[:, cv2.CC_STAT_AREA] >= _min_px_pre).sum())
                    _discard_pre = (_max_pct_pre > _thr_pre) or (_valid_pre > 5)
                    if _discard_pre:
                        _reason_pre = (f"最大连通域={_max_pct_pre:.1f}%>{_thr_pre:.0f}%"
                                       if _max_pct_pre > _thr_pre
                                       else f"有效连通域={_valid_pre}>5（碎片化）")
                        _max_idx_pre = int(_fg_pre[:, cv2.CC_STAT_AREA].argmax()) + 1
                        _cm_cand     = (_cc_lbl_pre == _max_idx_pre)
                        _cand_pct    = _cm_cand.sum() / max(_wok_px_pre, 1) * 100
                        if _cand_pct > 25.0:
                            carry_mask = None
                            last_relabel_s = -999   # 强制本批重标点
                            print(f"[B-check早检] 批次{chunk_i+1} {_reason_pre}，"
                                  f"最大连通域仍={_cand_pct:.1f}%>25%，discard+强制重标")
                        else:
                            carry_mask = _cm_cand
                            print(f"[B-check早检] 批次{chunk_i+1} {_reason_pre}，"
                                  f"保留最大单连通域({_cand_pct:.1f}%)")

            # ── 倾斜冻结：K-means 双峰差 < 30°C → 跳过本批 SAM2 ──────────────
            # 锅倾斜/翻炒时锅内无食材信号，强制追踪只会追到锅壁
            _skip_sam2_tilt = False
            if temp_data is not None and _wok_mask_al is not None:
                try:
                    _ir_idx_tilt = _get_ir_idx(chunk_start_abs)
                    _ir_frm_tilt = temp_data[_ir_idx_tilt]
                    _wok_t_tilt  = _ir_frm_tilt[_wok_mask_al]
                    if len(_wok_t_tilt) >= 10:
                        _tilt_cl = float(np.percentile(_wok_t_tilt, 10))
                        _tilt_ch = float(np.percentile(_wok_t_tilt, 90))
                        for _ in range(20):
                            _tfl = (np.abs(_wok_t_tilt - _tilt_cl)
                                    <= np.abs(_wok_t_tilt - _tilt_ch))
                            _nl = float(np.mean(_wok_t_tilt[_tfl]))  if _tfl.any()  else _tilt_cl
                            _nh = float(np.mean(_wok_t_tilt[~_tfl])) if (~_tfl).any() else _tilt_ch
                            if abs(_nl - _tilt_cl) < 0.1 and abs(_nh - _tilt_ch) < 0.1:
                                break
                            _tilt_cl, _tilt_ch = _nl, _nh
                        if (_tilt_ch - _tilt_cl) < 40.0:
                            _skip_sam2_tilt = True
                            print(f"[倾斜冻结] t={chunk_start_s:.1f}s  "
                                  f"K-means gap={_tilt_ch-_tilt_cl:.1f}°C<40°C，"
                                  f"锅内无食材信号，跳过SAM2本批")
                except Exception:
                    pass

            tmp_dir, frame_names, actual = extract_chunk_to_dir(
                video_path, chunk_start_abs, chunk_end_abs,
                infer_size=SAM2_INFER_SIZE
            )
            print(f"[抽帧] 临时目录: {tmp_dir}  实际帧数: {actual}")

            if actual == 0:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                break

            try:
                inject_this_chunk = []
                # 注入 food_labels.json 里的额外关键帧
                for abs_f, kf in inject_map.items():
                    if chunk_start_abs <= abs_f < chunk_end_abs:
                        local_f = abs_f - chunk_start_abs
                        inject_this_chunk.append({
                            "local_frame": local_f,
                            "fg_points":   kf["fg_points"],
                            "bg_points":   kf.get("bg_points", []),
                            "label":       kf.get("label", ""),
                        })
                # 注入补强点（local_frame=0，和 carry_mask 同帧，追加前景点）
                if _reinforce_inject is not None:
                    inject_this_chunk.append(_reinforce_inject)
                # 注入 IR-fix接管 生成的精细化前景点（让SAM2精细化IR粗mask边界）
                if _next_inject is not None:
                    inject_this_chunk.append(_next_inject)
                    print(f"[IR-fix精细化] 批次{chunk_i+1} 注入上批IR前景点 "
                          f"{len(_next_inject['fg_points'])} 个，SAM2将精细化边界")
                    _next_inject = None   # 消费后清除，避免重复注入

                # carry_mask 需要缩放到推理分辨率传给下一批
                carry_mask_infer = None
                if carry_mask is not None and do_resize:
                    carry_mask_infer = upscale_mask(carry_mask, infer_wh) \
                        if carry_mask.shape != (infer_wh[1], infer_wh[0]) else carry_mask
                else:
                    carry_mask_infer = carry_mask

                if _skip_sam2_tilt:
                    # 倾斜冻结：SAM2 跳过，本批所有帧输出空 mask（锅直立期无食材）
                    # 清零 carry_mask，避免漂移碎片遗留在锅外侧
                    _empty_tilt = np.zeros((infer_wh[1], infer_wh[0]), dtype=bool)
                    chunk_masks = {_fi: _empty_tilt for _fi in range(actual)}
                    carry_mask_raw = None   # 清零，下批重新采点
                    print(f"[倾斜冻结] 批次{chunk_i+1} SAM2已跳过，carry_mask清零（锅直立期无食材）")
                else:
                    chunk_masks, carry_mask_raw = track_chunk(
                        predictor, tmp_dir, frame_names,
                        fg_infer, bg_infer,
                        carry_mask=carry_mask_infer,
                        inject_keyframes=inject_this_chunk,
                    )
                # carry_mask 放大回原始分辨率，供下批 add_new_mask 使用
                if do_resize and carry_mask_raw is not None:
                    carry_mask = upscale_mask(carry_mask_raw, orig_wh)
                else:
                    carry_mask = carry_mask_raw
                # ── 对 carry_mask 也做 wok 约束，防止面积检查出现 >100% ──────
                if carry_mask is not None and _wok_rgb_constraint is not None:
                    carry_mask = carry_mask & _wok_rgb_constraint

                # ── B：carry_mask 连通域可靠性检查 ────────────────────────────
                # 检查两个指标，任一不满足则标记 carry_mask 为不可信（置 None）：
                #   1. 最大连通域面积 / wok 区域面积 > 25%（接近整锅）
                #   2. 有效连通域数量 > 5 个（碎片化，SAM2 追踪失控）
                if carry_mask is not None and _wok_rgb_constraint is not None:
                    _cm_u8_b = carry_mask.astype(np.uint8) * 255
                    _cc_n, _cc_labels, _cc_stats, _ = cv2.connectedComponentsWithStats(
                        _cm_u8_b, connectivity=8
                    )
                    # _cc_stats[0] = 背景，跳过；从 1 开始是前景连通域
                    _fg_components = _cc_stats[1:]   # 去掉背景
                    _wok_px_b = int(_wok_rgb_constraint.sum())
                    _carry_unreliable = False
                    if len(_fg_components) > 0:
                        _max_cc_area = int(_fg_components[:, cv2.CC_STAT_AREA].max())
                        _max_cc_pct  = _max_cc_area / max(_wok_px_b, 1) * 100
                        # 过滤掉面积 < 0.5% wok 的碎片，只数"有效"连通域
                        _min_cc_px   = max(100, int(_wok_px_b * 0.005))
                        _valid_cc    = int((_fg_components[:, cv2.CC_STAT_AREA] >= _min_cc_px).sum())
                        # 倾斜期间锅内食材快速位移，提前检测语义反转（30% < 50%）
                        _bcheck_thr = 30.0 if _wok_tilting else 50.0
                        if _max_cc_pct > _bcheck_thr:
                            _carry_unreliable = True
                            print(f"[B-check] 批次{chunk_i+1}末 carry_mask 最大连通域"
                                  f"={_max_cc_pct:.1f}%>{'30(倾斜)' if _wok_tilting else '50'}%"
                                  f"（接近整锅），标记不可信")
                        elif _valid_cc > 5:
                            _carry_unreliable = True
                            print(f"[B-check] 批次{chunk_i+1}末 carry_mask 有效连通域"
                                  f"={_valid_cc}>5（碎片化），标记不可信")
                    if _carry_unreliable:
                        # 不直接 None，而是缩小为仅保留最大连通域（减少硬重置次数）
                        if len(_fg_components) > 0:
                            _max_cc_idx = int(_fg_components[:, cv2.CC_STAT_AREA].argmax()) + 1
                            carry_mask = (_cc_labels == _max_cc_idx)
                            _new_pct = carry_mask.sum() / max(_wok_px_b, 1) * 100
                            if _new_pct > 25.0:
                                # 最大单连通域还是过大，才真正 discard
                                carry_mask = None
                                print(f"[B-check] 最大单连通域仍={_new_pct:.1f}%>25%，"
                                      f"discard carry_mask")
                            else:
                                print(f"[B-check] 保留最大单连通域({_new_pct:.1f}%)，"
                                      f"丢弃其余碎片")

                print(f"[SAM2] 批次 {chunk_i+1} 追踪完成，{len(chunk_masks)} 帧")

                # ── 锅底第二次 SAM2 追踪（反向语义）────────────────────────────
                bottom_chunk_masks = {}
                if has_bottom and chunk_start_abs >= bottom_start_frame:
                    try:
                        # 锅底注入关键帧（_bottom_inject_map）
                        _bottom_inject = []
                        for _abs_bf, _bkf in _bottom_inject_map.items():
                            if chunk_start_abs <= _abs_bf < chunk_end_abs:
                                _bottom_inject.append({
                                    "local_frame": _abs_bf - chunk_start_abs,
                                    "fg_points":   _bkf["fg_points"],
                                    "bg_points":   _bkf.get("bg_points", []),
                                    "label":       _bkf.get("label", ""),
                                })
                        _bottom_fg_run = bottom_fg_points
                        _bottom_bg_run = bottom_bg_points
                        if (False and temp_data is not None and homography is not None
                                and wok_mask_ir is not None
                                and _wok_rgb_constraint is not None):
                            try:
                                _rgb_b0 = cv2.imread(os.path.join(tmp_dir, frame_names[0]))
                                _ir_b0 = temp_data[_get_ir_idx(chunk_start_abs)]
                                _H_inv_bottom = (_H_inv_al if _H_inv_al is not None
                                                 else np.linalg.inv(homography))
                                _prev_btm = os.path.join(
                                    out_dir,
                                    f"inverse_autopoints_t{chunk_start_s:.0f}s_f{chunk_start_abs}.jpg"
                                )
                                _auto_fg_b, _auto_bg_b, _auto_ok_b = generate_inverse_bottom_points_from_ir(
                                    _rgb_b0, _ir_b0, wok_mask_ir, _H_inv_bottom,
                                    _wok_rgb_constraint, rng=_rng_al, preview_path=_prev_btm
                                )
                                if _auto_ok_b:
                                    _bottom_fg_run = _auto_fg_b
                                    _bottom_bg_run = _auto_bg_b
                                    print(f"[Inv自动补点] 批次{chunk_i+1} "
                                          f"FG-hot={len(_auto_fg_b)} BG-food={len(_auto_bg_b)} "
                                          f"preview={os.path.basename(_prev_btm)}")
                            except Exception as _bae:
                                print(f"[Inv自动补点] 批次{chunk_i+1} 失败: {_bae}")
                        if _bottom_auto_reset is not None:
                            _bottom_fg_run = _bottom_auto_reset["fg_points"]
                            _bottom_bg_run = _bottom_auto_reset["bg_points"]
                            _bc_infer = None
                            print(f"[Inv自动重启] 批次{chunk_i+1} 使用跟丢时IR自动点 "
                                  f"FG={len(_bottom_fg_run)} BG={len(_bottom_bg_run)} "
                                  f"src_frame={_bottom_auto_reset.get('frame')}")
                            _bottom_auto_reset = None
                        elif _bottom_carry is not None and do_resize:
                            _bc_infer = upscale_mask(_bottom_carry, infer_wh)
                        else:
                            _bc_infer = _bottom_carry
                        bottom_chunk_masks, _bottom_carry_raw = track_chunk(
                            predictor, tmp_dir, frame_names,
                            _bottom_fg_run, _bottom_bg_run,
                            carry_mask=_bc_infer,
                            inject_keyframes=_bottom_inject,
                        )
                        _bottom_carry = upscale_mask(_bottom_carry_raw, orig_wh) \
                            if (do_resize and _bottom_carry_raw is not None) \
                            else _bottom_carry_raw
                        print(f"[锅底SAM2] 批次 {chunk_i+1} 锅底追踪完成，"
                              f"{len(bottom_chunk_masks)} 帧")
                    except Exception as _be:
                        print(f"[锅底SAM2] 批次 {chunk_i+1} 追踪失败: {_be}")

                # ── mask 面积异常检测：若本批平均占比 > 60% 且比上批大 3 倍 → 强制下批重标点 ──
                if len(chunk_masks) > 0:
                    _total_px = infer_wh[0] * infer_wh[1] if do_resize else VW * VH
                    _ratios   = [m.sum() / _total_px * 100
                                 for m in chunk_masks.values() if m is not None]
                    _mean_ratio = float(np.mean(_ratios)) if _ratios else 0.0
                    if (_auto_label_func is not None
                            and _mean_ratio > 60.0
                            and _mean_ratio > prev_mask_ratio * 3.0
                            and prev_mask_ratio > 0.5):
                        carry_mask = None
                        last_relabel_s = -999   # 强制下批立即重标点
                        print(f"[异常检测] 批次{chunk_i+1} 平均mask={_mean_ratio:.1f}%"
                              f"（上批{prev_mask_ratio:.1f}%），追踪失控！强制下批重标点")
                    prev_mask_ratio = _mean_ratio
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                print(f"[清理] 临时帧已删除")

            cap = cv2.VideoCapture(video_path)
            cap.set(cv2.CAP_PROP_POS_FRAMES, chunk_start_abs)

            # ── IR-fix 批次统计：命中率 > 50% 时覆盖 carry_mask ────────────
            _irfix_count     = 0    # 本批被 IR-fix 成功修正的帧数
            _irfix_last_mask = None # 最后一次 IR-fix 成功的 mask

            for local_in_chunk in range(actual):
                ret, frame = cap.read()
                if not ret:
                    break

                abs_idx   = chunk_start_abs + local_in_chunk
                local_idx = global_local + local_in_chunk
                # SAM2 返回的是推理分辨率的 mask，放大回原始分辨率
                raw_mask  = chunk_masks.get(local_in_chunk,
                                            np.zeros((infer_wh[1], infer_wh[0]), dtype=bool))
                mask      = upscale_mask(raw_mask, orig_wh) if do_resize else raw_mask
                mask_src  = "SAM2"

                # ── wok 约束后处理：mask AND 预计算的锅内区域 ────────────────
                if _wok_rgb_constraint is not None:
                    mask = mask & _wok_rgb_constraint

                # ── 逐帧实时 IR 校正：mask 超过 wok 30% 时立即用 IR 重生成 ──
                # 手进入、语义反转等情况下 SAM2 mask 瞬间暴涨，
                # 不等批次结束，每帧即时用 IR K-means 重新圈选食材
                _frame_corrected = False
                if (_wok_rgb_constraint is not None
                        and temp_data is not None
                        and _wok_mask_al is not None
                        and _H_inv_al is not None):
                    _wok_px_fr = int(_wok_rgb_constraint.sum())
                    _mask_px_fr = int(mask.sum())
                    _ratio_fr = _mask_px_fr / max(_wok_px_fr, 1) * 100
                    if _ratio_fr > 50.0:
                        print(f"[IR-fix触发] t={abs_idx/fps:.1f}s  mask={_ratio_fr:.1f}%>50%，尝试IR校正")
                        try:
                            _ir_idx_fr = _get_ir_idx(abs_idx)
                            _ir_frm_fr = temp_data[_ir_idx_fr]
                            _food_ir = _build_ir_food_mask_by_temperature(
                                _ir_frm_fr, _wok_mask_al, min_cluster_gap=30.0)
                            if _food_ir is not None:
                                    _ys_f, _xs_f = np.where(_food_ir > 0)
                                    if len(_xs_f) >= 6:
                                        _pts_h = np.stack([_xs_f.astype(float),
                                                           _ys_f.astype(float),
                                                           np.ones(len(_xs_f))])
                                        _pts_rgb = _H_inv_al @ _pts_h
                                        _pts_rgb = _pts_rgb[:2] / _pts_rgb[2]
                                        _new_mask = np.zeros((VH, VW), dtype=bool)
                                        _xi_f = np.clip(np.round(_pts_rgb[0]).astype(int),0,VW-1)
                                        _yi_f = np.clip(np.round(_pts_rgb[1]).astype(int),0,VH-1)
                                        _new_mask[_yi_f, _xi_f] = True
                                        # 开运算：先膨胀11px填补投影离散孔洞，再腐蚀17px收缩边界
                                        # 净效果：边界向内收约3px，防止IR投影偏大
                                        _nm_u8 = _new_mask.astype(np.uint8) * 255
                                        _km_d = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
                                        _km_e = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (17, 17))
                                        _nm_u8 = cv2.dilate(_nm_u8, _km_d)
                                        _nm_u8 = cv2.erode(_nm_u8, _km_e)
                                        # 取最大连通域（去掉外圈碎片/锅壁误分区域）
                                        _cc_n_fr, _cc_lbl_fr, _cc_st_fr, _ = cv2.connectedComponentsWithStats(
                                            _nm_u8, connectivity=8)
                                        if _cc_n_fr > 1:
                                            _max_cc_fr = 1 + int(np.argmax(_cc_st_fr[1:, cv2.CC_STAT_AREA]))
                                            _nm_u8 = (_cc_lbl_fr == _max_cc_fr).astype(np.uint8) * 255
                                        _new_mask = (_nm_u8 > 0) & _wok_rgb_constraint
                                        _new_ratio = _new_mask.sum() / max(_wok_px_fr, 1) * 100
                                        if _new_ratio <= 50.0:
                                            mask = _new_mask
                                            mask_src = "IR-fix"
                                            _frame_corrected = True
                                            _irfix_count += 1
                                            _irfix_last_mask = _new_mask
                                            print(f"[IR-fix成功] t={abs_idx/fps:.1f}s  新mask={_new_ratio:.1f}%")
                                        else:
                                            print(f"[IR-fix拒绝] 新mask={_new_ratio:.1f}%>50%，保留原mask")
                        except Exception as _irfix_e:
                            print(f"[IR-fix异常] {_irfix_e}")

                vis       = render_overlay(frame, mask, MASK_COLOR, MASK_ALPHA)
                temp_mean, temp_min, temp_max = _measure_rgb_mask_temperature(
                    mask, temp_data, homography, _get_ir_idx(abs_idx))

                time_s     = abs_idx / fps
                mask_ratio = mask.sum() / mask.size * 100
                if not np.isnan(temp_mean):
                    temp_history.append((time_s, temp_mean))

                # ── ROI 温度统计 ──────────────────────────────────────────────
                roi_temp_mean = float("nan")
                if roi_cfg is not None and temp_data is not None and homography is not None:
                    try:
                        ir_h, ir_w = temp_data.shape[1], temp_data.shape[2]
                        ir_idx_roi = _get_ir_idx(abs_idx)
                        if ir_idx_roi < temp_data.shape[0]:
                            # RGB 圆心 → IR 坐标
                            rgb_pt = np.array([[[float(roi_cfg["rgb_cx"]),
                                                 float(roi_cfg["rgb_cy"])]]], dtype=np.float32)
                            ir_pt  = cv2.perspectiveTransform(rgb_pt, homography)[0][0]
                            ir_cx_roi = int(round(ir_pt[0]))
                            ir_cy_roi = int(round(ir_pt[1]))
                            # RGB 半径 → IR 半径（按 IR/RGB 宽度比缩放）
                            ir_r = max(1, int(roi_cfg["rgb_radius"] * ir_w / roi_cfg["rgb_w"]))
                            # 生成圆形 mask
                            roi_mask_ir = np.zeros((ir_h, ir_w), dtype=np.uint8)
                            cv2.circle(roi_mask_ir, (ir_cx_roi, ir_cy_roi), ir_r, 255, -1)
                            roi_temps = temp_data[ir_idx_roi][roi_mask_ir > 0]
                            if len(roi_temps) > 0:
                                roi_temp_mean = float(np.mean(roi_temps))
                    except Exception:
                        pass
                if not np.isnan(roi_temp_mean):
                    roi_history.append((time_s, roi_temp_mean))

                # 在 RGB 帧上叠加 ROI 圆形
                if roi_cfg is not None:
                    cv2.circle(vis, (roi_cfg["rgb_cx"], roi_cfg["rgb_cy"]),
                               roi_cfg["rgb_radius"], (255, 200, 0), 2)
                    if not np.isnan(roi_temp_mean):
                        cv2.putText(vis, f"ROI:{roi_temp_mean:.1f}C",
                                    (roi_cfg["rgb_cx"] - 40,
                                     roi_cfg["rgb_cy"] - roi_cfg["rgb_radius"] - 8),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 200, 0), 1)

                info_bar = np.zeros((INFO_H, VW, 3), dtype=np.uint8)
                cv2.putText(info_bar,
                            f"Frame {abs_idx}  t={time_s:.1f}s  Mask={mask_ratio:.1f}%  [SAM2]",
                            (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)

                # ── IR mask 自动分割温度（K-means 双峰分类）──────────────────
                # 锅内温度分布是双峰：高温峰=锅壁/锅底，低温峰=食物
                # K-means 自适应分类，比固定百分位更准确
                ir_mask_temp = float("nan")
                if wok_mask_ir is not None and temp_data is not None:
                    ir_idx_wok = _get_ir_idx(abs_idx)
                    ir_mask_temp = _estimate_ir_wok_food_temp(
                        temp_data, ir_idx_wok, wok_mask_ir)
                if not np.isnan(ir_mask_temp):
                    ir_mask_history.append((time_s, ir_mask_temp))

                # ── info_bar 第二行：三个温度值 ───────────────────────────────
                parts = []
                if not np.isnan(temp_mean):
                    parts.append(f"SAM2:{temp_mean:.1f}C(min{temp_min:.0f}/max{temp_max:.0f})")
                else:
                    parts.append("SAM2:N/A")
                if not np.isnan(roi_temp_mean):
                    parts.append(f"ROI:{roi_temp_mean:.1f}C")
                # ── 锅底反向语义温度统计（先算，后写入 info_bar）─────────────
                # ── 锅底反向语义温度统计 ──────────────────────────────────────
                # inverse_mask = wok_rgb_ellipse(动态) & ~bottom_sam2_mask
                # 即：锅内除锅底以外的区域 = 食材区域（另一种语义）
                inverse_temp_mean = float("nan")
                if has_bottom and bottom_chunk_masks:
                    try:
                        _bm_raw = bottom_chunk_masks.get(local_in_chunk)
                        if _bm_raw is not None:
                            _bm_full = upscale_mask(_bm_raw, orig_wh) if do_resize else _bm_raw
                            # 构建动态锅椭圆 mask（用更新后的中心）
                            if _wok_rgb_constraint is not None:
                                _dyn_wok_bool = _wok_rgb_constraint
                            elif wok_rgb_mask_static is not None:
                                # 用动态中心重建椭圆
                                _dyn_wok_mask = np.zeros((VH, VW), dtype=np.uint8)
                                cv2.ellipse(_dyn_wok_mask,
                                            (int(round(_wok_rgb_cx_dyn)),
                                             int(round(_wok_rgb_cy_dyn))),
                                            (int(round(wok_rgb_rx)),
                                             int(round(wok_rgb_ry))),
                                            0, 0, 360, 255, -1)
                                _dyn_wok_bool = _dyn_wok_mask > 0
                            else:
                                # fallback：用 IR 反投影的锅约束
                                _dyn_wok_bool = np.ones((VH, VW), dtype=bool)
                            # inverse_mask = 锅内区域 AND NOT 锅底
                            _raw_inv_mask = _dyn_wok_bool & ~_bm_full
                            _wok_px_inv = int(_dyn_wok_bool.sum())
                            _raw_inv_ratio = int(_raw_inv_mask.sum()) / max(_wok_px_inv, 1) * 100
                            _inv_mask_override = None
                            _inv_too_large = (_raw_inv_ratio > 50.0)
                            _inv_too_small = (_raw_inv_ratio < 10.0)
                            if _inv_too_large or _inv_too_small:
                                _bottom_fail_streak += 1
                                if (_bottom_auto_reset is None and temp_data is not None
                                        and homography is not None and wok_mask_ir is not None
                                        and _wok_rgb_constraint is not None):
                                    try:
                                        _H_inv_bottom = (_H_inv_al if _H_inv_al is not None
                                                         else np.linalg.inv(homography))
                                        _prev_btm = os.path.join(
                                            out_dir,
                                            f"inverse_autopoints_t{time_s:.1f}s_f{abs_idx}.jpg"
                                        )
                                        _auto_fg_b, _auto_bg_b, _auto_ok_b = generate_inverse_bottom_points_from_ir(
                                            frame, temp_data[_get_ir_idx(abs_idx)],
                                            wok_mask_ir, _H_inv_bottom, _wok_rgb_constraint,
                                            rng=_rng_al, preview_path=_prev_btm
                                        )
                                        if _auto_ok_b:
                                            _bottom_auto_reset = {
                                                "frame": abs_idx,
                                                "fg_points": _auto_fg_b,
                                                "bg_points": _auto_bg_b,
                                            }
                                            _bottom_carry = None
                                            _inv_fail_reason = (
                                                f"inv_ratio<{10.0:.0f}%"
                                                if _inv_too_small else
                                                f"inv_ratio>{50.0:.0f}%"
                                            )
                                            print(f"[Inv跟丢补点] frame={abs_idx} "
                                                  f"{_inv_fail_reason}  "
                                                  f"FG-hot={len(_auto_fg_b)} BG-food={len(_auto_bg_b)} "
                                                  f"preview={os.path.basename(_prev_btm)}")
                                    except Exception as _bae:
                                        print(f"[Inv跟丢补点] frame={abs_idx} 失败: {_bae}")
                                if (False and temp_data is not None and homography is not None
                                        and wok_mask_ir is not None):
                                    try:
                                        _ir_idx_fb = _get_ir_idx(abs_idx)
                                        _ir_frm_fb = temp_data[_ir_idx_fb]
                                        _wok_t_fb = _ir_frm_fb[wok_mask_ir]
                                        if len(_wok_t_fb) >= 10:
                                            _c_low = float(np.percentile(_wok_t_fb, 10))
                                            _c_high = float(np.percentile(_wok_t_fb, 90))
                                            for _ in range(20):
                                                _dl = np.abs(_wok_t_fb - _c_low)
                                                _dh = np.abs(_wok_t_fb - _c_high)
                                                _low_sel = _dl <= _dh
                                                _nl = float(np.mean(_wok_t_fb[_low_sel])) if _low_sel.any() else _c_low
                                                _nh = float(np.mean(_wok_t_fb[~_low_sel])) if (~_low_sel).any() else _c_high
                                                if abs(_nl - _c_low) < 0.1 and abs(_nh - _c_high) < 0.1:
                                                    break
                                                _c_low, _c_high = _nl, _nh
                                            if (_c_high - _c_low) >= 25.0:
                                                _food_ir = np.zeros_like(wok_mask_ir, dtype=np.uint8)
                                                _ys_w, _xs_w = np.where(wok_mask_ir)
                                                _dl2 = np.abs(_ir_frm_fb[wok_mask_ir] - _c_low)
                                                _dh2 = np.abs(_ir_frm_fb[wok_mask_ir] - _c_high)
                                                _food_ir[_ys_w[_dl2 <= _dh2], _xs_w[_dl2 <= _dh2]] = 255
                                                _k_fb = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
                                                _food_ir = cv2.morphologyEx(_food_ir, cv2.MORPH_OPEN, _k_fb)
                                                _food_ir = cv2.morphologyEx(_food_ir, cv2.MORPH_CLOSE, _k_fb)
                                                _food_rgb = cv2.warpPerspective(
                                                    _food_ir,
                                                    np.linalg.inv(homography),
                                                    (VW, VH)
                                                ) > 64
                                                _food_rgb = _food_rgb & _dyn_wok_bool
                                                _fb_ratio = int(_food_rgb.sum()) / max(_wok_px_inv, 1) * 100
                                                if 1.0 <= _fb_ratio <= 60.0:
                                                    _inv_mask_override = _food_rgb
                                                    _bm_full = _dyn_wok_bool & ~_food_rgb
                                                    if not do_resize:
                                                        bottom_chunk_masks[local_in_chunk] = _bm_full
                                                    print(f"[Inv-IR兜底] frame={abs_idx} "
                                                          f"IR食材={_fb_ratio:.1f}% "
                                                          f"K=({_c_low:.1f},{_c_high:.1f})")
                                    except Exception:
                                        pass
                                if not do_resize:
                                    pass
                                if _bottom_fail_streak in (1, 10) or _bottom_fail_streak % 25 == 0:
                                    _inv_fail_desc = (
                                        "bottom_mask过大/紫色过小"
                                        if _inv_too_small else
                                        "bottom_mask疑似丢失"
                                    )
                                    print(f"[Inv兜底] frame={abs_idx}  {_inv_fail_desc} "
                                          f"inv_ratio={_raw_inv_ratio:.1f}%  "
                                          f"使用上一帧有效bottom_mask  streak={_bottom_fail_streak}")
                            elif 10.0 <= _raw_inv_ratio <= 60.0:
                                _bottom_fail_streak = 0
                            _inv_mask = (_inv_mask_override
                                         if _inv_mask_override is not None
                                         else (_dyn_wok_bool & ~_bm_full))
                            if _inv_mask.any() and temp_data is not None and homography is not None:
                                ir_h_inv, ir_w_inv = temp_data.shape[1], temp_data.shape[2]
                                ir_mask_inv = map_mask_to_ir(_inv_mask, homography,
                                                             (ir_h_inv, ir_w_inv))
                                ir_idx_inv  = _get_ir_idx(abs_idx)
                                if ir_idx_inv < temp_data.shape[0]:
                                    t_frame_inv  = temp_data[ir_idx_inv]
                                    inv_temps    = t_frame_inv[ir_mask_inv]
                                    if len(inv_temps) > 0:
                                        inverse_temp_mean = float(np.mean(inv_temps))
                    except Exception as _inv_e:
                        pass  # 计算失败不影响主流程
                # ── 反向语义面积门控：inv_mask > 60% wok椭圆时视为锅直立/异常，清空 ──
                _inv_area_ok = True
                if has_bottom and bottom_chunk_masks:
                    _bm_raw_chk = bottom_chunk_masks.get(local_in_chunk)
                    if _bm_raw_chk is not None:
                        _bm_full_chk = upscale_mask(_bm_raw_chk, orig_wh) if do_resize else _bm_raw_chk
                        if _wok_rgb_constraint is not None:
                            _dyn_wok_bool_chk = _wok_rgb_constraint
                        else:
                            _dyn_wok_chk = np.zeros((VH, VW), dtype=np.uint8)
                            cv2.ellipse(_dyn_wok_chk,
                                        (int(round(wok_rgb_cx)), int(round(wok_rgb_cy))),
                                        (int(round(wok_rgb_rx)), int(round(wok_rgb_ry))),
                                        0, 0, 360, 255, -1)
                            _dyn_wok_bool_chk = _dyn_wok_chk > 0
                        _inv_mask_chk = _dyn_wok_bool_chk & ~_bm_full_chk
                        _wok_px_chk2  = int(_dyn_wok_bool_chk.sum())
                        _inv_px_chk   = int(_inv_mask_chk.sum())
                        _inv_ratio    = _inv_px_chk / max(_wok_px_chk2, 1) * 100
                        if _inv_ratio > 60.0:
                            _inv_area_ok = False
                            inverse_temp_mean = float("nan")
                            print(f"[Inv门控] frame={abs_idx}  inv_ratio={_inv_ratio:.1f}%>60%，"
                                  f"跳过该帧反向语义温度")

                if _inv_area_ok and not np.isnan(inverse_temp_mean):
                    inverse_history.append((time_s, inverse_temp_mean))
                inverse_rows.append([abs_idx, local_idx, time_s, inverse_temp_mean])

                # ── info_bar 第二行：IR + Inv 温度追加（已算完后写入）────────
                if not np.isnan(ir_mask_temp):
                    parts.append(f"IR:{ir_mask_temp:.1f}C")
                if not np.isnan(inverse_temp_mean):
                    parts.append(f"Inv:{inverse_temp_mean:.1f}C")
                cv2.putText(info_bar, "  ".join(parts),
                            (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (100, 255, 200), 1)

                chart_bar = draw_temp_chart(temp_history, time_s, VW, CHART_H, CURVE_WIN_S,
                                            roi_history=roi_history,
                                            ir_mask_history=ir_mask_history,
                                            inverse_history=inverse_history if has_bottom else None)
                writer.write(np.vstack([vis, info_bar, chart_bar]))
                # 三策略数据分别记录
                sam2_rows.append([abs_idx, local_idx, time_s,
                                  int(mask.sum()), round(mask_ratio, 2),
                                  temp_mean, temp_min, temp_max])
                roi_rows.append([abs_idx, local_idx, time_s, roi_temp_mean])
                ir_rows.append([abs_idx, local_idx, time_s, ir_mask_temp])

                # ── 写 inverse 叠加帧（锅底反向 RGB 视频）────────────────────
                if writer_inv is not None:
                    if _inv_area_ok and has_bottom and bottom_chunk_masks:
                        _bm_r2 = bottom_chunk_masks.get(local_in_chunk)
                        if _bm_r2 is not None:
                            _bm_f2 = upscale_mask(_bm_r2, orig_wh) if do_resize else _bm_r2
                            if _wok_rgb_constraint is not None:
                                _inv_vis_mask = _wok_rgb_constraint & ~_bm_f2
                            elif wok_rgb_mask_static is not None:
                                _dyn2 = np.zeros((VH, VW), dtype=np.uint8)
                                cv2.ellipse(_dyn2,
                                            (int(round(_wok_rgb_cx_dyn)),
                                             int(round(_wok_rgb_cy_dyn))),
                                            (int(round(wok_rgb_rx)),
                                             int(round(wok_rgb_ry))),
                                            0, 0, 360, 255, -1)
                                _inv_vis_mask = (_dyn2 > 0) & ~_bm_f2
                            else:
                                _fb = np.ones((VH, VW), dtype=bool)
                                _inv_vis_mask = _fb & ~_bm_f2
                            vis_inv = render_overlay(frame, _inv_vis_mask,
                                                     (200, 80, 255), MASK_ALPHA)
                            cv2.putText(vis_inv,
                                        (f"Inverse(Wok-Bottom)  t={time_s:.1f}s"
                                         f"  Inv={inverse_temp_mean:.1f}C"
                                         if not np.isnan(inverse_temp_mean)
                                         else f"Inverse(Wok-Bottom)  t={time_s:.1f}s"),
                                        (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                                        (200, 80, 255), 2)
                        else:
                            vis_inv = frame.copy()
                    else:
                        vis_inv = frame.copy()
                    inv_info = np.zeros((INFO_H, VW, 3), dtype=np.uint8)
                    cv2.putText(inv_info,
                                f"Frame {abs_idx}  t={time_s:.1f}s  [Inverse/Bottom]",
                                (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                                (200, 80, 255), 1)
                    cv2.putText(inv_info,
                                (f"Inv:{inverse_temp_mean:.1f}C"
                                 if not np.isnan(inverse_temp_mean) else "Inv:N/A"),
                                (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.48,
                                (200, 100, 255), 1)
                    writer_inv.write(np.vstack([vis_inv, inv_info, chart_bar]))

                if local_in_chunk % 50 == 0:
                    print(f"  写帧: {local_in_chunk+1}/{actual}  "
                          f"mask={mask_ratio:.1f}%  temp={temp_mean:.1f}°C", end="\r")

            # ── IR-fix 批次命中率检查：>50% 时生成前景点注入下批 SAM2 精细化 ──
            # 改进前：直接用 IR 粗糙 mask 替换 carry_mask，SAM2 边界能力浪费
            # 改进后：IR 只做"粗定位"，从 IR mask 内采样前景点存入 _next_inject，
            #         下批 SAM2 接收这些点 + carry_mask 一起精细化边界
            if _irfix_count > actual * 0.5 and _irfix_last_mask is not None:
                # carry_mask 仍用 IR 末帧 mask 覆盖（确保跨批位置正确）
                carry_mask = _irfix_last_mask.copy()
                _wok_px_ni = int(_wok_rgb_constraint.sum()) if _wok_rgb_constraint is not None else 1
                _new_mask_pct = carry_mask.sum() / max(_wok_px_ni, 1) * 100
                print(f"[IR-fix接管] 批次{chunk_i+1} 命中率={_irfix_count}/{actual}"
                      f"={_irfix_count/actual*100:.0f}%>50%，"
                      f"carry_mask更新为IR末帧({_new_mask_pct:.1f}%wok)")
                # 从 IR 末帧 mask 内部采样前景点 → 存入 _next_inject，下批 SAM2 精细化
                if (_H_inv_al is not None and _rng_al is not None
                        and _wok_rgb_constraint is not None):
                    try:
                        _ys_ni, _xs_ni = np.where(_irfix_last_mask)
                        if len(_xs_ni) >= 4:
                            _sel_ni = _rng_al.choice(len(_xs_ni),
                                                     size=min(6, len(_xs_ni)),
                                                     replace=False)
                            _fg_ni = []
                            for _xi_ni, _yi_ni in zip(_xs_ni[_sel_ni], _ys_ni[_sel_ni]):
                                _xi_ni, _yi_ni = float(_xi_ni), float(_yi_ni)
                                if _AXIS_CX_RGB is not None:
                                    _d = ((_xi_ni-_AXIS_CX_RGB)**2+(_yi_ni-_AXIS_CY_RGB)**2)**0.5
                                    if _d < _AXIS_EXCL_R:
                                        continue
                                _fg_ni.append([_xi_ni, _yi_ni])
                            if _fg_ni:
                                _axis_bg_ni = [[_AXIS_CX_RGB, _AXIS_CY_RGB]] if _AXIS_CX_RGB is not None else []
                                _next_inject = {
                                    "local_frame": 0,
                                    "fg_points":   _fg_ni,
                                    "bg_points":   _axis_bg_ni,
                                    "label":       "IR-fix-next",
                                }
                                print(f"[IR-fix接管] 已生成下批注入前景点 {len(_fg_ni)} 个"
                                      f"，下批SAM2将精细化IR粗mask")
                    except Exception as _ni_e:
                        print(f"[IR-fix接管] 前景点采样失败({_ni_e})，跳过")

            cap.release()
            print()
            global_local += actual

    else:
        # ── 混合模式：逐帧处理，锚点帧用 SAM2，中间帧用光流 ──────────────────
        cap = cv2.VideoCapture(video_path)
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        anchor_set = set(anchor_frames)   # 快速查找
        n_total    = len(anchor_frames)
        anchor_cnt = 0

        for abs_idx in range(start_frame, track_end_frame):
            ret, frame = cap.read()
            if not ret:
                break

            local_idx  = abs_idx - start_frame
            is_anchor  = (abs_idx in anchor_set)

            if is_anchor:
                # SAM2 单帧推理：抽单帧到临时目录
                tmp_dir, frame_names, actual = extract_chunk_to_dir(
                    video_path, abs_idx, abs_idx + 1
                )
                try:
                    # 检查此帧是否有注入关键帧（对于第一帧之外的额外标注）
                    inject_this = []
                    if abs_idx in inject_map and abs_idx != start_frame:
                        kf = inject_map[abs_idx]
                        inject_this = [{
                            "local_frame": 0,
                            "fg_points":   kf["fg_points"],
                            "bg_points":   kf.get("bg_points", []),
                            "label":       kf.get("label", ""),
                        }]

                    chunk_masks, carry_mask = track_chunk(
                        predictor, tmp_dir, frame_names,
                        fg_points, bg_points,
                        carry_mask=carry_mask,
                        inject_keyframes=inject_this,
                    )
                    mask     = chunk_masks.get(0, np.zeros((VH, VW), dtype=bool))
                    mask_src = "SAM2"
                    anchor_cnt += 1
                    if anchor_cnt % 25 == 1 or anchor_cnt == n_total:
                        print(f"  [SAM2锚点 {anchor_cnt}/{n_total}] 帧 {abs_idx}"
                              f"  t={abs_idx/fps:.1f}s", end="\r")
                finally:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
            else:
                # 光流传播
                if flow_prev_gray is None or flow_prev_mask is None:
                    # 兜底：没有前帧信息时用空 mask
                    mask = np.zeros((VH, VW), dtype=bool)
                else:
                    cur_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    mask     = flow_propagate_mask(flow_prev_gray, cur_gray, flow_prev_mask)
                mask_src = "Flow"

            # 更新光流状态
            flow_prev_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            flow_prev_mask = mask

            # 温度统计
            temp_mean, temp_min, temp_max = _measure_rgb_mask_temperature(
                mask, temp_data, homography, _get_ir_idx(abs_idx))

            time_s     = abs_idx / fps
            mask_ratio = mask.sum() / mask.size * 100
            if not np.isnan(temp_mean):
                temp_history.append((time_s, temp_mean))

            info_bar  = np.zeros((INFO_H, VW, 3), dtype=np.uint8)
            hud_color = (255, 255, 255) if mask_src == "SAM2" else (80, 220, 255)
            color     = MASK_COLOR if mask_src == "SAM2" else (0, 200, 80)
            vis       = render_overlay(frame, mask, color, MASK_ALPHA)

            cv2.putText(info_bar,
                        f"Frame {abs_idx}  t={time_s:.1f}s  "
                        f"Mask={mask_ratio:.1f}%  [{mask_src}]",
                        (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, hud_color, 1)
            cv2.putText(info_bar,
                        (f"Temp: mean={temp_mean:.1f}C  min={temp_min:.1f}C  max={temp_max:.1f}C"
                         if not np.isnan(temp_mean) else "Temp: N/A"),
                        (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (100, 255, 200), 1)

            chart_bar = draw_temp_chart(temp_history, time_s, VW, CHART_H, CURVE_WIN_S)
            writer.write(np.vstack([vis, info_bar, chart_bar]))
            sam2_rows.append([abs_idx, local_idx, time_s,
                              int(mask.sum()), round(mask_ratio, 2),
                              temp_mean, temp_min, temp_max])

        cap.release()
        print()
        global_local = track_end_frame - start_frame

    writer.release()
    if writer_inv is not None:
        writer_inv.release()

    print(f"\n\n[DONE] 追踪完成！")
    print(f"   结果目录:   {out_dir}")
    print(f"   可视化视频: {out_video_viz}")
    print(f"   共处理 {global_local} 帧")

    # ── 保存三策略独立 Excel（含 inverse）────────────────────────────────────
    _output_utils._save_three_xlsx(
        sam2_rows, roi_rows, ir_rows, out_dir,
        inverse_rows=inverse_rows if has_bottom else None)

    # ── 绘制三策略温度曲线 PNG（含 inverse）──────────────────────────────────
    _output_utils._plot_three_curves(
        sam2_rows, roi_rows, ir_rows, out_curve,
        inverse_rows=inverse_rows if has_bottom else None)

    # ── 拼合 RGB + IR 视频 ────────────────────────────────────────────────────
    if temp_data is not None and wok_cfg is not None:
        out_combined = os.path.join(out_dir, "track_result_combined.mp4")
        ir_fps_val   = fps * ir_fps_ratio   # 估算 IR 帧率
        print(f"\n[拼合] 开始生成 RGB+IR 并排视频...")
        _output_utils.stitch_rgb_ir(
            rgb_viz_path=out_video_viz,
            temp_data=temp_data,
            ir_fps=ir_fps_val,
            wok_cfg=wok_cfg,
            out_path=out_combined,
            rgb_start_frame=start_frame,
            rgb_fps=fps,
            pct=IR_FOOD_PCT,
            wok_cx_history=_wok_cx_history,
            inv_viz_path=out_inv_viz if (has_bottom and os.path.exists(out_inv_viz)) else None,
            info_h=INFO_H,
            chart_h=CHART_H,
        )
        print(f"   并排视频: {out_combined}")
        # 删除中间产物（纯 RGB viz 视频），只保留最终并排视频
        try:
            os.remove(out_video_viz)
            print(f"   已删除中间文件: track_result_viz.mp4")
        except Exception:
            pass
        if has_bottom and os.path.exists(out_inv_viz):
            try:
                os.remove(out_inv_viz)
                print(f"   已删除中间文件: track_result_inv_viz.mp4")
            except Exception:
                pass
    else:
        print("[拼合] 缺少温度数据或锅区域配置，跳过 IR 拼合")

    # 清理空的 tmp 根目录（如果为空）
    try:
        if os.path.exists(TMP_BASE) and not os.listdir(TMP_BASE):
            os.rmdir(TMP_BASE)
    except Exception:
        pass
if __name__ == "__main__":
    main()
