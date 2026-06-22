"""
炒蛋熟度分类推理模块
支持：
  1. 单张图片推理
  2. 视频逐帧推理 + 报警（连续 N 帧 burnt 置信度 > 阈值）
  3. 作为模块被 TrackFood.py 调用

用法：
  # 单图测试
  python classify/infer.py --image path/to/egg.jpg

  # 视频测试
  python classify/infer.py --video path/to/video.mp4

  # 指定模型
  python classify/infer.py --image xxx.jpg --model classify/models/best_model.pth
"""

import os
import sys
import json
import argparse
import collections

import cv2
import numpy as np
import torch
import torch.nn as nn
from torchvision import transforms, models
from torchvision.models import EfficientNet_B3_Weights

_HERE      = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(_HERE, "models", "best_model.pth")
IMG_SIZE   = 300

# 推理用的预处理（和验证集一致）
_INFER_TRANSFORM = transforms.Compose([
    transforms.ToPILImage(),
    transforms.Resize(int(IMG_SIZE * 1.1)),
    transforms.CenterCrop(IMG_SIZE),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                         std=[0.229, 0.224, 0.225]),
])

# 报警参数
BURNT_CONF_THRESH  = 0.75   # burnt 置信度阈值
BURNT_CONSEC_FRAMES = 5      # 连续 N 帧超阈值才报警


class FoodStateClassifier:
    """
    炒蛋熟度分类器，单例模式，供 TrackFood.py 调用
    """

    def __init__(self, model_path: str = MODEL_PATH, device: str = None):
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(device)

        # 加载 checkpoint
        ckpt = torch.load(model_path, map_location=self.device)
        self.class_map: dict = ckpt["class_map"]   # {0: 'burnt', 1: 'done', 2: 'raw'}
        num_classes = len(self.class_map)

        # 重建模型结构
        model = models.efficientnet_b3(weights=None)
        in_features = model.classifier[1].in_features
        model.classifier = nn.Sequential(
            nn.Dropout(p=0.4, inplace=True),
            nn.Linear(in_features, num_classes),
        )
        model.load_state_dict(ckpt["model"])
        model.eval()
        self.model = model.to(self.device)

        # 报警状态
        self._burnt_deque = collections.deque(maxlen=BURNT_CONSEC_FRAMES)
        self._alarm_triggered = False

        print(f"[FoodClassifier] 模型加载成功  设备={device}  类别={self.class_map}")

    @torch.no_grad()
    def predict(self, img_bgr: np.ndarray) -> dict:
        """
        输入：BGR 格式 numpy 数组（OpenCV 格式）
        输出：{'label': 'done', 'conf': 0.92,
               'probs': {'burnt': 0.03, 'done': 0.92, 'raw': 0.05},
               'alarm': False}
        """
        # BGR → RGB
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        tensor  = _INFER_TRANSFORM(img_rgb).unsqueeze(0).to(self.device)

        logits = self.model(tensor)
        probs  = torch.softmax(logits, dim=1)[0].cpu().numpy()

        # 组装结果
        result = {
            "probs": {self.class_map[i]: float(probs[i]) for i in range(len(probs))},
        }
        best_idx        = int(np.argmax(probs))
        result["label"] = self.class_map[best_idx]
        result["conf"]  = float(probs[best_idx])

        # 连续帧报警检测
        burnt_conf = result["probs"].get("burnt", 0.0)
        self._burnt_deque.append(burnt_conf >= BURNT_CONF_THRESH)
        alarm = (len(self._burnt_deque) == BURNT_CONSEC_FRAMES
                 and all(self._burnt_deque))
        if alarm and not self._alarm_triggered:
            self._alarm_triggered = True
        result["alarm"] = alarm or self._alarm_triggered

        return result

    def reset_alarm(self):
        """重置报警状态（换菜后调用）"""
        self._burnt_deque.clear()
        self._alarm_triggered = False


def draw_result(frame: np.ndarray, result: dict, roi_box=None) -> np.ndarray:
    """
    在帧上叠加分类结果和报警信息
    roi_box: (x1, y1, x2, y2) SAM2 mask 的边界框，可选
    """
    out  = frame.copy()
    h, w = out.shape[:2]

    label = result["label"]
    conf  = result["conf"]
    alarm = result["alarm"]
    probs = result["probs"]

    # 颜色方案
    COLOR = {"raw": (200, 200, 0), "done": (0, 200, 0), "burnt": (0, 50, 220)}
    color = COLOR.get(label, (200, 200, 200))

    # ROI 框
    if roi_box is not None:
        x1, y1, x2, y2 = roi_box
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)

    # 主标签
    label_cn = {"raw": "生/未熟", "done": "已熟", "burnt": "⚠ 焦糊!"}
    text = f"{label_cn.get(label, label)}  {conf*100:.0f}%"
    cv2.putText(out, text, (12, 36),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2, cv2.LINE_AA)

    # 三类概率条
    bar_y = 60
    for cls_name in ["raw", "done", "burnt"]:
        p    = probs.get(cls_name, 0.0)
        bw   = int(p * 200)
        bc   = COLOR.get(cls_name, (180, 180, 180))
        cv2.rectangle(out, (12, bar_y), (12 + bw, bar_y + 14), bc, -1)
        cv2.putText(out, f"{cls_name} {p*100:.0f}%", (220, bar_y + 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, bc, 1, cv2.LINE_AA)
        bar_y += 20

    # 报警横幅
    if alarm:
        cv2.rectangle(out, (0, h - 50), (w, h), (0, 0, 200), -1)
        cv2.putText(out, "⚠  BURNT ALARM — 菜已焦糊！",
                    (w // 2 - 200, h - 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)

    return out


# ── CLI 入口 ──────────────────────────────────────────────────────────────────

def run_image(image_path, model_path):
    clf = FoodStateClassifier(model_path)
    img = cv2.imread(image_path)
    if img is None:
        print(f"无法读取图片: {image_path}")
        return
    result = clf.predict(img)
    print(f"\n预测结果: {result['label']}  置信度: {result['conf']*100:.1f}%")
    print(f"各类概率: {result['probs']}")
    vis = draw_result(img, result)
    win = "FoodStateClassifier — Q退出"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.imshow(win, vis)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


def run_video(video_path, model_path):
    clf = FoodStateClassifier(model_path)
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"无法打开视频: {video_path}")
        return

    win = "FoodStateClassifier — Q退出 空格暂停"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, 960, 540)
    paused = False

    while True:
        if not paused:
            ret, frame = cap.read()
            if not ret:
                break
            result = clf.predict(frame)
            vis    = draw_result(frame, result)
            label  = result['label']
            conf   = result['conf']
            alarm  = result['alarm']
            alarm_str = " ⚠ ALARM" if alarm else ""
            print(f"\r[{label}] {conf*100:.0f}%{alarm_str}", end="", flush=True)
            cv2.imshow(win, vis)

        key = cv2.waitKey(30) & 0xFF
        if key in (ord('q'), ord('Q'), 27):
            break
        elif key == ord(' '):
            paused = not paused

    cap.release()
    cv2.destroyAllWindows()
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="炒蛋熟度分类推理")
    parser.add_argument("--image", type=str, help="单张图片路径")
    parser.add_argument("--video", type=str, help="视频路径")
    parser.add_argument("--model", type=str, default=MODEL_PATH, help="模型路径")
    args = parser.parse_args()

    if args.image:
        run_image(args.image, args.model)
    elif args.video:
        run_video(args.video, args.model)
    else:
        print("请指定 --image 或 --video 参数")
        parser.print_help()
