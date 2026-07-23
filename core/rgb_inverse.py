import os

import cv2
import numpy as np

from ir_food_seg import SEG_TWO_CLUSTER, segment_ir_food


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


def build_inverse_auto_reset(
    frame_idx,
    reason=None,
    old_mask=None,
    ratio=None,
    time_s=None,
    violation_filename=None,
):
    """Store a pending inverse restart request after failure is detected."""
    return {
        "frame": frame_idx,
        "reason": reason,
        "old_mask": old_mask,
        "ratio": ratio,
        "time_s": time_s,
        "violation_filename": violation_filename,
    }


def apply_inverse_auto_reset(auto_reset_payload):
    """Normalize a pending inverse restart request for chunk startup."""
    return {
        "frame": auto_reset_payload.get("frame"),
        "reason": auto_reset_payload.get("reason"),
        "old_mask": auto_reset_payload.get("old_mask"),
        "ratio": auto_reset_payload.get("ratio"),
        "time_s": auto_reset_payload.get("time_s"),
        "violation_filename": auto_reset_payload.get("violation_filename"),
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


def _extract_top_components(mask_u8, max_components=2, min_area_px=120, min_area_ratio=0.18):
    """Keep the largest component and, if meaningful, the second-largest one."""
    if mask_u8 is None or int(mask_u8.sum()) == 0:
        return []

    cc_n, cc_lbl, cc_stats, _ = cv2.connectedComponentsWithStats(mask_u8, connectivity=8)
    if cc_n <= 1:
        return [mask_u8 > 0]

    components = []
    for cc_idx in range(1, cc_n):
        area = int(cc_stats[cc_idx, cv2.CC_STAT_AREA])
        if area <= 0:
            continue
        components.append((area, cc_idx))
    if not components:
        return []

    components.sort(reverse=True)
    top_area = float(components[0][0])
    keep = []
    for rank, (area, cc_idx) in enumerate(components):
        if rank >= max_components:
            break
        if area < min_area_px:
            continue
        if rank > 0 and area < top_area * float(min_area_ratio):
            continue
        keep.append((area, cc_idx))

    masks = []
    for _, cc_idx in keep:
        masks.append(cc_lbl == cc_idx)
    return masks


def _build_point_candidates(
    mask_ir,
    homography_inv,
    wok_rgb_constraint,
    gray_frame=None,
    min_gray=None,
    max_gray=None,
    axis_cx=None,
    axis_cy=None,
    axis_excl_r=None,
):
    if mask_ir is None or not np.any(mask_ir):
        return [], 0.0

    mask_u8 = mask_ir.astype(np.uint8) * 255
    dist = cv2.distanceTransform(mask_u8, cv2.DIST_L2, 5)
    max_dist = float(dist.max())
    if max_dist <= 0.0:
        return [], 0.0

    ys, xs = np.where(mask_ir)
    if len(xs) == 0:
        return [], 0.0

    h, w = wok_rgb_constraint.shape
    candidates = []
    cx_ir = float(np.mean(xs))
    cy_ir = float(np.mean(ys))
    n_sectors = 6
    for x_ir, y_ir in zip(xs, ys):
        score = float(dist[y_ir, x_ir])
        angle = float(np.arctan2(float(y_ir) - cy_ir, float(x_ir) - cx_ir))
        sector = int(np.floor((angle + np.pi) / (2.0 * np.pi) * n_sectors)) % n_sectors
        pt_ir = np.array([[[float(x_ir), float(y_ir)]]], dtype=np.float32)
        pt_rgb = cv2.perspectiveTransform(pt_ir, homography_inv).reshape(-1, 2)[0]
        xi = int(round(float(pt_rgb[0])))
        yi = int(round(float(pt_rgb[1])))
        if not (0 <= xi < w and 0 <= yi < h):
            continue
        if not wok_rgb_constraint[yi, xi]:
            continue
        if gray_frame is not None and min_gray is not None and int(gray_frame[yi, xi]) < int(min_gray):
            continue
        if gray_frame is not None and max_gray is not None and int(gray_frame[yi, xi]) > int(max_gray):
            continue
        if axis_cx is not None and axis_cy is not None and axis_excl_r is not None:
            if ((xi - axis_cx) ** 2 + (yi - axis_cy) ** 2) ** 0.5 < axis_excl_r:
                continue
        candidates.append({
            "ir": (float(x_ir), float(y_ir)),
            "rgb": [float(xi), float(yi)],
            "score": score,
            "sector": sector,
        })
    return candidates, max_dist


def _dedupe_point_list(points):
    unique = []
    seen = set()
    for x, y in points:
        key = (int(round(float(x))), int(round(float(y))))
        if key in seen:
            continue
        seen.add(key)
        unique.append([float(x), float(y)])
    return unique


def _dedupe_point_pairs(rgb_points, ir_points):
    unique_rgb = []
    unique_ir = []
    seen = set()
    for rgb_pt, ir_pt in zip(rgb_points, ir_points):
        key = (int(round(float(rgb_pt[0]))), int(round(float(rgb_pt[1]))))
        if key in seen:
            continue
        seen.add(key)
        unique_rgb.append([float(rgb_pt[0]), float(rgb_pt[1])])
        unique_ir.append([float(ir_pt[0]), float(ir_pt[1])])
    return unique_rgb, unique_ir


def _pick_sector_spread_points(candidates, n, rng, max_dist, return_ir_points=False):
    if not candidates or n <= 0:
        return ([], []) if return_ir_points else []

    scores = np.array([cand["score"] for cand in candidates], dtype=float)
    jitter = rng.random(len(candidates)) * 1e-3
    order = np.lexsort((jitter, -scores))
    ordered = [candidates[int(idx)] for idx in order]

    def _collect_with_spacing(min_spacing):
        pts_ir = []
        pts_rgb = []
        pts_ir_selected = []
        sector_counts = {}
        sector_cap = max(1, int(np.ceil(float(n) / 4.0)))

        def _try_pick(cand, enforce_sector_cap):
            x_ir, y_ir = cand["ir"]
            if any((x_ir - px) ** 2 + (y_ir - py) ** 2 < (min_spacing ** 2) for px, py in pts_ir):
                return False
            sector = cand["sector"]
            if enforce_sector_cap and sector_counts.get(sector, 0) >= sector_cap:
                return False
            pts_ir.append((x_ir, y_ir))
            pts_rgb.append(cand["rgb"])
            pts_ir_selected.append([float(x_ir), float(y_ir)])
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
            return True

        for cand in ordered:
            _try_pick(cand, True)
            if len(pts_rgb) >= n:
                break
        if len(pts_rgb) < n:
            for cand in ordered:
                if cand["rgb"] in pts_rgb:
                    continue
                _try_pick(cand, False)
                if len(pts_rgb) >= n:
                    break
        return pts_rgb, pts_ir_selected

    spacing_levels = [
        max(3.0, max_dist * 0.55),
        max(3.0, max_dist * 0.40),
        max(3.0, max_dist * 0.28),
        max(2.0, max_dist * 0.18),
        0.0,
    ]
    best_pts = []
    best_ir_pts = []
    for spacing in spacing_levels:
        pts, pts_ir_selected = _collect_with_spacing(spacing)
        if len(pts) > len(best_pts):
            best_pts = pts
            best_ir_pts = pts_ir_selected
        if len(best_pts) >= n:
            break

    if return_ir_points:
        return best_pts, best_ir_pts
    return best_pts


def _select_spread_points(
    mask_ir,
    homography_inv,
    wok_rgb_constraint,
    n,
    rng,
    gray_frame=None,
    min_gray=None,
    max_gray=None,
    axis_cx=None,
    axis_cy=None,
    axis_excl_r=None,
    return_ir_points=False,
):
    if mask_ir is None or not np.any(mask_ir) or n <= 0:
        return ([], []) if return_ir_points else []

    candidates, max_dist = _build_point_candidates(
        mask_ir,
        homography_inv,
        wok_rgb_constraint,
        gray_frame=gray_frame,
        min_gray=min_gray,
        max_gray=max_gray,
        axis_cx=axis_cx,
        axis_cy=axis_cy,
        axis_excl_r=axis_excl_r,
    )
    return _pick_sector_spread_points(
        candidates, n, rng, max_dist, return_ir_points=return_ir_points
    )


def _dilate_bool_mask(mask_bool, ksize):
    if mask_bool is None or not np.any(mask_bool):
        return np.zeros_like(mask_bool, dtype=bool)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksize, ksize))
    return cv2.dilate(mask_bool.astype(np.uint8) * 255, kernel) > 0


def _erode_bool_mask(mask_bool, ksize):
    if mask_bool is None or not np.any(mask_bool):
        return np.zeros_like(mask_bool, dtype=bool)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksize, ksize))
    return cv2.erode(mask_bool.astype(np.uint8) * 255, kernel) > 0


def _sample_food_bg_points(
    food_mask,
    homography_inv,
    wok_rgb_constraint,
    n,
    rng,
    gray_frame=None,
    min_gray=None,
    axis_cx=None,
    axis_cy=None,
    axis_excl_r=None,
    return_ir_points=False,
):
    """Sample BG-food points conservatively from the food core only."""
    if food_mask is None or not np.any(food_mask) or n <= 0:
        return ([], []) if return_ir_points else []

    pts = []
    pts_ir = []
    core_masks = []
    for ksize in (21, 17, 13, 9, 5):
        core_mask = _erode_bool_mask(food_mask, ksize)
        if np.any(core_mask):
            core_masks.append(core_mask)
    if not core_masks:
        core_masks = [food_mask]
    else:
        core_masks.append(food_mask)

    for core_mask in core_masks:
        fill_pts, fill_ir_pts = _select_spread_points(
            core_mask,
            homography_inv,
            wok_rgb_constraint,
            n,
            rng,
            gray_frame=gray_frame,
            min_gray=min_gray,
            axis_cx=axis_cx,
            axis_cy=axis_cy,
            axis_excl_r=axis_excl_r,
            return_ir_points=True,
        )
        pts, pts_ir = _dedupe_point_pairs(pts + fill_pts, pts_ir + fill_ir_pts)
        if len(pts) >= n:
            break
    if return_ir_points:
        return pts[:n], pts_ir[:n]
    return pts[:n]


def _project_ir_to_valid_rgb_point(
    x_ir,
    y_ir,
    homography_inv,
    wok_rgb_constraint,
    gray_frame=None,
    min_gray=None,
    max_gray=None,
    axis_cx=None,
    axis_cy=None,
    axis_excl_r=None,
):
    h, w = wok_rgb_constraint.shape
    pt_ir = np.array([[[float(x_ir), float(y_ir)]]], dtype=np.float32)
    pt_rgb = cv2.perspectiveTransform(pt_ir, homography_inv).reshape(-1, 2)[0]
    xi = int(round(float(pt_rgb[0])))
    yi = int(round(float(pt_rgb[1])))
    if not (0 <= xi < w and 0 <= yi < h):
        return None
    if not wok_rgb_constraint[yi, xi]:
        return None
    if gray_frame is not None and min_gray is not None and int(gray_frame[yi, xi]) < int(min_gray):
        return None
    if gray_frame is not None and max_gray is not None and int(gray_frame[yi, xi]) > int(max_gray):
        return None
    if axis_cx is not None and axis_cy is not None and axis_excl_r is not None:
        if ((xi - axis_cx) ** 2 + (yi - axis_cy) ** 2) ** 0.5 < axis_excl_r:
            return None
    return [float(xi), float(yi)]


def _sample_directional_ring_points(
    food_mask,
    near_ring_mask,
    homography_inv,
    wok_rgb_constraint,
    n,
    rng,
    gray_frame=None,
    min_gray=None,
    max_gray=None,
    axis_cx=None,
    axis_cy=None,
    axis_excl_r=None,
    return_ir_points=False,
):
    """Force FG-bottom-near points to wrap around the food contour by angle."""
    if (food_mask is None or near_ring_mask is None or n <= 0
            or not np.any(food_mask) or not np.any(near_ring_mask)):
        return ([], []) if return_ir_points else []

    food_u8 = (food_mask.astype(np.uint8) * 255)
    edge_mask = food_mask & (~_erode_bool_mask(food_mask, 3))
    ys_e, xs_e = np.where(edge_mask)
    if len(xs_e) == 0:
        ys_e, xs_e = np.where(food_mask)
        if len(xs_e) == 0:
            return ([], []) if return_ir_points else []

    cx = float(np.mean(xs_e))
    cy = float(np.mean(ys_e))
    ring_dist = cv2.distanceTransform((~food_mask).astype(np.uint8) * 255, cv2.DIST_L2, 5)

    boundary_samples = []
    for x, y in zip(xs_e, ys_e):
        dx = float(x) - cx
        dy = float(y) - cy
        angle = float(np.arctan2(dy, dx))
        radius = float(np.hypot(dx, dy))
        boundary_samples.append((angle, radius, int(x), int(y)))
    if not boundary_samples:
        return ([], []) if return_ir_points else []

    n_sectors = max(8, min(12, n))
    sector_angles = np.linspace(-np.pi, np.pi, n_sectors, endpoint=False)
    used_ir = set()
    forced_pts = []
    forced_ir_pts = []

    for target_angle in sector_angles:
        best_edge = None
        best_score = None
        for angle, radius, x0, y0 in boundary_samples:
            delta = abs(np.arctan2(np.sin(angle - target_angle), np.cos(angle - target_angle)))
            score = delta * 1000.0 - radius
            if best_score is None or score < best_score:
                best_score = score
                best_edge = (x0, y0, angle)
        if best_edge is None:
            continue

        x0, y0, angle = best_edge
        ux = float(np.cos(angle))
        uy = float(np.sin(angle))
        hit = None
        for step in range(2, 42):
            x1 = int(round(float(x0) + ux * step))
            y1 = int(round(float(y0) + uy * step))
            if not (0 <= x1 < near_ring_mask.shape[1] and 0 <= y1 < near_ring_mask.shape[0]):
                break
            if not near_ring_mask[y1, x1]:
                continue
            if ring_dist[y1, x1] > 20.0:
                continue
            rgb_pt = _project_ir_to_valid_rgb_point(
                x1, y1,
                homography_inv,
                wok_rgb_constraint,
                gray_frame=gray_frame,
                min_gray=min_gray,
                max_gray=max_gray,
                axis_cx=axis_cx,
                axis_cy=axis_cy,
                axis_excl_r=axis_excl_r,
            )
            if rgb_pt is None:
                continue
            key = (x1, y1)
            if key in used_ir:
                continue
            hit = (key, rgb_pt)
            break
        if hit is None:
            continue
        used_ir.add(hit[0])
        forced_ir_pts.append([float(hit[0][0]), float(hit[0][1])])
        forced_pts.append(hit[1])
        if len(forced_pts) >= n:
            break

    forced_pts, forced_ir_pts = _dedupe_point_pairs(forced_pts, forced_ir_pts)
    if len(forced_pts) < n:
        extra_pts, extra_ir_pts = _select_spread_points(
            near_ring_mask,
            homography_inv,
            wok_rgb_constraint,
            n,
            rng,
            gray_frame=gray_frame,
            min_gray=min_gray,
            max_gray=max_gray,
            axis_cx=axis_cx,
            axis_cy=axis_cy,
            axis_excl_r=axis_excl_r,
            return_ir_points=True,
        )
        forced_pts, forced_ir_pts = _dedupe_point_pairs(
            forced_pts + extra_pts,
            forced_ir_pts + extra_ir_pts,
        )
    if return_ir_points:
        return forced_pts[:n], forced_ir_pts[:n]
    return forced_pts[:n]


def save_inverse_preview(
    preview_path,
    rgb_frame,
    wok_rgb_constraint,
    old_mask=None,
    fg_points=None,
    bg_points=None,
    header="",
    detail_lines=None,
    header_color=(255, 255, 255),
    action_tag=None,
):
    """Render a labeled inverse preview image."""
    if preview_path is None or rgb_frame is None:
        return

    fg_points = fg_points or []
    bg_points = bg_points or []
    vis = rgb_frame.copy()
    if wok_rgb_constraint is not None:
        shade = np.zeros_like(vis)
        shade[wok_rgb_constraint] = (70, 70, 70)
        vis = cv2.addWeighted(vis, 1.0, shade, 0.25, 0)
    if old_mask is not None and np.any(old_mask):
        vis[old_mask] = (
            vis[old_mask].astype(float) * 0.5
            + np.array([0, 0, 220]) * 0.5
        ).astype(np.uint8)
    for x, y in fg_points:
        cv2.circle(vis, (int(x), int(y)), 8, (0, 255, 80), -1)
        cv2.circle(vis, (int(x), int(y)), 9, (0, 0, 0), 1)
    for x, y in bg_points:
        cv2.circle(vis, (int(x), int(y)), 8, (255, 80, 0), -1)
        cv2.circle(vis, (int(x), int(y)), 9, (0, 0, 0), 1)

    if action_tag:
        _tag = str(action_tag)
        _font = cv2.FONT_HERSHEY_SIMPLEX
        (_tw, _th), _ = cv2.getTextSize(_tag, _font, 0.9, 2)
        _right_pad = 140
        _x1 = max(_tw + 46, vis.shape[1] - _right_pad)
        _x0 = max(20, _x1 - _tw - 26)
        _y0 = 20
        _x1 = min(vis.shape[1] - 20, _x0 + _tw + 26)
        _y1 = _y0 + _th + 20
        cv2.rectangle(vis, (_x0, _y0), (_x1, _y1), (20, 20, 20), -1)
        cv2.rectangle(vis, (_x0, _y0), (_x1, _y1), (0, 220, 255), 2)
        cv2.putText(vis, _tag, (_x0 + 12, _y1 - 10),
                    _font, 0.9, (0, 220, 255), 2)

    if header:
        cv2.putText(vis, header,
                    (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, header_color, 2)
    for idx, line in enumerate(detail_lines or []):
        y = 78 + idx * 34
        cv2.putText(vis, line, (20, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.72, (255, 255, 255), 2)
    cv2.imwrite(preview_path, vis)


def generate_inverse_bottom_points_from_ir(
    rgb_frame,
    ir_frame,
    wok_mask_ir,
    homography_inv,
    wok_rgb_constraint,
    n_fg=20,
    n_bg=8,
    rng=None,
    preview_path=None,
    old_mask=None,
    reason_text=None,
    gray_frame=None,
    bg_min_gray=45,
    fg_max_gray=210,
    axis_cx=None,
    axis_cy=None,
    axis_excl_r=None,
    axis_ir_cx=None,
    axis_ir_cy=None,
    axis_ir_excl_r=None,
    detail_lines=None,
    action_tag=None,
    seg_mode=SEG_TWO_CLUSTER,
    seg_percentile=40,
    return_debug=False,
):
    """Generate inverse-SAM2 points from current IR: food interior=BG, other wok area=FG."""
    def _empty_inverse_result():
        if return_debug:
            return [], [], False, {"fg_ir_points": [], "bg_ir_points": [], "axis_guard_ir": None}
        return [], [], False

    if (rgb_frame is None or ir_frame is None or wok_mask_ir is None
            or homography_inv is None or wok_rgb_constraint is None):
        return _empty_inverse_result()

    rng = rng or np.random.default_rng(0)
    seg_result = segment_ir_food(
        ir_frame,
        wok_mask_ir,
        mode=seg_mode,
        percentile=seg_percentile,
        min_cluster_gap=25.0,
    )
    if seg_result.reason == "too_few_wok_pixels":
        return _empty_inverse_result()
    if not seg_result.ok:
        return _empty_inverse_result()

    c_low = seg_result.food_center
    c_high = seg_result.hot_center
    food_ir = seg_result.food_u8
    hot_ir = seg_result.hot_u8

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    food_ir = cv2.morphologyEx(food_ir, cv2.MORPH_OPEN, kernel)
    food_components = _extract_top_components(food_ir, max_components=2)
    food_ir = (food_ir > 0)
    if not food_components:
        return _empty_inverse_result()

    if gray_frame is None and rgb_frame is not None:
        gray_frame = cv2.cvtColor(rgb_frame, cv2.COLOR_BGR2GRAY)

    bg_pts = []
    bg_pts_ir = []
    if len(food_components) == 1:
        bg_pts, bg_pts_ir = _sample_food_bg_points(
            food_components[0],
            homography_inv,
            wok_rgb_constraint,
            n_bg,
            rng,
            gray_frame=gray_frame,
            min_gray=bg_min_gray,
            axis_cx=axis_cx,
            axis_cy=axis_cy,
            axis_excl_r=axis_excl_r,
            return_ir_points=True,
        )
    else:
        area1 = float(np.count_nonzero(food_components[0]))
        area2 = float(np.count_nonzero(food_components[1]))
        secondary_n = int(round(n_bg * area2 / max(area1 + area2, 1.0)))
        secondary_n = max(2, min(secondary_n, max(2, n_bg // 2)))
        primary_n = max(4, n_bg - secondary_n)
        primary_pts, primary_ir_pts = _sample_food_bg_points(
            food_components[0],
            homography_inv,
            wok_rgb_constraint,
            primary_n,
            rng,
            gray_frame=gray_frame,
            min_gray=bg_min_gray,
            axis_cx=axis_cx,
            axis_cy=axis_cy,
            axis_excl_r=axis_excl_r,
            return_ir_points=True,
        )
        secondary_pts, secondary_ir_pts = _sample_food_bg_points(
            food_components[1],
            homography_inv,
            wok_rgb_constraint,
            secondary_n,
            rng,
            gray_frame=gray_frame,
            min_gray=bg_min_gray,
            axis_cx=axis_cx,
            axis_cy=axis_cy,
            axis_excl_r=axis_excl_r,
            return_ir_points=True,
        )
        bg_pts, bg_pts_ir = _dedupe_point_pairs(
            primary_pts + secondary_pts,
            primary_ir_pts + secondary_ir_pts,
        )
        if len(bg_pts) < n_bg:
            merged_food = (food_components[0] | food_components[1])
            fill_pts, fill_ir_pts = _sample_food_bg_points(
                merged_food,
                homography_inv,
                wok_rgb_constraint,
                n_bg,
                rng,
                gray_frame=gray_frame,
                min_gray=bg_min_gray,
                axis_cx=axis_cx,
                axis_cy=axis_cy,
                axis_excl_r=axis_excl_r,
                return_ir_points=True,
            )
            bg_pts, bg_pts_ir = _dedupe_point_pairs(
                bg_pts + fill_pts,
                bg_pts_ir + fill_ir_pts,
            )
            bg_pts = bg_pts[:n_bg]
            bg_pts_ir = bg_pts_ir[:n_bg]

    merged_food = np.zeros_like(wok_mask_ir, dtype=bool)
    for comp in food_components:
        merged_food |= comp
    food_inner = _erode_bool_mask(merged_food, 9)
    if np.count_nonzero(food_inner) < max(40, int(0.2 * np.count_nonzero(merged_food))):
        food_inner = _erode_bool_mask(merged_food, 5)
    if np.count_nonzero(food_inner) < max(30, int(0.12 * np.count_nonzero(merged_food))):
        food_inner = merged_food

    fg_core = _erode_bool_mask(merged_food, 7)
    if np.count_nonzero(fg_core) < max(35, int(0.15 * np.count_nonzero(merged_food))):
        fg_core = _erode_bool_mask(merged_food, 5)
    if np.count_nonzero(fg_core) < max(24, int(0.08 * np.count_nonzero(merged_food))):
        fg_core = merged_food

    near_outer = _dilate_bool_mask(fg_core, 31)
    near_ring = near_outer & wok_mask_ir & (~merged_food)

    # Build a second FG ring just outside near_ring instead of sampling
    # arbitrary far-region wok pixels.
    outer_outer = _dilate_bool_mask(near_outer, 24)
    outer_ring = outer_outer & wok_mask_ir & (~near_outer) & (~merged_food)
    axis_guard_ir = None
    if axis_ir_cx is not None and axis_ir_cy is not None and axis_ir_excl_r is not None:
        yy, xx = np.indices(wok_mask_ir.shape)
        axis_guard_ir = (
            ((xx - float(axis_ir_cx)) ** 2 + (yy - float(axis_ir_cy)) ** 2)
            <= float(axis_ir_excl_r) ** 2
        )
        near_ring &= ~axis_guard_ir
        outer_ring &= ~axis_guard_ir
        food_inner &= ~axis_guard_ir
        fg_core &= ~axis_guard_ir
    elif axis_cx is not None and axis_cy is not None and axis_excl_r is not None:
        yy, xx = np.indices(wok_mask_ir.shape)
        axis_rgb_pts = np.array(
            [[[float(axis_cx), float(axis_cy)]]], dtype=np.float32
        )
        try:
            axis_ir_pt = cv2.perspectiveTransform(axis_rgb_pts, np.linalg.inv(homography_inv)).reshape(-1, 2)[0]
            axis_ir_cx = float(axis_ir_pt[0])
            axis_ir_cy = float(axis_ir_pt[1])
            axis_ir_r = max(6.0, float(axis_excl_r) / 6.0)
            axis_guard_ir = (((xx - axis_ir_cx) ** 2 + (yy - axis_ir_cy) ** 2) <= axis_ir_r ** 2)
            near_ring &= ~axis_guard_ir
            outer_ring &= ~axis_guard_ir
            food_inner &= ~axis_guard_ir
            fg_core &= ~axis_guard_ir
        except Exception:
            pass

    fg_near_n = min(12, max(8, int(round(n_fg * 0.6))))
    fg_far_n = max(0, n_fg - fg_near_n)
    fg_near_pts, fg_near_ir_pts = _sample_directional_ring_points(
        fg_core,
        near_ring,
        homography_inv,
        wok_rgb_constraint,
        fg_near_n,
        rng,
        gray_frame=gray_frame,
        max_gray=fg_max_gray,
        axis_cx=axis_cx,
        axis_cy=axis_cy,
        axis_excl_r=axis_excl_r,
        return_ir_points=True,
    )
    fg_far_pts, fg_far_ir_pts = _select_spread_points(
        outer_ring,
        homography_inv,
        wok_rgb_constraint,
        fg_far_n,
        rng,
        gray_frame=gray_frame,
        max_gray=fg_max_gray,
        axis_cx=axis_cx,
        axis_cy=axis_cy,
        axis_excl_r=axis_excl_r,
        return_ir_points=True,
    )
    fg_pts, fg_pts_ir = _dedupe_point_pairs(
        fg_near_pts + fg_far_pts,
        fg_near_ir_pts + fg_far_ir_pts,
    )
    if len(fg_pts) < n_fg:
        fg_fill_region = wok_mask_ir & (~food_inner)
        fg_fill_pts, fg_fill_ir_pts = _select_spread_points(
            fg_fill_region,
            homography_inv,
            wok_rgb_constraint,
            n_fg,
            rng,
            gray_frame=gray_frame,
            max_gray=fg_max_gray,
            axis_cx=axis_cx,
            axis_cy=axis_cy,
            axis_excl_r=axis_excl_r,
            return_ir_points=True,
        )
        fg_pts, fg_pts_ir = _dedupe_point_pairs(
            fg_pts + fg_fill_pts,
            fg_pts_ir + fg_fill_ir_pts,
        )
        fg_pts = fg_pts[:n_fg]
        fg_pts_ir = fg_pts_ir[:n_fg]
    ok = len(fg_pts) >= 4 and len(bg_pts) >= 4

    if ok and preview_path:
        header = (reason_text if reason_text
                  else f"Inverse auto points FG-bottom={len(fg_pts)} BG-food={len(bg_pts)}")
        lines = [
            f"[red=old bad mask | green=FG-bottom({len(fg_pts)}) | blue=BG-food({len(bg_pts)})]",
            (f"K-low/high=({c_low:.1f},{c_high:.1f})C"
             if c_low is not None and c_high is not None
             else f"threshold={seg_result.threshold:.1f}C"),
        ]
        lines.extend(detail_lines or [])
        save_inverse_preview(
            preview_path,
            rgb_frame,
            wok_rgb_constraint,
            old_mask=old_mask,
            fg_points=fg_pts,
            bg_points=bg_pts,
            header=header,
            detail_lines=lines,
            action_tag=action_tag,
        )

    debug_info = {
        "fg_ir_points": fg_pts_ir,
        "bg_ir_points": bg_pts_ir,
        "axis_guard_ir": axis_guard_ir,
    }
    if return_debug:
        return fg_pts, bg_pts, ok, debug_info
    return fg_pts, bg_pts, ok
