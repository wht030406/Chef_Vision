"""
check_ir_align.py — RGB / IR 时间对齐可视化验证

用法：
  python tools/check_ir_align.py                  # 自动用 data/ 里最新一对数据
  python tools/check_ir_align.py --n 10           # 抽 10 个时间点
  python tools/check_ir_align.py --ts             # 若有 _ts.npy 则用时间戳对齐
  python tools/check_ir_align.py --offset 2       # IR 比 RGB 晚 2 帧（补偿起始偏移）

输出：tools/ir_align_check.jpg
每行 = 一个时间点：[RGB 帧] | [IR 热力图]
"""

import os, sys, glob, re, argparse, json
import numpy as np
import cv2

_HERE     = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_HERE, "..", "data")
_HOM_PATH = os.path.join(_DATA_DIR, "homography.npy")
_WOK_PATH = os.path.join(_DATA_DIR, "wok_region.json")
_OUT_PATH = os.path.join(_HERE, "ir_align_check.jpg")


def temp_to_colormap(mat, out_w, out_h, wok_cfg=None):
    t_min, t_max = float(mat.min()), float(mat.max())
    if t_max - t_min < 0.1:
        norm = np.zeros_like(mat, dtype=np.uint8)
    else:
        norm = ((mat - t_min) / (t_max - t_min) * 255).astype(np.uint8)
    colored = cv2.applyColorMap(norm, cv2.COLORMAP_JET)
    ir_h, ir_w = mat.shape[:2]
    colored = cv2.resize(colored, (out_w, out_h), interpolation=cv2.INTER_NEAREST)
    cv2.putText(colored, f"MAX:{t_max:.1f}C", (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1)
    cv2.putText(colored, f"MIN:{t_min:.1f}C", (6, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1)
    cv2.putText(colored, f"AVG:{float(mat.mean()):.1f}C", (6, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1)
    if wok_cfg is not None:
        sx, sy = out_w / ir_w, out_h / ir_h
        cx, cy = int(wok_cfg["cx"]*sx), int(wok_cfg["cy"]*sy)
        rx, ry = int(wok_cfg["rx"]*sx), int(wok_cfg["ry"]*sy)
        cv2.ellipse(colored, (cx, cy), (rx, ry), 0, 0, 360, (0, 255, 255), 2)
    return colored


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rgb",    default=None)
    ap.add_argument("--temp",   default=None)
    ap.add_argument("--n",      type=int, default=8)
    ap.add_argument("--ts",     action="store_true")
    ap.add_argument("--offset", type=int, default=0,
                    help="IR帧偏移量：正数=IR比RGB晚N帧，负数=IR比RGB早N帧（补偿异步起始差）")
    ap.add_argument("--out",    default=_OUT_PATH)
    args = ap.parse_args()

    # 自动找最新一对
    if args.rgb is None:
        files = sorted(glob.glob(os.path.join(_DATA_DIR, "rgb_????????_??????.mp4")))
        args.rgb = files[-1] if files else None
    if args.temp is None:
        files = sorted(glob.glob(os.path.join(_DATA_DIR, "temp_????????_??????.npy")))
        # 排除 _ts.npy
        files = [f for f in files if "_ts" not in f]
        args.temp = files[-1] if files else None

    if not args.rgb or not args.temp:
        print("[错误] 找不到数据文件"); sys.exit(1)

    print(f"[RGB ] {args.rgb}")
    print(f"[IR  ] {args.temp}")

    cap       = cv2.VideoCapture(args.rgb)
    rgb_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps       = cap.get(cv2.CAP_PROP_FPS)
    VW        = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    VH        = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    ir_data  = np.load(args.temp)
    if ir_data.ndim == 2:
        ir_data = ir_data[np.newaxis]
    ir_total     = ir_data.shape[0]
    ir_fps_ratio = ir_total / rgb_total
    ir_fps_est   = fps * ir_fps_ratio

    print(f"[RGB ] {rgb_total}帧 @{fps:.1f}fps = {rgb_total/fps:.1f}s  ({VW}x{VH})")
    print(f"[IR  ] {ir_total}帧 @~{ir_fps_est:.2f}fps  ratio={ir_fps_ratio:.4f}")
    if args.offset != 0:
        print(f"[OFF ] IR帧偏移 {args.offset:+d} 帧")

    # 时间戳
    rgb_ts = ir_ts = None
    use_ts = False
    if args.ts:
        ts1 = os.path.splitext(args.rgb)[0] + "_ts.npy"
        ts2 = args.temp.replace(".npy", "_ts.npy")
        if os.path.exists(ts1): rgb_ts = np.load(ts1)
        if os.path.exists(ts2): ir_ts  = np.load(ts2)
        if rgb_ts is not None and ir_ts is not None:
            use_ts = True
            print(f"[TS  ] 时间戳对齐  RGB={len(rgb_ts)}  IR={len(ir_ts)}")
        else:
            print(f"[TS  ] _ts.npy 不存在，fallback 帧率比例")

    offset_str = f"{args.offset:+d}" if args.offset != 0 else "0"
    mode_str   = "TimestampAlign" if use_ts else f"RatioAlign(off={offset_str})"

    # 单应矩阵 & wok
    H_inv   = None
    wok_cfg = None
    if os.path.exists(_HOM_PATH):
        H = np.load(_HOM_PATH)
        H_inv = np.linalg.inv(H)
        print("[H   ] 单应矩阵已加载")
    if os.path.exists(_WOK_PATH):
        with open(_WOK_PATH) as f:
            wok_cfg = json.load(f)
        print(f"[wok ] cx={wok_cfg['cx']} cy={wok_cfg['cy']}")

    # 采样点
    sample_abs = [int(f * rgb_total) for f in np.linspace(0.10, 0.90, args.n)]

    # 输出尺寸
    THUMB_H   = 280
    THUMB_W   = int(VW / VH * THUMB_H)
    ir_aspect = ir_data.shape[2] / ir_data.shape[1]
    IR_W      = int(THUMB_H * ir_aspect)
    LABEL_H   = 28
    ROW_W     = THUMB_W + 4 + IR_W

    rows = []
    for abs_idx in sample_abs:
        t_rgb = abs_idx / fps

        # RGB 帧
        cap.set(cv2.CAP_PROP_POS_FRAMES, abs_idx)
        ret, rgb_frame = cap.read()
        if not ret:
            rgb_frame = np.zeros((VH, VW, 3), dtype=np.uint8)
        thumb = cv2.resize(rgb_frame, (THUMB_W, THUMB_H))

        # 在 RGB 上画 wok 投影椭圆
        if wok_cfg is not None and H_inv is not None:
            try:
                angles = np.linspace(0, 2*np.pi, 60)
                xs = wok_cfg["cx"] + wok_cfg["rx"] * np.cos(angles)
                ys = wok_cfg["cy"] + wok_cfg["ry"] * np.sin(angles)
                pts_ir  = np.stack([xs, ys, np.ones(60)])
                pts_rgb = H_inv @ pts_ir
                pts_rgb = (pts_rgb[:2] / pts_rgb[2]).T
                sx, sy  = THUMB_W/VW, THUMB_H/VH
                for i in range(len(pts_rgb)-1):
                    p1 = (int(pts_rgb[i,  0]*sx), int(pts_rgb[i,  1]*sy))
                    p2 = (int(pts_rgb[i+1,0]*sx), int(pts_rgb[i+1,1]*sy))
                    if all(0<=v<dim for v,dim in [(p1[0],THUMB_W),(p1[1],THUMB_H),(p2[0],THUMB_W),(p2[1],THUMB_H)]):
                        cv2.line(thumb, p1, p2, (0,255,255), 1)
            except Exception:
                pass
        cv2.putText(thumb, f"RGB t={t_rgb:.1f}s  f={abs_idx}", (6, THUMB_H-8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200,255,200), 1)

        # IR 帧索引
        if use_ts and rgb_ts is not None and ir_ts is not None and abs_idx < len(rgb_ts):
            t_ref  = rgb_ts[abs_idx]
            ir_idx = int(np.argmin(np.abs(ir_ts - t_ref)))
        else:
            ir_idx = int(abs_idx * ir_fps_ratio) + args.offset
        ir_idx = max(0, min(ir_idx, ir_total - 1))

        ir_mat   = ir_data[ir_idx]
        ir_thumb = temp_to_colormap(ir_mat, IR_W, THUMB_H, wok_cfg=wok_cfg)
        ir_t     = ir_idx / ir_fps_est
        cv2.putText(ir_thumb, f"IR f={ir_idx}  t={ir_t:.1f}s  [{mode_str}]",
                    (6, THUMB_H-8), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (200,200,200), 1)

        sep     = np.full((THUMB_H, 4, 3), 40, dtype=np.uint8)
        row_img = np.hstack([thumb, sep, ir_thumb])

        # 标签条
        label = np.zeros((LABEL_H, ROW_W, 3), dtype=np.uint8)
        dt    = abs(t_rgb - ir_t)
        cv2.putText(label,
                    f"RGB_t={t_rgb:.2f}s   IR_t={ir_t:.2f}s   delta={dt:.3f}s   "
                    f"ir_idx={ir_idx}  offset={args.offset}",
                    (6, LABEL_H-6), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255,255,100), 1)

        rows.append(np.vstack([label, row_img]))

    cap.release()

    # 标题
    title = np.zeros((46, ROW_W, 3), dtype=np.uint8)
    cv2.putText(title,
                f"IR-RGB Align [{mode_str}]  RGB={rgb_total}f@{fps:.0f}fps  "
                f"IR={ir_total}f@{ir_fps_est:.1f}fps  ratio={ir_fps_ratio:.4f}",
                (6, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255,255,100), 1)

    full = np.vstack([title] + rows)
    cv2.imwrite(args.out, full, [cv2.IMWRITE_JPEG_QUALITY, 93])
    print(f"\n[OK] 输出: {args.out}  ({full.shape[1]}x{full.shape[0]}px)")
    print("说明: 左=RGB  右=IR热力图  青色椭圆=wok区域  delta=两帧时间差")


if __name__ == "__main__":
    main()
