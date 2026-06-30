import cv2
import numpy as np


def measure_rgb_mask_temperature(
    rgb_mask,
    temp_data,
    homography,
    ir_frame_idx,
    project_mask_to_ir,
):
    """Project an RGB mask into IR space and return mean/min/max temperature."""
    nan_stats = (float("nan"), float("nan"), float("nan"))
    if rgb_mask is None or temp_data is None or homography is None:
        return nan_stats
    if ir_frame_idx < 0 or ir_frame_idx >= temp_data.shape[0]:
        return nan_stats

    ir_h, ir_w = temp_data.shape[1], temp_data.shape[2]
    ir_mask = project_mask_to_ir(rgb_mask, homography, (ir_h, ir_w))
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
    project_mask_to_ir,
):
    """Project an inverse-semantic RGB mask into IR and return its mean temperature."""
    if inverse_mask is None or temp_data is None or homography is None:
        return float("nan")
    if ir_frame_idx < 0 or ir_frame_idx >= temp_data.shape[0]:
        return float("nan")
    if not inverse_mask.any():
        return float("nan")

    ir_h, ir_w = temp_data.shape[1], temp_data.shape[2]
    ir_mask = project_mask_to_ir(inverse_mask, homography, (ir_h, ir_w))
    inv_temps = temp_data[ir_frame_idx][ir_mask]
    if len(inv_temps) == 0:
        return float("nan")
    return float(np.mean(inv_temps))
