def build_forward_inject_keyframe(fg_points, bg_points=None, label="", local_frame=0):
    """Build a standard injection payload for forward SAM2 tracking."""
    return {
        "local_frame": local_frame,
        "fg_points": fg_points,
        "bg_points": bg_points or [],
        "label": label,
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


def resolve_forward_reset_reason(
    mask_vs_wok,
    overlap_pct,
    last_reinforce_wok_pct,
    drop_pct,
):
    """Resolve the reason text for a forward-tracking reset."""
    if mask_vs_wok < 2.0:
        return f"RESET: mask过小({mask_vs_wok:.1f}%<2%)"
    if last_reinforce_wok_pct > 5.0 and drop_pct > 70.0:
        return f"RESET: 骤降({last_reinforce_wok_pct:.0f}%→{mask_vs_wok:.0f}%)"
    if mask_vs_wok > 35.0:
        return f"RESET: mask过大({mask_vs_wok:.0f}%>wok35%)"
    if overlap_pct < 60.0:
        return f"RESET: 偏离锅内(overlap={overlap_pct:.0f}%)"
    return "RESET"
