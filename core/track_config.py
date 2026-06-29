import argparse
import json
import os
from dataclasses import dataclass


@dataclass
class TrackRuntimeConfig:
    run_config_path: str | None
    labels_json: str
    video_override: str | None
    temp_override: str | None
    homography_path: str
    wok_cfg_path: str
    ir_wok_strategy: str
    output_root: str
    max_frames: int | None


def _resolve_project_path(path, project_root, base_dir=None):
    if path is None:
        return None
    path = os.path.expanduser(str(path))
    if os.path.isabs(path):
        return os.path.normpath(path)
    if base_dir:
        by_config = os.path.normpath(os.path.join(base_dir, path))
        if os.path.exists(by_config):
            return by_config
    return os.path.normpath(os.path.join(project_root, path))


def _load_run_config(path, project_root):
    if not path:
        return {}, None, None
    config_path = _resolve_project_path(path, project_root)
    if not os.path.exists(config_path):
        print(f"[error] run config not found: {config_path}")
        raise SystemExit(1)
    with open(config_path, "r", encoding="utf-8") as file_obj:
        return json.load(file_obj), os.path.dirname(config_path), config_path


def _cfg_first(config, *keys):
    for key in keys:
        value = config.get(key)
        if value not in (None, ""):
            return value
    return None


def _build_parser():
    parser = argparse.ArgumentParser(description="Run Chef Vision tracking")
    parser.add_argument("--run-config", "--config", dest="run_config", default=None,
                        help="JSON config with video/labels/temp/wok paths")
    parser.add_argument("--labels", default=None,
                        help="Path to food_labels.json")
    parser.add_argument("--video", default=None,
                        help="Override RGB video path from labels/config")
    parser.add_argument("--temp", "--npy", dest="temp", default=None,
                        help="Temperature npy path; omitted means auto-match from video")
    parser.add_argument("--homography", default=None,
                        help="Path to homography.npy")
    parser.add_argument("--wok", "--wok-config", dest="wok_config", default=None,
                        help="Path to wok_region.json")
    parser.add_argument("--ir-wok-strategy", default=None,
                        choices=("legacy", "static", "frame_shift"),
                        help="IR wok update strategy: legacy uses old cues; static keeps the initial manual region; frame_shift translates the previous mask by IR frame registration")
    parser.add_argument("--output-root", default=None,
                        help="Output root directory; default is project output/")
    parser.add_argument("--max-frames", type=int, default=None,
                        help="Optional short-run limit from the start frame; default runs the full video")
    return parser


def resolve_runtime_config(
    argv,
    project_root,
    default_labels_json,
    default_homography_path,
    default_wok_cfg_path,
    default_output_root,
):
    parser = _build_parser()
    args = parser.parse_args(argv)

    run_config, run_config_dir, run_config_path = _load_run_config(args.run_config, project_root)
    labels_json = _resolve_project_path(
        args.labels or _cfg_first(run_config, "labels", "labels_path", "food_labels"),
        project_root,
        run_config_dir,
    ) or default_labels_json
    video_override = _resolve_project_path(
        args.video or _cfg_first(run_config, "video", "video_path", "rgb_video"),
        project_root,
        run_config_dir,
    )
    homography_path = _resolve_project_path(
        args.homography or _cfg_first(run_config, "homography", "homography_path"),
        project_root,
        run_config_dir,
    ) or default_homography_path
    wok_cfg_path = _resolve_project_path(
        args.wok_config or _cfg_first(run_config, "wok", "wok_config", "wok_region"),
        project_root,
        run_config_dir,
    ) or default_wok_cfg_path
    temp_override = _resolve_project_path(
        args.temp or _cfg_first(run_config, "temp", "temp_path", "npy", "temperature"),
        project_root,
        run_config_dir,
    )
    ir_wok_strategy = (
        args.ir_wok_strategy
        or _cfg_first(run_config, "ir_wok_strategy", "wok_strategy")
        or "legacy"
    )
    if ir_wok_strategy not in ("legacy", "static", "frame_shift"):
        print(f"[error] invalid ir_wok_strategy: {ir_wok_strategy}")
        raise SystemExit(1)
    output_root = _resolve_project_path(
        args.output_root or _cfg_first(run_config, "output_root", "output_dir"),
        project_root,
        run_config_dir,
    ) or default_output_root

    return TrackRuntimeConfig(
        run_config_path=run_config_path,
        labels_json=labels_json,
        video_override=video_override,
        temp_override=temp_override,
        homography_path=homography_path,
        wok_cfg_path=wok_cfg_path,
        ir_wok_strategy=ir_wok_strategy,
        output_root=output_root,
        max_frames=args.max_frames,
    )
