import cv2
import numpy as np


def render_overlay(frame_bgr, mask, color_bgr, alpha):
    """Blend a binary mask onto a frame and draw its outer contour."""
    vis = frame_bgr.copy()
    color = np.array(color_bgr, dtype=np.uint8)
    vis[mask] = (vis[mask].astype(float) * (1 - alpha) + color * alpha).astype(np.uint8)
    mask_u8 = mask.astype(np.uint8) * 255
    contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(vis, contours, -1, (255, 255, 255), 1)
    return vis


def _draw_final_temp_chart(final_history, cur_time_s, w, h, curve_win_s):
    bar = np.zeros((h, w, 3), dtype=np.uint8)
    pts = [(t, v) for t, v in (final_history or []) if not np.isnan(v)]
    if len(pts) < 2:
        cv2.putText(bar, "Final Temp (waiting for data...)",
                    (10, max(18, h // 2)), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                    (170, 170, 170), 1)
        return bar

    t0 = max(0.0, cur_time_s - curve_win_s)
    pts = [(t, v) for t, v in pts if t >= t0]
    if len(pts) < 2:
        pts = final_history[-2:]

    times = [p[0] for p in pts]
    vals = [float(p[1]) for p in pts]
    t_min = t0
    t_max = max(cur_time_s, t0 + 1.0)
    lo = float(np.percentile(vals, 5)) if len(vals) >= 8 else float(min(vals))
    hi = float(np.percentile(vals, 95)) if len(vals) >= 8 else float(max(vals))
    if hi <= lo:
        hi = lo + 1.0
    pad_v = max(2.0, (hi - lo) * 0.12)
    v_min = max(0.0, float(np.floor((lo - pad_v) / 10.0) * 10.0))
    v_max = float(np.ceil((hi + pad_v) / 10.0) * 10.0)
    if v_max - v_min < 20.0:
        mid = 0.5 * (v_min + v_max)
        v_min = max(0.0, mid - 10.0)
        v_max = mid + 10.0

    pad_l, pad_r, pad_t, pad_b = 48, 12, 8, 18

    def tx(t):
        return pad_l + int((t - t_min) / (t_max - t_min) * (w - pad_l - pad_r))

    def ty(v):
        return pad_t + int((1.0 - (v - v_min) / (v_max - v_min)) * (h - pad_t - pad_b))

    for v in np.arange(v_min, v_max + 0.1, 10.0):
        yy = ty(v)
        cv2.line(bar, (pad_l, yy), (w - pad_r, yy), (42, 42, 42), 1)
        cv2.putText(bar, f"{v:.0f}", (2, yy + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.32, (180, 180, 180), 1)

    cv2.line(bar, (pad_l, pad_t), (pad_l, h - pad_b), (150, 150, 150), 1)
    cv2.line(bar, (pad_l, h - pad_b), (w - pad_r, h - pad_b), (150, 150, 150), 1)
    cv2.putText(bar, "[Final Output]", (pad_l + 4, pad_t + 11),
                cv2.FONT_HERSHEY_SIMPLEX, 0.38, (40, 80, 255), 1)

    screen_pts = [(tx(t), ty(v)) for t, v in zip(times, vals)]
    for i in range(1, len(screen_pts)):
        p1, p2 = screen_pts[i - 1], screen_pts[i]
        if all(0 <= c < dim for c, dim in [(p1[0], w), (p1[1], h), (p2[0], w), (p2[1], h)]):
            cv2.line(bar, p1, p2, (40, 80, 255), 2)

    cx, cy = screen_pts[-1]
    if 0 <= cx < w and 0 <= cy < h:
        cv2.circle(bar, (cx, cy), 4, (40, 80, 255), -1)
        cv2.putText(bar, f"Final:{vals[-1]:.1f}C", (cx + 6, cy + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.36, (60, 120, 255), 1)
    return bar


def draw_temp_chart(temp_history, cur_time_s, w, h, curve_win_s=60,
                    roi_history=None, ir_mask_history=None, inverse_history=None,
                    final_history=None):
    """Render the rolling temperature chart used in tracking videos."""
    if final_history:
        compare_h = max(72, int(h * 0.62))
        final_h = max(40, h - compare_h)
        compare_h = h - final_h
        top = draw_temp_chart(
            temp_history,
            cur_time_s,
            w,
            compare_h,
            curve_win_s,
            roi_history=roi_history,
            ir_mask_history=ir_mask_history,
            inverse_history=inverse_history,
            final_history=None,
        )
        bottom = _draw_final_temp_chart(final_history, cur_time_s, w, final_h, curve_win_s)
        return np.vstack([top, bottom])

    bar = np.zeros((h, w, 3), dtype=np.uint8)
    if len(temp_history) < 2:
        cv2.putText(bar, "Mask Avg Temp (waiting for data...)",
                    (10, h // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (160, 160, 160), 1)
        return bar

    t0 = max(0.0, cur_time_s - curve_win_s)
    pts = [(t, v) for t, v in temp_history if t >= t0 and not np.isnan(v)]
    if len(pts) < 2:
        pts = temp_history[-2:]

    times = [p[0] for p in pts]
    vals = [p[1] for p in pts]

    roi_pts = []
    if roi_history:
        roi_pts = [(t, v) for t, v in roi_history if t >= t0 and not np.isnan(v)]

    ir_pts = []
    if ir_mask_history:
        ir_pts = [(t, v) for t, v in ir_mask_history if t >= t0 and not np.isnan(v)]

    inv_pts = []
    if inverse_history:
        inv_pts = [(t, v) for t, v in inverse_history if t >= t0 and not np.isnan(v)]

    all_vals = vals + [v for _, v in roi_pts] + [v for _, v in ir_pts] + [v for _, v in inv_pts]
    t_min = t0
    t_max = max(cur_time_s, t0 + 1.0)
    if len(all_vals) >= 8:
        lo = float(np.percentile(all_vals, 5))
        hi = float(np.percentile(all_vals, 95))
    else:
        lo = float(min(all_vals))
        hi = float(max(all_vals))
    if hi <= lo:
        hi = lo + 1.0
    pad_v = max(2.0, (hi - lo) * 0.08)
    latest_vals = [vals[-1]]
    if roi_pts:
        latest_vals.append(roi_pts[-1][1])
    if ir_pts:
        latest_vals.append(ir_pts[-1][1])
    if inv_pts:
        latest_vals.append(inv_pts[-1][1])
    v_min = max(0.0, min(lo, min(latest_vals)) - pad_v)
    v_max = max(hi, max(latest_vals)) + pad_v
    if v_max <= v_min:
        v_max = v_min + 10.0

    # Use a cleaner 10C vertical unit so the chart is easier to read.
    v_min = float(np.floor(v_min / 10.0) * 10.0)
    v_max = float(np.ceil(v_max / 10.0) * 10.0)
    if v_max - v_min < 20.0:
        mid = 0.5 * (v_min + v_max)
        v_min = max(0.0, mid - 10.0)
        v_max = mid + 10.0

    pad_l, pad_r, pad_t, pad_b = 48, 12, 10, 22

    def tx(t):
        return pad_l + int((t - t_min) / (t_max - t_min) * (w - pad_l - pad_r))

    def ty(v):
        return pad_t + int((1.0 - (v - v_min) / (v_max - v_min)) * (h - pad_t - pad_b))

    grid_vals = np.arange(v_min, v_max + 0.1, 10.0)
    for v in grid_vals:
        yy = ty(v)
        cv2.line(bar, (pad_l, yy), (w - pad_r, yy), (45, 45, 45), 1)
        cv2.putText(bar, f"{v:.0f}", (2, yy + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (180, 180, 180), 1)

    cv2.line(bar, (pad_l, pad_t), (pad_l, h - pad_b), (160, 160, 160), 1)
    cv2.line(bar, (pad_l, h - pad_b), (w - pad_r, h - pad_b), (160, 160, 160), 1)

    cv2.putText(bar, f"{t_min:.0f}s", (pad_l, h - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.32, (140, 140, 140), 1)
    cv2.putText(bar, f"{cur_time_s:.1f}s", (w - pad_r - 30, h - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.32, (140, 140, 140), 1)

    screen_pts = [(tx(t), ty(v)) for t, v in zip(times, vals)]
    for i in range(1, len(screen_pts)):
        p1, p2 = screen_pts[i - 1], screen_pts[i]
        if all(0 <= c < dim for c, dim in [(p1[0], w), (p1[1], h), (p2[0], w), (p2[1], h)]):
            cv2.line(bar, p1, p2, (50, 165, 255), 2)

    if len(roi_pts) >= 2:
        roi_screen = [(tx(t), ty(v)) for t, v in roi_pts]
        for i in range(1, len(roi_screen)):
            p1, p2 = roi_screen[i - 1], roi_screen[i]
            if all(0 <= c < dim for c, dim in [(p1[0], w), (p1[1], h), (p2[0], w), (p2[1], h)]):
                cv2.line(bar, p1, p2, (255, 160, 30), 2)
        rx, ry = roi_screen[-1]
        if 0 <= rx < w and 0 <= ry < h:
            cv2.circle(bar, (rx, ry), 4, (255, 100, 0), -1)
            cv2.putText(bar, f"ROI:{roi_pts[-1][1]:.1f}C", (rx + 6, ry + 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 180, 60), 1)

    if len(ir_pts) >= 2:
        ir_screen = [(tx(t), ty(v)) for t, v in ir_pts]
        for i in range(1, len(ir_screen)):
            p1, p2 = ir_screen[i - 1], ir_screen[i]
            if all(0 <= c < dim for c, dim in [(p1[0], w), (p1[1], h), (p2[0], w), (p2[1], h)]):
                cv2.line(bar, p1, p2, (0, 220, 80), 2)
        irx, iry = ir_screen[-1]
        if 0 <= irx < w and 0 <= iry < h:
            cv2.circle(bar, (irx, iry), 4, (0, 255, 60), -1)
            cv2.putText(bar, f"IR:{ir_pts[-1][1]:.1f}C", (irx + 6, iry + 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 255, 100), 1)

    cx, cy = tx(cur_time_s), ty(vals[-1])
    if 0 <= cx < w and 0 <= cy < h:
        cv2.circle(bar, (cx, cy), 4, (0, 60, 255), -1)
        cv2.putText(bar, f"Mask:{vals[-1]:.1f}C", (cx + 6, cy + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 200, 255), 1)

    if len(inv_pts) >= 2:
        inv_screen = [(tx(t), ty(v)) for t, v in inv_pts]
        for i in range(1, len(inv_screen)):
            p1, p2 = inv_screen[i - 1], inv_screen[i]
            if all(0 <= c < dim for c, dim in [(p1[0], w), (p1[1], h), (p2[0], w), (p2[1], h)]):
                cv2.line(bar, p1, p2, (200, 80, 255), 2)
        ivx, ivy = inv_screen[-1]
        if 0 <= ivx < w and 0 <= ivy < h:
            cv2.circle(bar, (ivx, ivy), 4, (200, 80, 255), -1)
            cv2.putText(bar, f"Inv:{inv_pts[-1][1]:.1f}C", (ivx + 6, ivy + 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.38, (200, 80, 255), 1)

    cv2.putText(bar, "[SAM2]", (pad_l + 4, pad_t + 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.38, (50, 165, 255), 1)
    if roi_pts:
        cv2.putText(bar, "[ROI]", (pad_l + 70, pad_t + 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 160, 30), 1)
    if ir_pts:
        cv2.putText(bar, "[IR-Auto]", (pad_l + 120, pad_t + 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 220, 80), 1)
    if inv_pts:
        cv2.putText(bar, "[Inv]", (pad_l + 200, pad_t + 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (200, 80, 255), 1)

    return bar
