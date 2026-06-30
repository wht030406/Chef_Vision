import cv2
import numpy as np


def render_overlay(frame_bgr, mask, color_bgr, alpha):
    """Blend a binary mask onto a frame and draw its outer contour."""
    vis = frame_bgr.copy()
    color = np.array(color_bgr, dtype=np.uint8)
    vis[mask] = (vis[mask].astype(float) * (1 - alpha) + color * alpha).astype(np.uint8)
    mask_u8 = mask.astype(np.uint8) * 255
    contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(vis, contours, -1, (255, 255, 255), 1)
    return vis
