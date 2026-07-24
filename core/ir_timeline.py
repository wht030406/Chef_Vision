import glob
import os
import re
from dataclasses import dataclass

import numpy as np


@dataclass
class IRTimeline:
    temp_path: str | None
    temp_data: np.ndarray | None
    ir_total_frames: int
    rgb_timestamps: np.ndarray | None
    ir_timestamps: np.ndarray | None
    ir_fps_ratio: float

    def get_ir_idx(self, rgb_abs_idx: int) -> int:
        """Map an absolute RGB frame index to the nearest IR frame index."""
        if self.ir_total_frames <= 0:
            return -1
        if self.rgb_timestamps is not None and self.ir_timestamps is not None:
            if rgb_abs_idx < len(self.rgb_timestamps):
                timestamp = self.rgb_timestamps[rgb_abs_idx]
                return int(np.argmin(np.abs(self.ir_timestamps - timestamp)))
        return min(int(rgb_abs_idx * self.ir_fps_ratio), self.ir_total_frames - 1)


def find_temp_npy(video_path):
    """
    Auto-match a temperature npy file for an RGB video.

    Strategy:
    1. Prefer same-name replacement: rgb_xxx.mp4 -> temp_xxx.npy.
    2. Otherwise scan temp_*.npy in the same directory and pick nearest timestamp.
    """
    base = os.path.splitext(os.path.basename(video_path))[0]
    video_dir = os.path.dirname(os.path.abspath(video_path))

    candidate = base.replace("rgb_", "temp_") + ".npy"
    candidate_path = os.path.join(video_dir, candidate)
    if os.path.exists(candidate_path):
        print(f"[温度] 找到同名温度文件: {candidate}")
        return candidate_path

    match = re.search(r"(\d{8}_\d{6})", base)
    if match:
        video_ts = match.group(1)
        best_path, best_diff = None, float("inf")
        for path in glob.glob(os.path.join(video_dir, "temp_*.npy")):
            npy_match = re.search(r"(\d{8}_\d{6})", os.path.basename(path))
            if not npy_match:
                continue
            diff = abs(
                int(npy_match.group(1).replace("_", ""))
                - int(video_ts.replace("_", ""))
            )
            if diff < best_diff:
                best_diff, best_path = diff, path
        if best_path:
            print(
                f"[温度] 自动匹配到最近温度文件: {os.path.basename(best_path)}"
                f"  (时间差 {best_diff})"
            )
            return best_path

    print("[温度] 未找到匹配的温度文件，跳过温度统计")
    return None


def load_temp_data(npy_path):
    """Load full IR temperature frames without slicing by RGB frame number."""
    if npy_path is None or not os.path.exists(npy_path):
        return None, 0
    data = np.load(npy_path)
    print(
        f"[温度] 加载 {os.path.basename(npy_path)}: "
        f"shape={data.shape}, dtype={data.dtype}"
    )
    if data.ndim == 2:
        data = data[np.newaxis, ...]
    t_min_val = float(np.min(data))
    t_max_val = float(np.max(data))
    print(
        f"[温度] 总帧数: {data.shape[0]}  "
        f"温度范围: {t_min_val:.1f}C ~ {t_max_val:.1f}C"
    )
    return data, data.shape[0]


def resolve_temp_path(video_path, temp_override=None, current_temp_path=None):
    """Resolve the temperature npy path using override, existing config, or auto-match."""
    if temp_override is not None:
        return temp_override
    if current_temp_path is not None:
        return current_temp_path
    return find_temp_npy(video_path)


def _load_rgb_timestamps(video_path):
    base = os.path.splitext(os.path.basename(video_path))[0]
    timestamp_base = base.replace("rgb_", "") if base.startswith("rgb_") else base
    candidates = [
        os.path.splitext(os.path.abspath(video_path))[0] + "_ts.npy",
        os.path.join(
            os.path.dirname(os.path.abspath(video_path)),
            f"rgb_{timestamp_base}_ts.npy",
        ),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            timestamps = np.load(candidate)
            print(
                f"[时间戳] RGB 时间戳已加载: "
                f"{os.path.basename(candidate)}  {len(timestamps)} 帧"
            )
            return timestamps
    return None


def _load_ir_timestamps(temp_path, temp_data):
    if temp_data is None or not temp_path:
        return None
    ir_ts_path = temp_path.replace(".npy", "_ts.npy")
    if os.path.exists(ir_ts_path):
        timestamps = np.load(ir_ts_path)
        print(
            f"[时间戳] IR 时间戳已加载: "
            f"{os.path.basename(ir_ts_path)}  {len(timestamps)} 帧"
        )
        return timestamps
    return None


def load_ir_timeline(video_path, temp_path, total_rgb_frames, rgb_fps):
    """Load temperature data and build the RGB->IR frame mapping helper."""
    temp_data, ir_total_frames = load_temp_data(temp_path)
    ir_timestamps = _load_ir_timestamps(temp_path, temp_data)
    rgb_timestamps = _load_rgb_timestamps(video_path)

    if rgb_timestamps is not None and ir_timestamps is not None:
        print("[时间戳] 启用时间戳帧对齐模式")
    else:
        print("[时间戳] 时间戳文件不完整，fallback 到帧率比例估算")

    ir_fps_ratio = 1.0
    if temp_data is not None and total_rgb_frames > 0:
        ir_fps_ratio = ir_total_frames / total_rgb_frames
        ir_fps_est = rgb_fps * ir_fps_ratio
        print(
            f"[帧率对齐] RGB {rgb_fps:.1f}fps x {total_rgb_frames}帧 | "
            f"IR ~{ir_fps_est:.1f}fps x {ir_total_frames}帧 | "
            f"比例 {ir_fps_ratio:.4f}"
        )

    return IRTimeline(
        temp_path=temp_path,
        temp_data=temp_data,
        ir_total_frames=ir_total_frames,
        rgb_timestamps=rgb_timestamps,
        ir_timestamps=ir_timestamps,
        ir_fps_ratio=ir_fps_ratio,
    )
