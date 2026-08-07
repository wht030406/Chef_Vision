# test_data 测试数据说明

本目录保存离线算法测试使用的 RGB 视频、IR 视频、红外温度矩阵、时间戳和
ROI 配置。

`test_data/` 是输入数据仓库，不是程序输出目录。当前不要删除或移动现有
测试集。

## 1. 单个测试集的常见文件

以 `test8_1/` 为例：

| 文件 | 含义 |
|---|---|
| `rgb_YYYYMMDD_HHMMSS.mp4` | 可见光视频，主追踪画面 |
| `ir_YYYYMMDD_HHMMSS.mp4` | 便于人工查看的 IR 伪彩视频 |
| `temp_YYYYMMDD_HHMMSS.npy` | 逐帧温度矩阵，温度计算的真实数据源 |
| `rgb_..._ts.npy` | RGB 帧时间戳 |
| `temp_..._ts.npy` | IR 温度帧时间戳 |
| `roi_config.json` | 采集时设置的固定 RGB ROI |
| `trim_summary.json` | 剪辑版数据删除了哪些时间段及前后帧数 |

IR 视频主要用于查看，主程序实际温度统计读取 `temp_*.npy`。

## 2. RGB 与 IR 如何对应

`core/ir_timeline.py` 按以下顺序建立映射：

1. 若 RGB 和 IR 时间戳文件都存在，按最近时间戳匹配。
2. 时间戳不完整时，根据 RGB/IR 总帧数比例估算。

因此同一个测试集中的 RGB、温度矩阵和两份时间戳必须一起保留。只复制视频
而遗漏温度矩阵，主流程仍可尝试追踪，但不会得到完整温度结果。

## 3. 原始版与剪辑版

现场录制得到的原始数据建议先做必要剪辑，去除锅直立、空锅、食材不可见
或其他明显无效的时间段，再用于主程序测试。剪辑后应同步保存 RGB 视频、
IR 视频、温度矩阵、时间戳和 ROI 配置。

剪辑数据中的 `trim_summary.json` 可记录：

- 原始数据来源；
- 被删除的时间段；
- 剪辑前后的 RGB/IR 帧数；
- 新时间戳是否已同步保存。

主线目前主要使用剪辑后的数据，因此
`ENABLE_UPRIGHT_WOK_FREEZE=False`。如果重新处理未剪辑原始视频，需要重新
评估锅直立/白烟/空锅干扰。

## 4. 通用测试数据使用方式

先对目标数据目录运行统一标注入口：

```powershell
python core/LabelInitialSetup.py --data-dir test_data/你的数据目录
```

标注完成后可先运行 120 帧短测：

```powershell
python core/TrackFood.py --max-frames 120
```

若同时保留多套标注，可显式指定标注、视频和温度文件；三者必须来自同一套
数据：

```powershell
python core/TrackFood.py `
  --labels core/food_labels_你的数据名.json `
  --video test_data/你的数据目录/rgb_TIMESTAMP.mp4 `
  --temp test_data/你的数据目录/temp_TIMESTAMP.npy
```

## 5. 新增测试集的推荐步骤

1. 把同次采集的 RGB、IR、温度矩阵和时间戳放入独立子目录。
2. 保持同一时间戳命名，便于自动匹配。
3. 如需剪辑，使用 `tools/trim_dataset_segments.py` 同步处理所有数据。
4. 运行 `core/LabelInitialSetup.py --data-dir ...`，依次完成食材、锅底和 IR 标注。
5. 确认 `data/homography.npy` 与当前相机位置仍匹配。
6. 先跑 120 帧短测，再跑完整视频。

## 6. 注意事项

- `.npy` 可能很大，不要用普通文本编辑器打开。
- 不要单独剪 RGB 视频；必须同步剪 IR、温度和时间戳。
- `roi_config.json` 属于对应采集画面，复制到另一分辨率或构图可能失效。
- 测试数据独立于代码版本；删除本地数据前应先确认已有其他备份。
- 当前用户要求保留 `test_data/` 全部内容，不做空间清理。
