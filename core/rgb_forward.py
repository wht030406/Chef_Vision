def build_forward_inject_keyframe(fg_points, bg_points=None, label="", local_frame=0):
    """Build a standard injection payload for forward SAM2 tracking."""
    return {
        "local_frame": local_frame,
        "fg_points": fg_points,
        "bg_points": bg_points or [],
        "label": label,
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
