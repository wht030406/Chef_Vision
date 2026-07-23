import os

import cv2
import numpy as np


def build_chunk_reference_path(out_dir, scheme, chunk_index, time_s, frame_idx, source_tag):
    safe_source = "".join(
        ch.lower() if str(ch).isalnum() else "_"
        for ch in str(source_tag or "reference")
    ).strip("_") or "reference"
    filename = (
        f"{scheme}_chunk{int(chunk_index):03d}_"
        f"t{float(time_s):05.1f}s_f{int(frame_idx)}_{safe_source}.jpg"
    )
    return os.path.join(out_dir, filename)


def _draw_action_badge(vis, action_tag, color):
    if vis is None or not action_tag:
        return
    text = str(action_tag)
    font = cv2.FONT_HERSHEY_SIMPLEX
    (tw, th), _ = cv2.getTextSize(text, font, 0.82, 2)
    x0 = max(20, vis.shape[1] - tw - 250)
    y0 = 18
    x1 = min(vis.shape[1] - 20, x0 + tw + 26)
    y1 = y0 + th + 20
    cv2.rectangle(vis, (x0, y0), (x1, y1), (20, 20, 20), -1)
    cv2.rectangle(vis, (x0, y0), (x1, y1), color, 2)
    cv2.putText(vis, text, (x0 + 12, y1 - 10), font, 0.82, color, 2)


def save_rgb_chunk_reference(
    preview_path,
    frame_bgr,
    header,
    detail_lines=None,
    wok_rgb_constraint=None,
    carry_mask=None,
    fg_points=None,
    bg_points=None,
    action_tag=None,
    header_color=(255, 255, 255),
    action_color=(0, 220, 255),
    fg_color=(0, 255, 255),
    bg_color=(255, 80, 0),
    legend_line=None,
):
    if preview_path is None or frame_bgr is None:
        return

    os.makedirs(os.path.dirname(preview_path), exist_ok=True)
    vis = frame_bgr.copy()
    if wok_rgb_constraint is not None:
        shade = np.zeros_like(vis)
        shade[wok_rgb_constraint] = (70, 70, 70)
        vis = cv2.addWeighted(vis, 1.0, shade, 0.22, 0)
    if carry_mask is not None and np.any(carry_mask):
        vis[carry_mask] = (
            vis[carry_mask].astype(float) * 0.5
            + np.array([0, 0, 220]) * 0.5
        ).astype(np.uint8)

    for x, y in fg_points or []:
        cv2.circle(vis, (int(round(x)), int(round(y))), 8, fg_color, -1)
        cv2.circle(vis, (int(round(x)), int(round(y))), 9, (0, 0, 0), 1)
    for x, y in bg_points or []:
        cv2.circle(vis, (int(round(x)), int(round(y))), 8, bg_color, -1)
        cv2.circle(vis, (int(round(x)), int(round(y))), 9, (255, 255, 255), 1)

    if header:
        cv2.putText(vis, header, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.90, header_color, 2)

    lines = list(detail_lines or [])
    if legend_line:
        lines.append(legend_line)
    for idx, line in enumerate(lines):
        y = 78 + idx * 32
        cv2.putText(vis, str(line), (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (255, 255, 255), 2)

    _draw_action_badge(vis, action_tag, action_color)
    cv2.imwrite(preview_path, vis)


def save_irfix_mask_comparison(
    preview_path,
    frame_bgr,
    header,
    detail_lines=None,
    wok_rgb_constraint=None,
    original_mask=None,
    fixed_mask=None,
    action_tag="IR-fix",
):
    if preview_path is None or frame_bgr is None:
        return

    os.makedirs(os.path.dirname(preview_path), exist_ok=True)
    vis = frame_bgr.copy()

    if wok_rgb_constraint is not None:
        shade = np.zeros_like(vis)
        shade[wok_rgb_constraint] = (70, 70, 70)
        vis = cv2.addWeighted(vis, 1.0, shade, 0.22, 0)

    orig = None
    fixed = None
    if original_mask is not None:
        orig = np.asarray(original_mask).astype(bool)
    if fixed_mask is not None:
        fixed = np.asarray(fixed_mask).astype(bool)

    if orig is not None and np.any(orig):
        vis[orig] = (
            vis[orig].astype(float) * 0.45
            + np.array([0, 0, 255]) * 0.55
        ).astype(np.uint8)
    if fixed is not None and np.any(fixed):
        vis[fixed] = (
            vis[fixed].astype(float) * 0.45
            + np.array([0, 255, 0]) * 0.55
        ).astype(np.uint8)
    if orig is not None and fixed is not None:
        overlap = orig & fixed
        if np.any(overlap):
            vis[overlap] = (
                vis[overlap].astype(float) * 0.35
                + np.array([0, 255, 255]) * 0.65
            ).astype(np.uint8)

    if header:
        cv2.putText(vis, header, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.90, (255, 255, 255), 2)

    lines = list(detail_lines or [])
    lines.append("[red=old RGB mask | green=IR-fix mask | yellow=overlap]")
    for idx, line in enumerate(lines):
        y = 78 + idx * 32
        cv2.putText(vis, str(line), (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (255, 255, 255), 2)

    _draw_action_badge(vis, action_tag, (0, 220, 255))
    cv2.imwrite(preview_path, vis)
