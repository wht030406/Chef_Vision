# data 目录说明

`data/` 只保存当前主流程共用的几何配置，不再保存默认采集视频或温度矩阵。
RGB/IR 测试数据已经统一放在 `test_data/`。

当前文件：

| 文件 | 作用 | 生成/更新方式 |
|---|---|---|
| `homography.npy` | RGB 坐标到 IR 坐标的 3x3 单应矩阵 | `tools/Calibrate.py` |
| `wok_region.json` | IR 锅区椭圆、旋转轴圆心和排除半径 | `python core/LabelInitialSetup.py` 的 IR 标注步骤 |

## 1. homography.npy

主程序把 RGB 正向/反向 mask、固定 RGB ROI 和 IR/RGB 锅区相互映射时都会
使用该矩阵。其方向是：

```text
RGB 点/区域 --homography.npy--> IR 点/区域
```

需要反向映射时，代码内部使用其逆矩阵。

重新标定：

```powershell
python tools/Calibrate.py `
  --video test_data/test8_1/rgb_20260707_153017.mp4 `
  --npy test_data/test8_1/temp_20260707_153017.npy
```

结果会覆盖 `data/homography.npy`。标定后应使用
`排查工具/check_ir_align.py` 或 `排查工具/check_homography.py`
检查对齐。

## 2. wok_region.json

当前字段示例：

```json
{
  "cx": 113,
  "cy": 108,
  "rx": 56,
  "ry": 55,
  "axis_cx": 108,
  "axis_cy": 106,
  "axis_excl_r_ir": 16,
  "ir_h": 192,
  "ir_w": 256
}
```

字段含义：

- `cx/cy`：IR 锅区中心。
- `rx/ry`：IR 锅区椭圆半轴。
- `axis_cx/axis_cy`：旋转轴中心。
- `axis_excl_r_ir`：IR 中手工定义的旋转轴排除半径。
- `ir_h/ir_w`：配置对应的 IR 分辨率。

主程序先在 IR 中构造锅区，再通过单应矩阵反投影为 RGB 锅区约束。旋转轴
排除圆也会从 IR 尺寸换算到 RGB 尺寸。

自动估计示例：

```powershell
python tools/auto_wok_detect.py `
  --temp test_data/test8_1/temp_20260707_153017.npy `
  --start_sec 5 `
  --out data/wok_region.json
```

自动结果仍应人工检查。旋转轴位置和排除半径通常需要结合实际画面确认。
公司交接版仓库不固定提交当前调试用的 `wok_region.json`；更换视频或重新
标注时，由统一标注入口生成/更新。

## 3. 主程序如何读取

默认路径固定为：

```text
data/homography.npy
data/wok_region.json
```

也可在运行时覆盖：

```powershell
python core/TrackFood.py `
  --homography D:/path/to/homography.npy `
  --wok D:/path/to/wok_region.json
```

## 4. 注意事项

1. 相机位置、焦距、画面裁剪或 RGB/IR 分辨率改变后，应重新标定。
2. `homography.npy` 不是普通图片，不要用文本编辑器修改。
3. `wok_region.json` 可手工查看，但修改前应保存备份并记录对应测试视频。
4. 锅区和排除圆当前仍是后续精度优化重点；“文件存在”不等于所有时刻定位
   都准确。
5. 早期 `data/rgb_20260428_121157.mp4` 和
   `data/temp_20260428_121546.npy` 已删除。任何仍引用这两个路径的归档脚本
   都需要手动改为 `test_data/` 中的实际文件。
