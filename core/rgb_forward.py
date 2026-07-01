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


def build_forward_ir_inject(fg_points, axis_cx, axis_cy, label, local_frame=0):
    """Build a standard IR-derived forward injection payload."""
    return build_forward_inject_keyframe(
        fg_points,
        build_forward_axis_bg(axis_cx, axis_cy),
        label=label,
        local_frame=local_frame,
    )


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
    if mask_vs_wok > 50.0:
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
    if mask_vs_wok > 50.0:
        return f"RESET: mask too large ({mask_vs_wok:.0f}%>wok50%)"
    if overlap_pct < 60.0:
        return f"RESET: mask left wok area (overlap={overlap_pct:.0f}%)"
    return "RESET"
