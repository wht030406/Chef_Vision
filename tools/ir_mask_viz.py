"""
IR mask visualization and manual wok-region setup.

This tool serves two jobs:
1. Interactively label the IR wok ellipse, stir-axis center, and axis exclusion radius.
2. Render an IR-only preview video using the currently selected food-segmentation mode.
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime

import cv2
import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_CORE_DIR = os.path.abspath(os.path.join(_HERE, "..", "core"))
if _CORE_DIR not in sys.path:
    sys.path.insert(0, _CORE_DIR)

from ir_food_seg import SEG_KMEANS, SEG_PERCENTILE, SEG_TWO_CLUSTER, segment_ir_food


DEFAULT_NPY = os.path.join(_HERE, "..", "test_data", "test1", "temp_20260529_112414.npy")
OUTPUT_DIR = os.path.join(_HERE, "..", "output")
WOK_CFG_PATH = os.path.join(_HERE, "..", "data", "wok_region.json")

IR_W, IR_H = 512, 384
CHART_H = 120
CURVE_WIN_S = 60
IR_FPS = 25.0

FOOD_PERCENTILE = 40
MIN_FOOD_AREA = 20


def _draw_food_boundary_overlay(ir_img, food_mask_u8):
    """Draw a high-contrast food boundary on top of the IR colormap."""
    if food_mask_u8 is None or not np.any(food_mask_u8):
        return
    contours, _ = cv2.findContours(food_mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return
    cv2.drawContours(ir_img, contours, -1, (0, 0, 0), 6)
    cv2.drawContours(ir_img, contours, -1, (255, 255, 255), 4)
    cv2.drawContours(ir_img, contours, -1, (255, 0, 220), 2)


def load_wok_region(ir_h, ir_w):
    """Load wok config and backfill newly added manual-axis fields."""
    default_cfg = {
        "cx": ir_w // 2,
        "cy": ir_h // 2,
        "rx": int(ir_w * 0.38),
        "ry": int(ir_h * 0.42),
        "axis_cx": ir_w // 2,
        "axis_cy": ir_h // 2,
        "axis_excl_r_ir": max(8, int(round(min(ir_w, ir_h) * 0.08))),
    }
    if os.path.exists(WOK_CFG_PATH):
        with open(WOK_CFG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        for key, value in default_cfg.items():
            cfg.setdefault(key, value)
        return cfg
    return default_cfg


def make_wok_mask(ir_h, ir_w, cfg):
    """Build the wok-area mask from the labeled ellipse."""
    mask = np.zeros((ir_h, ir_w), dtype=np.uint8)
    cv2.ellipse(
        mask,
        (int(cfg["cx"]), int(cfg["cy"])),
        (int(cfg["rx"]), int(cfg["ry"])),
        0, 0, 360, 255, -1,
    )
    return mask > 0


def _make_ir_color_frame(frame, out_w, out_h):
    t_min = float(np.min(frame))
    t_max = float(np.max(frame))
    norm = ((frame - t_min) / max(t_max - t_min, 0.1) * 255).astype(np.uint8)
    img = cv2.applyColorMap(norm, cv2.COLORMAP_JET)
    return cv2.resize(img, (out_w, out_h), interpolation=cv2.INTER_NEAREST)


def setup_wok_region(npy_path):
    """Interactively label wok ellipse, axis center, and axis exclusion radius."""
    data = np.load(npy_path)
    if data.ndim == 2:
        data = data[np.newaxis, ...]

    ref_frame = data[len(data) // 2]
    ir_h, ir_w = ref_frame.shape
    cfg = load_wok_region(ir_h, ir_w)

    cx, cy = int(cfg["cx"]), int(cfg["cy"])
    rx, ry = int(cfg["rx"]), int(cfg["ry"])
    axis_cx = int(cfg.get("axis_cx", cx))
    axis_cy = int(cfg.get("axis_cy", cy))
    axis_excl_r_ir = int(cfg.get("axis_excl_r_ir", max(8, int(round(min(ir_w, ir_h) * 0.08)))))

    scale = IR_W / ir_w
    disp_w, disp_h = IR_W, IR_H
    ellipse_state = {"dragging": False, "mode": "center"}
    radius_state = {"dragging": False, "mode": "radius"}
    axis_confirmed = False
    radius_confirmed = False

    def to_disp(x, y):
        return int(round(x * scale)), int(round(y * scale))

    def to_ir(x, y):
        return (
            max(0, min(ir_w - 1, int(round(x / scale)))),
            max(0, min(ir_h - 1, int(round(y / scale)))),
        )

    def base_img():
        return _make_ir_color_frame(ref_frame, disp_w, disp_h)

    def draw_phase1():
        img = base_img()
        dcx, dcy = to_disp(cx, cy)
        drx, dry = int(round(rx * scale)), int(round(ry * scale))
        cv2.ellipse(img, (dcx, dcy), (drx, dry), 0, 0, 360, (0, 255, 255), 2)
        cv2.circle(img, (dcx, dcy), 5, (0, 255, 255), -1)
        cv2.circle(img, (dcx + drx, dcy), 5, (255, 200, 0), -1)
        cv2.circle(img, (dcx, dcy + dry), 5, (255, 200, 0), -1)
        cv2.putText(img, "Phase 1: drag center / right handle / bottom handle",
                    (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
        cv2.putText(img, f"cx={cx} cy={cy} rx={rx} ry={ry}  [S]=confirm  [Q]=cancel",
                    (8, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (200, 255, 200), 1)
        return img

    def draw_phase2():
        img = base_img()
        dcx, dcy = to_disp(cx, cy)
        drx, dry = int(round(rx * scale)), int(round(ry * scale))
        ax, ay = to_disp(axis_cx, axis_cy)
        cv2.ellipse(img, (dcx, dcy), (drx, dry), 0, 0, 360, (120, 120, 120), 1)
        cv2.circle(img, (ax, ay), 8, (0, 255, 255), -1)
        cv2.circle(img, (ax, ay), 10, (255, 255, 255), 1)
        cv2.line(img, (ax - 14, ay), (ax + 14, ay), (0, 255, 255), 1)
        cv2.line(img, (ax, ay - 14), (ax, ay + 14), (0, 255, 255), 1)
        cv2.putText(img, "Phase 2: click the stir-axis center",
                    (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
        cv2.putText(img, f"axis_cx={axis_cx} axis_cy={axis_cy}  [S]=confirm  [Q]=keep current",
                    (8, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (200, 255, 200), 1)
        return img

    def draw_phase3():
        img = base_img()
        dcx, dcy = to_disp(cx, cy)
        drx, dry = int(round(rx * scale)), int(round(ry * scale))
        ax, ay = to_disp(axis_cx, axis_cy)
        rr = max(1, int(round(axis_excl_r_ir * scale)))
        cv2.ellipse(img, (dcx, dcy), (drx, dry), 0, 0, 360, (120, 120, 120), 1)
        cv2.circle(img, (ax, ay), rr, (20, 20, 20), 2)
        cv2.circle(img, (ax, ay), 6, (0, 255, 255), -1)
        cv2.circle(img, (ax + rr, ay), 6, (255, 80, 0), -1)
        cv2.putText(img, "Phase 3: drag center or radius handle",
                    (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
        cv2.putText(img, f"axis_excl_r_ir={axis_excl_r_ir}px  [S]=save  [Q]=keep current",
                    (8, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (200, 255, 200), 1)
        return img

    def phase1_mouse(event, x, y, flags, param):
        nonlocal cx, cy, rx, ry
        ix, iy = to_ir(x, y)
        dcx, dcy = to_disp(cx, cy)
        drx, dry = int(round(rx * scale)), int(round(ry * scale))
        if event == cv2.EVENT_LBUTTONDOWN:
            if abs(x - (dcx + drx)) < 12 and abs(y - dcy) < 12:
                ellipse_state["dragging"] = True
                ellipse_state["mode"] = "rx"
            elif abs(x - dcx) < 12 and abs(y - (dcy + dry)) < 12:
                ellipse_state["dragging"] = True
                ellipse_state["mode"] = "ry"
            elif abs(x - dcx) < 15 and abs(y - dcy) < 15:
                ellipse_state["dragging"] = True
                ellipse_state["mode"] = "center"
        elif event == cv2.EVENT_MOUSEMOVE and ellipse_state["dragging"]:
            if ellipse_state["mode"] == "center":
                cx, cy = ix, iy
            elif ellipse_state["mode"] == "rx":
                rx = max(5, abs(ix - cx))
            elif ellipse_state["mode"] == "ry":
                ry = max(5, abs(iy - cy))
        elif event == cv2.EVENT_LBUTTONUP:
            ellipse_state["dragging"] = False

    def phase2_mouse(event, x, y, flags, param):
        nonlocal axis_cx, axis_cy
        if event == cv2.EVENT_LBUTTONDOWN:
            axis_cx, axis_cy = to_ir(x, y)

    def phase3_mouse(event, x, y, flags, param):
        nonlocal axis_cx, axis_cy, axis_excl_r_ir
        ax, ay = to_disp(axis_cx, axis_cy)
        rr = max(1, int(round(axis_excl_r_ir * scale)))
        if event == cv2.EVENT_LBUTTONDOWN:
            radius_state["dragging"] = True
            if abs(x - ax) <= 12 and abs(y - ay) <= 12:
                radius_state["mode"] = "center"
            elif abs(x - (ax + rr)) <= 12 and abs(y - ay) <= 12:
                radius_state["mode"] = "radius"
            else:
                dist = ((x - ax) ** 2 + (y - ay) ** 2) ** 0.5
                radius_state["mode"] = "radius" if abs(dist - rr) <= 14 else "center"
        elif event == cv2.EVENT_LBUTTONUP:
            radius_state["dragging"] = False
        if event in (cv2.EVENT_LBUTTONDOWN, cv2.EVENT_MOUSEMOVE) and radius_state["dragging"]:
            ix, iy = to_ir(x, y)
            if radius_state["mode"] == "center":
                axis_cx, axis_cy = ix, iy
            else:
                axis_excl_r_ir = max(4, int(round(((ix - axis_cx) ** 2 + (iy - axis_cy) ** 2) ** 0.5)))

    win = "IR wok setup"
    cv2.namedWindow(win)
    cv2.setMouseCallback(win, phase1_mouse)

    while True:
        cv2.imshow(win, draw_phase1())
        key = cv2.waitKey(30) & 0xFF
        if key in (ord("s"), ord("S")):
            break
        if key in (ord("q"), ord("Q")):
            print("[QUIT] wok region not saved")
            cv2.destroyAllWindows()
            return

    cv2.setWindowTitle(win, "Phase 2: axis center")
    cv2.setMouseCallback(win, phase2_mouse)
    while True:
        cv2.imshow(win, draw_phase2())
        key = cv2.waitKey(30) & 0xFF
        if key in (ord("s"), ord("S")):
            axis_confirmed = True
            break
        if key in (ord("q"), ord("Q")):
            axis_cx = int(cfg.get("axis_cx", cx))
            axis_cy = int(cfg.get("axis_cy", cy))
            break

    cv2.setWindowTitle(win, "Phase 3: axis exclusion radius")
    cv2.setMouseCallback(win, phase3_mouse)
    while True:
        cv2.imshow(win, draw_phase3())
        key = cv2.waitKey(30) & 0xFF
        if key in (ord("s"), ord("S")):
            radius_confirmed = True
            break
        if key in (ord("q"), ord("Q")):
            axis_excl_r_ir = int(cfg.get("axis_excl_r_ir", axis_excl_r_ir))
            break

    cv2.destroyAllWindows()

    os.makedirs(os.path.dirname(WOK_CFG_PATH), exist_ok=True)
    cfg_save = {
        "cx": int(cx),
        "cy": int(cy),
        "rx": int(rx),
        "ry": int(ry),
        "axis_cx": int(axis_cx),
        "axis_cy": int(axis_cy),
        "axis_excl_r_ir": int(axis_excl_r_ir),
        "ir_h": int(ir_h),
        "ir_w": int(ir_w),
    }
    with open(WOK_CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg_save, f, indent=2)

    print(f"[OK] wok region saved: {WOK_CFG_PATH}")
    print(f"     cx={cx} cy={cy} rx={rx} ry={ry}")
    print(f"     axis_cx={axis_cx} axis_cy={axis_cy}"
          f"{'  (manual)' if axis_confirmed else '  (kept current/default)'}")
    print(f"     axis_excl_r_ir={axis_excl_r_ir}"
          f"{'  (manual)' if radius_confirmed else '  (kept current/default)'}")


def draw_chart(temp_history, cur_time_s, w, h, curve_win_s=60):
    bar = np.zeros((h, w, 3), dtype=np.uint8)
    if len(temp_history) < 2:
        cv2.putText(bar, "IR Mask Avg Temp (waiting...)",
                    (10, h // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (160, 160, 160), 1)
        return bar

    t0 = max(0.0, cur_time_s - curve_win_s)
    pts = [(t, v) for t, v in temp_history if t >= t0 and not np.isnan(v)]
    if len(pts) < 2:
        pts = temp_history[-2:]

    times = [p[0] for p in pts]
    vals = [p[1] for p in pts]
    t_min_ax = t0
    t_max_ax = max(cur_time_s, t0 + 1.0)
    v_min_ax = max(0.0, min(vals) - 5.0)
    v_max_ax = max(vals) + 5.0
    if v_max_ax <= v_min_ax:
        v_max_ax = v_min_ax + 10.0

    pad_l, pad_r, pad_t, pad_b = 48, 12, 10, 22

    def tx(t):
        return pad_l + int((t - t_min_ax) / (t_max_ax - t_min_ax) * (w - pad_l - pad_r))

    def ty(v):
        return pad_t + int((1.0 - (v - v_min_ax) / (v_max_ax - v_min_ax)) * (h - pad_t - pad_b))

    for v in np.linspace(v_min_ax, v_max_ax, 3):
        yy = ty(v)
        cv2.line(bar, (pad_l, yy), (w - pad_r, yy), (45, 45, 45), 1)
        cv2.putText(bar, f"{v:.0f}", (2, yy + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (180, 180, 180), 1)

    cv2.line(bar, (pad_l, pad_t), (pad_l, h - pad_b), (160, 160, 160), 1)
    cv2.line(bar, (pad_l, h - pad_b), (w - pad_r, h - pad_b), (160, 160, 160), 1)
    cv2.putText(bar, f"{t_min_ax:.0f}s", (pad_l, h - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.32, (140, 140, 140), 1)
    cv2.putText(bar, f"{cur_time_s:.1f}s", (w - pad_r - 30, h - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.32, (140, 140, 140), 1)

    screen_pts = [(tx(t), ty(v)) for t, v in zip(times, vals)]
    for i in range(1, len(screen_pts)):
        cv2.line(bar, screen_pts[i - 1], screen_pts[i], (0, 220, 100), 2)

    cx_pt, cy_pt = tx(cur_time_s), ty(vals[-1])
    if 0 <= cx_pt < w and 0 <= cy_pt < h:
        cv2.circle(bar, (cx_pt, cy_pt), 4, (0, 255, 80), -1)
        cv2.putText(bar, f"{vals[-1]:.1f}C", (cx_pt + 6, cy_pt + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 255, 120), 1)

    cv2.putText(bar, "IR Mask Avg Temp (C)", (pad_l + 4, pad_t + 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 220, 100), 1)
    return bar


def _normalize_seg_mode(seg_mode):
    normalized = (seg_mode or SEG_PERCENTILE).lower()
    if normalized in ("kmeans", SEG_KMEANS):
        return SEG_KMEANS
    if normalized in ("two_cluster", SEG_TWO_CLUSTER):
        return SEG_TWO_CLUSTER
    return SEG_PERCENTILE


def _segment_food(temp_frame, wok_mask, percentile, seg_mode):
    return segment_ir_food(
        temp_frame,
        wok_mask,
        mode=_normalize_seg_mode(seg_mode),
        percentile=percentile,
    )


def render_ir_frame(temp_frame, wok_cfg, pct=40, out_w=512, out_h=384, seg_mode="percentile"):
    """Render one IR frame with the selected segmentation mode."""
    ir_h, ir_w = temp_frame.shape
    scale_x = out_w / ir_w
    scale_y = out_h / ir_h
    wok_mask = make_wok_mask(ir_h, ir_w, wok_cfg)
    seg_result = _segment_food(temp_frame, wok_mask, pct, seg_mode)
    food_mask = seg_result.food_mask

    ir_img = _make_ir_color_frame(temp_frame, out_w, out_h)
    cv2.ellipse(
        ir_img,
        (int(round(wok_cfg["cx"] * scale_x)), int(round(wok_cfg["cy"] * scale_y))),
        (int(round(wok_cfg["rx"] * scale_x)), int(round(wok_cfg["ry"] * scale_y))),
        0, 0, 360, (255, 255, 255), 1,
    )

    if "axis_cx" in wok_cfg and "axis_cy" in wok_cfg and "axis_excl_r_ir" in wok_cfg:
        cv2.circle(
            ir_img,
            (int(round(wok_cfg["axis_cx"] * scale_x)), int(round(wok_cfg["axis_cy"] * scale_y))),
            max(1, int(round(wok_cfg["axis_excl_r_ir"] * scale_x))),
            (20, 20, 20),
            1,
        )

    food_resized = cv2.resize(food_mask.astype(np.uint8) * 255, (out_w, out_h), interpolation=cv2.INTER_NEAREST)
    food_bool = food_resized > 127
    ir_img[food_bool] = (ir_img[food_bool].astype(float) * 0.65 + np.array([255, 255, 255]) * 0.35).astype(np.uint8)
    _draw_food_boundary_overlay(ir_img, food_resized)

    mask_ratio = food_mask.sum() / wok_mask.sum() * 100 if wok_mask.sum() > 0 else 0.0
    food_temps = temp_frame[food_mask]
    temp_mean = float(np.mean(food_temps)) if len(food_temps) >= MIN_FOOD_AREA else float("nan")
    mode_label = "KMeans" if _normalize_seg_mode(seg_mode) in (SEG_KMEANS, SEG_TWO_CLUSTER) else f"Pct<={pct}%"
    cv2.putText(ir_img, f"mask={mask_ratio:.1f}%  avg={temp_mean:.1f}C",
                (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
    cv2.putText(ir_img, f"MAX:{float(np.max(temp_frame)):.1f}C  MIN:{float(np.min(temp_frame)):.1f}C  {mode_label}",
                (8, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (200, 200, 200), 1)
    return ir_img


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--npy", default=DEFAULT_NPY)
    parser.add_argument("--setup", action="store_true", help="Interactively label wok ellipse / axis / exclusion radius")
    parser.add_argument("--pct", type=int, default=FOOD_PERCENTILE)
    parser.add_argument("--seg-mode", default="percentile", choices=["percentile", "two_cluster", "kmeans"])
    args = parser.parse_args()

    if args.setup:
        setup_wok_region(args.npy)
        return

    if not os.path.exists(args.npy):
        print(f"[ERROR] missing temperature file: {args.npy}")
        sys.exit(1)

    data = np.load(args.npy)
    if data.ndim == 2:
        data = data[np.newaxis, ...]
    n_frames, ir_h, ir_w = data.shape
    print(f"[LOAD] {args.npy}")
    print(f"[TEMP] shape={data.shape}  range={data.min():.1f}C ~ {data.max():.1f}C")

    wok_cfg = load_wok_region(ir_h, ir_w)
    wok_mask = make_wok_mask(ir_h, ir_w, wok_cfg)
    print(f"[WOK] cx={wok_cfg['cx']} cy={wok_cfg['cy']} rx={wok_cfg['rx']} ry={wok_cfg['ry']}")
    print(f"      axis=({wok_cfg['axis_cx']},{wok_cfg['axis_cy']})  axis_excl_r_ir={wok_cfg['axis_excl_r_ir']}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_dir = os.path.join(OUTPUT_DIR, f"ir_mask_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(out_dir, exist_ok=True)
    out_video = os.path.join(out_dir, "ir_mask_viz.mp4")

    writer = cv2.VideoWriter(
        out_video,
        cv2.VideoWriter_fourcc(*"mp4v"),
        IR_FPS,
        (IR_W, IR_H + CHART_H),
    )

    temp_history = []
    csv_rows = []
    mode = _normalize_seg_mode(args.seg_mode)

    for i in range(n_frames):
        frame = data[i]
        time_s = i / IR_FPS
        seg_result = _segment_food(frame, wok_mask, args.pct, mode)
        food_mask = seg_result.food_mask
        mask_ratio = food_mask.sum() / wok_mask.sum() * 100 if wok_mask.sum() > 0 else 0.0
        food_vals = frame[food_mask]
        temp_mean = float(np.mean(food_vals)) if len(food_vals) >= MIN_FOOD_AREA else float("nan")
        if not np.isnan(temp_mean):
            temp_history.append((time_s, temp_mean))
        csv_rows.append([i, f"{time_s:.3f}", "" if np.isnan(temp_mean) else f"{temp_mean:.2f}"])

        ir_img = render_ir_frame(frame, wok_cfg, pct=args.pct, out_w=IR_W, out_h=IR_H, seg_mode=mode)
        cv2.putText(ir_img, f"t={time_s:.1f}s", (8, 58),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1)
        cv2.putText(ir_img, f"mode={mode}  mask={mask_ratio:.1f}%",
                    (8, 76), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (200, 200, 200), 1)
        writer.write(np.vstack([ir_img, draw_chart(temp_history, time_s, IR_W, CHART_H, CURVE_WIN_S)]))

        if i % 200 == 0:
            print(f"  frame {i}/{n_frames}  mask={mask_ratio:.1f}%  temp={temp_mean:.1f}C", end="\r")

    writer.release()
    print(f"\n[DONE] video: {out_video}")

    csv_path = os.path.join(out_dir, "ir_mask_temp.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer_csv = csv.writer(f)
        writer_csv.writerow(["frame", "time_s", "ir_mask_temp_mean"])
        writer_csv.writerows(csv_rows)
    print(f"[DONE] csv: {csv_path}")


if __name__ == "__main__":
    main()
