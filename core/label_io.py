import json


def _clip_points(points, limit):
    if limit is None:
        return list(points)
    return list(points[:limit])


def _normalize_keyframe_points(keyframe, max_fg_points=None, max_bg_points=None):
    fg_points = _clip_points(keyframe.get("fg_points", []), max_fg_points)
    bg_points = _clip_points(keyframe.get("bg_points", []), max_bg_points)
    normalized = dict(keyframe)
    normalized["fg_points"] = fg_points
    normalized["bg_points"] = bg_points
    return normalized


def load_labels(path, max_fg_points=None, max_bg_points=None):
    """Load tracking labels from either keyframe or legacy flat format."""
    with open(path, "r", encoding="utf-8") as file_obj:
        data = json.load(file_obj)

    video_path = data["video_path"]
    print(f"[Labels] video: {video_path}")

    bottom_keyframes = []
    if "bottom_keyframes" in data:
        bottom_keyframes = sorted(data["bottom_keyframes"], key=lambda item: item["frame"])
        bottom_keyframes = [
            _normalize_keyframe_points(
                keyframe,
                max_fg_points=max_fg_points,
                max_bg_points=max_bg_points,
            )
            for keyframe in bottom_keyframes
        ]
        print(f"[Bottom] {len(bottom_keyframes)} bottom keyframes loaded for inverse tracking:")
        for keyframe in bottom_keyframes:
            print(
                f"  frame {keyframe['frame']:6d} ({keyframe['time_s']:.1f}s)  "
                f"label={keyframe.get('label', '')}  "
                f"FG={len(keyframe['fg_points'])}  BG={len(keyframe['bg_points'])}"
            )

    if "keyframes" in data:
        keyframes = sorted(data["keyframes"], key=lambda item: item["frame"])
        keyframes = [
            _normalize_keyframe_points(
                keyframe,
                max_fg_points=max_fg_points,
                max_bg_points=max_bg_points,
            )
            for keyframe in keyframes
        ]
        print(f"[Labels] {len(keyframes)} food keyframes loaded:")
        for keyframe in keyframes:
            print(
                f"  frame {keyframe['frame']:6d} ({keyframe['time_s']:.1f}s)  "
                f"label={keyframe.get('label', '')}  "
                f"FG={len(keyframe['fg_points'])}  BG={len(keyframe['bg_points'])}"
            )
        start_frame = keyframes[0]["frame"]
        return video_path, start_frame, keyframes, bottom_keyframes

    fg_points = _clip_points(data["fg_points"], max_fg_points)
    bg_points = _clip_points(data["bg_points"], max_bg_points)
    start_frame = data.get("start_frame", 0)
    fps = data.get("fps", 25.0)

    print(
        f"[Labels] legacy flat format: start_frame={start_frame}  "
        f"FG={len(fg_points)}  BG={len(bg_points)}"
    )

    keyframe = {
        "frame": start_frame,
        "time_s": round(start_frame / fps, 3),
        "label": "initial_food",
        "fg_points": fg_points,
        "bg_points": bg_points,
    }
    return video_path, start_frame, [keyframe], bottom_keyframes
