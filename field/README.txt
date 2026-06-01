field/ — 厨房现场采集脚本（低配笔记本用）
==========================================

这些脚本设计用于带进厨房的低配置笔记本，
只需 numpy + opencv，不依赖 SAM2 等重型库。

脚本说明：

  FieldCapture.py       【主采集脚本】
                        实时显示 RGB + IR 双画面预览。
                        按 S 开始录制，按 Q 停止保存。
                        自动以时间戳命名，输出到 data/ 目录。
                        输出：data/rgb_YYYYMMDD_HHMMSS.mp4
                              data/temp_YYYYMMDD_HHMMSS.npy

  FieldTempMonitor.py   【实时温度监测】
                        连接热像仪，显示 IR 热图。
                        按 R 框选 ROI，按 S 录制，按 Q 保存。
                        输出：output/temp_monitor_TIMESTAMP.csv
                              output/temp_monitor_TIMESTAMP.png

  DataLogger.py         【早期采集脚本（已被 FieldCapture 替代）】
                        基于 ThermalCamera 封装类的数据采集器。
                        输出：data/rgb_record.mp4、data/temp_matrices.npy

  TempMonitor.py        【离线温度分析工具】
                        加载已录制的 .npy 文件，手动圈选 ROI，
                        提取温度统计并导出 CSV + 曲线图。
                        输出：output/temp_monitor_log.csv
                              output/temp_monitor_curve.png

设备参数（各脚本顶部修改）：
  DEVICE_IP   = "192.168.1.123"
  DEVICE_PORT = 80
  USERNAME    = "admin"
  PASSWORD    = "ZGTC2026"

DLL 依赖：自动从 ../sdk/ 目录加载，无需手动复制。
