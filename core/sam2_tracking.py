import os
import tempfile

import cv2
import numpy as np
import torch


def build_sam2_predictor(device, model_cfg, checkpoint_path):
    """Load the SAM2 video predictor used by chunk tracking."""
    from sam2.build_sam import build_sam2_video_predictor

    print(f"\n[SAM2] 加载模型: {checkpoint_path}")
    predictor = build_sam2_video_predictor(model_cfg, checkpoint_path, device=device)
    print("[SAM2] 模型加载完成")
    return predictor


def extract_chunk_to_dir(video_path, start_abs, end_abs, tmp_base, infer_size=None):
    """
    Extract video frames in [start_abs, end_abs) into a temporary SAM2 frame dir.

    infer_size is an optional (W, H) resize target for faster inference.
    Returns (tmp_dir, frame_names, actual_count).
    """
    os.makedirs(tmp_base, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="chunk_", dir=tmp_base)

    cap = cv2.VideoCapture(video_path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_abs)

    frame_names = []
    local_idx = 0
    for _ in range(end_abs - start_abs):
        ret, frame = cap.read()
        if not ret:
            break
        if infer_size is not None:
            frame = cv2.resize(frame, infer_size, interpolation=cv2.INTER_AREA)
        fname = f"{local_idx:06d}.jpg"
        cv2.imwrite(
            os.path.join(tmp_dir, fname),
            frame,
            [cv2.IMWRITE_JPEG_QUALITY, 92],
        )
        frame_names.append(fname)
        local_idx += 1

    cap.release()
    return tmp_dir, frame_names, local_idx


def scale_points(points, src_wh, dst_wh):
    """Scale point coordinates from src_wh to dst_wh."""
    if not points or src_wh == dst_wh:
        return points
    sx = dst_wh[0] / src_wh[0]
    sy = dst_wh[1] / src_wh[1]
    return [[p[0] * sx, p[1] * sy] for p in points]


def upscale_mask(mask, dst_wh):
    """Resize a boolean mask back to dst_wh=(W, H)."""
    mh, mw = mask.shape
    if (mw, mh) == dst_wh:
        return mask
    m_u8 = mask.astype(np.uint8) * 255
    m_up = cv2.resize(m_u8, dst_wh, interpolation=cv2.INTER_NEAREST)
    return m_up > 127


def track_chunk(
    predictor,
    tmp_dir,
    frame_names,
    fg_points,
    bg_points,
    carry_mask=None,
    inject_keyframes=None,
):
    """
    Run SAM2 tracking for one chunk.

    The chunk may start from a previous carry_mask, initial FG/BG points, or a
    frame-0 injected keyframe. Extra injected keyframes can be applied inside
    the chunk.
    """
    inject_keyframes = inject_keyframes or []

    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
        inference_state = predictor.init_state(video_path=tmp_dir)

        if carry_mask is not None and carry_mask.any():
            predictor.add_new_mask(
                inference_state=inference_state,
                frame_idx=0,
                obj_id=1,
                mask=carry_mask,
            )
        elif fg_points or bg_points:
            points = np.array(fg_points + bg_points, dtype=np.float32)
            labels = np.array(
                [1] * len(fg_points) + [0] * len(bg_points),
                dtype=np.int32,
            )
            predictor.add_new_points_or_box(
                inference_state=inference_state,
                frame_idx=0,
                obj_id=1,
                points=points,
                labels=labels,
            )
        else:
            has_frame0_inject = any(
                int(kf.get("local_frame", -1)) == 0 and kf.get("fg_points")
                for kf in inject_keyframes
            )
            if not has_frame0_inject:
                raise ValueError(
                    "track_chunk requires carry_mask, base points, or a frame-0 inject keyframe"
                )

        for kf_inject in inject_keyframes:
            local_f = kf_inject["local_frame"]
            kf_fg = kf_inject["fg_points"]
            kf_bg = kf_inject.get("bg_points", [])
            if not kf_fg:
                continue
            if 0 <= local_f < len(frame_names):
                pts = np.array(kf_fg + kf_bg, dtype=np.float32)
                lbls = np.array(
                    [1] * len(kf_fg) + [0] * len(kf_bg),
                    dtype=np.int32,
                )
                predictor.add_new_points_or_box(
                    inference_state=inference_state,
                    frame_idx=local_f,
                    obj_id=1,
                    points=pts,
                    labels=lbls,
                )
                print(
                    f"  [注入] 局部帧 {local_f}: FG={len(kf_fg)} BG={len(kf_bg)}"
                    f"  标签={kf_inject.get('label', '')}"
                )

        masks = {}
        for out_frame_idx, out_obj_ids, out_mask_logits in predictor.propagate_in_video(
            inference_state
        ):
            mask = (out_mask_logits[0] > 0.0).cpu().numpy().squeeze().astype(bool)
            masks[out_frame_idx] = mask

        predictor.reset_state(inference_state)
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    last_mask = masks.get(len(frame_names) - 1, None)
    return masks, last_mask


def flow_propagate_mask(prev_gray, cur_gray, prev_mask):
    """
    Propagate a mask to the next frame with Farneback optical flow.

    This is a retained, disabled-by-default acceleration path. It can reduce
    SAM2 calls in stable scenes, but food tumbling, reflections, occlusion, and
    tool motion can easily drag the propagated mask away from the real food.
    """
    if not prev_mask.any():
        return prev_mask.copy()

    flow = cv2.calcOpticalFlowFarneback(
        prev_gray,
        cur_gray,
        None,
        pyr_scale=0.5,
        levels=3,
        winsize=15,
        iterations=3,
        poly_n=5,
        poly_sigma=1.2,
        flags=0,
    )

    h, w = prev_mask.shape
    ys, xs = np.where(prev_mask)

    dx = flow[ys, xs, 0]
    dy = flow[ys, xs, 1]
    new_xs = np.round(xs + dx).astype(int)
    new_ys = np.round(ys + dy).astype(int)

    valid = (new_xs >= 0) & (new_xs < w) & (new_ys >= 0) & (new_ys < h)
    new_xs = new_xs[valid]
    new_ys = new_ys[valid]

    cur_mask = np.zeros((h, w), dtype=np.uint8)
    cur_mask[new_ys, new_xs] = 255

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    cur_mask = cv2.morphologyEx(cur_mask, cv2.MORPH_CLOSE, kernel)

    return cur_mask.astype(bool)
