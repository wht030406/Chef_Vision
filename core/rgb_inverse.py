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


def generate_inverse_bottom_points_from_ir(
    rgb_frame,
    ir_frame,
    wok_mask_ir,
    homography_inv,
    wok_rgb_constraint,
    n_fg=18,
    n_bg=18,
    rng=None,
    preview_path=None,
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
