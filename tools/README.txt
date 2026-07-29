# tools 目录说明

`tools/` 保存主流程运行前的数据准备工具。它们不是
`core/TrackFood.py` 的自动步骤，而是标定、锅区建立或数据同步剪辑时按需
手动运行。

开发排查脚本放在根目录 `排查工具/`，不要把两类工具混用。

## 1. Calibrate.py

作用：在多个 RGB/IR 对应画面上手工点击同名点，计算 RGB 到 IR 的单应矩阵。

```powershell
python tools/Calibrate.py `
  --video test_data/test8_1/rgb_20260707_153017.mp4 `
  --npy test_data/test8_1/temp_20260707_153017.npy
```

输出：

```text
data/homography.npy
```

注意：

- 会覆盖当前标定矩阵。
- 选择分布在画面不同位置、在 RGB/IR 中都可辨认的对应点。
- 相机移动、裁剪或分辨率变化后需要重新标定。
- 保存后使用 `排查工具/check_ir_align.py` 验证。

## 2. auto_wok_detect.py

作用：在若干 IR 温度帧的平均图中寻找高温锅环并拟合椭圆。

```powershell
python tools/auto_wok_detect.py `
  --temp test_data/test8_1/temp_20260707_153017.npy `
  --start_sec 5 `
  --out data/wok_region.json `
  --viz tools/auto_wok_detect_result.jpg
```

重要参数：

- `--start_sec`：选择锅形较清晰、温度较稳定的起点。
- `--rx_scale`：横向半径缩放，当前默认 0.85。
- `--ry_scale`：纵向半径缩放，当前默认 1.0。

自动检测只生成锅椭圆基础结果。旋转轴中心和排除半径仍需人工检查；若输出
JSON 缺少主程序所需字段，应通过现有标注流程补齐。

## 3. trim_dataset_segments.py

作用：同步删除 RGB、IR 视频和温度矩阵中的指定时间段，生成新的剪辑测试集。

```powershell
python tools/trim_dataset_segments.py `
  --src-dir test_data/test8 `
  --dst-dir test_data/test8_1_new `
  --rgb rgb_20260707_153017.mp4 `
  --ir ir_20260707_153017.mp4 `
  --temp temp_20260707_153017.npy `
  --segments 0-1.5 40-48 55-63
```

输出目录包含同步剪辑后的数据和 `trim_summary.json`。工具会按时间建立保留
掩码，不能用它代替精确的硬件同步校准。

## 4. 推荐的数据准备顺序

```text
field/ 采集
   |
   +--> 可选：trim_dataset_segments.py
   |
   +--> Calibrate.py 生成 homography.npy
   |
   +--> auto_wok_detect.py / 人工标注锅区
   |
   +--> LabelInitialSetup.py 顺序完成正向、反向和 IR 锅区初始标注
   |
   v
TrackFood.py
```

## 5. 注意事项

1. 这些工具会写配置或新数据，运行前确认输出路径。
2. 不要在只想“看效果”时无意覆盖 `data/homography.npy` 或
   `data/wok_region.json`。
3. 自动锅区结果不是最终真值，需要结合 RGB/IR 对齐画面检查。
4. 剪辑后要使用新的时间戳和标注，不能直接沿用原视频帧号。
5. 旧调试工具已归档到 `排查工具/`；那里部分脚本含失效的默认路径。
