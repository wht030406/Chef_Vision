import json
import os
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class FrameShiftState:
    prev_ir: object = None
    prev_ir_idx: int | None = None
    total_dx: float = 0.0
    total_dy: float = 0.0


@dataclass
class FrameShiftUpdate:
    wok_mask_ir: object
    wok_cx: float
    wok_cy: float
    wok_rgb_constraint: object
    disable_static_rgb_mask: bool
    history_entry: tuple[int, float, float] | None


def build_ir_wok_mask(wok_cfg, ir_shape):
    ir_h, ir_w = ir_shape
    mask = np.zeros((ir_h, ir_w), dtype=np.uint8)
    cv2.ellipse(
        mask,
        (int(wok_cfg["cx"]), int(wok_cfg["cy"])),
        (int(wok_cfg["rx"]), int(wok_cfg["ry"])),
        0,
        0,
        360,
        255,
        -1,
    )
    return mask > 0


def load_ir_wok_region(wok_cfg_path, temp_data):
    if temp_data is None:
        print("[IR Mask] skipped: no temperature data")
        return None, None
    if not os.path.exists(wok_cfg_path):
        print(f"[IR Mask] skipped: wok config not found: {wok_cfg_path}")
        return None, None

    with open(wok_cfg_path, "r", encoding="utf-8") as file_obj:
        wok_cfg = json.load(file_obj)
    wok_mask_ir = build_ir_wok_mask(wok_cfg, temp_data.shape[1:3])
    print(f"[IR Mask] loaded: {wok_cfg_path}")
    print(
        f"  cx={wok_cfg['cx']} cy={wok_cfg['cy']} "
        f"rx={wok_cfg['rx']} ry={wok_cfg['ry']}  "
        f"pixels={int(wok_mask_ir.sum())}"
    )
    return wok_cfg, wok_mask_ir


def estimate_ir_frame_translation(prev_ir, curr_ir, max_shift=20.0, min_response=0.08):
    if prev_ir is None or curr_ir is None or prev_ir.shape != curr_ir.shape:
        return 0.0, 0.0, 0.0, False

    def _prep(frame):
        img = np.asarray(frame, dtype=np.float32)
        finite = np.isfinite(img)
        if not finite.any():
            return None
        lo, hi = np.percentile(img[finite], [2, 98])
        if hi <= lo:
            return None
        img = np.clip(img, lo, hi)
        img = (img - lo) / max(hi - lo, 1e-6)
        img = cv2.GaussianBlur(img, (3, 3), 0)
        img = img - cv2.GaussianBlur(img, (0, 0), 5)
        return img.astype(np.float32)

    prev = _prep(prev_ir)
    curr = _prep(curr_ir)
    if prev is None or curr is None:
        return 0.0, 0.0, 0.0, False

    try:
        win = cv2.createHanningWindow((prev.shape[1], prev.shape[0]), cv2.CV_32F)
        (dx, dy), response = cv2.phaseCorrelate(prev, curr, win)
    except Exception:
        return 0.0, 0.0, 0.0, False

    if (not np.isfinite(dx) or not np.isfinite(dy)
            or not np.isfinite(response)
            or abs(dx) > max_shift or abs(dy) > max_shift
            or response < min_response):
        return float(dx), float(dy), float(response), False
    return float(dx), float(dy), float(response), True


def translate_binary_mask(mask, dx, dy):
    if mask is None:
        return None
    h, w = mask.shape[:2]
    mat = np.array([[1.0, 0.0, float(dx)], [0.0, 1.0, float(dy)]], dtype=np.float32)
    moved = cv2.warpAffine(
        mask.astype(np.uint8),
        mat,
        (w, h),
        flags=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    return moved > 0


def project_ir_wok_to_rgb_constraint(wok_mask_ir, homography, rgb_shape):
    if wok_mask_ir is None or homography is None:
        return None
    rgb_h, rgb_w = rgb_shape
    h_inv = np.linalg.inv(homography)
    wok_u8 = wok_mask_ir.astype(np.uint8) * 255
    projected = cv2.warpPerspective(wok_u8, h_inv, (rgb_w, rgb_h))
    return projected > 64


def init_frame_shift_state(ir_wok_strategy, temp_data, wok_mask_ir, start_frame, get_ir_idx):
    state = FrameShiftState()
    if ir_wok_strategy == "frame_shift" and temp_data is not None and wok_mask_ir is not None:
        state.prev_ir_idx = get_ir_idx(start_frame)
        if state.prev_ir_idx < temp_data.shape[0]:
            state.prev_ir = temp_data[state.prev_ir_idx].copy()
            print(f"[IR Mask] frame_shift reference IR frame={state.prev_ir_idx}")
    return state


def apply_frame_shift_update(
    ir_wok_strategy,
    temp_data,
    wok_mask_ir,
    chunk_start_abs,
    get_ir_idx,
    frame_shift_state,
    wok_cx,
    wok_cy,
    homography,
    rgb_shape,
):
    wok_rgb_constraint = None
    disable_static_rgb_mask = False
    history_entry = None

    if (ir_wok_strategy != "frame_shift"
            or temp_data is None
            or wok_mask_ir is None):
        return FrameShiftUpdate(
            wok_mask_ir=wok_mask_ir,
            wok_cx=wok_cx,
            wok_cy=wok_cy,
            wok_rgb_constraint=wok_rgb_constraint,
            disable_static_rgb_mask=disable_static_rgb_mask,
            history_entry=history_entry,
        )

    try:
        ir_idx_shift = get_ir_idx(chunk_start_abs)
        if ir_idx_shift < temp_data.shape[0]:
            ir_frame_shift = temp_data[ir_idx_shift]
            if (frame_shift_state.prev_ir is not None
                    and frame_shift_state.prev_ir_idx != ir_idx_shift):
                dx, dy, response, ok = estimate_ir_frame_translation(
                    frame_shift_state.prev_ir, ir_frame_shift)
                if ok:
                    wok_mask_ir = translate_binary_mask(wok_mask_ir, dx, dy)
                    wok_cx += dx
                    wok_cy += dy
                    frame_shift_state.total_dx += dx
                    frame_shift_state.total_dy += dy
                    if homography is not None:
                        wok_rgb_constraint = project_ir_wok_to_rgb_constraint(
                            wok_mask_ir, homography, rgb_shape)
                        disable_static_rgb_mask = True
                    history_entry = (chunk_start_abs, wok_cx, wok_cy)
                    print(f"[IR Mask] frame_shift f={chunk_start_abs} "
                          f"ir={frame_shift_state.prev_ir_idx}->{ir_idx_shift} "
                          f"dx={dx:.2f} dy={dy:.2f} resp={response:.3f} "
                          f"total=({frame_shift_state.total_dx:.1f},{frame_shift_state.total_dy:.1f})")
                else:
                    print(f"[IR Mask] frame_shift skip f={chunk_start_abs} "
                          f"ir={frame_shift_state.prev_ir_idx}->{ir_idx_shift} "
                          f"dx={dx:.2f} dy={dy:.2f} resp={response:.3f}")
            frame_shift_state.prev_ir = ir_frame_shift.copy()
            frame_shift_state.prev_ir_idx = ir_idx_shift
    except Exception as exc:
        print(f"[IR Mask] frame_shift failed: {exc}")

    return FrameShiftUpdate(
        wok_mask_ir=wok_mask_ir,
        wok_cx=wok_cx,
        wok_cy=wok_cy,
        wok_rgb_constraint=wok_rgb_constraint,
        disable_static_rgb_mask=disable_static_rgb_mask,
        history_entry=history_entry,
    )
