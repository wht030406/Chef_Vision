from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np


SEG_PERCENTILE = "percentile"
SEG_TWO_CLUSTER = "two_cluster"
SEG_KMEANS = "kmeans"


@dataclass
class IRFoodSegmentation:
    food_mask: np.ndarray
    hot_mask: np.ndarray
    ok: bool
    mode: str
    threshold: Optional[float] = None
    food_center: Optional[float] = None
    hot_center: Optional[float] = None
    cluster_gap: Optional[float] = None
    reason: str = ""

    @property
    def food_u8(self):
        return self.food_mask.astype(np.uint8) * 255

    @property
    def hot_u8(self):
        return self.hot_mask.astype(np.uint8) * 255


def _empty_result(ir_frame, wok_mask_ir, mode, reason):
    shape = ir_frame.shape if ir_frame is not None else wok_mask_ir.shape
    empty = np.zeros(shape, dtype=bool)
    return IRFoodSegmentation(
        food_mask=empty,
        hot_mask=empty.copy(),
        ok=False,
        mode=mode,
        reason=reason,
    )


def segment_percentile_food(
    ir_frame,
    wok_mask_ir,
    percentile=40,
    morph_kernel=3,
):
    """Segment low-temperature food pixels with a fixed wok-percentile cutoff."""
    mode = SEG_PERCENTILE
    if ir_frame is None or wok_mask_ir is None:
        return _empty_result(ir_frame, wok_mask_ir, mode, "missing_input")

    wok_bool = wok_mask_ir.astype(bool)
    wok_temps = ir_frame[wok_bool]
    if len(wok_temps) == 0:
        return _empty_result(ir_frame, wok_bool, mode, "empty_wok")

    threshold = float(np.percentile(wok_temps, percentile))
    food_mask = wok_bool & (ir_frame <= threshold)
    if morph_kernel and morph_kernel > 1:
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (int(morph_kernel), int(morph_kernel)),
        )
        food_u8 = food_mask.astype(np.uint8) * 255
        food_u8 = cv2.morphologyEx(food_u8, cv2.MORPH_OPEN, kernel)
        food_u8 = cv2.morphologyEx(food_u8, cv2.MORPH_CLOSE, kernel)
        food_mask = food_u8 > 127

    hot_mask = wok_bool & (~food_mask)
    return IRFoodSegmentation(
        food_mask=food_mask,
        hot_mask=hot_mask,
        ok=bool(np.any(food_mask)),
        mode=mode,
        threshold=threshold,
    )


def segment_two_cluster_food(
    ir_frame,
    wok_mask_ir,
    min_cluster_gap=30.0,
    max_iter=20,
    tolerance=0.1,
):
    """Segment food as the low-temperature class from a hand-written 2-means split."""
    mode = SEG_TWO_CLUSTER
    if ir_frame is None or wok_mask_ir is None:
        return _empty_result(ir_frame, wok_mask_ir, mode, "missing_input")

    wok_bool = wok_mask_ir.astype(bool)
    wok_temps = ir_frame[wok_bool]
    if len(wok_temps) < 10:
        return _empty_result(ir_frame, wok_bool, mode, "too_few_wok_pixels")

    c_low = float(np.percentile(wok_temps, 10))
    c_high = float(np.percentile(wok_temps, 90))
    for _ in range(int(max_iter)):
        d_low = np.abs(wok_temps - c_low)
        d_high = np.abs(wok_temps - c_high)
        low_sel = d_low <= d_high
        new_low = float(np.mean(wok_temps[low_sel])) if low_sel.any() else c_low
        new_high = float(np.mean(wok_temps[~low_sel])) if (~low_sel).any() else c_high
        if abs(new_low - c_low) < tolerance and abs(new_high - c_high) < tolerance:
            break
        c_low, c_high = new_low, new_high

    cluster_gap = float(c_high - c_low)
    if cluster_gap < float(min_cluster_gap):
        return IRFoodSegmentation(
            food_mask=np.zeros(ir_frame.shape, dtype=bool),
            hot_mask=np.zeros(ir_frame.shape, dtype=bool),
            ok=False,
            mode=mode,
            food_center=c_low,
            hot_center=c_high,
            cluster_gap=cluster_gap,
            reason="cluster_gap_too_small",
        )

    vals = ir_frame[wok_bool]
    food_sel = np.abs(vals - c_low) <= np.abs(vals - c_high)
    food_mask = np.zeros(ir_frame.shape, dtype=bool)
    food_mask[wok_bool] = food_sel
    hot_mask = wok_bool & (~food_mask)

    return IRFoodSegmentation(
        food_mask=food_mask,
        hot_mask=hot_mask,
        ok=bool(np.any(food_mask)),
        mode=mode,
        food_center=c_low,
        hot_center=c_high,
        cluster_gap=cluster_gap,
    )


def segment_ir_food(
    ir_frame,
    wok_mask_ir,
    mode=SEG_TWO_CLUSTER,
    percentile=40,
    min_cluster_gap=30.0,
):
    """Dispatch the configured IR food segmentation strategy."""
    normalized = (mode or SEG_TWO_CLUSTER).lower()
    if normalized == SEG_PERCENTILE:
        return segment_percentile_food(
            ir_frame,
            wok_mask_ir,
            percentile=percentile,
        )
    if normalized in (SEG_TWO_CLUSTER, SEG_KMEANS):
        return segment_two_cluster_food(
            ir_frame,
            wok_mask_ir,
            min_cluster_gap=min_cluster_gap,
        )
    raise ValueError(f"Unknown IR food segmentation mode: {mode}")
