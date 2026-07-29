import argparse
import cv2, sys, os

_HERE = os.path.dirname(os.path.abspath(__file__))
_OUT_DEFAULT = os.path.join(_HERE, "..", "output")

parser = argparse.ArgumentParser(description="从指定 RGB 视频抽取若干预览帧")
parser.add_argument("--video", required=True, help="RGB 视频路径")
parser.add_argument("--out", default=_OUT_DEFAULT, help="输出目录，默认 output/")
args = parser.parse_args()

os.makedirs(args.out, exist_ok=True)

cap = cv2.VideoCapture(args.video)
if not cap.isOpened():
    print(f"ERROR: cannot open video: {args.video}")
    sys.exit(1)

total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
fps   = cap.get(cv2.CAP_PROP_FPS)
w     = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
h     = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
print(f"Video: {total} frames, {fps}fps, {w}x{h}, duration={total/fps:.1f}s")

indices = [0, total//5, total*2//5, total*3//5, total*4//5, total-1]
for idx in indices:
    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
    ret, frame = cap.read()
    if ret:
        small = cv2.resize(frame, (640, 480))
        fname = os.path.join(args.out, f'preview_frame_{idx}.jpg')
        ok = cv2.imwrite(fname, small, [cv2.IMWRITE_JPEG_QUALITY, 85])
        print(f"  {'OK' if ok else 'FAIL'} -> {fname}  (t={idx/fps:.1f}s)")
    else:
        print(f"  FAIL read frame {idx}")

cap.release()
print("Done.")
