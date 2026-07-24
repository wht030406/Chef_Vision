import cv2
import numpy as np


def map_mask_to_ir(rgb_mask, homography, ir_shape):
    """Project an RGB mask into IR image coordinates."""
    h_ir, w_ir = ir_shape
    ys, xs = np.where(rgb_mask)
    if len(xs) == 0:
        return np.zeros(ir_shape, dtype=bool)

    pts_rgb = np.stack([xs, ys, np.ones(len(xs))], axis=1).T
    pts_ir = homography @ pts_rgb
    pts_ir = pts_ir[:2] / pts_ir[2]

    xi = np.round(pts_ir[0]).astype(int)
    yi = np.round(pts_ir[1]).astype(int)
    valid = (xi >= 0) & (xi < w_ir) & (yi >= 0) & (yi < h_ir)
    xi, yi = xi[valid], yi[valid]

    ir_mask = np.zeros(ir_shape, dtype=bool)
    ir_mask[yi, xi] = True
    return ir_mask


def project_ir_radius_to_rgb_radius(
    homography_inv,
    axis_ir_cx,
    axis_ir_cy,
    radius_ir,
    fallback=None,
):
    """Estimate the local RGB radius that corresponds to a manual IR radius."""
    if (
        homography_inv is None
        or axis_ir_cx is None
        or axis_ir_cy is None
        or radius_ir is None
    ):
        return fallback
    try:
        pts_ir = np.array(
            [
                [[float(axis_ir_cx), float(axis_ir_cy)]],
                [[float(axis_ir_cx) + float(radius_ir), float(axis_ir_cy)]],
                [[float(axis_ir_cx), float(axis_ir_cy) + float(radius_ir)]],
            ],
            dtype=np.float32,
        )
        pts_rgb = cv2.perspectiveTransform(pts_ir, homography_inv).reshape(-1, 2)
        radius_x = float(np.linalg.norm(pts_rgb[1] - pts_rgb[0]))
        radius_y = float(np.linalg.norm(pts_rgb[2] - pts_rgb[0]))
        radius = max(radius_x, radius_y)
        if not np.isfinite(radius) or radius <= 1.0:
            return fallback
        return radius
    except Exception:
        return fallback
