import cv2
import numpy as np

from projection_utils import map_mask_to_ir


def _kmeans_food_temperature(wok_temps, min_cluster_gap=30.0):
    """Estimate food temperature from the low-temperature cluster inside the wok."""
    vals = wok_temps.astype(np.float32).flatten()
    if len(vals) < 10:
        return float("nan")

    c_low = float(np.percentile(vals, 10))
    c_high = float(np.percentile(vals, 90))

    for _ in range(20):
        dist_low = np.abs(vals - c_low)
        dist_high = np.abs(vals - c_high)
        label_low = dist_low <= dist_high

        new_low = float(np.mean(vals[label_low])) if label_low.any() else c_low
        new_high = float(np.mean(vals[~label_low])) if (~label_low).any() else c_high

        if abs(new_low - c_low) < 0.1 and abs(new_high - c_high) < 0.1:
            break
        c_low, c_high = new_low, new_high

    if (c_high - c_low) < min_cluster_gap:
        return float("nan")

    dist_low = np.abs(vals - c_low)
    dist_high = np.abs(vals - c_high)
    food_mask = dist_low <= dist_high
    return float(np.mean(vals[food_mask])) if food_mask.any() else float("nan")


def estimate_ir_wok_food_temperature(
    temp_data,
    ir_frame_idx,
    wok_mask_ir,
    min_cluster_gap=30.0,
):
    """Estimate food temperature inside the current IR wok mask."""
    if temp_data is None or wok_mask_ir is None:
        return float("nan")
    if ir_frame_idx < 0 or ir_frame_idx >= temp_data.shape[0]:
        return float("nan")

    t_frame = temp_data[ir_frame_idx]
    wok_temps = t_frame[wok_mask_ir]
    if len(wok_temps) < 10:
        return float("nan")
    return _kmeans_food_temperature(wok_temps, min_cluster_gap=min_cluster_gap)


def build_ir_food_mask_by_temperature(ir_frame, wok_mask_ir, min_cluster_gap=30.0):
    """Build an IR food mask from the low-temperature cluster inside the wok."""
    if ir_frame is None or wok_mask_ir is None:
        return None

    wok_temps = ir_frame[wok_mask_ir]
    if len(wok_temps) < 10:
        return None

    c_low = float(np.percentile(wok_temps, 10))
    c_high = float(np.percentile(wok_temps, 90))
    for _ in range(20):
        food_sel = np.abs(wok_temps - c_low) <= np.abs(wok_temps - c_high)
        new_low = float(np.mean(wok_temps[food_sel])) if food_sel.any() else c_low
        new_high = float(np.mean(wok_temps[~food_sel])) if (~food_sel).any() else c_high
        if abs(new_low - c_low) < 0.1 and abs(new_high - c_high) < 0.1:
            break
        c_low, c_high = new_low, new_high

    if (c_high - c_low) < min_cluster_gap:
        return None

    ys_wok, xs_wok = np.where(wok_mask_ir)
    food_sel = np.abs(ir_frame[wok_mask_ir] - c_low) <= np.abs(ir_frame[wok_mask_ir] - c_high)
    food_ir = np.zeros(ir_frame.shape, dtype=np.uint8)
    food_ir[ys_wok[food_sel], xs_wok[food_sel]] = 255
    return food_ir


def measure_rgb_mask_temperature(
    rgb_mask,
    temp_data,
    homography,
    ir_frame_idx,
):
    """Project an RGB mask into IR space and return mean/min/max temperature."""
    nan_stats = (float("nan"), float("nan"), float("nan"))
    if rgb_mask is None or temp_data is None or homography is None:
        return nan_stats
    if ir_frame_idx < 0 or ir_frame_idx >= temp_data.shape[0]:
        return nan_stats

    ir_h, ir_w = temp_data.shape[1], temp_data.shape[2]
    ir_mask = map_mask_to_ir(rgb_mask, homography, (ir_h, ir_w))
    food_temps = temp_data[ir_frame_idx][ir_mask]
    if len(food_temps) == 0:
        return nan_stats
    return (
        float(np.mean(food_temps)),
        float(np.min(food_temps)),
        float(np.max(food_temps)),
    )


def measure_roi_temperature(temp_data, homography, ir_frame_idx, roi_cfg):
    """Project the configured RGB ROI circle into IR and return its mean temperature."""
    if roi_cfg is None or temp_data is None or homography is None:
        return float("nan")
    if ir_frame_idx < 0 or ir_frame_idx >= temp_data.shape[0]:
        return float("nan")

    try:
        ir_h, ir_w = temp_data.shape[1], temp_data.shape[2]
        rgb_pt = np.array(
            [[[float(roi_cfg["rgb_cx"]), float(roi_cfg["rgb_cy"])]]],
            dtype=np.float32,
        )
        ir_pt = cv2.perspectiveTransform(rgb_pt, homography)[0][0]
        ir_cx = int(round(ir_pt[0]))
        ir_cy = int(round(ir_pt[1]))
        ir_r = max(1, int(roi_cfg["rgb_radius"] * ir_w / roi_cfg["rgb_w"]))

        roi_mask_ir = np.zeros((ir_h, ir_w), dtype=np.uint8)
        cv2.circle(roi_mask_ir, (ir_cx, ir_cy), ir_r, 255, -1)
        roi_temps = temp_data[ir_frame_idx][roi_mask_ir > 0]
        if len(roi_temps) == 0:
            return float("nan")
        return float(np.mean(roi_temps))
    except Exception:
        return float("nan")


def measure_inverse_mask_temperature(
    inverse_mask,
    temp_data,
    homography,
    ir_frame_idx,
):
    """Project an inverse-semantic RGB mask into IR and return its mean temperature."""
    if inverse_mask is None or temp_data is None or homography is None:
        return float("nan")
    if ir_frame_idx < 0 or ir_frame_idx >= temp_data.shape[0]:
        return float("nan")
    if not inverse_mask.any():
        return float("nan")

    ir_h, ir_w = temp_data.shape[1], temp_data.shape[2]
    ir_mask = map_mask_to_ir(inverse_mask, homography, (ir_h, ir_w))
    inv_temps = temp_data[ir_frame_idx][ir_mask]
    if len(inv_temps) == 0:
        return float("nan")
    return float(np.mean(inv_temps))
