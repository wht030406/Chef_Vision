"""Helpers for saving tracking debug artifacts."""

import os

import cv2
import numpy as np


def save_violation_event_image(out_dir, filename, frame_bgr, bad_mask, header, detail_lines):
    if frame_bgr is None:
        return
    vis = frame_bgr.copy()
    if bad_mask is not None and np.any(bad_mask):
        vis[bad_mask] = (
            vis[bad_mask].astype(float) * 0.5
            + np.array([0, 0, 220]) * 0.5
        ).astype(np.uint8)
    cv2.putText(vis, header, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.95, (0, 0, 255), 2)
    for idx, line in enumerate(detail_lines or []):
        y = 78 + idx * 32
        cv2.putText(vis, line, (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (255, 255, 255), 2)
    cv2.imwrite(os.path.join(out_dir, filename), vis)


def save_ir_relabel_frame_image(
    out_dir,
    filename,
    ir_frame,
    wok_mask,
    header,
    detail_lines,
    food_mask=None,
    hot_mask=None,
    fg_points_ir=None,
    bg_points_ir=None,
    axis_guard_mask=None,
):
    if ir_frame is None:
        return
    try:
        ir_vis = ir_frame.astype(np.float32)
        if wok_mask is not None and np.any(wok_mask):
            vals = ir_vis[wok_mask]
        else:
            vals = ir_vis.reshape(-1)
        lo = float(np.percentile(vals, 2)) if len(vals) else float(np.min(ir_vis))
        hi = float(np.percentile(vals, 98)) if len(vals) else float(np.max(ir_vis))
        if hi <= lo:
            hi = lo + 1.0
        norm = np.clip((ir_vis - lo) / (hi - lo), 0.0, 1.0)
        ir_u8 = (norm * 255.0).astype(np.uint8)
        vis = cv2.applyColorMap(ir_u8, cv2.COLORMAP_TURBO)
        vis = cv2.resize(vis, None, fx=4.0, fy=4.0, interpolation=cv2.INTER_NEAREST)

        def draw_mask_outline(mask, color):
            if mask is None:
                return
            mask_u8 = (mask > 0).astype(np.uint8) * 255
            cnts, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not cnts:
                return
            scaled = [(c * 4).astype(np.int32) for c in cnts]
            cv2.drawContours(vis, scaled, -1, color, 2)

        draw_mask_outline(wok_mask, (255, 255, 255))
        draw_mask_outline(food_mask, (0, 255, 255))
        draw_mask_outline(hot_mask, (0, 80, 255))
        draw_mask_outline(axis_guard_mask, (20, 20, 20))

        for x_ir, y_ir in (fg_points_ir or []):
            cx = int(round(float(x_ir) * 4.0))
            cy = int(round(float(y_ir) * 4.0))
            cv2.circle(vis, (cx, cy), 7, (0, 255, 80), -1)
            cv2.circle(vis, (cx, cy), 8, (0, 0, 0), 1)
        for x_ir, y_ir in (bg_points_ir or []):
            cx = int(round(float(x_ir) * 4.0))
            cy = int(round(float(y_ir) * 4.0))
            cv2.circle(vis, (cx, cy), 7, (255, 80, 0), -1)
            cv2.circle(vis, (cx, cy), 8, (255, 255, 255), 1)

        cv2.putText(vis, header, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.95, (255, 255, 255), 2)
        for idx, line in enumerate(detail_lines or []):
            y = 78 + idx * 30
            cv2.putText(vis, line, (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (255, 255, 255), 2)
        cv2.imwrite(os.path.join(out_dir, filename), vis)
    except Exception:
        pass


def draw_action_badge(vis, action_tag, color=(0, 220, 255)):
    if vis is None or not action_tag:
        return vis
    tag = str(action_tag)
    font = cv2.FONT_HERSHEY_SIMPLEX
    (tw, th), _ = cv2.getTextSize(tag, font, 0.9, 2)
    right_pad = 140
    x1 = max(tw + 46, vis.shape[1] - right_pad)
    x0 = max(20, x1 - tw - 26)
    y0 = 20
    x1 = min(vis.shape[1] - 20, x0 + tw + 26)
    y1 = y0 + th + 20
    cv2.rectangle(vis, (x0, y0), (x1, y1), (20, 20, 20), -1)
    cv2.rectangle(vis, (x0, y0), (x1, y1), color, 2)
    cv2.putText(vis, tag, (x0 + 12, y1 - 10), font, 0.9, color, 2)
    return vis


def append_violation_event_action(out_dir, filename, action_tag, action_line):
    if not filename:
        return
    path = os.path.join(out_dir, filename)
    if not os.path.exists(path):
        return
    vis = cv2.imread(path)
    if vis is None:
        return
    draw_action_badge(vis, action_tag)
    y0 = min(vis.shape[0] - 24, 220)
    cv2.putText(vis, action_line, (20, y0), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (255, 255, 255), 2)
    cv2.imwrite(path, vis)
