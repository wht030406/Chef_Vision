"""
对测试视频跑推理，输出带熟度标注的视频文件
用法：
  python classify/run_infer_video.py classify/test_videos/asmr_tomato_egg.mp4
  python classify/run_infer_video.py video.mp4 --start 148 --end 350
"""
import os, sys, cv2, numpy as np, argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from classify.infer import FoodStateClassifier, BURNT_CONF_THRESH, BURNT_CONSEC_FRAMES

# ── 标签（纯 ASCII，cv2.putText 可以显示）───────────────────────────
LABEL_EN = {"raw": "RAW", "done": "DONE", "burnt": "BURNT!"}
COLOR    = {"raw": (30, 200, 200), "done": (30, 220, 30), "burnt": (30, 30, 220)}


def draw_overlay(frame, result, frame_idx, fps):
    out   = frame.copy()
    h, w  = out.shape[:2]
    label = result["label"]
    conf  = result["conf"]
    probs = result["probs"]
    alarm = result["alarm"]

    # 半透明背景
    overlay = out.copy()
    cv2.rectangle(overlay, (0, 0), (290, 120), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.6, out, 0.4, 0, out)

    # 主标签
    col    = COLOR.get(label, (200, 200, 200))
    prefix = "!! " if label == "burnt" else ""
    txt    = f"{prefix}{LABEL_EN.get(label, label)}  {conf*100:.0f}%"
    cv2.putText(out, txt, (10, 32), cv2.FONT_HERSHEY_DUPLEX, 0.9, col, 2, cv2.LINE_AA)

    # 三类概率条
    bar_y = 48
    for cls in ["raw", "done", "burnt"]:
        p  = probs.get(cls, 0.0)
        bw = int(p * 220)
        bc = COLOR.get(cls, (180, 180, 180))
        cv2.rectangle(out, (10, bar_y), (10 + bw, bar_y + 14), bc, -1)
        cv2.rectangle(out, (10, bar_y), (230, bar_y + 14), (100, 100, 100), 1)
        cv2.putText(out, f"{cls} {p*100:.0f}%", (234, bar_y + 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.40, bc, 1, cv2.LINE_AA)
        bar_y += 20

    # 时间戳（视频实际时间）
    ts = f"{int(frame_idx/fps//60):02d}:{int(frame_idx/fps%60):02d}"
    cv2.putText(out, ts, (w - 70, h - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1, cv2.LINE_AA)

    # 报警横幅
    if alarm:
        cv2.rectangle(out, (0, h - 52), (w, h), (0, 0, 180), -1)
        cv2.putText(out, "!! BURNT ALARM - Remove from heat NOW !!",
                    (w // 2 - 260, h - 14),
                    cv2.FONT_HERSHEY_DUPLEX, 0.85, (255, 255, 255), 2, cv2.LINE_AA)

    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video", help="输入视频路径")
    parser.add_argument("--start", type=float, default=0, help="开始时间（秒）")
    parser.add_argument("--end",   type=float, default=0, help="结束时间（秒），0=到结尾")
    args = parser.parse_args()

    VIDEO_IN  = args.video
    suffix    = f"_s{int(args.start)}-e{int(args.end)}" if args.start or args.end else ""
    VIDEO_OUT = VIDEO_IN.replace(".mp4", f"{suffix}_annotated.mp4")

    clf = FoodStateClassifier()
    cap = cv2.VideoCapture(VIDEO_IN)
    if not cap.isOpened():
        print(f"无法打开: {VIDEO_IN}"); return

    fps   = cap.get(cv2.CAP_PROP_FPS) or 25
    w     = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h     = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    # 跳到起始帧
    start_frame = int(args.start * fps) if args.start > 0 else 0
    end_frame   = int(args.end   * fps) if args.end   > 0 else total
    if start_frame > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(VIDEO_OUT, fourcc, fps, (w, h))

    print(f"输入: {VIDEO_IN}")
    print(f"输出: {VIDEO_OUT}")
    print(f"分辨率: {w}x{h}  fps={fps:.1f}")
    if args.start or args.end:
        print(f"时间段: {int(args.start//60):02d}:{int(args.start%60):02d} ~ "
              f"{int(args.end//60):02d}:{int(args.end%60):02d}")
    print("推理中...\n")

    alarm_times = []
    fi = start_frame
    while fi < end_frame:
        ret, frame = cap.read()
        if not ret:
            break
        result = clf.predict(frame)
        vis    = draw_overlay(frame, result, fi, fps)
        writer.write(vis)

        if result["alarm"] and (not alarm_times or fi - alarm_times[-1] > fps * 3):
            alarm_times.append(fi)
            ts = f"{int(fi/fps//60):02d}:{int(fi/fps%60):02d}"
            print(f"  !! 报警 @ {ts}  burnt={result['probs']['burnt']*100:.0f}%")

        if fi % 30 == 0:
            pct = (fi - start_frame) / max(end_frame - start_frame, 1) * 100
            print(f"\r  [{pct:5.1f}%] frame {fi:5d}  "
                  f"{result['label']} {result['conf']*100:.0f}%", end="", flush=True)
        fi += 1

    cap.release()
    writer.release()
    n = fi - start_frame
    print(f"\n\n完成！共处理 {n} 帧")
    print(f"报警触发 {len(alarm_times)} 次")
    print(f"输出: {VIDEO_OUT}")


if __name__ == "__main__":
    main()
