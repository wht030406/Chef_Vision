import cv2
import numpy as np


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
