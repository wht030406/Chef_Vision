"""
browse_video.py — 快速浏览视频，目视确认关键帧帧号

用途：
  在青椒入锅的那一帧追加标注之前，先用此脚本找到准确帧号。

操作键：
  → / D           → 前进 30 帧
  ← / A           → 后退 30 帧
  ] / .           → 前进 1 帧（精细）
  [ / ,           → 后退 1 帧（精细）
  Page Down       → 前进 300 帧（快速跳转）
  Page Up         → 后退 300 帧（快速跳转）
  数字键 0-9      → 跳到视频 0%~90% 位置
  G               → 输入帧号直接跳转
  T               → 输入时间(秒)直接跳转
  Space           → 打印当前帧号到控制台（方便记录）
  Q / Esc         → 退出

用法：
  python browse_video.py --video path/to/rgb.mp4
  python browse_video.py --video path/to/rgb.mp4 --start 1000
"""

import cv2
import sys
import os
import argparse

# ── 配置 ─────────────────────────────────────────────────────────────────────
_HERE         = os.path.dirname(os.path.abspath(__file__))
SKIP_FRAMES   = 30    # ← → 每次跳几帧


# ── 工具函数 ─────────────────────────────────────────────────────────────────

def get_frame(cap, idx):
    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
    ret, frame = cap.read()
    return frame if ret else None


def draw_hud(frame, frame_idx, total_frames, fps, note=""):
    """在画面顶部绘制半透明信息栏"""
    vis = frame.copy()
    H, W = vis.shape[:2]

    # 半透明黑底
    overlay = vis.copy()
    cv2.rectangle(overlay, (0, 0), (W, 80), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.55, vis, 0.45, 0, vis)

    ts = frame_idx / fps
    m, s_int = divmod(int(ts), 60)
    frac = ts - int(ts)

    # 主信息
    cv2.putText(vis,
                f"Frame: {frame_idx} / {total_frames-1}   "
                f"Time: {m:02d}:{s_int:02d}.{int(frac*10)}   "
                f"({ts:.2f}s)   FPS={fps:.1f}",
                (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 255, 255), 1)

    # 进度条
    bar_x0, bar_x1 = 10, W - 10
    bar_y = 42
    bar_w = bar_x1 - bar_x0
    cv2.rectangle(vis, (bar_x0, bar_y - 6), (bar_x1, bar_y + 6), (80, 80, 80), -1)
    filled = int(bar_w * frame_idx / max(total_frames - 1, 1))
    cv2.rectangle(vis, (bar_x0, bar_y - 6), (bar_x0 + filled, bar_y + 6), (0, 200, 100), -1)

    # 操作提示
    cv2.putText(vis,
                "[</>]=30f  [,.]=1f  [PgDn/Up]=300f  [0-9]=%  [G]=goto  [T]=time  [Space]=mark  [Q]=quit",
                (10, 68), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (180, 220, 255), 1)

    if note:
        # 底部临时提示
        cv2.rectangle(vis, (0, H - 30), (W, H), (0, 0, 80), -1)
        cv2.putText(vis, note, (10, H - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 255, 255), 1)

    return vis


def prompt_input_in_console(prompt_text):
    """在控制台提示用户输入（OpenCV 无法弹出输入框）"""
    print(f"\n  {prompt_text}", end="", flush=True)
    try:
        return input()
    except EOFError:
        return ""


# ── 主程序 ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="快速浏览视频并确认关键帧帧号")
    parser.add_argument("--video", required=True, help="视频路径")
    parser.add_argument("--start",  type=int, default=0,   help="起始帧号")
    args = parser.parse_args()

    video_path = args.video
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
    print(f"[视频] 分辨率: {W}x{H}  总帧数: {total_frames}  FPS: {fps:.1f}")
    print(f"[视频] 时长: {total_frames/fps:.1f}s  ({int(total_frames/fps//60):02d}:{int(total_frames/fps%60):02d})")
    print()
    print("操作：← →(30帧)  [](1帧)  PgDn/Up(300帧)  G(跳帧)  T(跳时间)  Space(记录帧号)  Q(退出)")
    print()

    current_idx = max(0, min(args.start, total_frames - 1))
    win_name    = "browse_video — 浏览视频确认关键帧（Space=记录帧号，Q=退出）"
    cv2.namedWindow(win_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win_name, min(W, 1280), min(H + 10, 730))

    note      = ""
    note_ttl  = 0   # 提示持续帧数

    marked_frames = []   # 用户 Space 记录的帧号列表

    while True:
        frame = get_frame(cap, current_idx)
        if frame is None:
            print(f"[警告] 无法读取第 {current_idx} 帧")
            current_idx = max(0, current_idx - 1)
            continue

        if note_ttl <= 0:
            note = ""
        vis = draw_hud(frame, current_idx, total_frames, fps, note)
        cv2.imshow(win_name, vis)
        note_ttl -= 1

        key = cv2.waitKey(0) & 0xFF
        ext = cv2.waitKeyEx(1)   # 扩展键（用于方向键）

        # ── 退出 ──────────────────────────────────────────────────────────────
        if key in (ord('q'), ord('Q'), 27):   # Q / Esc
            break

        # ── 记录当前帧号 ──────────────────────────────────────────────────────
        elif key == ord(' '):
            marked_frames.append(current_idx)
            ts = current_idx / fps
            m2, s2 = divmod(int(ts), 60)
            print(f"  ★ 记录帧号: {current_idx}  ({m2:02d}:{s2:02d}, {ts:.1f}s)")
            note = f"★ 已记录帧号 {current_idx}  ({m2:02d}:{s2:02d})"
            note_ttl = 60

        # ── 跳到指定帧号（G 键）──────────────────────────────────────────────
        elif key in (ord('g'), ord('G')):
            cv2.destroyWindow(win_name)   # 先隐藏窗口，避免遮挡控制台
            raw = prompt_input_in_console("输入帧号: ")
            try:
                target = int(raw.strip())
                current_idx = max(0, min(target, total_frames - 1))
                note = f"跳转到第 {current_idx} 帧"
                note_ttl = 60
                print(f"  → 跳转到第 {current_idx} 帧  ({current_idx/fps:.1f}s)")
            except ValueError:
                print("  [无效输入]")
            cv2.namedWindow(win_name, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(win_name, min(W, 1280), min(H + 10, 730))

        # ── 跳到指定时间（T 键）──────────────────────────────────────────────
        elif key in (ord('t'), ord('T')):
            cv2.destroyWindow(win_name)
            raw = prompt_input_in_console("输入时间（秒）: ")
            try:
                t_sec = float(raw.strip())
                current_idx = max(0, min(int(t_sec * fps), total_frames - 1))
                note = f"跳转到 {t_sec:.1f}s → 第 {current_idx} 帧"
                note_ttl = 60
                print(f"  → 跳转到 {t_sec:.1f}s：第 {current_idx} 帧")
            except ValueError:
                print("  [无效输入]")
            cv2.namedWindow(win_name, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(win_name, min(W, 1280), min(H + 10, 730))

        # ── 前进 30 帧（→ / D）────────────────────────────────────────────────
        elif key in (ord('d'), ord('D'), 83, 3):
            current_idx = min(total_frames - 1, current_idx + SKIP_FRAMES)

        # ── 后退 30 帧（← / A）────────────────────────────────────────────────
        elif key in (ord('a'), ord('A'), 81, 2):
            current_idx = max(0, current_idx - SKIP_FRAMES)

        # ── 前进 1 帧（] / .）────────────────────────────────────────────────
        elif key in (ord(']'), ord('.')):
            current_idx = min(total_frames - 1, current_idx + 1)

        # ── 后退 1 帧（[ / ,）────────────────────────────────────────────────
        elif key in (ord('['), ord(',')):
            current_idx = max(0, current_idx - 1)

        # ── Page Down → 前进 300 帧 ───────────────────────────────────────────
        elif key in (85, 54):
            current_idx = min(total_frames - 1, current_idx + 300)

        # ── Page Up → 后退 300 帧 ─────────────────────────────────────────────
        elif key in (86, 56):
            current_idx = max(0, current_idx - 300)

        # ── 数字键 0-9 → 跳到百分比位置 ─────────────────────────────────────
        elif ord('0') <= key <= ord('9'):
            pct = (key - ord('0')) / 10.0
            current_idx = int(total_frames * pct)
            print(f"  → 跳到 {pct*100:.0f}%：第 {current_idx} 帧  ({current_idx/fps:.1f}s)")

    cap.release()
    cv2.destroyAllWindows()

    # ── 退出时打印汇总 ────────────────────────────────────────────────────────
    print()
    print("=" * 55)
    if marked_frames:
        print("★ 已记录的帧号列表：")
        for f in marked_frames:
            ts = f / fps
            m2, s2 = divmod(int(ts), 60)
            print(f"   帧 {f:6d}   {m2:02d}:{s2:02d}   ({ts:.1f}s)")
        print()
        print(f"下一步：用 LabelFirstFrame.py 追加标注")
        print(f"  python LabelFirstFrame.py --append --frame {marked_frames[-1]}")
    else:
        print("（未记录任何帧号）")
    print("=" * 55)


if __name__ == "__main__":
    main()
