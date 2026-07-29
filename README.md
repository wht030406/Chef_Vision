# Chef Vision

Chef Vision 是基于 RGB 视频、红外温度矩阵和 SAM2 追踪的炒菜食材温度检测
项目。当前主线包括 RGB 正向食材追踪、IR 辅助重采点、RGB 反向辅助、ROI
对照和最终温度决策。

## 主要入口

```powershell
python core/LabelInitialSetup.py
python core/TrackFood.py
```

运行前需要准备：

- 现场采集或整理后的 RGB/IR 测试数据；
- `models/sam2.1_hiera_large.pt` 模型权重；
- `data/homography.npy` RGB/IR 标定矩阵；
- 通过统一标注入口生成的 `core/food_labels.json` 和 `data/wok_region.json`。

## 说明文档

- `Chef_Vision_项目总说明.md`：项目总览和目录导航。
- `docs/`：PDF 版流程图解和现场操作手册。
- 各子目录中的 `README.md` / `README.txt`：对应目录的用途和注意事项。

## GitHub 交接说明

仓库保留主要代码、SDK、现场采集程序、标定矩阵和说明文档。`output/` 是
运行输出目录，`test_data/` 是测试数据目录；两者中的真实大文件由本地运行
或现场采集产生。
