import cv2, sys, os

_HERE = os.path.dirname(os.path.abspath(__file__))
_VIDEO = os.path.join(_HERE, "..", "data", "rgb_20260428_121157.mp4")
_OUT   = os.path.join(_HERE, "..", "output")

cap = cv2.VideoCapture(_VIDEO)
if not cap.isOpened():
    print("ERROR: cannot open video")
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
        fname = os.path.join(_OUT, f'preview_frame_{idx}.jpg')
        ok = cv2.imwrite(fname, small, [cv2.IMWRITE_JPEG_QUALITY, 85])
        print(f"  {'OK' if ok else 'FAIL'} -> {fname}  (t={idx/fps:.1f}s)")
    else:
        print(f"  FAIL read frame {idx}")

cap.release()
print("Done.")
