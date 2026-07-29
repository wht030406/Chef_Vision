"""Sequential manual setup for Chef Vision initial labels.

This is only an entry-point wrapper. It keeps the mature GUI tools separate and
launches them in the order used by the main tracking workflow:

1. RGB forward food label.
2. RGB inverse bottom label.
3. IR wok ellipse, stir-axis center, and exclusion circle.
"""

import argparse
import glob
import json
import os
import subprocess
import sys

import ir_timeline


_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, ".."))


def _project_path(path):
    if path is None:
        return None
    path = os.path.expanduser(str(path))
    if os.path.isabs(path):
        return os.path.normpath(path)
    return os.path.normpath(os.path.join(_PROJECT_ROOT, path))


def _video_from_labels(labels_path):
    if not labels_path or not os.path.exists(labels_path):
        return None
    try:
        with open(labels_path, "r", encoding="utf-8") as file_obj:
            return json.load(file_obj).get("video_path")
    except Exception:
        return None


def _single_match(pattern, label):
    matches = sorted(glob.glob(pattern))
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print(f"[setup] multiple {label} files found. Please pass --video/--temp explicitly:")
        for path in matches:
            print(f"  {path}")
        raise SystemExit(1)
    return None


def _find_dataset_temp(data_dir):
    matches = [
        path for path in sorted(glob.glob(os.path.join(data_dir, "temp_*.npy")))
        if not os.path.splitext(os.path.basename(path))[0].endswith("_ts")
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print("[setup] multiple IR temperature files found. Please pass --temp explicitly:")
        for path in matches:
            print(f"  {path}")
        raise SystemExit(1)
    return None


def _run_step(title, args, *, dry_run=False):
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)
    print(" ".join(args))
    print()
    if dry_run:
        return
    result = subprocess.run(args, cwd=_PROJECT_ROOT)
    if result.returncode != 0:
        print(f"[setup] stopped at: {title}")
        raise SystemExit(result.returncode)


def _build_parser():
    parser = argparse.ArgumentParser(
        description="Run initial manual labeling in the correct order."
    )
    parser.add_argument("--video", default=None, help="RGB video path")
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Dataset directory; auto-picks rgb_*.mp4 and temp_*.npy when unique",
    )
    parser.add_argument(
        "--temp",
        "--npy",
        dest="temp",
        default=None,
        help="IR temperature npy path; omitted means auto-match from RGB video",
    )
    parser.add_argument(
        "--labels",
        default=os.path.join("core", "food_labels.json"),
        help="Output food_labels.json path",
    )
    parser.add_argument(
        "--frame",
        type=int,
        default=None,
        help="Initial RGB frame for both forward and inverse labeling windows",
    )
    parser.add_argument(
        "--skip-ir",
        action="store_true",
        help="Only run RGB forward/inverse labels, skip IR wok/axis setup",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve paths and print the three commands without opening GUI windows",
    )
    return parser


def main():
    args = _build_parser().parse_args()
    labels_path = _project_path(args.labels)
    data_dir = _project_path(args.data_dir)
    video_path = _project_path(args.video)
    if video_path is None and data_dir:
        video_path = _single_match(os.path.join(data_dir, "rgb_*.mp4"), "RGB video")
    if video_path is None:
        video_path = _project_path(_video_from_labels(labels_path))

    temp_path = _project_path(args.temp)
    if temp_path is None and data_dir:
        temp_path = _find_dataset_temp(data_dir)
    if temp_path is None:
        temp_path = ir_timeline.resolve_temp_path(video_path)

    if not video_path or not os.path.exists(video_path):
        print(f"[setup] RGB video not found: {video_path}")
        raise SystemExit(1)
    if not labels_path:
        print("[setup] labels path is required")
        raise SystemExit(1)
    if not args.skip_ir and (not temp_path or not os.path.exists(temp_path)):
        print(f"[setup] IR temperature npy not found: {temp_path}")
        raise SystemExit(1)

    label_tool = os.path.join("core", "LabelFirstFrame.py")
    ir_tool = os.path.join("core", "ir_mask_viz.py")

    frame_args = []
    if args.frame is not None:
        frame_args = ["--frame", str(args.frame)]

    _run_step(
        "Step 1/3: RGB forward food label. LMB=food FG, RMB=background BG.",
        [
            sys.executable,
            label_tool,
            "--food",
            "--video",
            video_path,
            "--output",
            labels_path,
            "--label",
            "rgb_forward_food_initial",
            *frame_args,
        ],
        dry_run=args.dry_run,
    )

    _run_step(
        "Step 2/3: RGB inverse bottom label. LMB=bottom FG, RMB=food BG.",
        [
            sys.executable,
            label_tool,
            "--bottom",
            "--video",
            video_path,
            "--output",
            labels_path,
            "--label",
            "rgb_inverse_bottom_initial",
            *frame_args,
        ],
        dry_run=args.dry_run,
    )

    if args.skip_ir:
        print("[setup] skipped IR wok/axis setup.")
        return

    _run_step(
        "Step 3/3: IR wok ellipse, stir-axis center, and exclusion circle.",
        [
            sys.executable,
            ir_tool,
            "--setup",
            "--npy",
            temp_path,
        ],
        dry_run=args.dry_run,
    )

    print()
    if args.dry_run:
        print("[setup] dry-run completed; no GUI windows were opened.")
    else:
        print("[setup] all initial manual labels completed.")
    print(f"[setup] labels: {labels_path}")
    print(f"[setup] IR wok config: {os.path.join(_PROJECT_ROOT, 'data', 'wok_region.json')}")


if __name__ == "__main__":
    main()
