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


@dataclass
class LegacyHotRingUpdate:
    wok_cx: float
    wok_cy: float
    wok_rx: float
    wok_ry: float
    wok_mask_ir: object
    wok_rgb_constraint: object
    disable_static_rgb_mask: bool
    history_entry: tuple[int, float, float] | None
    hot_ref_ready: bool
    hot_sx: float
    hot_sy: float
    recent_drifts: list[float]
    tilting: bool


@dataclass
class IrWokStrategyUpdate:
    wok_mask_ir: object
    wok_cx: float
    wok_cy: float
    wok_rx: float
    wok_ry: float
    wok_rgb_constraint: object
    disable_static_rgb_mask: bool
    history_entry: tuple[int, float, float] | None
    hot_ref_ready: bool
    hot_sx: float
    hot_sy: float
    recent_drifts: list[float]
    tilting: bool


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


def apply_legacy_hot_ring_update(
    hot_fit,
    wok_cfg,
    wok_cx,
    wok_cy,
    wok_rx,
    wok_ry,
    hot_ref_ready,
    hot_sx,
    hot_sy,
    max_drift,
    chunk_start_abs,
    chunk_start_s,
    homography,
    rgb_shape,
    recent_drifts,
    tilting,
    ir_shape,
):
    wok_mask_ir = None
    wok_rgb_constraint = None
    disable_static_rgb_mask = False
    history_entry = None
    updated_recent_drifts = list(recent_drifts)
    updated_tilting = tilting

    if not hot_fit:
        return LegacyHotRingUpdate(
            wok_cx=wok_cx,
            wok_cy=wok_cy,
            wok_rx=wok_rx,
            wok_ry=wok_ry,
            wok_mask_ir=wok_mask_ir,
            wok_rgb_constraint=wok_rgb_constraint,
            disable_static_rgb_mask=disable_static_rgb_mask,
            history_entry=history_entry,
            hot_ref_ready=hot_ref_ready,
            hot_sx=hot_sx,
            hot_sy=hot_sy,
            recent_drifts=updated_recent_drifts,
            tilting=updated_tilting,
        )

    if not hot_fit.get("ok"):
        print(f"[wok-hot] t={chunk_start_s:.1f}s  skip: {hot_fit.get('reason')}")
        return LegacyHotRingUpdate(
            wok_cx=wok_cx,
            wok_cy=wok_cy,
            wok_rx=wok_rx,
            wok_ry=wok_ry,
            wok_mask_ir=wok_mask_ir,
            wok_rgb_constraint=wok_rgb_constraint,
            disable_static_rgb_mask=disable_static_rgb_mask,
            history_entry=history_entry,
            hot_ref_ready=hot_ref_ready,
            hot_sx=hot_sx,
            hot_sy=hot_sy,
            recent_drifts=updated_recent_drifts,
            tilting=updated_tilting,
        )

    ring_cx = float(hot_fit["cx"])
    ring_cy = float(hot_fit["cy"])
    ring_rx = float(hot_fit["rx"])
    ring_ry = float(hot_fit["ry"])
    if not hot_ref_ready:
        hot_sx = float(np.clip(wok_rx / max(ring_rx, 1.0), 1.02, 1.40))
        hot_sy = float(np.clip(wok_ry / max(ring_ry, 1.0), 1.02, 1.40))
        hot_ref_ready = True
        print(f"[wok-hot] expand locked  sx={hot_sx:.3f} sy={hot_sy:.3f}")

    cx_candidate = ring_cx
    cy_candidate = ring_cy
    rx_candidate = ring_rx * hot_sx
    ry_candidate = ring_ry * hot_sy
    raw_drift = (((cx_candidate - wok_cx) ** 2 + (cy_candidate - wok_cy) ** 2) ** 0.5)
    init_drift = (((cx_candidate - float(wok_cfg["cx"])) ** 2
                   + (cy_candidate - float(wok_cfg["cy"])) ** 2) ** 0.5)
    max_init_drift = max(12.0, max(wok_rx, wok_ry) * 0.28)
    rx_init_ratio = rx_candidate / max(float(wok_cfg["rx"]), 1.0)
    ry_init_ratio = ry_candidate / max(float(wok_cfg["ry"]), 1.0)

    if raw_drift > max_drift:
        print(f"[wok-edge] t={chunk_start_s:.1f}s  "
              f"reject drift={raw_drift:.1f}px>{max_drift}px")
    elif init_drift > max_init_drift:
        print(f"[wok-edge] t={chunk_start_s:.1f}s  "
              f"reject cumulative={init_drift:.1f}px>{max_init_drift:.1f}px")
    elif (rx_init_ratio < 0.78 or rx_init_ratio > 1.22
          or ry_init_ratio < 0.78 or ry_init_ratio > 1.22):
        print(f"[wok-edge] t={chunk_start_s:.1f}s  "
              f"reject radius rx={rx_init_ratio:.2f} ry={ry_init_ratio:.2f}")
    elif raw_drift > 0.5:
        cx_old, cy_old = wok_cx, wok_cy
        rx_old, ry_old = wok_rx, wok_ry
        smooth = 0.35
        r_smooth = 0.18
        wok_cx = wok_cx * (1.0 - smooth) + cx_candidate * smooth
        wok_cy = wok_cy * (1.0 - smooth) + cy_candidate * smooth
        wok_rx = wok_rx * (1.0 - r_smooth) + rx_candidate * r_smooth
        wok_ry = wok_ry * (1.0 - r_smooth) + ry_candidate * r_smooth
        drift = (((wok_cx - cx_old) ** 2 + (wok_cy - cy_old) ** 2) ** 0.5)

        ir_h, ir_w = ir_shape
        wm_new = np.zeros((ir_h, ir_w), dtype=np.uint8)
        cv2.ellipse(
            wm_new,
            (int(round(wok_cx)), int(round(wok_cy))),
            (int(round(wok_rx)), int(round(wok_ry))),
            0,
            0,
            360,
            255,
            -1,
        )
        wok_mask_ir = wm_new > 0
        if homography is not None:
            wok_rgb_constraint = project_ir_wok_to_rgb_constraint(
                wok_mask_ir, homography, rgb_shape)
            disable_static_rgb_mask = True
        history_entry = (chunk_start_abs, wok_cx, wok_cy)
        print(f"[wok-hot] t={chunk_start_s:.1f}s  "
              f"cx: {cx_old:.1f}->{wok_cx:.1f}  "
              f"cy: {cy_old:.1f}->{wok_cy:.1f}  "
              f"rx: {rx_old:.1f}->{wok_rx:.1f}  "
              f"ry: {ry_old:.1f}->{wok_ry:.1f}  "
              f"raw={raw_drift:.1f}px step={drift:.1f}px  "
              f"pts={hot_fit['points']} sectors={hot_fit['sectors']} "
              f"peak={hot_fit['peak']:.1f} mode={hot_fit['fit_mode']}")

        updated_recent_drifts.append(drift)
        if len(updated_recent_drifts) > 3:
            updated_recent_drifts.pop(0)
        cum_drift = sum(updated_recent_drifts)
        was_tilting = updated_tilting
        updated_tilting = (len(updated_recent_drifts) >= 2 and cum_drift > 30.0)
        if updated_tilting and not was_tilting:
            print(f"[tilt] t={chunk_start_s:.1f}s  "
                  f"detected quick wok motion (cum drift={cum_drift:.1f}px)")
        elif was_tilting and not updated_tilting:
            print(f"[tilt] t={chunk_start_s:.1f}s  "
                  f"wok motion stabilized (cum drift={cum_drift:.1f}px)")

    return LegacyHotRingUpdate(
        wok_cx=wok_cx,
        wok_cy=wok_cy,
        wok_rx=wok_rx,
        wok_ry=wok_ry,
        wok_mask_ir=wok_mask_ir,
        wok_rgb_constraint=wok_rgb_constraint,
        disable_static_rgb_mask=disable_static_rgb_mask,
        history_entry=history_entry,
        hot_ref_ready=hot_ref_ready,
        hot_sx=hot_sx,
        hot_sy=hot_sy,
        recent_drifts=updated_recent_drifts,
        tilting=updated_tilting,
    )


def apply_ir_wok_strategy_update(
    ir_wok_strategy,
    temp_data,
    wok_cfg,
    wok_mask_ir,
    chunk_start_abs,
    chunk_start_s,
    get_ir_idx,
    frame_shift_state,
    wok_cx,
    wok_cy,
    wok_rx,
    wok_ry,
    homography,
    rgb_shape,
    hot_ref_ready,
    hot_sx,
    hot_sy,
    max_drift,
    recent_drifts,
    tilting,
    allow_legacy_update,
    estimate_hot_ring,
):
    wok_rgb_constraint = None
    disable_static_rgb_mask = False
    history_entry = None

    frame_shift_update = apply_frame_shift_update(
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
    )
    wok_mask_ir = frame_shift_update.wok_mask_ir
    wok_cx = frame_shift_update.wok_cx
    wok_cy = frame_shift_update.wok_cy
    if frame_shift_update.wok_rgb_constraint is not None:
        wok_rgb_constraint = frame_shift_update.wok_rgb_constraint
    if frame_shift_update.disable_static_rgb_mask:
        disable_static_rgb_mask = True
    if frame_shift_update.history_entry is not None:
        history_entry = frame_shift_update.history_entry

    if (ir_wok_strategy == "legacy"
            and wok_cfg is not None
            and temp_data is not None
            and allow_legacy_update
            and homography is not None):
        ir_idx = get_ir_idx(chunk_start_abs)
        ir_frame = temp_data[ir_idx]
        hot_fit = estimate_hot_ring(ir_frame, wok_cx, wok_cy, wok_rx, wok_ry)
        legacy_update = apply_legacy_hot_ring_update(
            hot_fit,
            wok_cfg,
            wok_cx,
            wok_cy,
            wok_rx,
            wok_ry,
            hot_ref_ready,
            hot_sx,
            hot_sy,
            max_drift,
            chunk_start_abs,
            chunk_start_s,
            homography,
            rgb_shape,
            recent_drifts,
            tilting,
            ir_frame.shape[:2],
        )
        wok_cx = legacy_update.wok_cx
        wok_cy = legacy_update.wok_cy
        wok_rx = legacy_update.wok_rx
        wok_ry = legacy_update.wok_ry
        hot_ref_ready = legacy_update.hot_ref_ready
        hot_sx = legacy_update.hot_sx
        hot_sy = legacy_update.hot_sy
        recent_drifts = legacy_update.recent_drifts
        tilting = legacy_update.tilting
        if legacy_update.wok_mask_ir is not None:
            wok_mask_ir = legacy_update.wok_mask_ir
        if legacy_update.wok_rgb_constraint is not None:
            wok_rgb_constraint = legacy_update.wok_rgb_constraint
        if legacy_update.disable_static_rgb_mask:
            disable_static_rgb_mask = True
        if legacy_update.history_entry is not None:
            history_entry = legacy_update.history_entry

    return IrWokStrategyUpdate(
        wok_mask_ir=wok_mask_ir,
        wok_cx=wok_cx,
        wok_cy=wok_cy,
        wok_rx=wok_rx,
        wok_ry=wok_ry,
        wok_rgb_constraint=wok_rgb_constraint,
        disable_static_rgb_mask=disable_static_rgb_mask,
        history_entry=history_entry,
        hot_ref_ready=hot_ref_ready,
        hot_sx=hot_sx,
        hot_sy=hot_sy,
        recent_drifts=recent_drifts,
        tilting=tilting,
    )
