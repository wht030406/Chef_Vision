"""
快速预览指定类别的图片，支持键盘删除噪声图
用途：手动筛除 burnt / raw / done 目录中的不相关图片

用法：
  python classify/preview_class.py burnt
  python classify/preview_class.py done
  python classify/preview_class.py raw

操作：
  ← → 或 A/D   上一张 / 下一张
  Delete 或 X   删除当前图片
  Q / ESC       退出
"""

import os
import sys
import cv2
import numpy as np

_HERE    = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_HERE, "data")


def main():
    cls = sys.argv[1] if len(sys.argv) > 1 else "burnt"
    cls_dir = os.path.join(DATA_DIR, cls)
    if not os.path.isdir(cls_dir):
        print(f"目录不存在: {cls_dir}")
        return

    exts = (".jpg", ".jpeg", ".png", ".webp")
    files = sorted([f for f in os.listdir(cls_dir) if f.lower().endswith(exts)])
    if not files:
        print("目录为空")
        return

    idx     = 0
    deleted = 0
    WIN     = f"预览 [{cls}]  ← → 翻页  X/Del 删除  Q 退出"
    cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WIN, 800, 650)

    while 0 <= idx < len(files):
        fpath = os.path.join(cls_dir, files[idx])
        img   = cv2.imread(fpath)
        if img is None:
            files.pop(idx)
            continue

        # 缩放到 800×600 显示
        h, w = img.shape[:2]
        scale = min(800 / w, 600 / h)
        disp  = cv2.resize(img, (int(w * scale), int(h * scale)))

        # 底部信息条
        bar = np.zeros((50, disp.shape[1], 3), dtype=np.uint8)
        cv2.putText(bar, f"[{idx+1}/{len(files)}]  {files[idx]}",
                    (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        cv2.putText(bar, f"已删除: {deleted}  | X/Del=删除  A/D=翻页  Q=退出",
                    (8, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (100, 200, 100), 1)
        combined = np.vstack([disp, bar])
        cv2.imshow(WIN, combined)

        key = cv2.waitKey(0) & 0xFF
        if key in (ord('q'), ord('Q'), 27):   # Q / ESC
            break
        elif key in (ord('d'), ord('D'), 83, 0xFF & 0xFF):  # D / →
            idx = min(idx + 1, len(files) - 1)
        elif key in (ord('a'), ord('A'), 81):  # A / ←
            idx = max(idx - 1, 0)
        elif key in (ord('x'), ord('X'), 255, 0):  # X / Delete
            os.remove(fpath)
            print(f"[删除] {files[idx]}")
            files.pop(idx)
            deleted += 1
            if idx >= len(files):
                idx = len(files) - 1
        else:
            idx = min(idx + 1, len(files) - 1)

    cv2.destroyAllWindows()
    print(f"\n完成！共删除 {deleted} 张，剩余 {len(files)} 张")


if __name__ == "__main__":
    main()
