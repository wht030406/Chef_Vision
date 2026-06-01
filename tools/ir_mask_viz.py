
"""
ir_mask_viz.py — 基于 IR 温度矩阵自动分割菜区域，生成带 mask 和温度曲线的 IR 视频

关键观察（来自实际 IR 视频）：
  - 锅底中心：最热（黄/白色，>200°C）
  - 菜：蓝色，温度低于锅底（因为菜吸热降温）
  - 锅边：红色环形，中等温度
  - 锅外环境：深蓝色，最冷

分割策略：
  1. 先限制处理区域为"锅内椭圆"，排除锅外环境干扰
  2. 在锅内区域里，找"相对低温"区域（低于锅内温度中位数）= 菜
  3. 排除锅外的冷背景（避免把环境误判为菜）

用法：
  # 第一次运行：交互式设置锅区域椭圆
  python ir_mask_viz.py --setup

  # 正常处理
  python ir_mask_viz.py
  python ir_mask_viz.py --npy test_data/test1/temp_20260529_112414.npy
"""

import os
import sys
import argparse
import numpy as np
import cv2
import json

_HERE = os.path.dirname(os.path.abspath(__file__))

# ── 配置 ─────────────────────────────────────────────────────────────────────
DEFAULT_NPY   = os.path.join(_HERE, "..", "test_data", "test1", "temp_20260529_112414.npy")
OUTPUT_DIR    = os.path.join(_HERE, "..", "output")
WOK_CFG_PATH  = os.path.join(_HERE, "..", "data", "wok_region.json")  # 锅区域配置

# IR 输出视频分辨率
IR_W, IR_H    = 512, 384
CHART_H       = 120
CURVE_WIN_S   = 60
IR_FPS        = 25.0

# 菜分割阈值（在锅内区域内）
# 菜的温度低于锅内温度的 FOOD_PERCENTILE 百分位
FOOD_PERCENTILE = 40   # 锅内低于40%分位的像素 = 菜（可调）
MIN_FOOD_AREA   = 20   # 最小菜区域像素数（IR 原始分辨率）


# ── 锅区域椭圆 ────────────────────────────────────────────────────────────────

def load_wok_region(ir_h, ir_w):
    """加载锅区域椭圆配置，不存在则返回默认（覆盖整个画面中心）"""
    if os.path.exists(WOK_CFG_PATH):
        with open(WOK_CFG_PATH) as f:
            cfg = json.load(f)
        return cfg
    # 默认：画面中心 60% 区域
    return {
        "cx": ir_w // 2,
        "cy": ir_h // 2,
        "rx": int(ir_w * 0.38),
        "ry": int(ir_h * 0.42),
    }


def make_wok_mask(ir_h, ir_w, cfg):
    """生成锅内区域 mask（椭圆形）"""
    mask = np.zeros((ir_h, ir_w), dtype=np.uint8)
    cv2.ellipse(mask,
                (cfg["cx"], cfg["cy"]),
                (cfg["rx"], cfg["ry"]),
                0, 0, 360, 255, -1)
    return mask > 0


def setup_wok_region(npy_path):
    """
    交互式设置锅区域椭圆。
    显示 IR 热力图，用鼠标拖拽设置椭圆中心和半径。
    """
    data = np.load(npy_path)
    if data.ndim == 2:
        data = data[np.newaxis, ...]

    # 取中间帧作为参考
    ref_frame = data[len(data) // 2]
    ir_h, ir_w = ref_frame.shape

    # 初始椭圆参数
    cfg = load_wok_region(ir_h, ir_w)
    cx, cy = cfg["cx"], cfg["cy"]
    rx, ry = cfg["rx"], cfg["ry"]

    # 放大显示
    SCALE = IR_W / ir_w
    disp_w, disp_h = IR_W, IR_H

    state = {"dragging": False, "mode": "center"}  # mode: center/rx/ry

    def to_disp(x, y):
        return int(x * SCALE), int(y * SCALE)

    def to_ir(x, y):
        return int(x / SCALE), int(y / SCALE)

    def draw():
        t_min = float(ref_frame.min())
        t_max = float(ref_frame.max())
        norm = ((ref_frame - t_min) / max(t_max - t_min, 0.1) * 255).astype(np.uint8)
        img = cv2.applyColorMap(norm, cv2.COLORMAP_JET)
        img = cv2.resize(img, (disp_w, disp_h))

        # 绘制椭圆
        dcx, dcy = to_disp(cx, cy)
        drx, dry = int(rx * SCALE), int(ry * SCALE)
        cv2.ellipse(img, (dcx, dcy), (drx, dry), 0, 0, 360, (0, 255, 255), 2)
        cv2.circle(img, (dcx, dcy), 5, (0, 255, 255), -1)
        cv2.circle(img, (dcx + drx, dcy), 5, (255, 200, 0), -1)
        cv2.circle(img, (dcx, dcy + dry), 5, (255, 200, 0), -1)

        cv2.putText(img, "拖拽圆心=移动椭圆  拖拽右侧点=调X半径  拖拽下方点=调Y半径",
                    (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
        cv2.putText(img, f"cx={cx} cy={cy} rx={rx} ry={ry}  [S]=保存  [Q]=退出",
                    (8, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 255, 200), 1)
        return img

    def mouse_cb(event, x, y, flags, param):
        nonlocal cx, cy, rx, ry
        ix, iy = to_ir(x, y)
        dcx, dcy = to_disp(cx, cy)
        drx = int(rx * SCALE)
        dry = int(ry * SCALE)

        if event == cv2.EVENT_LBUTTONDOWN:
            # 判断点击的是哪个控制点
            if abs(x - (dcx + drx)) < 12 and abs(y - dcy) < 12:
                state["dragging"] = True
                state["mode"] = "rx"
            elif abs(x - dcx) < 12 and abs(y - (dcy + dry)) < 12:
                state["dragging"] = True
                state["mode"] = "ry"
            elif abs(x - dcx) < 15 and abs(y - dcy) < 15:
                state["dragging"] = True
                state["mode"] = "center"
        elif event == cv2.EVENT_MOUSEMOVE and state["dragging"]:
            if state["mode"] == "center":
                cx, cy = max(0, min(ir_w-1, ix)), max(0, min(ir_h-1, iy))
            elif state["mode"] == "rx":
                rx = max(5, abs(ix - cx))
            elif state["mode"] == "ry":
                ry = max(5, abs(iy - cy))
        elif event == cv2.EVENT_LBUTTONUP:
            state["dragging"] = False

    win = "设置锅区域椭圆 — [S]=保存 [Q]=退出"
    cv2.namedWindow(win)
    cv2.setMouseCallback(win, mouse_cb)

    while True:
        cv2.imshow(win, draw())
        key = cv2.waitKey(30) & 0xFF
        if key in (ord('s'), ord('S')):
            os.makedirs(os.path.dirname(WOK_CFG_PATH), exist_ok=True)
            cfg_save = {"cx": cx, "cy": cy, "rx": rx, "ry": ry,
                        "ir_h": ir_h, "ir_w": ir_w}
            with open(WOK_CFG_PATH, "w") as f:
                json.dump(cfg_save, f, indent=2)
            print(f"[OK] 锅区域已保存: {WOK_CFG_PATH}")
            print(f"     cx={cx} cy={cy} rx={rx} ry={ry}")
            break
        elif key in (ord('q'), ord('Q')):
            print("[退出] 未保存锅区域")
            break

    cv2.destroyAllWindows()


# ── 温度曲线绘制 ──────────────────────────────────────────────────────────────

def draw_chart(temp_history, cur_time_s, w, h, curve_win_s=60):
    bar = np.zeros((h, w, 3), dtype=np.uint8)
    if len(temp_history) < 2:
        cv2.putText(bar, "IR Mask Avg Temp (waiting...)",
                    (10, h // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (160, 160, 160), 1)
        return bar

    t0  = max(0.0, cur_time_s - curve_win_s)
    pts = [(t, v) for t, v in temp_history if t >= t0 and not np.isnan(v)]
    if len(pts) < 2:
        pts = temp_history[-2:]

    times = [p[0] for p in pts]
    vals  = [p[1] for p in pts]

    t_min_ax = t0
    t_max_ax = max(cur_time_s, t0 + 1.0)
    v_min_ax = max(0.0, min(vals) - 5.0)
    v_max_ax = max(vals) + 5.0
    if v_max_ax <= v_min_ax:
        v_max_ax = v_min_ax + 10.0

    pad_l, pad_r, pad_t, pad_b = 48, 12, 10, 22

    def tx(t):
        return pad_l + int((t - t_min_ax) / (t_max_ax - t_min_ax) * (w - pad_l - pad_r))

    def ty(v):
        return pad_t + int((1.0 - (v - v_min_ax) / (v_max_ax - v_min_ax)) * (h - pad_t - pad_b))

    for v in np.linspace(v_min_ax, v_max_ax, 3):
        yy = ty(v)
        cv2.line(bar, (pad_l, yy), (w - pad_r, yy), (45, 45, 45), 1)
        cv2.putText(bar, f"{v:.0f}", (2, yy + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (180, 180, 180), 1)

    cv2.line(bar, (pad_l, pad_t), (pad_l, h - pad_b), (160, 160, 160), 1)
    cv2.line(bar, (pad_l, h - pad_b), (w - pad_r, h - pad_b), (160, 160, 160), 1)
    cv2.putText(bar, f"{t_min_ax:.0f}s", (pad_l, h - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.32, (140, 140, 140), 1)
    cv2.putText(bar, f"{cur_time_s:.1f}s", (w - pad_r - 30, h - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.32, (140, 140, 140), 1)

    screen_pts = [(tx(t), ty(v)) for t, v in zip(times, vals)]
    for i in range(1, len(screen_pts)):
        p1, p2 = screen_pts[i - 1], screen_pts[i]
        if all(0 <= c < dim for c, dim in [(p1[0], w), (p1[1], h), (p2[0], w), (p2[1], h)]):
            cv2.line(bar, p1, p2, (0, 220, 100), 2)

    cx_pt, cy_pt = tx(cur_time_s), ty(vals[-1])
    if 0 <= cx_pt < w and 0 <= cy_pt < h:
        cv2.circle(bar, (cx_pt, cy_pt), 4, (0, 255, 80), -1)
        cv2.putText(bar, f"{vals[-1]:.1f}C", (cx_pt + 6, cy_pt + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 255, 120), 1)

    cv2.putText(bar, "— IR Mask Avg Temp (C)", (pad_l + 4, pad_t + 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 220, 100), 1)
    return bar


# ── 主处理 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--npy",   default=DEFAULT_NPY)
    parser.add_argument("--setup", action="store_true", help="交互式设置锅区域椭圆")
    parser.add_argument("--pct",   type=int, default=FOOD_PERCENTILE,
                        help=f"菜区域百分位阈值（默认{FOOD_PERCENTILE}）")
    args = parser.parse_args()

    if args.setup:
        setup_wok_region(args.npy)
        return

    if not os.path.exists(args.npy):
        print(f"[错误] 找不到温度文件: {args.npy}")
        sys.exit(1)

    print(f"[加载] {args.npy}")
    data = np.load(args.npy)
    if data.ndim == 2:
        data = data[np.newaxis, ...]
    n_frames, ir_h, ir_w = data.shape
    print(f"[温度] shape={data.shape}  范围: {data.min():.1f}°C ~ {data.max():.1f}°C")

    # 加载锅区域
    wok_cfg  = load_wok_region(ir_h, ir_w)
    wok_mask = make_wok_mask(ir_h, ir_w, wok_cfg)
    print(f"[锅区域] cx={wok_cfg['cx']} cy={wok_cfg['cy']} "
          f"rx={wok_cfg['rx']} ry={wok_cfg['ry']}  "
          f"覆盖像素: {wok_mask.sum()}/{ir_h*ir_w} ({wok_mask.sum()/(ir_h*ir_w)*100:.1f}%)")
    if not os.path.exists(WOK_CFG_PATH):
        print("[提示] 使用默认锅区域，建议先运行: python ir_mask_viz.py --setup 精确设置")

    # 输出路径
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(OUTPUT_DIR, f"ir_mask_{ts}")
    os.makedirs(out_dir, exist_ok=True)
    out_video = os.path.join(out_dir, "ir_mask_viz.mp4")

    OUT_H  = IR_H + CHART_H
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(out_video, fourcc, IR_FPS, (IR_W, OUT_H))

    temp_history = []
    SCALE = IR_W / ir_w

    print(f"[处理] 共 {n_frames} 帧...")
    for i in range(n_frames):
        frame   = data[i]
        time_s  = i / IR_FPS

        # ── 在锅内区域分割菜 ──────────────────────────────────────────────────
        wok_temps = frame[wok_mask]
        if len(wok_temps) > 0:
            # 菜 = 锅内温度低于 pct 百分位的区域（菜比锅底冷）
            t_thresh = np.percentile(wok_temps, args.pct)
            food_mask = wok_mask & (frame <= t_thresh)
            # 形态学去噪
            m_u8   = food_mask.astype(np.uint8) * 255
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
            m_u8   = cv2.morphologyEx(m_u8, cv2.MORPH_OPEN,  kernel)
            m_u8   = cv2.morphologyEx(m_u8, cv2.MORPH_CLOSE, kernel)
            food_mask = m_u8 > 127
        else:
            food_mask = np.zeros((ir_h, ir_w), dtype=bool)

        mask_ratio = food_mask.sum() / wok_mask.sum() * 100 if wok_mask.sum() > 0 else 0
        food_temps_vals = frame[food_mask]
        temp_mean = float(np.mean(food_temps_vals)) if len(food_temps_vals) >= MIN_FOOD_AREA else float("nan")
        if not np.isnan(temp_mean):
            temp_history.append((time_s, temp_mean))

        # ── 绘制 IR 热力图 ────────────────────────────────────────────────────
        t_min_f = float(np.min(frame))
        t_max_f = float(np.max(frame))
        norm    = ((frame - t_min_f) / max(t_max_f - t_min_f, 0.1) * 255).astype(np.uint8)
        ir_img  = cv2.applyColorMap(norm, cv2.COLORMAP_JET)
        ir_img  = cv2.resize(ir_img, (IR_W, IR_H), interpolation=cv2.INTER_NEAREST)

        # 叠加锅区域边界（白色虚线椭圆）
        cv2.ellipse(ir_img,
                    (int(wok_cfg["cx"] * SCALE), int(wok_cfg["cy"] * SCALE)),
                    (int(wok_cfg["rx"] * SCALE), int(wok_cfg["ry"] * SCALE)),
                    0, 0, 360, (255, 255, 255), 1)

        # 叠加菜 mask（半透明白色，轮廓亮红色，在任何背景上都清晰）
        food_resized = cv2.resize(food_mask.astype(np.uint8) * 255,
                                  (IR_W, IR_H), interpolation=cv2.INTER_NEAREST)
        food_bool = food_resized > 127
        # 白色半透明叠加（alpha=0.35，保留底图颜色同时突出 mask）
        ir_img[food_bool] = (ir_img[food_bool].astype(float) * 0.65 +
                              np.array([255, 255, 255]) * 0.35).astype(np.uint8)
        # 亮紫色轮廓线（2px，在 IR 热力图上最醒目）
        contours, _ = cv2.findContours(food_resized, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(ir_img, contours, -1, (255, 0, 200), 2)

        # 信息文字
        cv2.putText(ir_img, f"t={time_s:.1f}s  WokMask={mask_ratio:.1f}%",
                    (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(ir_img,
                    f"FoodAvg:{temp_mean:.1f}C  MAX:{t_max_f:.1f}C  MIN:{t_min_f:.1f}C",
                    (8, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 150), 1)
        cv2.putText(ir_img, f"Pct<={args.pct}% in wok region",
                    (8, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (200, 200, 200), 1)

        # 温度曲线
        chart    = draw_chart(temp_history, time_s, IR_W, CHART_H, CURVE_WIN_S)
        combined = np.vstack([ir_img, chart])
        writer.write(combined)

        if i % 200 == 0:
            print(f"  帧 {i}/{n_frames}  mask={mask_ratio:.1f}%  temp={temp_mean:.1f}°C", end="\r")

    writer.release()
    print(f"\n\n✅ 完成！")
    print(f"   输出目录: {out_dir}")
    print(f"   IR mask 视频: {out_video}")

    # 保存 CSV
    import csv
    csv_path = os.path.join(out_dir, "ir_mask_temp.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["frame", "time_s", "ir_mask_temp_mean"])
        for idx, (t, v) in enumerate(temp_history):
            w.writerow([idx, f"{t:.3f}", f"{v:.2f}"])
    print(f"   温度日志: {csv_path}")
    print(f"\n下一步：如需调整锅区域，运行:")
    print(f"  python tools/ir_mask_viz.py --setup")


if __name__ == "__main__":
    main()
