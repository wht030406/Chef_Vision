"""
SegmentFood.py — 单帧食物分割验证
使用 SAM2.1 对 preview_frame_0.jpg 做自动分割，输出可视化结果
"""

import os
import numpy as np
import torch
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from PIL import Image

# ── 1. 检查环境 ──────────────────────────────────────────────
print(f"PyTorch: {torch.__version__}")
print(f"CUDA available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"GPU: {torch.cuda.get_device_name(0)}")

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# ── 2. 模型配置 ──────────────────────────────────────────────
# 使用 SAM2.1 large，精度最好
MODEL_CFG = "configs/sam2.1/sam2.1_hiera_l.yaml"
CHECKPOINT_URL = (
    "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_large.pt"
)
CHECKPOINT_PATH = "D:/sam2_checkpoints/sam2.1_hiera_large.pt"

# ── 3. 下载权重（如果不存在）────────────────────────────────
os.makedirs(os.path.dirname(CHECKPOINT_PATH), exist_ok=True)
if not os.path.exists(CHECKPOINT_PATH) or os.path.getsize(CHECKPOINT_PATH) == 0:
    print(f"下载 SAM2.1 权重到 {CHECKPOINT_PATH} ...")
    try:
        # 优先用 huggingface_hub（支持断点续传，国内镜像快）
        from huggingface_hub import hf_hub_download
        import shutil
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        tmp = hf_hub_download(
            repo_id="facebook/sam2.1-hiera-large",
            filename="sam2.1_hiera_large.pt",
            local_dir=os.path.dirname(CHECKPOINT_PATH),
        )
        if os.path.abspath(tmp) != os.path.abspath(CHECKPOINT_PATH):
            shutil.move(tmp, CHECKPOINT_PATH)
        print("下载完成（huggingface_hub）")
    except Exception as e:
        print(f"huggingface_hub 失败: {e}")
        print("回退到直接下载...")
        import urllib.request
        def _progress(count, block, total):
            pct = count * block / total * 100
            print(f"\r  {min(pct,100):.1f}%", end="", flush=True)
        urllib.request.urlretrieve(CHECKPOINT_URL, CHECKPOINT_PATH, _progress)
        print("\n下载完成")
else:
    print(f"权重已存在: {CHECKPOINT_PATH}  ({os.path.getsize(CHECKPOINT_PATH)//1024//1024} MB)")

# ── 4. 加载模型 ──────────────────────────────────────────────
from sam2.build_sam import build_sam2
from sam2.sam2_image_predictor import SAM2ImagePredictor

print("加载 SAM2.1 模型...")
sam2_model = build_sam2(MODEL_CFG, CHECKPOINT_PATH, device=DEVICE)
predictor = SAM2ImagePredictor(sam2_model)
print("模型加载完成")

# ── 5. 读取测试图像 ──────────────────────────────────────────
_HERE      = os.path.dirname(os.path.abspath(__file__))
IMAGE_PATH = os.path.join(_HERE, "..", "output", "preview_frame_0.jpg")
assert os.path.exists(IMAGE_PATH), f"找不到图像: {IMAGE_PATH}"

image = np.array(Image.open(IMAGE_PATH).convert("RGB"))
H, W = image.shape[:2]
print(f"图像尺寸: {W}x{H}")

# ── 6. 设置图像 ──────────────────────────────────────────────
predictor.set_image(image)

# ── 7. 用图像中心点作为提示（假设食物在画面中央）────────────
# 可以改成多个点来提升精度
cx, cy = W // 2, H // 2
input_point = np.array([[cx, cy]])
input_label = np.array([1])  # 1=前景

print(f"提示点: ({cx}, {cy})")

masks, scores, logits = predictor.predict(
    point_coords=input_point,
    point_labels=input_label,
    multimask_output=True,   # 返回3个候选mask
)

print(f"生成 {len(masks)} 个候选 mask，得分: {scores.round(3)}")

# ── 8. 选最高分 mask ─────────────────────────────────────────
best_idx = np.argmax(scores)
best_mask = masks[best_idx].astype(bool)
best_score = scores[best_idx]
print(f"最佳 mask 索引: {best_idx}, 得分: {best_score:.4f}")
print(f"Mask 覆盖像素: {best_mask.sum()} / {H*W} ({best_mask.sum()/(H*W)*100:.1f}%)")

# ── 9. 可视化 ────────────────────────────────────────────────
fig, axes = plt.subplots(1, 3, figsize=(18, 6))
fig.suptitle(f"SAM2.1 单帧分割验证  |  {IMAGE_PATH}", fontsize=13)

# 原图 + 提示点
axes[0].imshow(image)
axes[0].plot(cx, cy, "r*", markersize=15, label="提示点")
axes[0].set_title("原图 + 提示点")
axes[0].legend()
axes[0].axis("off")

# 最佳 mask 叠加
overlay = image.copy()
color = np.array([0, 255, 100], dtype=np.uint8)
overlay[best_mask] = (overlay[best_mask] * 0.4 + color * 0.6).astype(np.uint8)
axes[1].imshow(overlay)
axes[1].set_title(f"最佳 Mask (score={best_score:.3f})")
axes[1].axis("off")

# 所有3个候选 mask
combined = np.zeros((H, W, 3), dtype=np.uint8)
colors = [(255, 80, 80), (80, 255, 80), (80, 80, 255)]
for i, (m, s) in enumerate(zip(masks, scores)):
    c = np.array(colors[i], dtype=np.uint8)
    mb = m.astype(bool)
    combined[mb] = (combined[mb] * 0.3 + c * 0.7).astype(np.uint8)
axes[2].imshow(image)
axes[2].imshow(combined, alpha=0.5)
score_str = " / ".join([f"{s:.3f}" for s in scores])
axes[2].set_title(f"3个候选 Mask\n得分: {score_str}")
axes[2].axis("off")

plt.tight_layout()
out_path = os.path.join(_HERE, "..", "output", "segment_result.png")
plt.savefig(out_path, dpi=120, bbox_inches="tight")
print(f"\n结果已保存: {out_path}")
plt.show()
