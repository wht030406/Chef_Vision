import cv2
import sys
sys.path.insert(0, 'D:/Chef_Vision')

video = 'D:/Chef_Vision/test_data/test4/rgb_20260616_151415.mp4'
cap = cv2.VideoCapture(video)
cap.set(cv2.CAP_PROP_POS_FRAMES, 90)
ret, frame = cap.read()
cap.release()

if not ret:
    print("ERROR: cannot read frame")
    exit(1)

cx, cy = 558, 578
rx0, ry0 = 528, 514
candidates = [
    (380, 370, 'A: rx=380 ry=370 (72%)', (0, 255, 0)),
    (320, 310, 'B: rx=320 ry=310 (61%)', (255, 200, 0)),
    (260, 250, 'C: rx=260 ry=250 (49%)', (0, 200, 255)),
]

vis = frame.copy()
cv2.ellipse(vis, (cx, cy), (rx0, ry0), 0, 0, 360, (0, 0, 255), 3)
cv2.putText(vis, 'Current rx=528 ry=514', (cx - 200, cy - ry0 - 20),
            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)

for rx, ry, label, color in candidates:
    cv2.ellipse(vis, (cx, cy), (rx, ry), 0, 0, 360, color, 2)
    cv2.putText(vis, label, (cx - 200, cy - ry - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.75, color, 2)

out = 'D:/Chef_Vision/tools/wok_rgb_compare.jpg'
cv2.imwrite(out, vis)
print(f'saved: {out}  frame size: {frame.shape}')
