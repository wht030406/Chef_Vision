import json
import os
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class FrameShiftState:
    prev_ir: object = None
    prev_ir_idx: int | None = None
    total_dx: float = 0.0
    total_dy: float = 0.0


@dataclass
class FrameShiftUpdate:
    wok_mask_ir: object
    wok_cx: float
    wok_cy: float
    wok_rgb_constraint: object
    disable_static_rgb_mask: bool
    history_entry: tuple[int, float, float] | None


@dataclass
class LegacyHotRingUpdate:
    wok_cx: float
    wok_cy: float
    wok_rx: float
    wok_ry: float
    wok_mask_ir: object
    wok_rgb_constraint: object
    disable_static_rgb_mask: bool
    history_entry: tuple[int, float, float] | None
    hot_ref_ready: bool
    hot_sx: float
    hot_sy: float
    recent_drifts: list[float]
    tilting: bool


@dataclass
class IrWokStrategyUpdate:
    wok_mask_ir: object
    wok_cx: float
    wok_cy: float
    wok_rx: float
    wok_ry: float
    wok_rgb_constraint: object
    disable_static_rgb_mask: bool
    history_entry: tuple[int, float, float] | None
    hot_ref_ready: bool
    hot_sx: float
    hot_sy: float
    recent_drifts: list[float]
    tilting: bool


def build_ir_wok_mask(wok_cfg, ir_shape):
    ir_h, ir_w = ir_shape
    mask = np.zeros((ir_h, ir_w), dtype=np.uint8)
    cv2.ellipse(
        mask,
        (int(wok_cfg["cx"]), int(wok_cfg["cy"])),
        (int(wok_cfg["rx"]), int(wok_cfg["ry"])),
        0,
        0,
        360,
        255,
        -1,
    )
    return mask > 0


def load_ir_wok_region(wok_cfg_path, temp_data):
    if temp_data is None:
        print("[IR Mask] skipped: no temperature data")
        return None, None
    if not os.path.exists(wok_cfg_path):
        print(f"[IR Mask] skipped: wok config not found: {wok_cfg_path}")
        return None, None

    with open(wok_cfg_path, "r", encoding="utf-8") as file_obj:
        wok_cfg = json.load(file_obj)
    wok_mask_ir = build_ir_wok_mask(wok_cfg, temp_data.shape[1:3])
    print(f"[IR Mask] loaded: {wok_cfg_path}")
    print(
        f"  cx={wok_cfg['cx']} cy={wok_cfg['cy']} "
        f"rx={wok_cfg['rx']} ry={wok_cfg['ry']}  "
        f"pixels={int(wok_mask_ir.sum())}"
    )
    return wok_cfg, wok_mask_ir


def estimate_ir_frame_translation(prev_ir, curr_ir, max_shift=20.0, min_response=0.08):
    if prev_ir is None or curr_ir is None or prev_ir.shape != curr_ir.shape:
        return 0.0, 0.0, 0.0, False

    def _prep(frame):
        img = np.asarray(frame, dtype=np.float32)
        finite = np.isfinite(img)
        if not finite.any():
            return None
        lo, hi = np.percentile(img[finite], [2, 98])
        if hi <= lo:
            return None
        img = np.clip(img, lo, hi)
        img = (img - lo) / max(hi - lo, 1e-6)
        img = cv2.GaussianBlur(img, (3, 3), 0)
        img = img - cv2.GaussianBlur(img, (0, 0), 5)
        return img.astype(np.float32)

    prev = _prep(prev_ir)
    curr = _prep(curr_ir)
    if prev is None or curr is None:
        return 0.0, 0.0, 0.0, False

    try:
        win = cv2.createHanningWindow((prev.shape[1], prev.shape[0]), cv2.CV_32F)
        (dx, dy), response = cv2.phaseCorrelate(prev, curr, win)
    except Exception:
        return 0.0, 0.0, 0.0, False

    if (not np.isfinite(dx) or not np.isfinite(dy)
            or not np.isfinite(response)
            or abs(dx) > max_shift or abs(dy) > max_shift
            or response < min_response):
        return float(dx), float(dy), float(response), False
    return float(dx), float(dy), float(response), True


def translate_binary_mask(mask, dx, dy):
    if mask is None:
        return None
    h, w = mask.shape[:2]
    mat = np.array([[1.0, 0.0, float(dx)], [0.0, 1.0, float(dy)]], dtype=np.float32)
    moved = cv2.warpAffine(
        mask.astype(np.uint8),
        mat,
        (w, h),
        flags=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    return moved > 0


def project_ir_wok_to_rgb_constraint(wok_mask_ir, homography, rgb_shape):
    if wok_mask_ir is None or homography is None:
        return None
    rgb_h, rgb_w = rgb_shape
    h_inv = np.linalg.inv(homography)
    wok_u8 = wok_mask_ir.astype(np.uint8) * 255
    projected = cv2.warpPerspective(wok_u8, h_inv, (rgb_w, rgb_h))
    return projected > 64


def estimate_wok_center_from_ir_edge(ir_frame, cx, cy, rx, ry,
                                     n_angles=160,
                                     r_min=0.72, r_max=1.32,
                                     min_sectors=7,
                                     min_points=35):
    """Estimate the IR wok ellipse from the temperature cliff near the rim."""
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

        sector = ai * 16 // n_angles
        points.append((
            float(xs_v[bi]), float(ys_v[bi]), r_edge, th,
            best_drop, inner_med, outer_med, sector,
        ))
        sectors.add(sector)

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

    drop_thr = float(np.percentile(drop_arr[keep_radius], 65))
    inner_thr = float(np.percentile(inner_arr[keep_radius], 55))
    keep_strong = keep_radius & (drop_arr >= drop_thr) & (inner_arr >= inner_thr)
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


def estimate_wok_from_ir_hot_ring(ir_frame, cx, cy, rx, ry,
                                  n_angles=160,
                                  r_min=0.58, r_max=1.08,
                                  min_sectors=7,
                                  min_points=28):
    """Track the visible hot wok rim and estimate the business wok ellipse."""
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
            peak_t, inner_med, outer_med, ai * 16 // n_angles,
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
    """Refine a manually provided RGB wok ellipse from visible edge pixels."""
    try:
        h, w = frame_bgr.shape[:2]
        outer_mask = np.zeros((h, w), dtype=np.uint8)
        inner_mask = np.zeros((h, w), dtype=np.uint8)
        cv2.ellipse(outer_mask, (int(cx), int(cy)),
                    (int(rx * 1.15), int(ry * 1.15)), 0, 0, 360, 255, -1)
        cv2.ellipse(inner_mask, (int(cx), int(cy)),
                    (int(rx * 0.80), int(ry * 0.80)), 0, 0, 360, 255, -1)
        ring_mask = (outer_mask > 0) & (inner_mask == 0)

        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        gray_ring = cv2.bitwise_and(gray, gray, mask=ring_mask.astype(np.uint8))
        blurred = cv2.GaussianBlur(gray_ring, (5, 5), 1.2)
        edges = cv2.Canny(blurred, 30, 90)
        edges = cv2.bitwise_and(edges, edges, mask=ring_mask.astype(np.uint8))

        ys, xs = np.where(edges > 0)
        if len(xs) < 20:
            return cx, cy, rx, ry

        pts = np.column_stack([xs, ys]).astype(np.float32)
        ellipse = cv2.fitEllipse(pts)
        (ecx, ecy), (ew, eh), _ = ellipse
        if abs(ecx - cx) > rx * 0.3 or abs(ecy - cy) > ry * 0.3:
            return cx, cy, rx, ry

        new_rx = max(ew, eh) / 2.0 - shrink_px
        new_ry = min(ew, eh) / 2.0 - shrink_px
        if new_rx < rx * 0.5 or new_ry < ry * 0.5:
            return cx, cy, rx, ry

        print(f"[wok-rgb-refine] success "
              f"cx={ecx:.0f}({cx:.0f}) cy={ecy:.0f}({cy:.0f}) "
              f"rx={new_rx:.0f}({rx:.0f}) ry={new_ry:.0f}({ry:.0f})")
        return float(ecx), float(ecy), float(new_rx), float(new_ry)
    except Exception as exc:
        print(f"[wok-rgb-refine] failed ({exc}), keep original ellipse")
        return cx, cy, rx, ry


def init_frame_shift_state(ir_wok_strategy, temp_data, wok_mask_ir, start_frame, get_ir_idx):
    state = FrameShiftState()
    if ir_wok_strategy == "frame_shift" and temp_data is not None and wok_mask_ir is not None:
        state.prev_ir_idx = get_ir_idx(start_frame)
        if state.prev_ir_idx < temp_data.shape[0]:
            state.prev_ir = temp_data[state.prev_ir_idx].copy()
            print(f"[IR Mask] frame_shift reference IR frame={state.prev_ir_idx}")
    return state


def apply_frame_shift_update(
    ir_wok_strategy,
    temp_data,
    wok_mask_ir,
    chunk_start_abs,
    get_ir_idx,
    frame_shift_state,
    wok_cx,
    wok_cy,
    homography,
    rgb_shape,
):
    wok_rgb_constraint = None
    disable_static_rgb_mask = False
    history_entry = None

    if (ir_wok_strategy != "frame_shift"
            or temp_data is None
            or wok_mask_ir is None):
        return FrameShiftUpdate(
            wok_mask_ir=wok_mask_ir,
            wok_cx=wok_cx,
            wok_cy=wok_cy,
            wok_rgb_constraint=wok_rgb_constraint,
            disable_static_rgb_mask=disable_static_rgb_mask,
            history_entry=history_entry,
        )

    try:
        ir_idx_shift = get_ir_idx(chunk_start_abs)
        if ir_idx_shift < temp_data.shape[0]:
            ir_frame_shift = temp_data[ir_idx_shift]
            if (frame_shift_state.prev_ir is not None
                    and frame_shift_state.prev_ir_idx != ir_idx_shift):
                dx, dy, response, ok = estimate_ir_frame_translation(
                    frame_shift_state.prev_ir, ir_frame_shift)
                if ok:
                    wok_mask_ir = translate_binary_mask(wok_mask_ir, dx, dy)
                    wok_cx += dx
                    wok_cy += dy
                    frame_shift_state.total_dx += dx
                    frame_shift_state.total_dy += dy
                    if homography is not None:
                        wok_rgb_constraint = project_ir_wok_to_rgb_constraint(
                            wok_mask_ir, homography, rgb_shape)
                        disable_static_rgb_mask = True
                    history_entry = (chunk_start_abs, wok_cx, wok_cy)
                    print(f"[IR Mask] frame_shift f={chunk_start_abs} "
                          f"ir={frame_shift_state.prev_ir_idx}->{ir_idx_shift} "
                          f"dx={dx:.2f} dy={dy:.2f} resp={response:.3f} "
                          f"total=({frame_shift_state.total_dx:.1f},{frame_shift_state.total_dy:.1f})")
                else:
                    print(f"[IR Mask] frame_shift skip f={chunk_start_abs} "
                          f"ir={frame_shift_state.prev_ir_idx}->{ir_idx_shift} "
                          f"dx={dx:.2f} dy={dy:.2f} resp={response:.3f}")
            frame_shift_state.prev_ir = ir_frame_shift.copy()
            frame_shift_state.prev_ir_idx = ir_idx_shift
    except Exception as exc:
        print(f"[IR Mask] frame_shift failed: {exc}")

    return FrameShiftUpdate(
        wok_mask_ir=wok_mask_ir,
        wok_cx=wok_cx,
        wok_cy=wok_cy,
        wok_rgb_constraint=wok_rgb_constraint,
        disable_static_rgb_mask=disable_static_rgb_mask,
        history_entry=history_entry,
    )


def apply_legacy_hot_ring_update(
    hot_fit,
    wok_cfg,
    wok_cx,
    wok_cy,
    wok_rx,
    wok_ry,
    hot_ref_ready,
    hot_sx,
    hot_sy,
    max_drift,
    chunk_start_abs,
    chunk_start_s,
    homography,
    rgb_shape,
    recent_drifts,
    tilting,
    ir_shape,
):
    wok_mask_ir = None
    wok_rgb_constraint = None
    disable_static_rgb_mask = False
    history_entry = None
    updated_recent_drifts = list(recent_drifts)
    updated_tilting = tilting

    if not hot_fit:
        return LegacyHotRingUpdate(
            wok_cx=wok_cx,
            wok_cy=wok_cy,
            wok_rx=wok_rx,
            wok_ry=wok_ry,
            wok_mask_ir=wok_mask_ir,
            wok_rgb_constraint=wok_rgb_constraint,
            disable_static_rgb_mask=disable_static_rgb_mask,
            history_entry=history_entry,
            hot_ref_ready=hot_ref_ready,
            hot_sx=hot_sx,
            hot_sy=hot_sy,
            recent_drifts=updated_recent_drifts,
            tilting=updated_tilting,
        )

    if not hot_fit.get("ok"):
        print(f"[wok-hot] t={chunk_start_s:.1f}s  skip: {hot_fit.get('reason')}")
        return LegacyHotRingUpdate(
            wok_cx=wok_cx,
            wok_cy=wok_cy,
            wok_rx=wok_rx,
            wok_ry=wok_ry,
            wok_mask_ir=wok_mask_ir,
            wok_rgb_constraint=wok_rgb_constraint,
            disable_static_rgb_mask=disable_static_rgb_mask,
            history_entry=history_entry,
            hot_ref_ready=hot_ref_ready,
            hot_sx=hot_sx,
            hot_sy=hot_sy,
            recent_drifts=updated_recent_drifts,
            tilting=updated_tilting,
        )

    ring_cx = float(hot_fit["cx"])
    ring_cy = float(hot_fit["cy"])
    ring_rx = float(hot_fit["rx"])
    ring_ry = float(hot_fit["ry"])
    if not hot_ref_ready:
        hot_sx = float(np.clip(wok_rx / max(ring_rx, 1.0), 1.02, 1.40))
        hot_sy = float(np.clip(wok_ry / max(ring_ry, 1.0), 1.02, 1.40))
        hot_ref_ready = True
        print(f"[wok-hot] expand locked  sx={hot_sx:.3f} sy={hot_sy:.3f}")

    cx_candidate = ring_cx
    cy_candidate = ring_cy
    rx_candidate = ring_rx * hot_sx
    ry_candidate = ring_ry * hot_sy
    raw_drift = (((cx_candidate - wok_cx) ** 2 + (cy_candidate - wok_cy) ** 2) ** 0.5)
    init_drift = (((cx_candidate - float(wok_cfg["cx"])) ** 2
                   + (cy_candidate - float(wok_cfg["cy"])) ** 2) ** 0.5)
    max_init_drift = max(12.0, max(wok_rx, wok_ry) * 0.28)
    rx_init_ratio = rx_candidate / max(float(wok_cfg["rx"]), 1.0)
    ry_init_ratio = ry_candidate / max(float(wok_cfg["ry"]), 1.0)

    if raw_drift > max_drift:
        print(f"[wok-edge] t={chunk_start_s:.1f}s  "
              f"reject drift={raw_drift:.1f}px>{max_drift}px")
    elif init_drift > max_init_drift:
        print(f"[wok-edge] t={chunk_start_s:.1f}s  "
              f"reject cumulative={init_drift:.1f}px>{max_init_drift:.1f}px")
    elif (rx_init_ratio < 0.78 or rx_init_ratio > 1.22
          or ry_init_ratio < 0.78 or ry_init_ratio > 1.22):
        print(f"[wok-edge] t={chunk_start_s:.1f}s  "
              f"reject radius rx={rx_init_ratio:.2f} ry={ry_init_ratio:.2f}")
    elif raw_drift > 0.5:
        cx_old, cy_old = wok_cx, wok_cy
        rx_old, ry_old = wok_rx, wok_ry
        smooth = 0.35
        r_smooth = 0.18
        wok_cx = wok_cx * (1.0 - smooth) + cx_candidate * smooth
        wok_cy = wok_cy * (1.0 - smooth) + cy_candidate * smooth
        wok_rx = wok_rx * (1.0 - r_smooth) + rx_candidate * r_smooth
        wok_ry = wok_ry * (1.0 - r_smooth) + ry_candidate * r_smooth
        drift = (((wok_cx - cx_old) ** 2 + (wok_cy - cy_old) ** 2) ** 0.5)

        ir_h, ir_w = ir_shape
        wm_new = np.zeros((ir_h, ir_w), dtype=np.uint8)
        cv2.ellipse(
            wm_new,
            (int(round(wok_cx)), int(round(wok_cy))),
            (int(round(wok_rx)), int(round(wok_ry))),
            0,
            0,
            360,
            255,
            -1,
        )
        wok_mask_ir = wm_new > 0
        if homography is not None:
            wok_rgb_constraint = project_ir_wok_to_rgb_constraint(
                wok_mask_ir, homography, rgb_shape)
            disable_static_rgb_mask = True
        history_entry = (chunk_start_abs, wok_cx, wok_cy)
        print(f"[wok-hot] t={chunk_start_s:.1f}s  "
              f"cx: {cx_old:.1f}->{wok_cx:.1f}  "
              f"cy: {cy_old:.1f}->{wok_cy:.1f}  "
              f"rx: {rx_old:.1f}->{wok_rx:.1f}  "
              f"ry: {ry_old:.1f}->{wok_ry:.1f}  "
              f"raw={raw_drift:.1f}px step={drift:.1f}px  "
              f"pts={hot_fit['points']} sectors={hot_fit['sectors']} "
              f"peak={hot_fit['peak']:.1f} mode={hot_fit['fit_mode']}")

        updated_recent_drifts.append(drift)
        if len(updated_recent_drifts) > 3:
            updated_recent_drifts.pop(0)
        cum_drift = sum(updated_recent_drifts)
        was_tilting = updated_tilting
        updated_tilting = (len(updated_recent_drifts) >= 2 and cum_drift > 30.0)
        if updated_tilting and not was_tilting:
            print(f"[tilt] t={chunk_start_s:.1f}s  "
                  f"detected quick wok motion (cum drift={cum_drift:.1f}px)")
        elif was_tilting and not updated_tilting:
            print(f"[tilt] t={chunk_start_s:.1f}s  "
                  f"wok motion stabilized (cum drift={cum_drift:.1f}px)")

    return LegacyHotRingUpdate(
        wok_cx=wok_cx,
        wok_cy=wok_cy,
        wok_rx=wok_rx,
        wok_ry=wok_ry,
        wok_mask_ir=wok_mask_ir,
        wok_rgb_constraint=wok_rgb_constraint,
        disable_static_rgb_mask=disable_static_rgb_mask,
        history_entry=history_entry,
        hot_ref_ready=hot_ref_ready,
        hot_sx=hot_sx,
        hot_sy=hot_sy,
        recent_drifts=updated_recent_drifts,
        tilting=updated_tilting,
    )


def apply_ir_wok_strategy_update(
    ir_wok_strategy,
    temp_data,
    wok_cfg,
    wok_mask_ir,
    chunk_start_abs,
    chunk_start_s,
    get_ir_idx,
    frame_shift_state,
    wok_cx,
    wok_cy,
    wok_rx,
    wok_ry,
    homography,
    rgb_shape,
    hot_ref_ready,
    hot_sx,
    hot_sy,
    max_drift,
    recent_drifts,
    tilting,
    allow_legacy_update,
    estimate_hot_ring,
):
    wok_rgb_constraint = None
    disable_static_rgb_mask = False
    history_entry = None

    frame_shift_update = apply_frame_shift_update(
        ir_wok_strategy,
        temp_data,
        wok_mask_ir,
        chunk_start_abs,
        get_ir_idx,
        frame_shift_state,
        wok_cx,
        wok_cy,
        homography,
        rgb_shape,
    )
    wok_mask_ir = frame_shift_update.wok_mask_ir
    wok_cx = frame_shift_update.wok_cx
    wok_cy = frame_shift_update.wok_cy
    if frame_shift_update.wok_rgb_constraint is not None:
        wok_rgb_constraint = frame_shift_update.wok_rgb_constraint
    if frame_shift_update.disable_static_rgb_mask:
        disable_static_rgb_mask = True
    if frame_shift_update.history_entry is not None:
        history_entry = frame_shift_update.history_entry

    if (ir_wok_strategy == "legacy"
            and wok_cfg is not None
            and temp_data is not None
            and allow_legacy_update
            and homography is not None):
        ir_idx = get_ir_idx(chunk_start_abs)
        ir_frame = temp_data[ir_idx]
        hot_fit = estimate_hot_ring(ir_frame, wok_cx, wok_cy, wok_rx, wok_ry)
        legacy_update = apply_legacy_hot_ring_update(
            hot_fit,
            wok_cfg,
            wok_cx,
            wok_cy,
            wok_rx,
            wok_ry,
            hot_ref_ready,
            hot_sx,
            hot_sy,
            max_drift,
            chunk_start_abs,
            chunk_start_s,
            homography,
            rgb_shape,
            recent_drifts,
            tilting,
            ir_frame.shape[:2],
        )
        wok_cx = legacy_update.wok_cx
        wok_cy = legacy_update.wok_cy
        wok_rx = legacy_update.wok_rx
        wok_ry = legacy_update.wok_ry
        hot_ref_ready = legacy_update.hot_ref_ready
        hot_sx = legacy_update.hot_sx
        hot_sy = legacy_update.hot_sy
        recent_drifts = legacy_update.recent_drifts
        tilting = legacy_update.tilting
        if legacy_update.wok_mask_ir is not None:
            wok_mask_ir = legacy_update.wok_mask_ir
        if legacy_update.wok_rgb_constraint is not None:
            wok_rgb_constraint = legacy_update.wok_rgb_constraint
        if legacy_update.disable_static_rgb_mask:
            disable_static_rgb_mask = True
        if legacy_update.history_entry is not None:
            history_entry = legacy_update.history_entry

    return IrWokStrategyUpdate(
        wok_mask_ir=wok_mask_ir,
        wok_cx=wok_cx,
        wok_cy=wok_cy,
        wok_rx=wok_rx,
        wok_ry=wok_ry,
        wok_rgb_constraint=wok_rgb_constraint,
        disable_static_rgb_mask=disable_static_rgb_mask,
        history_entry=history_entry,
        hot_ref_ready=hot_ref_ready,
        hot_sx=hot_sx,
        hot_sy=hot_sy,
        recent_drifts=recent_drifts,
        tilting=tilting,
    )
