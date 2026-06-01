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

import cv2
import numpy as np
import torch
import matplotlib
matplotlib.use("Agg")   # 无头模式，不弹窗
import matplotlib.pyplot as plt

# ── 配置 ─────────────────────────────────────────────────────────────────────
LABELS_JSON     = "food_labels.json"
HOMOGRAPHY_PATH = "homography.npy"          # RGB→IR 单应矩阵
OUTPUT_VIDEO    = "track_result_chunk12.mp4"        # 可视化输出视频
OUTPUT_CSV      = "food_temp_log_chunk12.csv"       # 温度日志

# SAM2 配置
MODEL_CFG       = "configs/sam2.1/sam2.1_hiera_l.yaml"
CHECKPOINT_PATH = "D:/sam2_checkpoints/sam2.1_hiera_large.pt"

# 分批处理参数（核心：避免 OOM）
CHUNK_SIZE      = 12      # 每批处理帧数，12帧约480ms延迟（25 FPS）
# RTX 5070 Ti 16GB 显存：12 帧约占 <1 GB

# 提示点数量上限（None = 不限制，使用全部标注点）
MAX_FG_POINTS   = None
MAX_BG_POINTS   = None

# 温度数据（自动推断）
TEMP_NPY_PATH   = None   # None = 自动扫描项目目录

# 可视化参数
MASK_COLOR      = (0, 255, 100)   # BGR 绿色，食材 mask 叠加色
MASK_ALPHA      = 0.45
SHOW_PREVIEW    = False           # 关闭实时预览，减少资源占用

# 临时帧目录（放在项目目录下，不占 C 盘）
TMP_BASE        = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tmp_sam2_frames")


# ── 工具函数 ─────────────────────────────────────────────────────────────────

def load_labels(path):
    """
    加载标注文件，兼容新格式（多关键帧列表）和旧格式（flat 单帧）。

    返回:
        video_path  : str
        start_frame : int           第一个关键帧的帧号（追踪起始点）
        keyframes   : list[dict]    所有关键帧，按 frame 升序排列
          每条: {"frame": int, "fg_points": [...], "bg_points": [...], "label": str}
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"[标注] 视频: {data['video_path']}")

    if "keyframes" in data:
        # ── 新格式 ────────────────────────────────────────────────────────────
        kfs = sorted(data["keyframes"], key=lambda k: k["frame"])
        for kf in kfs:
            fg = kf.get("fg_points", [])
            bg = kf.get("bg_points", [])
            kf["fg_points"] = fg if MAX_FG_POINTS is None else fg[:MAX_FG_POINTS]
            kf["bg_points"] = bg if MAX_BG_POINTS is None else bg[:MAX_BG_POINTS]
        print(f"[标注] 共 {len(kfs)} 个关键帧：")
        for kf in kfs:
            print(f"  帧 {kf['frame']:6d} ({kf['time_s']:.1f}s)  "
                  f"标签={kf.get('label','')}  "
                  f"FG={len(kf['fg_points'])}  BG={len(kf['bg_points'])}")
        start_frame = kfs[0]["frame"]
        return data["video_path"], start_frame, kfs
    else:
        # ── 旧格式兼容 ────────────────────────────────────────────────────────
        fg_all = data["fg_points"]
        bg_all = data["bg_points"]
        fg = fg_all if MAX_FG_POINTS is None else fg_all[:MAX_FG_POINTS]
        bg = bg_all if MAX_BG_POINTS is None else bg_all[:MAX_BG_POINTS]
        start_frame = data.get("start_frame", 0)
        fps_json    = data.get("fps", 25.0)
        print(f"[标注] 旧格式：起始帧={start_frame}  FG={len(fg)}  BG={len(bg)}")
        kf = {
            "frame":     start_frame,
            "time_s":    round(start_frame / fps_json, 3),
            "label":     "初始标注",
            "fg_points": fg,
            "bg_points": bg,
        }
        return data["video_path"], start_frame, [kf]


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


def load_temp_data(npy_path, start_frame):
    if npy_path is None or not os.path.exists(npy_path):
        return None
    data = np.load(npy_path)
    print(f"[温度] 加载 {os.path.basename(npy_path)}，shape: {data.shape}，dtype: {data.dtype}")
    if data.ndim == 2:
        data = data[np.newaxis, ...]
    if data.shape[0] > start_frame:
        data = data[start_frame:]
    print(f"[温度] 从第 {start_frame} 帧开始，剩余 {data.shape[0]} 帧温度数据")
    return data


def build_sam2_predictor(device):
    from sam2.build_sam import build_sam2_video_predictor
    print(f"\n[SAM2] 加载模型: {CHECKPOINT_PATH}")
    predictor = build_sam2_video_predictor(MODEL_CFG, CHECKPOINT_PATH, device=device)
    print("[SAM2] 模型加载完成")
    return predictor


def extract_chunk_to_dir(video_path, start_abs, end_abs):
    """
    将视频 [start_abs, end_abs) 帧抽到临时目录。
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
        fname = f"{local_idx:06d}.jpg"
        cv2.imwrite(os.path.join(tmp_dir, fname),
                    frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        frame_names.append(fname)
        local_idx += 1

    cap.release()
    return tmp_dir, frame_names, local_idx


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

        # ── 注入额外关键帧的前景点（例如青椒入锅帧）────────────────────────
        for kf_inject in inject_keyframes:
            local_f  = kf_inject["local_frame"]
            kf_fg    = kf_inject["fg_points"]
            kf_bg    = kf_inject.get("bg_points", [])
            if not kf_fg:
                continue
            if 0 < local_f < len(frame_names):
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


def render_overlay(frame_bgr, mask, color_bgr, alpha):
    """在帧上叠加半透明 mask + 轮廓"""
    vis = frame_bgr.copy()
    c   = np.array(color_bgr, dtype=np.uint8)
    vis[mask] = (vis[mask].astype(float) * (1 - alpha) + c * alpha).astype(np.uint8)
    mask_u8 = mask.astype(np.uint8) * 255
    contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(vis, contours, -1, (255, 255, 255), 1)
    return vis


# ── 主程序 ───────────────────────────────────────────────────────────────────

def main():
    # ── 检查依赖文件 ──────────────────────────────────────────────────────────
    if not os.path.exists(LABELS_JSON):
        print(f"[错误] 找不到标注文件: {LABELS_JSON}")
        print("请先运行 LabelFirstFrame.py 完成标注")
        sys.exit(1)

    video_path, start_frame, keyframes = load_labels(LABELS_JSON)
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
    track_frames = total_frames - start_frame
    print(f"\n[视频] {video_path}")
    print(f"[视频] 分辨率: {VW}x{VH}  总帧数: {total_frames}  FPS: {fps:.1f}")
    print(f"[视频] 追踪范围: 第 {start_frame} ~ {total_frames} 帧，共 {track_frames} 帧")
    print(f"[分批] 每批 {CHUNK_SIZE} 帧，共需 {(track_frames + CHUNK_SIZE - 1)//CHUNK_SIZE} 批")

    # ── 预构建关键帧注入表：{abs_frame: kf_dict} ──────────────────────────────
    # 只包含 extra_kfs（index>=1），第一个关键帧已经作为初始标注点使用
    inject_map = {kf["frame"]: kf for kf in extra_kfs}

    # ── 加载单应矩阵（可选）──────────────────────────────────────────────────
    homography = None
    if os.path.exists(HOMOGRAPHY_PATH):
        homography = np.load(HOMOGRAPHY_PATH)
        print(f"[单应矩阵] 已加载: {HOMOGRAPHY_PATH}  shape: {homography.shape}")
    else:
        print(f"[单应矩阵] 未找到 {HOMOGRAPHY_PATH}，跳过温度融合")

    # ── 自动匹配温度文件 ──────────────────────────────────────────────────────
    global TEMP_NPY_PATH
    if TEMP_NPY_PATH is None:
        TEMP_NPY_PATH = find_temp_npy(video_path)
    temp_data = load_temp_data(TEMP_NPY_PATH, start_frame)

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
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(OUTPUT_VIDEO, fourcc, fps, (VW, VH))
    csv_lines = ["frame_abs,frame_rel,time_s,mask_pixels,mask_ratio,temp_mean,temp_min,temp_max"]

    # ── 分批追踪主循环 ────────────────────────────────────────────────────────
    carry_mask = None   # 上批末帧 mask，用于跨批传递目标信息
    global_local = 0    # 全局相对帧计数

    n_chunks = (track_frames + CHUNK_SIZE - 1) // CHUNK_SIZE
    for chunk_i in range(n_chunks):
        chunk_start_abs = start_frame + chunk_i * CHUNK_SIZE
        chunk_end_abs   = min(chunk_start_abs + CHUNK_SIZE, total_frames)
        chunk_len       = chunk_end_abs - chunk_start_abs

        print(f"\n{'='*55}")
        print(f"[批次 {chunk_i+1}/{n_chunks}] 帧 {chunk_start_abs} ~ {chunk_end_abs-1}"
              f"  ({chunk_len} 帧)")

        # 抽帧到临时目录
        tmp_dir, frame_names, actual = extract_chunk_to_dir(
            video_path, chunk_start_abs, chunk_end_abs
        )
        print(f"[抽帧] 临时目录: {tmp_dir}  实际帧数: {actual}")

        if actual == 0:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            break

        try:
            # ── 计算本批内哪些帧需要注入额外关键帧 ──────────────────────────
            inject_this_chunk = []
            for abs_f, kf in inject_map.items():
                if chunk_start_abs <= abs_f < chunk_end_abs:
                    local_f = abs_f - chunk_start_abs
                    inject_this_chunk.append({
                        "local_frame": local_f,
                        "fg_points":   kf["fg_points"],
                        "bg_points":   kf.get("bg_points", []),
                        "label":       kf.get("label", ""),
                    })

            # SAM2 追踪本批
            chunk_masks, carry_mask = track_chunk(
                predictor, tmp_dir, frame_names,
                fg_points, bg_points,
                carry_mask=carry_mask,
                inject_keyframes=inject_this_chunk,
            )
            print(f"[SAM2] 批次 {chunk_i+1} 追踪完成，{len(chunk_masks)} 帧")
        finally:
            # 每批完成后立即清理临时目录（不等全部批次）
            shutil.rmtree(tmp_dir, ignore_errors=True)
            print(f"[清理] 临时帧已删除")

        # ── 写入本批输出 ──────────────────────────────────────────────────────
        cap = cv2.VideoCapture(video_path)
        cap.set(cv2.CAP_PROP_POS_FRAMES, chunk_start_abs)

        for local_in_chunk in range(actual):
            ret, frame = cap.read()
            if not ret:
                break

            abs_idx   = chunk_start_abs + local_in_chunk
            local_idx = global_local + local_in_chunk
            mask      = chunk_masks.get(local_in_chunk,
                                        np.zeros((VH, VW), dtype=bool))

            # 叠加可视化
            vis = render_overlay(frame, mask, MASK_COLOR, MASK_ALPHA)

            # 温度统计
            temp_mean = temp_min = temp_max = float("nan")
            if temp_data is not None and homography is not None:
                ir_h, ir_w = temp_data.shape[1], temp_data.shape[2]
                ir_mask = map_mask_to_ir(mask, homography, (ir_h, ir_w))
                if local_idx < temp_data.shape[0]:
                    t_frame    = temp_data[local_idx]
                    food_temps = t_frame[ir_mask]
                    if len(food_temps) > 0:
                        temp_mean = float(np.mean(food_temps))
                        temp_min  = float(np.min(food_temps))
                        temp_max  = float(np.max(food_temps))

            # 视频帧 HUD
            time_s     = abs_idx / fps
            mask_ratio = mask.sum() / mask.size * 100
            info1 = f"Frame {abs_idx}  t={time_s:.1f}s  Mask={mask_ratio:.1f}%"
            info2 = (f"Temp: mean={temp_mean:.1f}C  min={temp_min:.1f}C  max={temp_max:.1f}C"
                     if not np.isnan(temp_mean) else "Temp: N/A")

            cv2.rectangle(vis, (0, VH - 50), (VW, VH), (0, 0, 0), -1)
            cv2.putText(vis, info1, (10, VH - 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
            cv2.putText(vis, info2, (10, VH - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (100, 255, 200), 1)

            writer.write(vis)
            csv_lines.append(
                f"{abs_idx},{local_idx},{time_s:.3f},"
                f"{mask.sum()},{mask_ratio:.2f},"
                f"{temp_mean:.2f},{temp_min:.2f},{temp_max:.2f}"
            )

            if local_in_chunk % 50 == 0:
                print(f"  写帧: {local_in_chunk+1}/{actual}  "
                      f"mask={mask_ratio:.1f}%  temp={temp_mean:.1f}°C", end="\r")

        cap.release()
        print()
        global_local += actual

    writer.release()

    # ── 保存 CSV ──────────────────────────────────────────────────────────────
    with open(OUTPUT_CSV, "w", encoding="utf-8") as f:
        f.write("\n".join(csv_lines))

    print(f"\n\n✅ 追踪完成！")
    print(f"   可视化视频: {OUTPUT_VIDEO}")
    print(f"   温度日志:   {OUTPUT_CSV}")
    print(f"   共处理 {global_local} 帧")

    # ── 绘制温度曲线 ──────────────────────────────────────────────────────────
    if temp_data is not None:
        _plot_temp_curve(OUTPUT_CSV)

    # 清理空的 tmp 根目录（如果为空）
    try:
        if os.path.exists(TMP_BASE) and not os.listdir(TMP_BASE):
            os.rmdir(TMP_BASE)
    except Exception:
        pass


def _plot_temp_curve(csv_path):
    """从 CSV 绘制菜温随时间变化曲线"""
    import csv
    times, means, mins, maxs = [], [], [], []
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                tm = float(row["temp_mean"])
                if not np.isnan(tm):
                    times.append(float(row["time_s"]))
                    means.append(tm)
                    mins.append(float(row["temp_min"]))
                    maxs.append(float(row["temp_max"]))
            except (ValueError, KeyError):
                continue

    if not times:
        print("[温度曲线] 无有效温度数据，跳过绘图")
        return

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.fill_between(times, mins, maxs, alpha=0.2, color="orange", label="min~max 区间")
    ax.plot(times, means, color="red", linewidth=1.5, label="均值温度")
    ax.set_xlabel("时间 (s)")
    ax.set_ylabel("温度 (°C)")
    ax.set_title("食材温度随时间变化曲线（SAM2 Mask 区域）")
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    out = "food_temp_curve.png"
    plt.savefig(out, dpi=120)
    plt.close()
    print(f"[温度曲线] 已保存: {out}")


if __name__ == "__main__":
    main()
