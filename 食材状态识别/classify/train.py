"""
EfficientNet-B3 迁移训练脚本
分类任务：炒鸡蛋熟度识别（raw / done / burnt）

训练策略：
  Phase 1 — 冻结 backbone，只训练分类头（5 epoch，快速收敛）
  Phase 2 — 解冻全部，小学习率微调（20 epoch）

用法：
  python classify/train.py

输出：
  classify/models/best_model.pth   ← 验证集最优权重
  classify/models/last_model.pth   ← 最后一轮权重
  classify/models/train_log.csv    ← 逐 epoch 训练曲线
"""

import os
import csv
import time
import shutil

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader
from torchvision import datasets, transforms, models
from torchvision.models import EfficientNet_B3_Weights

# ── 路径配置 ──────────────────────────────────────────────────────────────────
_HERE      = os.path.dirname(os.path.abspath(__file__))
TRAIN_DIR  = os.path.join(_HERE, "data_tomato_train")
VAL_DIR    = os.path.join(_HERE, "data_tomato_val")
MODEL_DIR  = os.path.join(_HERE, "models")
os.makedirs(MODEL_DIR, exist_ok=True)

BEST_MODEL = os.path.join(MODEL_DIR, "best_model.pth")
LAST_MODEL = os.path.join(MODEL_DIR, "last_model.pth")
LOG_CSV    = os.path.join(MODEL_DIR, "train_log.csv")

# ── 超参数 ────────────────────────────────────────────────────────────────────
CLASSES      = ["raw", "done", "burnt"]   # 顺序固定，推理时用
NUM_CLASSES  = len(CLASSES)
IMG_SIZE     = 300          # EfficientNet-B3 标准输入尺寸
BATCH_SIZE   = 8    # 数据量小，batch 调小
NUM_WORKERS  = 2

# Phase 1：只训分类头
P1_EPOCHS = 8
P1_LR     = 1e-3

# Phase 2：全部微调
P2_EPOCHS = 40     # 数据少，多训几轮
P2_LR     = 2e-5

WEIGHT_DECAY = 1e-4
LABEL_SMOOTH = 0.1         # 标签平滑，防止过拟合

# ── 数据增强 ──────────────────────────────────────────────────────────────────
# 训练集：随机翻转 + 色彩扰动 + 随机旋转
# 模拟锅内光照变化（亮度/对比度/色调抖动）
train_transform = transforms.Compose([
    transforms.RandomResizedCrop(IMG_SIZE, scale=(0.7, 1.0)),
    transforms.RandomHorizontalFlip(),
    transforms.RandomVerticalFlip(p=0.2),
    transforms.RandomRotation(30),
    transforms.ColorJitter(brightness=0.4, contrast=0.4,
                           saturation=0.3, hue=0.1),
    transforms.RandomGrayscale(p=0.05),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                         std=[0.229, 0.224, 0.225]),
])

val_transform = transforms.Compose([
    transforms.Resize(int(IMG_SIZE * 1.1)),
    transforms.CenterCrop(IMG_SIZE),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                         std=[0.229, 0.224, 0.225]),
])


def build_model(num_classes, device):
    """加载预训练 EfficientNet-B3，替换分类头"""
    model = models.efficientnet_b3(weights=EfficientNet_B3_Weights.IMAGENET1K_V1)
    # 替换最后的分类层
    in_features = model.classifier[1].in_features
    model.classifier = nn.Sequential(
        nn.Dropout(p=0.4, inplace=True),
        nn.Linear(in_features, num_classes),
    )
    return model.to(device)


def freeze_backbone(model):
    """冻结 backbone（features），只训分类头"""
    for param in model.features.parameters():
        param.requires_grad = False
    for param in model.classifier.parameters():
        param.requires_grad = True
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"  [Phase 1] 冻结 backbone，可训参数: {trainable:,}")


def unfreeze_all(model):
    """解冻全部参数"""
    for param in model.parameters():
        param.requires_grad = True
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"  [Phase 2] 解冻全部，可训参数: {trainable:,}")


def train_one_epoch(model, loader, criterion, optimizer, device, scaler):
    model.train()
    total_loss = correct = total = 0
    for imgs, labels in loader:
        imgs, labels = imgs.to(device), labels.to(device)
        optimizer.zero_grad()
        with torch.autocast(device_type="cuda", dtype=torch.float16):
            outputs = model(imgs)
            loss    = criterion(outputs, labels)
        scaler.scale(loss).backward()
        scaler.step(optimizer)
        scaler.update()
        total_loss += loss.item() * imgs.size(0)
        _, preds    = outputs.max(1)
        correct    += preds.eq(labels).sum().item()
        total      += imgs.size(0)
    return total_loss / total, correct / total * 100


@torch.no_grad()
def evaluate(model, loader, criterion, device):
    model.eval()
    total_loss = correct = total = 0
    class_correct = [0] * NUM_CLASSES
    class_total   = [0] * NUM_CLASSES
    for imgs, labels in loader:
        imgs, labels = imgs.to(device), labels.to(device)
        outputs = model(imgs)
        loss    = criterion(outputs, labels)
        total_loss += loss.item() * imgs.size(0)
        _, preds    = outputs.max(1)
        correct    += preds.eq(labels).sum().item()
        total      += imgs.size(0)
        for i in range(len(labels)):
            lbl = labels[i].item()
            class_correct[lbl] += (preds[i] == labels[i]).item()
            class_total[lbl]   += 1
    per_class = {CLASSES[i]: f"{class_correct[i]/max(class_total[i],1)*100:.1f}%"
                 for i in range(NUM_CLASSES)}
    return total_loss / total, correct / total * 100, per_class


def main():
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print("=" * 60)
    print("  Chef Vision — EfficientNet-B3 炒蛋熟度分类训练")
    print("=" * 60)
    print(f"  设备: {device}")
    if device.type == "cuda":
        print(f"  GPU: {torch.cuda.get_device_name(0)}")

    # ── 数据集 ────────────────────────────────────────────────────────────────
    train_ds = datasets.ImageFolder(TRAIN_DIR, transform=train_transform)
    val_ds   = datasets.ImageFolder(VAL_DIR,   transform=val_transform)

    # 确认类别顺序和预期一致
    print(f"\n  训练集类别映射: {train_ds.class_to_idx}")
    print(f"  训练集: {len(train_ds)} 张  验证集: {len(val_ds)} 张")

    # 保存类别映射（推理时用）
    import json
    class_map = {v: k for k, v in train_ds.class_to_idx.items()}
    with open(os.path.join(MODEL_DIR, "class_map.json"), "w") as f:
        json.dump(class_map, f, ensure_ascii=False, indent=2)
    print(f"  类别映射已保存: {os.path.join(MODEL_DIR, 'class_map.json')}")

    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True,
                              num_workers=NUM_WORKERS, pin_memory=True,
                              persistent_workers=True)
    val_loader   = DataLoader(val_ds,   batch_size=BATCH_SIZE, shuffle=False,
                              num_workers=NUM_WORKERS, pin_memory=True,
                              persistent_workers=True)

    # ── 模型 ──────────────────────────────────────────────────────────────────
    model  = build_model(NUM_CLASSES, device)
    scaler = torch.cuda.amp.GradScaler()

    # 标签平滑 CrossEntropy + 类别权重（提升 burnt 类召回率）
    # 权重顺序对应 class_to_idx 的字母序：burnt=0, done=1, raw=2
    # burnt 分类最难，给 2.5 倍权重；raw 稍难给 1.5 倍
    _idx = train_ds.class_to_idx   # {'burnt':0, 'done':1, 'raw':2}
    class_weights = torch.zeros(NUM_CLASSES)
    class_weights[_idx["burnt"]] = 2.5
    class_weights[_idx["done"]]  = 1.0
    class_weights[_idx["raw"]]   = 1.5
    class_weights = class_weights.to(device)
    criterion = nn.CrossEntropyLoss(label_smoothing=LABEL_SMOOTH,
                                    weight=class_weights)

    # ── 训练日志 ──────────────────────────────────────────────────────────────
    log_rows  = []
    best_acc  = 0.0
    total_start = time.time()

    # ══════════════════════════════════════════════════════════════════════════
    # Phase 1：只训分类头
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'─'*60}")
    print(f"  Phase 1 — 冻结 backbone，训练分类头  ({P1_EPOCHS} epoch)")
    print(f"{'─'*60}")
    freeze_backbone(model)
    optimizer = optim.AdamW(filter(lambda p: p.requires_grad, model.parameters()),
                            lr=P1_LR, weight_decay=WEIGHT_DECAY)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=P1_EPOCHS, eta_min=1e-5)

    for epoch in range(1, P1_EPOCHS + 1):
        t0 = time.time()
        tr_loss, tr_acc = train_one_epoch(model, train_loader, criterion, optimizer, device, scaler)
        va_loss, va_acc, per_cls = evaluate(model, val_loader, criterion, device)
        scheduler.step()
        elapsed = time.time() - t0

        print(f"  [P1 E{epoch:02d}] loss={tr_loss:.4f} acc={tr_acc:.1f}%  "
              f"val_loss={va_loss:.4f} val_acc={va_acc:.1f}%  "
              f"({elapsed:.1f}s)  {per_cls}")

        if va_acc > best_acc:
            best_acc = va_acc
            torch.save({"epoch": epoch, "model": model.state_dict(),
                        "val_acc": va_acc, "class_map": class_map}, BEST_MODEL)
            print(f"  ✓ 保存最优模型 val_acc={va_acc:.1f}%")

        log_rows.append(["P1", epoch, tr_loss, tr_acc, va_loss, va_acc])

    # ══════════════════════════════════════════════════════════════════════════
    # Phase 2：全部微调
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'─'*60}")
    print(f"  Phase 2 — 解冻全部，微调  ({P2_EPOCHS} epoch)")
    print(f"{'─'*60}")
    unfreeze_all(model)
    optimizer = optim.AdamW(model.parameters(), lr=P2_LR, weight_decay=WEIGHT_DECAY)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=P2_EPOCHS, eta_min=1e-6)

    for epoch in range(1, P2_EPOCHS + 1):
        t0 = time.time()
        tr_loss, tr_acc = train_one_epoch(model, train_loader, criterion, optimizer, device, scaler)
        va_loss, va_acc, per_cls = evaluate(model, val_loader, criterion, device)
        scheduler.step()
        elapsed = time.time() - t0

        print(f"  [P2 E{epoch:02d}] loss={tr_loss:.4f} acc={tr_acc:.1f}%  "
              f"val_loss={va_loss:.4f} val_acc={va_acc:.1f}%  "
              f"({elapsed:.1f}s)  {per_cls}")

        if va_acc > best_acc:
            best_acc = va_acc
            torch.save({"epoch": P1_EPOCHS + epoch, "model": model.state_dict(),
                        "val_acc": va_acc, "class_map": class_map}, BEST_MODEL)
            print(f"  ✓ 保存最优模型 val_acc={va_acc:.1f}%")

        log_rows.append(["P2", epoch, tr_loss, tr_acc, va_loss, va_acc])

    # 保存最后一轮
    torch.save({"epoch": P1_EPOCHS + P2_EPOCHS, "model": model.state_dict(),
                "val_acc": va_acc, "class_map": class_map}, LAST_MODEL)

    # 保存训练日志
    with open(LOG_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["phase", "epoch", "train_loss", "train_acc", "val_loss", "val_acc"])
        writer.writerows(log_rows)

    total_time = time.time() - total_start
    print(f"\n{'='*60}")
    print(f"  训练完成！  最优验证集 acc = {best_acc:.1f}%")
    print(f"  总耗时: {total_time/60:.1f} 分钟")
    print(f"  最优模型: {BEST_MODEL}")
    print(f"  训练日志: {LOG_CSV}")
    print(f"  下一步：运行 classify/infer.py 推理测试")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
