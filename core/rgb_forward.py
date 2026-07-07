import cv2
import numpy as np


def build_forward_inject_keyframe(fg_points, bg_points=None, label="", local_frame=0):
    """Build a standard injection payload for forward SAM2 tracking."""
    return {
        "local_frame": local_frame,
        "fg_points": fg_points,
        "bg_points": bg_points or [],
        "label": label,
    }


def build_forward_axis_bg(axis_cx, axis_cy):
    """Build the optional axis-center background point list for forward injection."""
    if axis_cx is None or axis_cy is None:
        return []
    return [[axis_cx, axis_cy]]


def build_forward_ir_inject(fg_points, axis_cx=None, axis_cy=None, label="",
                            local_frame=0, bg_points=None, append_axis_bg=True):
    """Build a standard IR-derived forward injection payload."""
    merged_bg = list(bg_points or [])
    if append_axis_bg:
        merged_bg.extend(build_forward_axis_bg(axis_cx, axis_cy))
    return build_forward_inject_keyframe(
        fg_points,
        merged_bg,
        label=label,
        local_frame=local_frame,
    )


def build_forward_ir_relabel_inject(fg_points, bg_points, label="", local_frame=0):
    """Build a relabel payload that uses IR-derived FG and BG points together."""
    return build_forward_inject_keyframe(
        fg_points,
        bg_points or [],
        label=label,
        local_frame=local_frame,
    )


def _largest_component(mask_u8):
    if mask_u8 is None or int(mask_u8.sum()) == 0:
        return mask_u8
    cc_n, cc_lbl, cc_stats, _ = cv2.connectedComponentsWithStats(mask_u8, connectivity=8)
    if cc_n <= 1:
        return mask_u8
    max_cc = 1 + int(np.argmax(cc_stats[1:, cv2.CC_STAT_AREA]))
    return (cc_lbl == max_cc).astype(np.uint8) * 255


def _project_ir_points_to_rgb(
    mask_ir,
    homography_inv,
    rgb_shape,
    rng,
    limit,
    wok_rgb_constraint=None,
    gray_frame=None,
    min_gray=40,
    axis_cx=None,
    axis_cy=None,
    axis_excl_r=None,
):
    ys, xs = np.where(mask_ir > 0)
    if len(xs) == 0:
        return []

    sample_size = min(len(xs), max(limit * 8, limit))
    pick = rng.choice(len(xs), size=sample_size, replace=False)
    pts_ir = np.array([[[float(xs[i]), float(ys[i])]] for i in pick], dtype=np.float32)
    pts_rgb = cv2.perspectiveTransform(pts_ir, homography_inv).reshape(-1, 2)

    rgb_h, rgb_w = rgb_shape
    pts = []
    for x, y in pts_rgb:
        xi = int(round(float(x)))
        yi = int(round(float(y)))
        if not (0 <= xi < rgb_w and 0 <= yi < rgb_h):
            continue
        if wok_rgb_constraint is not None and not wok_rgb_constraint[yi, xi]:
            continue
        if axis_cx is not None and axis_cy is not None and axis_excl_r is not None:
            if ((xi - axis_cx) ** 2 + (yi - axis_cy) ** 2) ** 0.5 < axis_excl_r:
                continue
        if gray_frame is not None and int(gray_frame[yi, xi]) < min_gray:
            continue
        pts.append([float(xi), float(yi)])
        if len(pts) >= limit:
            break
    return pts


def generate_forward_relabel_points_from_ir(
    ir_frame,
    wok_mask_ir,
    homography_inv,
    rgb_shape,
    rng=None,
    wok_rgb_constraint=None,
    gray_frame=None,
    axis_cx=None,
    axis_cy=None,
    axis_excl_r=None,
    n_fg=8,
    n_bg=8,
    min_cluster_gap=30.0,
):
    """Split IR wok pixels into food FG and hot-wok BG, then project both to RGB."""
    if (ir_frame is None or wok_mask_ir is None or homography_inv is None
            or rgb_shape is None):
        return [], [], False, None

    rng = rng or np.random.default_rng(0)
    wok_t = ir_frame[wok_mask_ir]
    if len(wok_t) < 10:
        return [], [], False, None

    c_low = float(np.percentile(wok_t, 10))
    c_high = float(np.percentile(wok_t, 90))
    for _ in range(20):
        d_low = np.abs(wok_t - c_low)
        d_high = np.abs(wok_t - c_high)
        food_sel = d_low <= d_high
        n_low = float(np.mean(wok_t[food_sel])) if food_sel.any() else c_low
        n_high = float(np.mean(wok_t[~food_sel])) if (~food_sel).any() else c_high
        if abs(n_low - c_low) < 0.1 and abs(n_high - c_high) < 0.1:
            break
        c_low, c_high = n_low, n_high

    cluster_gap = c_high - c_low
    if cluster_gap < min_cluster_gap:
        return [], [], False, {
            "food_center": c_low,
            "hot_center": c_high,
            "cluster_gap": cluster_gap,
        }

    ys_wok, xs_wok = np.where(wok_mask_ir)
    vals = ir_frame[wok_mask_ir]
    d_low = np.abs(vals - c_low)
    d_high = np.abs(vals - c_high)

    food_ir = np.zeros_like(wok_mask_ir, dtype=np.uint8)
    hot_ir = np.zeros_like(wok_mask_ir, dtype=np.uint8)
    food_ir[ys_wok[d_low <= d_high], xs_wok[d_low <= d_high]] = 255
    hot_ir[ys_wok[d_high < d_low], xs_wok[d_high < d_low]] = 255

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    food_ir = cv2.morphologyEx(food_ir, cv2.MORPH_OPEN, kernel)
    hot_ir = cv2.morphologyEx(hot_ir, cv2.MORPH_OPEN, kernel)
    food_ir = _largest_component(food_ir)

    fg_points = _project_ir_points_to_rgb(
        food_ir,
        homography_inv,
        rgb_shape,
        rng,
        n_fg,
        wok_rgb_constraint=wok_rgb_constraint,
        gray_frame=gray_frame,
        min_gray=40,
        axis_cx=axis_cx,
        axis_cy=axis_cy,
        axis_excl_r=axis_excl_r,
    )
    bg_points = _project_ir_points_to_rgb(
        hot_ir,
        homography_inv,
        rgb_shape,
        rng,
        n_bg,
        wok_rgb_constraint=wok_rgb_constraint,
        gray_frame=gray_frame,
        min_gray=40,
        axis_cx=axis_cx,
        axis_cy=axis_cy,
        axis_excl_r=axis_excl_r,
    )

    ok = len(fg_points) >= 4 and len(bg_points) >= 4
    return fg_points, bg_points, ok, {
        "food_center": c_low,
        "hot_center": c_high,
        "cluster_gap": cluster_gap,
        "fg_count": len(fg_points),
        "bg_count": len(bg_points),
    }


def compute_forward_reset_metrics(
    carry_mask,
    wok_rgb_constraint,
    default_wok_pixels,
    last_reinforce_wok_pct,
):
    """Compute shared metrics used by the forward reset checks."""
    mask_px = int(carry_mask.sum())
    overlap_pct = 100.0

    if wok_rgb_constraint is not None and mask_px > 0:
        overlap_px = int((carry_mask & wok_rgb_constraint).sum())
        overlap_pct = overlap_px / mask_px * 100

    wok_px = int(wok_rgb_constraint.sum()) if wok_rgb_constraint is not None else int(default_wok_pixels)
    mask_vs_wok = mask_px / max(wok_px, 1) * 100
    drop_pct = (last_reinforce_wok_pct - mask_vs_wok) / max(last_reinforce_wok_pct, 0.1) * 100

    return {
        "mask_px": mask_px,
        "overlap_pct": overlap_pct,
        "wok_px": wok_px,
        "mask_vs_wok": mask_vs_wok,
        "drop_pct": drop_pct,
    }


def evaluate_forward_reset(metrics, last_reinforce_wok_pct):
    """Evaluate whether forward tracking should reset, using shared metrics."""
    overlap_pct = metrics["overlap_pct"]
    mask_vs_wok = metrics["mask_vs_wok"]
    drop_pct = metrics["drop_pct"]
    wok_px = metrics["wok_px"]

    if overlap_pct < 60.0:
        return {"need_reset": True, "reason": "overlap"}
    if mask_vs_wok > 60.0:
        return {"need_reset": True, "reason": "oversize"}
    if wok_px > 0:
        if mask_vs_wok < 5.0:
            return {"need_reset": True, "reason": "undersize"}
        if last_reinforce_wok_pct > 5.0 and drop_pct > 70.0:
            return {"need_reset": True, "reason": "drop"}
    return {"need_reset": False, "reason": None}


def resolve_forward_reset_reason(
    mask_vs_wok,
    overlap_pct,
    last_reinforce_wok_pct,
    drop_pct,
):
    """Resolve the reason text for a forward-tracking reset."""
    if mask_vs_wok < 5.0:
        return f"RESET: mask too small ({mask_vs_wok:.1f}%<5%)"
    if last_reinforce_wok_pct > 5.0 and drop_pct > 70.0:
        return f"RESET: sharp drop ({last_reinforce_wok_pct:.0f}%->{mask_vs_wok:.0f}%)"
    if mask_vs_wok > 60.0:
        return f"RESET: mask too large ({mask_vs_wok:.0f}%>wok60%)"
    if overlap_pct < 60.0:
        return f"RESET: mask left wok area (overlap={overlap_pct:.0f}%)"
    return "RESET"
