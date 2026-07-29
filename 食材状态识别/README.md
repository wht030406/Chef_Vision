# 食材状态识别归档说明

本目录是早期“生 / 熟 / 焦糊”视觉分类实验。它与当前
RGB/IR/SAM2 温度检测主线相互独立，`core/TrackFood.py` 没有导入这里的
任何代码。

当前决定是：代码、图片、测试视频和模型都保留，作为历史实验；短期不继续
训练，也不把分类结果接入最终温度。

## 1. 实验目标

以番茄炒蛋/炒蛋画面为主要样本，将食材状态分为：

- `raw`：生或未熟；
- `done`：已熟；
- `burnt`：焦糊。

核心模型使用 ImageNet 预训练的 EfficientNet-B3：

1. 替换分类头为三分类。
2. 第一阶段冻结 backbone，只训练分类头。
3. 第二阶段解冻全网络，以较小学习率微调。
4. 使用随机裁剪、翻转、旋转和颜色扰动做增强。
5. 对 `raw`、`burnt` 给予较高类别权重，尝试缓解样本不平衡。

## 2. 目录与文件

```text
classify/
  data_tomato/        原始整理数据，96 张
  data_tomato_train/  训练集，78 张
  data_tomato_val/    验证集，18 张
  frames_preview/     视频抽帧和联系图
  models/             best/last 权重、类别映射、训练日志
  test_videos/        早期下载的测试视频
  train.py            EfficientNet-B3 两阶段训练
  infer.py            单图/视频推理和连续焦糊报警
  run_infer_video.py  视频推理可视化
  prepare_*.py        数据抽取、训练/验证拆分
  crawl_*.py          图片/视频爬取
  filter_data.py      pHash 去重和数据过滤
```

当前本地规模约为：

- 图片训练/验证主体不足 100 张；
- 测试视频约 416 MB；
- 模型约 83 MB；
- 全目录约 562 MB。

训练日志中出现过较高验证准确率，但验证集只有 18 张，不能据此证明模型具备
真实泛化能力。

## 3. 训练流程

若未来重新启动，当前代码链路大致是：

```text
爬取/视频抽帧
   |
   v
人工清洗与状态标准定义
   |
   v
prepare_trainval.py / filter_data.py
   |
   v
train.py
   |
   v
models/best_model.pth
   |
   v
infer.py / run_infer_video.py
```

现有训练入口：

```powershell
cd 食材状态识别/classify
python train.py
```

现有推理示例：

```powershell
python infer.py --image D:/path/to/image.jpg
python infer.py --video D:/path/to/video.mp4
python run_infer_video.py D:/path/to/video.mp4 --start 0 --end 30
```

所需额外依赖包括 `torchvision`、Pillow，以及下载脚本可能使用的
`yt-dlp`、ffmpeg 和网络访问。它们未写入当前根目录 `requirements.txt`。

## 4. 当前模型与报警逻辑

`infer.py` 中的 `FoodStateClassifier` 提供单帧分类接口。焦糊报警不是看到
一帧就触发，而是要求：

- `burnt` 置信度达到约 0.75；
- 连续 5 帧超过阈值。

这个接口曾为接入主流程预留，但目前没有实际调用。

## 5. 暂停推进的主要原因

1. 早期爬虫和视频切帧数据质量较差，主体不干净、标签不可靠、拍摄条件混杂。
2. “生、熟、焦糊”缺少可执行且跨菜品一致的评价标准。
3. 样本数量太少，训练集和验证集高度同源，容易得到虚高验证结果。
4. 锅内遮挡、反光、白烟和工具会让全帧分类学习到背景偏差。
5. 多份爬虫/准备脚本仍硬编码旧路径
   `D:\Chef_Vision\classify\...`，目录归档后不能直接运行。

## 6. 未来重新启动的最低条件

- 先限定菜品或食材类型，不直接追求通用三分类。
- 由人工定义状态判据并进行双人复核。
- 采集独立日期、独立锅次的高质量训练/验证数据。
- 优先使用当前主线食材 mask 裁剪主体，再做状态分类。
- 报告混淆矩阵、按视频分组的验证结果，而不是只看随机图片准确率。

## 7. 注意事项

- 当前模型仅是实验权重，不应用于现场报警或专利效果结论。
- 网络爬虫脚本可能受网站变化、网络权限和版权约束影响。
- 不要把低质量爬取图片继续扩充到训练集而不做人工清洗。
- 该目录已归档但暂时保留全部文件，当前不从 Git 或磁盘移除。
