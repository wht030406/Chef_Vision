"""
bench_chunk.py — 测试 SAM2 + 640p 缩放的单批次处理速度
只跑前 3 批，输出每批耗时，不写视频/CSV
"""
import os, sys, time, shutil
import cv2, numpy as np, torch

# 把 core 加入路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "core"))

from TrackFood import (
    load_labels, build_sam2_predictor,
    extract_chunk_to_dir, track_chunk,
    scale_points, upscale_mask,
    LABELS_JSON, CHECKPOINT_PATH, MODEL_CFG,
    SAM2_INFER_SIZE, CHUNK_SIZE
)

BENCH_BATCHES = 2   # 只跑前 N 批（100帧批次跑2批就够了）

def main():
    video_path, start_frame, keyframes = load_labels(LABELS_JSON)
    first_kf  = keyframes[0]
    fg_points = first_kf["fg_points"]
    bg_points = first_kf["bg_points"]

    cap_info = cv2.VideoCapture(video_path)
    total_frames = int(cap_info.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap_info.get(cv2.CAP_PROP_FPS)
    VW  = int(cap_info.get(cv2.CAP_PROP_FRAME_WIDTH))
    VH  = int(cap_info.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap_info.release()

    orig_wh  = (VW, VH)
    infer_wh = SAM2_INFER_SIZE if SAM2_INFER_SIZE else orig_wh
    do_resize = (infer_wh != orig_wh)

    fg_infer = scale_points(fg_points, orig_wh, infer_wh) if do_resize else fg_points
    bg_infer = scale_points(bg_points, orig_wh, infer_wh) if do_resize else bg_points

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[设备] {device}  GPU: {torch.cuda.get_device_name(0) if device.type=='cuda' else 'N/A'}")
    print(f"[配置] CHUNK_SIZE={CHUNK_SIZE}  SAM2_INFER_SIZE={SAM2_INFER_SIZE}")
    print(f"[视频] {VW}x{VH}  FPS={fps:.1f}  起始帧={start_frame}")

    predictor = build_sam2_predictor(device)

    carry_mask = None
    times = []

    for chunk_i in range(BENCH_BATCHES):
        chunk_start = start_frame + chunk_i * CHUNK_SIZE
        chunk_end   = min(chunk_start + CHUNK_SIZE, total_frames)

        t0 = time.perf_counter()

        tmp_dir, frame_names, actual = extract_chunk_to_dir(
            video_path, chunk_start, chunk_end,
            infer_size=SAM2_INFER_SIZE
        )

        try:
            carry_infer = None
            if carry_mask is not None and do_resize:
                carry_infer = upscale_mask(carry_mask, infer_wh) \
                    if carry_mask.shape != (infer_wh[1], infer_wh[0]) else carry_mask
            else:
                carry_infer = carry_mask

            chunk_masks, carry_raw = track_chunk(
                predictor, tmp_dir, frame_names,
                fg_infer, bg_infer,
                carry_mask=carry_infer,
            )
            if do_resize and carry_raw is not None:
                carry_mask = upscale_mask(carry_raw, orig_wh)
            else:
                carry_mask = carry_raw
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        elapsed = time.perf_counter() - t0
        times.append(elapsed)
        video_dur = actual / fps
        print(f"  批次 {chunk_i+1}: {actual}帧  耗时 {elapsed:.2f}s  "
              f"视频时长 {video_dur:.2f}s  "
              f"{'✅ 实时' if elapsed <= video_dur else f'❌ 超时 {elapsed/video_dur:.1f}x'}")

    avg = sum(times) / len(times)
    video_dur = CHUNK_SIZE / fps
    print(f"\n平均耗时: {avg:.2f}s / 批  视频时长: {video_dur:.2f}s/批")
    print(f"速度比: {avg/video_dur:.2f}x  "
          f"({'✅ 可实时' if avg <= video_dur else '❌ 需要 tiny 模型或进一步降分辨率'})")

if __name__ == "__main__":
    main()
