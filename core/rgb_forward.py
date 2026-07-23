import cv2
import numpy as np

from ir_food_seg import SEG_TWO_CLUSTER, segment_ir_food


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
    mask_u8 = (_bool_mask(mask_u8).astype(np.uint8) * 255)
    cc_n, cc_lbl, cc_stats, _ = cv2.connectedComponentsWithStats(mask_u8, connectivity=8)
    if cc_n <= 1:
        return mask_u8
    max_cc = 1 + int(np.argmax(cc_stats[1:, cv2.CC_STAT_AREA]))
    return (cc_lbl == max_cc).astype(np.uint8) * 255


def _bool_mask(mask):
    if mask is None:
        return None
    return np.asarray(mask) > 0


def _erode_mask(mask_bool, ksize):
    mask_bool = _bool_mask(mask_bool)
    if mask_bool is None or not np.any(mask_bool):
        return np.zeros_like(mask_bool, dtype=bool)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksize, ksize))
    return cv2.erode(mask_bool.astype(np.uint8) * 255, kernel) > 0


def _dilate_mask(mask_bool, ksize):
    mask_bool = _bool_mask(mask_bool)
    if mask_bool is None or not np.any(mask_bool):
        return np.zeros_like(mask_bool, dtype=bool)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksize, ksize))
    return cv2.dilate(mask_bool.astype(np.uint8) * 255, kernel) > 0


def _dedupe_mask_list(mask_list):
    unique = []
    signatures = set()
    for mask in mask_list:
        mask = _bool_mask(mask)
        if mask is None or not np.any(mask):
            continue
        signature = (int(mask.sum()), tuple(np.flatnonzero(mask)[:8]))
        if signature in signatures:
            continue
        signatures.add(signature)
        unique.append(mask)
    return unique


def _build_ir_axis_exclusion_mask(
    ir_shape,
    homography_inv,
    axis_ir_cx=None,
    axis_ir_cy=None,
    axis_rgb_radius=None,
    axis_ir_radius=None,
):
    """Build an IR-space circular guard for the manual axis exclusion region."""
    if axis_ir_cx is None or axis_ir_cy is None:
        return None, None

    ir_radius = None
    if axis_ir_radius is not None:
        ir_radius = float(axis_ir_radius)
    elif axis_rgb_radius is not None and homography_inv is not None:
        try:
            ir_points = np.array([[[
                float(axis_ir_cx), float(axis_ir_cy),
            ]], [[
                float(axis_ir_cx) + 1.0, float(axis_ir_cy),
            ]], [[
                float(axis_ir_cx), float(axis_ir_cy) + 1.0,
            ]]], dtype=np.float32)
            rgb_points = cv2.perspectiveTransform(ir_points, homography_inv).reshape(-1, 2)
            scale_x = float(np.linalg.norm(rgb_points[1] - rgb_points[0]))
            scale_y = float(np.linalg.norm(rgb_points[2] - rgb_points[0]))
            local_scale = max((scale_x * scale_y) ** 0.5, 1e-6)
            ir_radius = float(axis_rgb_radius) / local_scale
        except Exception:
            return None, None
    if ir_radius is None:
        return None, None

    guard = np.zeros(ir_shape, dtype=np.uint8)
    cv2.circle(
        guard,
        (int(round(float(axis_ir_cx))), int(round(float(axis_ir_cy)))),
        max(1, int(round(ir_radius))),
        255,
        -1,
    )
    return guard > 0, ir_radius


def _build_forward_core_masks(food_ir, hot_ir, wok_mask_ir):
    """Build conservative food and hot-wok candidate masks in IR space.

    The first mask in each list is the preferred core. Later masks are
    deliberately milder fallbacks so thin or fragmented regions still retain
    enough points after RGB projection filters.
    """
    food = _bool_mask(food_ir)
    hot = _bool_mask(hot_ir)
    wok = _bool_mask(wok_mask_ir)
    if food is None or hot is None:
        return [], []

    food_masks = [
        _erode_mask(food, 5),
        _erode_mask(food, 3),
        food,
    ]

    if wok is None:
        wok = np.ones_like(hot, dtype=bool)
    hot_masks = [
        hot & _erode_mask(wok, 5) & ~_dilate_mask(food, 5),
        hot & _erode_mask(wok, 3) & ~_dilate_mask(food, 3),
        hot & _erode_mask(wok, 3),
        hot,
    ]
    return _dedupe_mask_list(food_masks), _dedupe_mask_list(hot_masks)


def _project_valid_ir_candidates(
    mask_ir,
    homography_inv,
    rgb_shape,
    wok_rgb_constraint=None,
    gray_frame=None,
    min_gray=40,
    axis_cx=None,
    axis_cy=None,
    axis_excl_r=None,
):
    """Project all valid core candidates before selecting a spread subset."""
    mask_bool = _bool_mask(mask_ir)
    if mask_bool is None or not np.any(mask_bool):
        return []

    ys, xs = np.where(mask_bool)
    pts_ir = np.column_stack((xs.astype(np.float32), ys.astype(np.float32)))
    pts_rgb = cv2.perspectiveTransform(
        pts_ir.reshape(-1, 1, 2), homography_inv
    ).reshape(-1, 2)
    rgb_h, rgb_w = rgb_shape
    candidates = []
    for (x_ir, y_ir), (x, y) in zip(pts_ir, pts_rgb):
        xi = int(round(float(x)))
        yi = int(round(float(y)))
        if not (0 <= xi < rgb_w and 0 <= yi < rgb_h):
            continue
        if wok_rgb_constraint is not None and not wok_rgb_constraint[yi, xi]:
            continue
        if axis_cx is not None and axis_cy is not None and axis_excl_r is not None:
            if ((xi - axis_cx) ** 2 + (yi - axis_cy) ** 2) ** 0.5 < axis_excl_r:
                continue
        if min_gray is not None and gray_frame is not None and int(gray_frame[yi, xi]) < min_gray:
            continue
        candidates.append({
            "ir": (float(x_ir), float(y_ir)),
            "rgb": [float(xi), float(yi)],
        })
    return candidates


def _pick_diverse_core_points(candidates, distance_map, limit, rng):
    """Pick central but spatially separated points from a wide core band."""
    if not candidates or limit <= 0:
        return [], []

    height, width = distance_map.shape
    for candidate in candidates:
        x_ir, y_ir = candidate["ir"]
        xi = min(max(int(round(x_ir)), 0), width - 1)
        yi = min(max(int(round(y_ir)), 0), height - 1)
        candidate["score"] = float(distance_map[yi, xi])

    max_score = max(candidate["score"] for candidate in candidates)
    candidates = [
        candidate for candidate in candidates
        if candidate["score"] >= max_score * 0.22
    ] or candidates
    tie_break = rng.random(len(candidates)) * 1e-3
    candidates = [candidate for _, candidate in sorted(
        zip(tie_break, candidates),
        key=lambda item: (-item[1]["score"], item[0]),
    )]

    selected = []
    selected_ir = []
    selected_rgb = []
    max_dist = max_score if max_score > 0 else 1.0
    while candidates and len(selected_rgb) < limit:
        if not selected_ir:
            chosen_idx = 0
        else:
            best_idx = 0
            best_value = -1.0
            for idx, candidate in enumerate(candidates):
                x_ir, y_ir = candidate["ir"]
                min_distance = min(
                    ((x_ir - px) ** 2 + (y_ir - py) ** 2) ** 0.5
                    for px, py in selected_ir
                )
                centrality = candidate["score"] / max_dist
                value = min_distance + 0.18 * max_dist * centrality
                if value > best_value:
                    best_idx = idx
                    best_value = value
            chosen_idx = best_idx

        chosen = candidates.pop(chosen_idx)
        selected.append(chosen)
        selected_ir.append(chosen["ir"])
        selected_rgb.append(chosen["rgb"])

    return selected_rgb, [[float(x), float(y)] for x, y in selected_ir]


def _pick_grid_food_points(candidates, distance_map, limit, rng):
    """Place food points across the middle 60% of the valid food core."""
    if not candidates or limit <= 0:
        return [], []

    height, width = distance_map.shape
    for candidate in candidates:
        x_ir, y_ir = candidate["ir"]
        xi = min(max(int(round(x_ir)), 0), width - 1)
        yi = min(max(int(round(y_ir)), 0), height - 1)
        candidate["score"] = float(distance_map[yi, xi])

    max_score = max(candidate["score"] for candidate in candidates)
    core_candidates = [
        candidate for candidate in candidates
        if candidate["score"] >= max_score * 0.45
    ] or candidates
    coords = np.array([candidate["ir"] for candidate in core_candidates], dtype=float)
    min_x, min_y = coords.min(axis=0)
    max_x, max_y = coords.max(axis=0)
    span_x = max(float(max_x - min_x), 1.0)
    span_y = max(float(max_y - min_y), 1.0)
    target_xs = np.linspace(min_x + span_x * 0.20, max_x - span_x * 0.20, 3)
    target_ys = np.linspace(min_y + span_y * 0.20, max_y - span_y * 0.20, 3)
    targets = [(target_x, target_y) for target_y in target_ys for target_x in target_xs]
    targets = targets[:limit]
    min_spacing = max(2.0, 0.16 * max(span_x, span_y))

    jitter = rng.random(len(core_candidates)) * 1e-3
    selected = []
    selected_ir = []
    used = set()
    for target_x, target_y in targets:
        best_candidate = None
        best_value = float("inf")
        for candidate, tie in zip(core_candidates, jitter):
            x_ir, y_ir = candidate["ir"]
            key = (int(round(x_ir)), int(round(y_ir)))
            if key in used:
                continue
            nearest_selected = min(
                (np.hypot(x_ir - px, y_ir - py) for px, py in selected_ir),
                default=min_spacing,
            )
            spacing_penalty = max(0.0, min_spacing - nearest_selected) / min_spacing
            target_distance = np.hypot(
                (x_ir - target_x) / span_x,
                (y_ir - target_y) / span_y,
            )
            centrality = candidate["score"] / max(max_score, 1e-6)
            value = target_distance + 0.35 * spacing_penalty - 0.20 * centrality + tie
            if value < best_value:
                best_candidate = candidate
                best_value = value
        if best_candidate is not None:
            x_ir, y_ir = best_candidate["ir"]
            used.add((int(round(x_ir)), int(round(y_ir))))
            selected.append(best_candidate["rgb"])
            selected_ir.append([float(x_ir), float(y_ir)])

    if len(selected) < limit:
        fill_rgb, fill_ir = _pick_diverse_core_points(
            core_candidates,
            distance_map,
            limit,
            rng,
        )
        selected, selected_ir = _merge_point_pairs(
            selected + fill_rgb,
            selected_ir + fill_ir,
            limit,
        )
    return selected[:limit], selected_ir[:limit]


def _merge_point_pairs(rgb_points, ir_points, limit):
    merged_rgb = []
    merged_ir = []
    seen = set()
    for rgb_point, ir_point in zip(rgb_points, ir_points):
        key = (int(round(float(rgb_point[0]))), int(round(float(rgb_point[1]))))
        if key in seen:
            continue
        seen.add(key)
        merged_rgb.append([float(rgb_point[0]), float(rgb_point[1])])
        merged_ir.append([float(ir_point[0]), float(ir_point[1])])
        if len(merged_rgb) >= limit:
            break
    return merged_rgb, merged_ir


def _sample_forward_core_masks(
    masks_ir,
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
    sampling_mode="diverse",
):
    """Use the strict core first, then gently widen only if points are missing."""
    points = []
    points_ir = []
    for mask_ir in masks_ir:
        candidate_points, candidate_ir_points = _project_ir_points_to_rgb(
            mask_ir,
            homography_inv,
            rgb_shape,
            rng,
            limit,
            wok_rgb_constraint=wok_rgb_constraint,
            gray_frame=gray_frame,
            min_gray=min_gray,
            axis_cx=axis_cx,
            axis_cy=axis_cy,
            axis_excl_r=axis_excl_r,
            return_ir_points=True,
            sampling_mode=sampling_mode,
        )
        points, points_ir = _merge_point_pairs(
            points + candidate_points,
            points_ir + candidate_ir_points,
            limit,
        )
        if len(points) >= limit:
            break
    return points, points_ir


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
    return_ir_points=False,
    sampling_mode="diverse",
):
    """Project a core mask, then select a wider, central spread of points."""
    mask_bool = _bool_mask(mask_ir)
    if mask_bool is None or not np.any(mask_bool):
        return ([], []) if return_ir_points else []

    mask_u8 = mask_bool.astype(np.uint8) * 255
    distance_map = cv2.distanceTransform(mask_u8, cv2.DIST_L2, 5)
    max_dist = float(distance_map.max())
    if max_dist <= 0.0:
        return ([], []) if return_ir_points else []

    candidates = _project_valid_ir_candidates(
        mask_bool,
        homography_inv,
        rgb_shape,
        wok_rgb_constraint=wok_rgb_constraint,
        gray_frame=gray_frame,
        min_gray=min_gray,
        axis_cx=axis_cx,
        axis_cy=axis_cy,
        axis_excl_r=axis_excl_r,
    )
    if sampling_mode == "grid_food":
        pts, pts_ir = _pick_grid_food_points(candidates, distance_map, limit, rng)
    else:
        pts, pts_ir = _pick_diverse_core_points(candidates, distance_map, limit, rng)
    if return_ir_points:
        return pts, pts_ir
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
    axis_ir_cx=None,
    axis_ir_cy=None,
    axis_ir_excl_r=None,
    n_fg=9,
    n_bg=8,
    min_cluster_gap=30.0,
    seg_mode=SEG_TWO_CLUSTER,
    seg_percentile=40,
    fg_min_gray=40,
    bg_min_gray=None,
):
    """Split IR wok pixels into food FG and hot-wok BG, then project both to RGB."""
    if (ir_frame is None or wok_mask_ir is None or homography_inv is None
            or rgb_shape is None):
        return [], [], False, None

    rng = rng or np.random.default_rng(0)
    seg_result = segment_ir_food(
        ir_frame,
        wok_mask_ir,
        mode=seg_mode,
        percentile=seg_percentile,
        min_cluster_gap=min_cluster_gap,
    )
    if seg_result.reason == "too_few_wok_pixels":
        return [], [], False, None
    c_low = seg_result.food_center
    c_high = seg_result.hot_center
    cluster_gap = seg_result.cluster_gap
    if not seg_result.ok:
        return [], [], False, {
            "food_center": c_low,
            "hot_center": c_high,
            "cluster_gap": cluster_gap,
            "threshold": seg_result.threshold,
            "seg_mode": seg_result.mode,
        }
    food_ir = seg_result.food_u8
    hot_ir = seg_result.hot_u8

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    food_ir = cv2.morphologyEx(food_ir, cv2.MORPH_OPEN, kernel)
    hot_ir = cv2.morphologyEx(hot_ir, cv2.MORPH_OPEN, kernel)
    axis_guard_ir, axis_guard_ir_radius = _build_ir_axis_exclusion_mask(
        food_ir.shape,
        homography_inv,
        axis_ir_cx=axis_ir_cx,
        axis_ir_cy=axis_ir_cy,
        axis_rgb_radius=axis_excl_r,
        axis_ir_radius=axis_ir_excl_r,
    )
    food_sampling_ir = _bool_mask(food_ir)
    if axis_guard_ir is not None:
        food_sampling_ir &= ~axis_guard_ir
    food_sampling_ir = _largest_component(food_sampling_ir)

    food_core_masks, hot_core_masks = _build_forward_core_masks(
        food_sampling_ir,
        hot_ir,
        wok_mask_ir,
    )
    fg_points, fg_ir_points = _sample_forward_core_masks(
        food_core_masks,
        homography_inv,
        rgb_shape,
        rng,
        n_fg,
        wok_rgb_constraint=wok_rgb_constraint,
        gray_frame=gray_frame,
        min_gray=fg_min_gray,
        axis_cx=axis_cx,
        axis_cy=axis_cy,
        axis_excl_r=axis_excl_r,
        sampling_mode="grid_food",
    )
    bg_points, bg_ir_points = _sample_forward_core_masks(
        hot_core_masks,
        homography_inv,
        rgb_shape,
        rng,
        n_bg,
        wok_rgb_constraint=wok_rgb_constraint,
        gray_frame=gray_frame,
        min_gray=bg_min_gray,
        axis_cx=None,
        axis_cy=None,
        axis_excl_r=None,
    )

    ok = len(fg_points) >= 4 and len(bg_points) >= 4
    return fg_points, bg_points, ok, {
        "food_center": c_low,
        "hot_center": c_high,
        "cluster_gap": cluster_gap,
        "threshold": seg_result.threshold,
        "seg_mode": seg_result.mode,
        "fg_count": len(fg_points),
        "bg_count": len(bg_points),
        "fg_ir_points": fg_ir_points,
        "bg_ir_points": bg_ir_points,
        "axis_ir_radius": axis_guard_ir_radius,
        "axis_guard_ir": axis_guard_ir,
    }


def compute_forward_reset_metrics(
    carry_mask,
    wok_rgb_constraint,
    default_wok_pixels,
    last_reinforce_wok_pct,
    axis_cx=None,
    axis_cy=None,
    axis_excl_r=None,
):
    """Compute shared metrics used by the forward reset checks."""
    mask_px = int(carry_mask.sum())
    overlap_pct = 100.0
    axis_overlap_pct = None
    centroid_dist_px = None
    upper_wok_ratio_pct = None
    upper_wok_px = None
    upper_wok_mid_y = None

    if wok_rgb_constraint is not None and mask_px > 0:
        overlap_px = int((carry_mask & wok_rgb_constraint).sum())
        overlap_pct = overlap_px / mask_px * 100
        if overlap_px > 0:
            wok_ys = np.where(wok_rgb_constraint)[0]
            if len(wok_ys) > 0:
                upper_wok_mid_y = (float(wok_ys.min()) + float(wok_ys.max())) * 0.5
                mask_wok_ys = np.where(carry_mask & wok_rgb_constraint)[0]
                upper_wok_px = int(np.count_nonzero(mask_wok_ys < upper_wok_mid_y))
                upper_wok_ratio_pct = upper_wok_px / overlap_px * 100.0

    wok_px = int(wok_rgb_constraint.sum()) if wok_rgb_constraint is not None else int(default_wok_pixels)
    mask_vs_wok = mask_px / max(wok_px, 1) * 100
    drop_pct = (last_reinforce_wok_pct - mask_vs_wok) / max(last_reinforce_wok_pct, 0.1) * 100

    if (mask_px > 0 and axis_cx is not None and axis_cy is not None
            and axis_excl_r is not None):
        ys, xs = np.where(carry_mask)
        if len(xs) > 0:
            axis_mask_px = int(np.count_nonzero(
                ((xs - float(axis_cx)) ** 2 + (ys - float(axis_cy)) ** 2)
                <= float(axis_excl_r) ** 2
            ))
            axis_overlap_pct = axis_mask_px / mask_px * 100.0
            centroid_x = float(xs.mean())
            centroid_y = float(ys.mean())
            centroid_dist_px = float(
                ((centroid_x - float(axis_cx)) ** 2 + (centroid_y - float(axis_cy)) ** 2) ** 0.5
            )

    return {
        "mask_px": mask_px,
        "overlap_pct": overlap_pct,
        "wok_px": wok_px,
        "mask_vs_wok": mask_vs_wok,
        "drop_pct": drop_pct,
        "axis_overlap_pct": axis_overlap_pct,
        "centroid_dist_px": centroid_dist_px,
        "upper_wok_ratio_pct": upper_wok_ratio_pct,
        "upper_wok_px": upper_wok_px,
        "upper_wok_mid_y": upper_wok_mid_y,
    }


def is_forward_axis_stuck_frame(
    metrics,
    axis_excl_r,
    min_axis_overlap_pct=60.0,
    centroid_radius_ratio=1.0,
):
    """Return True when the forward mask is dominated by the rotation-axis area."""
    if axis_excl_r is None:
        return False
    if metrics.get("mask_px", 0) <= 0:
        return False
    axis_overlap_pct = metrics.get("axis_overlap_pct")
    centroid_dist_px = metrics.get("centroid_dist_px")
    if axis_overlap_pct is None or centroid_dist_px is None:
        return False
    return (
        axis_overlap_pct >= float(min_axis_overlap_pct)
        and centroid_dist_px <= float(axis_excl_r) * float(centroid_radius_ratio)
    )


def is_forward_upper_wok_stuck_frame(
    metrics,
    min_upper_ratio_pct=40.0,
    min_mask_vs_wok=5.0,
    max_mask_vs_wok=25.0,
):
    """Return True when the forward mask is concentrated in the upper wok half."""
    upper_ratio = metrics.get("upper_wok_ratio_pct")
    if upper_ratio is None:
        return False
    mask_vs_wok = float(metrics.get("mask_vs_wok", 0.0))
    return (
        float(upper_ratio) >= float(min_upper_ratio_pct)
        and mask_vs_wok >= float(min_mask_vs_wok)
        and mask_vs_wok <= float(max_mask_vs_wok)
    )


def evaluate_forward_reset(
    metrics,
    last_reinforce_wok_pct,
    axis_stuck_streak=0,
    axis_stuck_min_frames=15,
    axis_excl_r=None,
    upper_wok_stuck_streak=0,
    upper_wok_stuck_min_frames=25,
    upper_wok_min_ratio_pct=40.0,
    upper_wok_min_mask_vs_wok=5.0,
    upper_wok_max_mask_vs_wok=25.0,
):
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
    if (axis_stuck_streak >= axis_stuck_min_frames
            and is_forward_axis_stuck_frame(metrics, axis_excl_r)):
        return {"need_reset": True, "reason": "axis_stuck"}
    if (upper_wok_stuck_streak >= upper_wok_stuck_min_frames
            and is_forward_upper_wok_stuck_frame(
                metrics,
                min_upper_ratio_pct=upper_wok_min_ratio_pct,
                min_mask_vs_wok=upper_wok_min_mask_vs_wok,
                max_mask_vs_wok=upper_wok_max_mask_vs_wok,
            )):
        return {"need_reset": True, "reason": "upper_wok_stuck"}
    return {"need_reset": False, "reason": None}


def resolve_forward_reset_reason(
    mask_vs_wok,
    overlap_pct,
    last_reinforce_wok_pct,
    drop_pct,
    axis_overlap_pct=None,
    centroid_dist_px=None,
    axis_stuck_streak=0,
    axis_stuck_min_frames=15,
    upper_wok_ratio_pct=None,
    upper_wok_stuck_streak=0,
    upper_wok_stuck_min_frames=25,
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
    if (axis_stuck_streak >= axis_stuck_min_frames
            and axis_overlap_pct is not None and centroid_dist_px is not None):
        return ("RESET: mask stuck near axis "
                f"(axis_overlap={axis_overlap_pct:.0f}%"
                f", centroid={centroid_dist_px:.0f}px"
                f", streak={axis_stuck_streak})")
    if (upper_wok_stuck_streak >= upper_wok_stuck_min_frames
            and upper_wok_ratio_pct is not None):
        return ("RESET: mask stuck in upper wok "
                f"(upper={upper_wok_ratio_pct:.0f}%"
                f", streak={upper_wok_stuck_streak})")
    return "RESET"
