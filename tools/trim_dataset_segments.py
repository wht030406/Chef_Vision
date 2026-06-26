import argparse
import json
import shutil
from pathlib import Path

import cv2
import numpy as np


def parse_segment(seg_text):
    start_text, end_text = seg_text.split("-")
    start_s = float(start_text)
    end_s = float(end_text)
    if end_s <= start_s:
        raise ValueError(f"invalid segment: {seg_text}")
    return start_s, end_s


def build_keep_mask(n_frames, fps, segments):
    keep = np.ones(n_frames, dtype=bool)
    for start_s, end_s in segments:
        start_idx = int(np.floor(start_s * fps))
        end_idx = int(np.ceil(end_s * fps))
        start_idx = max(0, min(start_idx, n_frames))
        end_idx = max(0, min(end_idx, n_frames))
        keep[start_idx:end_idx] = False
    return keep


def trim_video(src_path, dst_path, keep_mask):
    cap = cv2.VideoCapture(str(src_path))
    if not cap.isOpened():
        raise RuntimeError(f"failed to open video: {src_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(dst_path), fourcc, fps, (width, height))
    if not writer.isOpened():
        cap.release()
        raise RuntimeError(f"failed to open writer: {dst_path}")

    frame_idx = 0
    written = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame_idx < len(keep_mask) and keep_mask[frame_idx]:
            writer.write(frame)
            written += 1
        frame_idx += 1

    cap.release()
    writer.release()
    return frame_idx, written, fps


def main():
    parser = argparse.ArgumentParser(description="Trim aligned RGB/IR/temp segments into a new dataset folder.")
    parser.add_argument("--src-dir", required=True)
    parser.add_argument("--dst-dir", required=True)
    parser.add_argument("--rgb", required=True)
    parser.add_argument("--ir", required=True)
    parser.add_argument("--temp", required=True)
    parser.add_argument("--segments", nargs="+", required=True,
                        help="Segments in seconds, format start-end, e.g. 33-38 40-46")
    args = parser.parse_args()

    src_dir = Path(args.src_dir)
    dst_dir = Path(args.dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)

    rgb_path = src_dir / args.rgb
    ir_path = src_dir / args.ir
    temp_path = src_dir / args.temp
    roi_path = src_dir / "roi_config.json"

    segments = [parse_segment(seg) for seg in args.segments]

    rgb_cap = cv2.VideoCapture(str(rgb_path))
    ir_cap = cv2.VideoCapture(str(ir_path))
    if not rgb_cap.isOpened() or not ir_cap.isOpened():
        raise RuntimeError("failed to open source videos")

    rgb_frames = int(rgb_cap.get(cv2.CAP_PROP_FRAME_COUNT))
    rgb_fps = float(rgb_cap.get(cv2.CAP_PROP_FPS))
    ir_frames = int(ir_cap.get(cv2.CAP_PROP_FRAME_COUNT))
    ir_fps_meta = float(ir_cap.get(cv2.CAP_PROP_FPS))
    rgb_cap.release()
    ir_cap.release()

    temp_data = np.load(temp_path)
    temp_frames = int(temp_data.shape[0])

    if ir_frames != temp_frames:
        raise RuntimeError(f"IR video/temp frame mismatch: {ir_frames} vs {temp_frames}")

    duration_s = rgb_frames / rgb_fps
    ir_time_fps = temp_frames / duration_s

    rgb_keep = build_keep_mask(rgb_frames, rgb_fps, segments)
    ir_keep = build_keep_mask(ir_frames, ir_time_fps, segments)

    rgb_total, rgb_written, _ = trim_video(rgb_path, dst_dir / args.rgb, rgb_keep)
    ir_total, ir_written, _ = trim_video(ir_path, dst_dir / args.ir, ir_keep)

    np.save(dst_dir / args.temp, temp_data[ir_keep])
    if roi_path.exists():
        shutil.copy2(roi_path, dst_dir / roi_path.name)

    summary = {
        "source_dir": str(src_dir),
        "segments_s": segments,
        "rgb": {
            "frames_in": rgb_total,
            "frames_out": rgb_written,
            "fps": rgb_fps,
        },
        "ir": {
            "frames_in": ir_total,
            "frames_out": ir_written,
            "fps_meta": ir_fps_meta,
            "fps_time_aligned": ir_time_fps,
        },
        "temp": {
            "frames_in": temp_frames,
            "frames_out": int(ir_keep.sum()),
        },
    }
    with open(dst_dir / "trim_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
