"""
把 data_tomato 按 8:2 分割成 train/val
输出到 data_tomato_train / data_tomato_val
"""
import os, shutil, random

SRC = r"D:\Chef_Vision\classify\data_tomato"
TRAIN_DST = r"D:\Chef_Vision\classify\data_tomato_train"
VAL_DST   = r"D:\Chef_Vision\classify\data_tomato_val"

random.seed(42)
VAL_RATIO = 0.2

for cls in ["raw", "done", "burnt"]:
    src_dir = os.path.join(SRC, cls)
    if not os.path.exists(src_dir):
        print(f"  跳过 {cls}（目录不存在）")
        continue
    files = [f for f in os.listdir(src_dir) if f.lower().endswith((".jpg", ".jpeg", ".png"))]
    random.shuffle(files)
    n_val = max(1, int(len(files) * VAL_RATIO))
    val_files   = files[:n_val]
    train_files = files[n_val:]

    for dst, flist in [(TRAIN_DST, train_files), (VAL_DST, val_files)]:
        d = os.path.join(dst, cls)
        os.makedirs(d, exist_ok=True)
        for f in flist:
            shutil.copy2(os.path.join(src_dir, f), os.path.join(d, f))
    print(f"  {cls:8s}: train={len(train_files)}  val={len(val_files)}")

print("\n完成！")
