# models 目录说明

本目录存放 SAM2.1 模型权重。公司交接版仓库需要保留权重文件路径，因此
`*.pt` / `*.pth` 通过 Git LFS 跟踪，而不是作为普通 Git 文本/二进制对象提交。

## 当前文件

| 文件 | 约占空间 | 用途 |
|---|---:|---|
| `sam2.1_hiera_large.pt` | 857 MB | 当前 `core/TrackFood.py` 正式使用 |
| `sam2.1_hiera_tiny.pt` | 149 MB | 速度优先的备选权重，当前未启用 |

主程序当前配置为：

```text
MODEL_CFG       = configs/sam2.1/sam2.1_hiera_l.yaml
CHECKPOINT_PATH = models/sam2.1_hiera_large.pt
```

切换 tiny 不只是改权重路径，还必须同时改为对应的 tiny 配置文件。模型配置
来自已安装的 `sam2` 包或其源码环境，不在本目录中。

## 使用前检查

1. 确认本机已安装 Git LFS，并且 clone 后权重文件不是 LFS 指针小文件。
2. 确认权重文件不是 0 字节，文件大小与上表量级接近。
3. 确认 Python 环境可以执行 `import sam2`。
4. 确认配置名和权重规格一致，large 配 large，tiny 配 tiny。
5. CUDA GPU 推荐。SAM2 Large 在 CPU 上运行会非常慢。

## 注意事项

- 不要重复下载同名权重覆盖已经可用的文件。
- 权重由 Git LFS 管理。换电脑后应使用支持 Git LFS 的方式 clone/pull。
- 复制“关键代码备份”时，是否包含权重取决于备份目的；仅源码备份通常可
  排除，离线可运行备份则应包含。
- `排查工具/SegmentFood.py` 仍保留早期外部权重路径和自动下载逻辑，
  不能代表主程序的实际加载路径。
