"""
LabelFirstFrame.py — 手动定位食材入锅帧 + 交互标注（支持多关键帧追加）

功能：
1. 弹出 OpenCV 交互窗口，让用户用键盘跳帧到食材入锅的位置
2. 用户点前景/背景点标注食材
3. 保存结果到 food_labels.json，供 TrackFood.py 使用

food_labels.json 结构（多关键帧格式）：
{
  "video_path": "rgb_20260428_121157.mp4",
  "fps": 25.0,
  "keyframes": [
    {
      "frame":      780,
      "time_s":     31.2,
      "label":      "肉（初始帧）",
      "fg_points":  [[x, y], ...],
      "bg_points":  [[x, y], ...]
    },
    {
      "frame":      1500,
      "time_s":     60.0,
      "label":      "青椒入锅",
      "fg_points":  [[x, y], ...],
      "bg_points":  []
    }
  ]
}

用法：
  # 初始标注（新建文件，覆盖旧格式）
  python LabelFirstFrame.py

  # 追加模式：在第 N 帧追加新关键帧标注
  python LabelFirstFrame.py --append --frame 1500

  # 追加并指定标签说明
  python LabelFirstFrame.py --append --frame 1500 --label "青椒入锅"

操作键：
  左键点击      → 添加前景点（绿色圆点，点在食材上）
  右键点击      → 添加背景点（红色圆点，点在锅底/锅外）
  Z 键          → 撤销上一个点
  S 键          → 保存并退出
  Q 键          → 退出不保存
  ← / A         → 向前 SKIP_FRAMES 帧
  → / D         → 向后 SKIP_FRAMES 帧
  [ / ,         → 向前/向后 1 帧（精细调整）
  ] / .         → 向前/向后 1 帧（精细调整）
  Page Up/Down  → 向前/向后 300 帧（快速跳转）
  数字键 0-9   → 跳到视频 0%~90% 位置（快速定位）
"""

import cv2
import numpy as np
import json
import sys
import os
import argparse

# ── 路径基准（本文件所在目录）────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))

# ── 配置 ─────────────────────────────────────────────────────────────────────
VIDEO_PATH   = os.path.join(_HERE, "..", "test_data", "test2", "rgb_20260529_115116.mp4")
OUTPUT_JSON  = os.path.join(_HERE, "food_labels.json")
SKIP_FRAMES  = 30      # ← → 键每次跳多少帧


# ── JSON 格式处理 ─────────────────────────────────────────────────────────────

def load_or_init_labels(json_path, video_path, fps):
    """
    加载现有 JSON（自动兼容旧格式迁移为新格式）。
    若文件不存在则返回空结构。
    """
    if not os.path.exists(json_path):
        return {
            "video_path": video_path,
            "fps": fps,
            "keyframes": []
        }

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # ── 旧格式迁移（flat 结构 → 多关键帧列表）──────────────────────────────
    if "keyframes" not in data:
        print("[迁移] 检测到旧版 food_labels.json，自动迁移为多关键帧格式...")
        old_frame = data.get("start_frame", 0)
        old_fps   = data.get("fps", fps)
        migrated = {
            "video_path": data.get("video_path", video_path),
            "fps":        old_fps,
            "keyframes": [
                {
                    "frame":     old_frame,
                    "time_s":    round(old_frame / old_fps, 3),
                    "label":     "初始标注（肉）",
                    "fg_points": data.get("fg_points", []),
                    "bg_points": data.get("bg_points", []),
                }
            ]
        }
        print(f"[迁移] 已将旧格式（起始帧={old_frame}）迁移为新格式")
        return migrated

    # 新格式：更新 video_path 和 fps（以当前视频为准）
    data["video_path"] = video_path
    data["fps"]        = fps
    return data


def save_labels(data, json_path):
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"\n✅ 已保存到: {json_path}")
    print(f"   共 {len(data['keyframes'])} 个关键帧标注：")
    for kf in data["keyframes"]:
        print(f"     帧 {kf['frame']:6d} ({kf['time_s']:.1f}s)  "
              f"标签={kf['label']}  "
              f"FG={len(kf['fg_points'])}  BG={len(kf['bg_points'])}")


# ── 绘制 ──────────────────────────────────────────────────────────────────────

def draw_frame(frame, fg_points, bg_points, frame_idx, total_frames, fps,
               mode_label="初始标注", existing_kf_count=0):
    """在帧上绘制已标注的点和信息"""
    vis = frame.copy()
    H, W = vis.shape[:2]

    for (x, y) in fg_points:
        cv2.circle(vis, (x, y), 8, (0, 255, 0), -1)
        cv2.circle(vis, (x, y), 8, (255, 255, 255), 2)

    for (x, y) in bg_points:
        cv2.circle(vis, (x, y), 8, (0, 0, 255), -1)
        cv2.circle(vis, (x, y), 8, (255, 255, 255), 2)

    # 信息栏
    overlay = vis.copy()
    cv2.rectangle(overlay, (0, 0), (W, 100), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.5, vis, 0.5, 0, vis)

    ts = frame_idx / fps
    m, s = divmod(int(ts), 60)

    mode_color = (100, 255, 100) if existing_kf_count == 0 else (100, 200, 255)

    cv2.putText(vis, f"Frame: {frame_idx}/{total_frames}  Time: {m:02d}:{s:02d}",
                (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    cv2.putText(vis, f"模式: {mode_label}  已有关键帧: {existing_kf_count} 个",
                (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.50, mode_color, 1)
    cv2.putText(vis, f"FG points: {len(fg_points)}  BG points: {len(bg_points)}",
                (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (100, 255, 100), 1)
    cv2.putText(vis,
                "[LMB]=前景  [RMB]=背景  [Z]=撤销  [S]=保存  [Q]=退出  [</>]=跳帧",
                (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (200, 200, 200), 1)
    cv2.putText(vis,
                "左键点食材(绿)，右键点锅底/锅外(红)，不需要排除搅拌爪",
                (10, 97), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (180, 220, 255), 1)

    return vis


# ── 主程序 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="食材关键帧标注工具")
    parser.add_argument("--append",  action="store_true",
                        help="追加模式：在已有 JSON 中追加新关键帧（不覆盖旧标注）")
    parser.add_argument("--frame",   type=int, default=None,
                        help="追加模式下，直接跳到指定帧号开始标注")
    parser.add_argument("--label",   type=str, default=None,
                        help="本次标注的说明标签，如 '青椒入锅'")
    parser.add_argument("--video",   type=str, default=VIDEO_PATH,
                        help="视频路径（默认使用脚本顶部 VIDEO_PATH）")
    parser.add_argument("--output",  type=str, default=OUTPUT_JSON,
                        help="输出 JSON 路径")
    args = parser.parse_args()

    video_path  = args.video
    output_json = args.output

    # ── 检查视频 ──────────────────────────────────────────────────────────────
    if not os.path.exists(video_path):
        print(f"[错误] 找不到视频: {video_path}")
        sys.exit(1)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"[错误] 无法打开视频: {video_path}")
        sys.exit(1)

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps          = cap.get(cv2.CAP_PROP_FPS)
    W            = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H            = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    print(f"[视频] {video_path}")
    print(f"[视频] 分辨率: {W}x{H}  帧数: {total_frames}  FPS: {fps:.1f}")
    print(f"[视频] 时长: {total_frames/fps:.1f}s")
    print()

    # ── 加载已有 JSON（或初始化）──────────────────────────────────────────────
    data = load_or_init_labels(output_json, video_path, fps)
    existing_kf_count = len(data["keyframes"])

    # ── 确定模式和起始帧 ──────────────────────────────────────────────────────
    if args.append:
        if existing_kf_count == 0:
            print("[提示] JSON 中暂无关键帧，追加模式等同于初始标注")
        mode_label = args.label or f"关键帧 #{existing_kf_count + 1}"
        current_idx = args.frame if args.frame is not None else 0
        current_idx = max(0, min(current_idx, total_frames - 1))
        print(f"[追加模式] 将在第 {current_idx} 帧追加关键帧标注")
        print(f"[追加模式] 标签: {mode_label}")
    else:
        # 初始模式：第一次标注，若 JSON 已有数据给出提示
        if existing_kf_count > 0:
            print(f"[警告] food_labels.json 中已有 {existing_kf_count} 个关键帧标注！")
            print("  若继续初始标注，将【覆盖】第一个关键帧（其余关键帧保留）")
            print("  如需追加，请用：python LabelFirstFrame.py --append --frame N")
            print()
        mode_label  = args.label or "初始标注"
        current_idx = 0

    print()
    print("=" * 60)
    print("操作说明：")
    print("  → / D               : 前进 30 帧")
    print("  ← / A               : 后退 30 帧")
    print("  ] / .               : 前进 1 帧（精细调整）")
    print("  [ / ,               : 后退 1 帧（精细调整）")
    print("  Page Down / Up      : 前进/后退 300 帧（快速跳转）")
    print("  数字键 0-9          : 跳到视频 0%~90% 位置")
    print("  左键点击             : 添加前景点（绿色，点在食材上）")
    print("  右键点击             : 添加背景点（红色，点在锅底/锅外）")
    print("  Z                   : 撤销上一个点")
    print("  S                   : 保存标注并退出")
    print("  Q                   : 退出不保存")
    print()
    if args.append:
        print("【追加模式】：搅拌爪不需要作为背景排除，只标食材前景点即可")
    print("=" * 60)
    print()

    fg_points  = []
    bg_points  = []
    all_points = []   # (x, y, label) 用于撤销

    win_name = "LabelFirstFrame — 标注食材（先跳帧，再点击）"
    cv2.namedWindow(win_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win_name, min(W, 1280), min(H + 10, 740))

    def mouse_callback(event, x, y, flags, param):
        nonlocal fg_points, bg_points, all_points
        if event == cv2.EVENT_LBUTTONDOWN:
            fg_points.append([x, y])
            all_points.append((x, y, 1))
            print(f"  + 前景点: ({x}, {y})  共 {len(fg_points)} 个")
        elif event == cv2.EVENT_RBUTTONDOWN:
            bg_points.append([x, y])
            all_points.append((x, y, 0))
            print(f"  - 背景点: ({x}, {y})  共 {len(bg_points)} 个")
        # 重绘
        frame_now = param["frame"]
        if frame_now is not None:
            vis = draw_frame(frame_now, fg_points, bg_points,
                             current_idx, total_frames, fps,
                             mode_label, existing_kf_count)
            cv2.imshow(win_name, vis)

    param = {"frame": None}
    cv2.setMouseCallback(win_name, mouse_callback, param)

    while True:
        frame = _get_frame(cap, current_idx)
        if frame is None:
            print(f"[警告] 无法读取第 {current_idx} 帧")
            current_idx = max(0, current_idx - 1)
            continue

        param["frame"] = frame
        vis = draw_frame(frame, fg_points, bg_points,
                         current_idx, total_frames, fps,
                         mode_label, existing_kf_count)
        cv2.imshow(win_name, vis)

        key = cv2.waitKey(0) & 0xFF

        # ── 保存 ──────────────────────────────────────────────────────────────
        if key in (ord('s'), ord('S')):
            if len(fg_points) == 0:
                print("[警告] 至少需要一个前景点！请先左键点击食材位置。")
                continue

            new_kf = {
                "frame":     current_idx,
                "time_s":    round(current_idx / fps, 3),
                "label":     mode_label,
                "fg_points": fg_points,
                "bg_points": bg_points,
            }

            if args.append:
                # 追加：检查是否已有同帧号，有则覆盖，否则追加
                existing_frames = [kf["frame"] for kf in data["keyframes"]]
                if current_idx in existing_frames:
                    idx = existing_frames.index(current_idx)
                    print(f"[追加] 帧 {current_idx} 已存在，覆盖该条目")
                    data["keyframes"][idx] = new_kf
                else:
                    data["keyframes"].append(new_kf)
                    # 按帧号排序
                    data["keyframes"].sort(key=lambda k: k["frame"])
            else:
                # 初始模式：替换或新建第一个关键帧
                if data["keyframes"]:
                    data["keyframes"][0] = new_kf
                else:
                    data["keyframes"].append(new_kf)

            save_labels(data, output_json)
            break

        # ── 退出不保存 ────────────────────────────────────────────────────────
        elif key in (ord('q'), ord('Q')):
            print("[退出] 未保存标注。")
            break

        # ── 撤销 ──────────────────────────────────────────────────────────────
        elif key in (ord('z'), ord('Z')):
            if all_points:
                last = all_points.pop()
                if last[2] == 1:
                    fg_points.pop()
                    print(f"  撤销：移除前景点，剩余 {len(fg_points)} 个")
                else:
                    bg_points.pop()
                    print(f"  撤销：移除背景点，剩余 {len(bg_points)} 个")

        # ── 后退 30 帧（← / A）────────────────────────────────────────────────
        elif key in (ord('a'), ord('A'), 81, 2):
            current_idx = max(0, current_idx - SKIP_FRAMES)
            print(f"  第 {current_idx} 帧  ({current_idx/fps:.1f}s)")

        # ── 前进 30 帧（→ / D）────────────────────────────────────────────────
        elif key in (ord('d'), ord('D'), 83, 3):
            current_idx = min(total_frames - 1, current_idx + SKIP_FRAMES)
            print(f"  第 {current_idx} 帧  ({current_idx/fps:.1f}s)")

        # ── 后退 1 帧（[ / ,）────────────────────────────────────────────────
        elif key in (ord('['), ord(',')):
            current_idx = max(0, current_idx - 1)
            print(f"  第 {current_idx} 帧  ({current_idx/fps:.1f}s)")

        # ── 前进 1 帧（] / .）────────────────────────────────────────────────
        elif key in (ord(']'), ord('.')):
            current_idx = min(total_frames - 1, current_idx + 1)
            print(f"  第 {current_idx} 帧  ({current_idx/fps:.1f}s)")

        # ── Page Down → 前进 300 帧 ───────────────────────────────────────────
        elif key in (85, 54):
            current_idx = min(total_frames - 1, current_idx + 300)
            print(f"  第 {current_idx} 帧  ({current_idx/fps:.1f}s)")

        # ── Page Up → 后退 300 帧 ─────────────────────────────────────────────
        elif key in (86, 56):
            current_idx = max(0, current_idx - 300)
            print(f"  第 {current_idx} 帧  ({current_idx/fps:.1f}s)")

        # ── 数字键 0-9 ────────────────────────────────────────────────────────
        elif ord('0') <= key <= ord('9'):
            pct = (key - ord('0')) / 10.0
            current_idx = int(total_frames * pct)
            print(f"  跳到 {pct*100:.0f}%：第 {current_idx} 帧  ({current_idx/fps:.1f}s)")

    cap.release()
    cv2.destroyAllWindows()

    if os.path.exists(output_json):
        print(f"\n下一步：运行 TrackFood.py 开始追踪")
        print(f"  python TrackFood.py")


def _get_frame(cap, idx):
    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
    ret, frame = cap.read()
    return frame if ret else None


if __name__ == "__main__":
    main()
