import os

import cv2
import numpy as np


def build_inverse_inject_keyframes(bottom_inject_map, chunk_start_abs, chunk_end_abs):
    """Collect inverse-tracking keyframes that fall inside the current chunk."""
    inject_keyframes = []
    for abs_frame, keyframe in bottom_inject_map.items():
        if chunk_start_abs <= abs_frame < chunk_end_abs:
            inject_keyframes.append({
                "local_frame": abs_frame - chunk_start_abs,
                "fg_points": keyframe["fg_points"],
                "bg_points": keyframe.get("bg_points", []),
                "label": keyframe.get("label", ""),
            })
    return inject_keyframes


def build_inverse_autopoints_preview_path(out_dir, time_text, frame_idx):
    """Build the preview image path for inverse auto-point generation."""
    return os.path.join(out_dir, f"inverse_autopoints_t{time_text}s_f{frame_idx}.jpg")


def build_inverse_auto_reset(frame_idx, reason=None, old_mask=None, ratio=None):
    """Store a pending inverse restart request after failure is detected."""
    return {
        "frame": frame_idx,
        "reason": reason,
        "old_mask": old_mask,
        "ratio": ratio,
    }


def apply_inverse_auto_reset(auto_reset_payload):
    """Normalize a pending inverse restart request for chunk startup."""
    return {
        "frame": auto_reset_payload.get("frame"),
        "reason": auto_reset_payload.get("reason"),
        "old_mask": auto_reset_payload.get("old_mask"),
        "ratio": auto_reset_payload.get("ratio"),
    }


def build_inverse_point_result(fg_points, bg_points, ok):
    """Standardize IR-derived inverse point generation results."""
    return {
        "fg_points": fg_points,
        "bg_points": bg_points,
        "ok": bool(ok),
    }


def evaluate_inverse_reset(raw_inv_ratio, min_ratio=5.0, max_ratio=60.0):
    """Evaluate whether inverse semantic tracking should auto-reset."""
    too_small = raw_inv_ratio < min_ratio
    too_large = raw_inv_ratio > max_ratio
    return {
        "need_reset": bool(too_small or too_large),
        "too_small": too_small,
        "too_large": too_large,
        "ratio": float(raw_inv_ratio),
        "min_ratio": float(min_ratio),
        "max_ratio": float(max_ratio),
    }


def describe_inverse_reset(decision):
    """Build a short reason string for inverse auto-reset logging."""
    if decision["too_small"]:
        return f"inv_ratio<{decision['min_ratio']:.0f}%"
    if decision["too_large"]:
        return f"inv_ratio>{decision['max_ratio']:.0f}%"
    return "inv_ratio_ok"


def is_inverse_ratio_stable(raw_inv_ratio, min_ratio=5.0, max_ratio=60.0):
    """Return True when inverse area is inside the healthy range."""
    return float(min_ratio) <= float(raw_inv_ratio) <= float(max_ratio)


def _largest_component(mask_u8):
    if mask_u8 is None or int(mask_u8.sum()) == 0:
        return mask_u8
    cc_n, cc_lbl, cc_stats, _ = cv2.connectedComponentsWithStats(mask_u8, connectivity=8)
    if cc_n <= 1:
        return mask_u8
    max_cc = 1 + int(np.argmax(cc_stats[1:, cv2.CC_STAT_AREA]))
    return (cc_lbl == max_cc).astype(np.uint8) * 255


def _select_spread_points(
    mask_ir,
    homography_inv,
    wok_rgb_constraint,
    n,
    rng,
    gray_frame=None,
    max_gray=None,
    axis_cx=None,
    axis_cy=None,
    axis_excl_r=None,
):
    if mask_ir is None or not np.any(mask_ir) or n <= 0:
        return []

    mask_u8 = mask_ir.astype(np.uint8) * 255
    dist = cv2.distanceTransform(mask_u8, cv2.DIST_L2, 5)
    max_dist = float(dist.max())
    if max_dist <= 0.0:
        return []

    ys, xs = np.where(mask_ir)
    if len(xs) == 0:
        return []

    scores = dist[ys, xs]
    h, w = wok_rgb_constraint.shape
    jitter = rng.random(len(xs)) * 1e-3
    order = np.lexsort((jitter, -scores))

    def _collect_with_spacing(min_spacing):
        pts_ir = []
        pts_rgb = []
        for idx in order:
            x_ir = float(xs[idx])
            y_ir = float(ys[idx])
            if any((x_ir - px) ** 2 + (y_ir - py) ** 2 < (min_spacing ** 2) for px, py in pts_ir):
                continue
            pt_ir = np.array([[[x_ir, y_ir]]], dtype=np.float32)
            pt_rgb = cv2.perspectiveTransform(pt_ir, homography_inv).reshape(-1, 2)[0]
            xi = int(round(float(pt_rgb[0])))
            yi = int(round(float(pt_rgb[1])))
            if not (0 <= xi < w and 0 <= yi < h):
                continue
            if not wok_rgb_constraint[yi, xi]:
                continue
            if gray_frame is not None and max_gray is not None and int(gray_frame[yi, xi]) > int(max_gray):
                continue
            if axis_cx is not None and axis_cy is not None and axis_excl_r is not None:
                if ((xi - axis_cx) ** 2 + (yi - axis_cy) ** 2) ** 0.5 < axis_excl_r:
                    continue
            pts_ir.append((x_ir, y_ir))
            pts_rgb.append([float(xi), float(yi)])
            if len(pts_rgb) >= n:
                break
        return pts_rgb

    spacing_levels = [
        max(3.0, max_dist * 0.55),
        max(3.0, max_dist * 0.40),
        max(3.0, max_dist * 0.28),
        max(2.0, max_dist * 0.18),
        0.0,
    ]
    best_pts = []
    for spacing in spacing_levels:
        pts = _collect_with_spacing(spacing)
        if len(pts) > len(best_pts):
            best_pts = pts
        if len(best_pts) >= n:
            break

    return best_pts


def generate_inverse_bottom_points_from_ir(
    rgb_frame,
    ir_frame,
    wok_mask_ir,
    homography_inv,
    wok_rgb_constraint,
    n_fg=10,
    n_bg=10,
    rng=None,
    preview_path=None,
    old_mask=None,
    reason_text=None,
    gray_frame=None,
    fg_max_gray=210,
    axis_cx=None,
    axis_cy=None,
    axis_excl_r=None,
):
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
    food_ir = cv2.morphologyEx(food_ir, cv2.MORPH_OPEN, kernel)
    hot_ir = cv2.morphologyEx(hot_ir, cv2.MORPH_OPEN, kernel)
    food_ir = _largest_component(food_ir) > 0
    hot_ir = _largest_component(hot_ir) > 0

    if gray_frame is None and rgb_frame is not None:
        gray_frame = cv2.cvtColor(rgb_frame, cv2.COLOR_BGR2GRAY)

    fg_pts = _select_spread_points(
        hot_ir,
        homography_inv,
        wok_rgb_constraint,
        n_fg,
        rng,
        gray_frame=gray_frame,
        max_gray=fg_max_gray,
    )
    bg_pts = _select_spread_points(
        food_ir,
        homography_inv,
        wok_rgb_constraint,
        n_bg,
        rng,
        axis_cx=axis_cx,
        axis_cy=axis_cy,
        axis_excl_r=axis_excl_r,
    )
    ok = len(fg_pts) >= 4 and len(bg_pts) >= 4

    if ok and preview_path:
        vis = rgb_frame.copy()
        shade = np.zeros_like(vis)
        shade[wok_rgb_constraint] = (70, 70, 70)
        vis = cv2.addWeighted(vis, 1.0, shade, 0.25, 0)
        if old_mask is not None and np.any(old_mask):
            vis[old_mask] = (
                vis[old_mask].astype(float) * 0.5
                + np.array([0, 0, 220]) * 0.5
            ).astype(np.uint8)
        for x, y in fg_pts:
            cv2.circle(vis, (int(x), int(y)), 8, (0, 255, 80), -1)
            cv2.circle(vis, (int(x), int(y)), 9, (0, 0, 0), 1)
        for x, y in bg_pts:
            cv2.circle(vis, (int(x), int(y)), 8, (255, 80, 0), -1)
            cv2.circle(vis, (int(x), int(y)), 9, (0, 0, 0), 1)
        header = (reason_text if reason_text
                  else f"Inverse auto points FG-hot={len(fg_pts)} BG-food={len(bg_pts)}")
        cv2.putText(vis, header,
                    (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        cv2.putText(vis,
                    f"[red=old bad mask | green=FG-hot({len(fg_pts)}) | blue=BG-food({len(bg_pts)})]",
                    (20, 78), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (255, 255, 255), 2)
        cv2.putText(vis, f"K-low/high=({c_low:.1f},{c_high:.1f})C",
                    (20, 112), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2)
        cv2.imwrite(preview_path, vis)

    return fg_pts, bg_pts, ok
