"""快速验证集测试脚本"""
import sys, os
sys.path.insert(0, "d:/Chef_Vision")
from classify.infer import FoodStateClassifier
import cv2

clf = FoodStateClassifier()
base = "d:/Chef_Vision/classify/data_val"

for cls in ["raw", "done", "burnt"]:
    d = os.path.join(base, cls)
    imgs = sorted([f for f in os.listdir(d) if f.lower().endswith((".jpg",".jpeg",".png"))])
    print(f"\n[{cls}] 前10张详情:")
    for f in imgs[:10]:
        img = cv2.imread(os.path.join(d, f))
        r = clf.predict(img)
        mark = "OK" if r["label"] == cls else "X "
        probs = {k: round(v*100) for k, v in r["probs"].items()}
        print(f"  {mark} {f[:28]:28s} -> {r['label']:6s} {r['conf']*100:.0f}%  {probs}")
