import json
import os

import cv2
import numpy as np


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
