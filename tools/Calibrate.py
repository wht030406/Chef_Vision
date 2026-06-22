"""
Calibrate.py — RGB/IR 多帧标定工具（升级版）

改进：
  - 支持多帧标定（在多个时间点各标一次，合并所有点对）
  - RANSAC 自动剔除标注偏差大的点对
  - 重投影误差报告（每对点的误差，帮助发现标注错误）
  - 验证图：RGB warp 到 IR 坐标系叠加显示

操作说明：
  - 先在左图（RGB）上点击一个角点
  - 再在右图（IR）上
  - 重复 6~8 次（至少 4 对）
  - 按 N 切换到下一帧继续标注（多帧模式）
  - 按 C 计算并保存（所有帧的点合并计算）
  - 按 Z 撤销上一个点
  - 按 Q 退出

选点建议：
  - 锅的左/右/上/下边缘（4 个方向）
  - 机器框架角点
  - 搅拌轴中心（如果清晰可见）
  - 避免选菜或温度变化区域

用法：
  python tools/Calibrate.py
  python tools/Calibrate.py --video test_data/test1/rgb_20260529_112414.mp4
                             --npy   test_data/test1/temp_20260529_112414.npy
"""

import numpy as np
import cv2
import os
import argparse

# ── 路径基准 ─────────────────────────────────────────────────────────────────
_HERE    = os.path.dirname(os.path.abspath(__file__))
RGB_FILE = os.path.join(_HERE, "..", "test_data", "test1", "rgb_20260529_112414.mp4")
NPY_FILE = os.path.join(_HERE, "..", "test_data", "test1", "temp_20260529_112414.npy")
OUTPUT_H = os.path.join(_HERE, "..", "data", "homography.npy")

# 多帧标定：在这些帧号上各标一次（选特征清晰的帧）
# 注意：会自动过滤超出视频总帧数的帧号，短视频也能正常使用
# 锅视频：500/1000/1500 = 约 20s/40s/60s（锅已加热，IR 特征清晰）
# 短视频：10/50/100 备用
CALIB_FRAMES = [500, 1000, 1500, 600, 800, 1200]   # 3个主帧 + 3个备用帧（均在锅内）

DISPLAY_H = 480   # 显示高度（像素）


# ── 全局状态 ─────────────────────────────────────────────────────────────────
# 每帧的点对独立存储，最后合并
all_rgb_points = []   # list of (x, y)，所有帧的 RGB 点
all_ir_points  = []   # list of (x, y)，所有帧的 IR 点
frame_labels   = []   # list of int，每对点来自哪一帧（用于报告）

cur_rgb_points = []   # 当前帧未配对的 RGB 点
cur_ir_points  = []   # 当前帧已配对的 IR 点
click_state    = "rgb"

rgb_display = None
ir_display  = None
rgb_scale   = 1.0
ir_scale    = 1.0
rgb_orig_size = (1600, 1200)
ir_orig_size  = (256, 192)

frame_idx_list = []   # 实际使用的帧号列表
cur_frame_pos  = 0    # 当前在 frame_idx_list 中的位置
cur_frame_idx  = 0    # 当前帧号


def load_frame(rgb_file, npy_file, frame_idx):
    """
    加载指定 RGB 帧号对应的 RGB 图和 IR 热力图。
    IR 帧号根据帧率比例精确对齐，确保两张图是同一时间点。
    """
    global rgb_orig_size, ir_orig_size

    temp_data = np.load(npy_file)
    rgb_total = get_rgb_total(rgb_file)
    # 精确对齐：IR帧号 = RGB帧号 × (IR总帧数 / RGB总帧数)
    ir_fps_ratio = temp_data.shape[0] / max(1, rgb_total)
    ir_idx = min(int(round(frame_idx * ir_fps_ratio)), temp_data.shape[0] - 1)
    temp_frame = temp_data[ir_idx]
    ir_orig_size = (temp_frame.shape[1], temp_frame.shape[0])

    # IR 渲染：纯灰度 + CLAHE 对比度增强，最清晰看特征边缘
    t_min, t_max = temp_frame.min(), temp_frame.max()
    temp_norm = ((temp_frame - t_min) / max(t_max - t_min, 0.1) * 255).astype(np.uint8)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
    temp_enhanced = clahe.apply(temp_norm)
    ir_img = cv2.cvtColor(temp_enhanced, cv2.COLOR_GRAY2BGR)

    cap = cv2.VideoCapture(rgb_file)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ret, rgb_img = cap.read()
    cap.release()
    if not ret or rgb_img is None:
        raise RuntimeError(f"无法读取 RGB 帧 {frame_idx}")
    rgb_orig_size = (rgb_img.shape[1], rgb_img.shape[0])
    print(f"  [帧对齐] RGB帧{frame_idx} ({frame_idx/max(1,get_rgb_fps(rgb_file)):.1f}s)"
          f" → IR帧{ir_idx} (比例={ir_fps_ratio:.4f})")
    return rgb_img, ir_img, ir_idx


def get_rgb_fps(rgb_file):
    cap = cv2.VideoCapture(rgb_file)
    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.release()
    return fps if fps > 0 else 25.0


def get_rgb_total(rgb_file):
    cap = cv2.VideoCapture(rgb_file)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return n


def make_display(rgb_img, ir_img):
    global rgb_display, ir_display, rgb_scale, ir_scale
    rgb_h, rgb_w = rgb_img.shape[:2]
    rgb_scale = DISPLAY_H / rgb_h
    rgb_display = cv2.resize(rgb_img, (int(rgb_w * rgb_scale), DISPLAY_H))
    ir_h, ir_w = ir_img.shape[:2]
    ir_scale = DISPLAY_H / ir_h
    ir_display = cv2.resize(ir_img, (int(ir_w * ir_scale), DISPLAY_H),
                            interpolation=cv2.INTER_NEAREST)


def draw_canvas():
    rgb_vis = rgb_display.copy()
    ir_vis  = ir_display.copy()
    colors = [(0,255,0),(0,200,255),(255,100,0),(200,0,200),(0,255,255),
              (255,255,0),(255,0,100),(100,255,100),(255,128,0),(0,128,255)]

    # 画已配对的点（当前帧）
    for i, (p_rgb, p_ir) in enumerate(zip(cur_rgb_points, cur_ir_points)):
        c = colors[i % len(colors)]
        dp_rgb = (int(p_rgb[0] * rgb_scale), int(p_rgb[1] * rgb_scale))
        dp_ir  = (int(p_ir[0]  * ir_scale),  int(p_ir[1]  * ir_scale))
        cv2.circle(rgb_vis, dp_rgb, 6, c, -1)
        cv2.putText(rgb_vis, str(i+1), (dp_rgb[0]+8, dp_rgb[1]-5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, c, 1)
        cv2.circle(ir_vis, dp_ir, 6, c, -1)
        cv2.putText(ir_vis, str(i+1), (dp_ir[0]+8, dp_ir[1]-5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, c, 1)

    # 未配对的 RGB 点
    if len(cur_rgb_points) > len(cur_ir_points):
        p = cur_rgb_points[-1]
        dp = (int(p[0] * rgb_scale), int(p[1] * rgb_scale))
        cv2.circle(rgb_vis, dp, 6, (255,255,255), -1)

    # 状态信息
    total_pairs = len(all_rgb_points) + len(cur_ir_points)
    frame_info  = f"Frame {cur_frame_idx} ({cur_frame_pos+1}/{len(frame_idx_list)})"
    cv2.putText(rgb_vis, frame_info, (8, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0,200,255), 2)
    cv2.putText(rgb_vis, f"Total pairs: {total_pairs}",
                (8, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200,200,200), 1)

    if click_state == "rgb":
        cv2.putText(rgb_vis, f"Click RGB pt {len(cur_rgb_points)+1}",
                    (8, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 2)
    else:
        cv2.putText(ir_vis, f"Click IR pt {len(cur_ir_points)+1}",
                    (8, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,255), 2)

    # 底部按钮区域（可点击，鼠标悬停在窗口内时有效）
    btn_y = rgb_vis.shape[0] - 40
    # [NEXT] 按钮
    cv2.rectangle(rgb_vis, (8, btn_y), (100, btn_y+30), (0,150,200), -1)
    cv2.putText(rgb_vis, "N: NEXT", (12, btn_y+20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1)
    # [CALC] 按钮
    cv2.rectangle(rgb_vis, (108, btn_y), (220, btn_y+30), (0,180,0), -1)
    cv2.putText(rgb_vis, "C: CALC", (112, btn_y+20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1)
    # [UNDO] 按钮
    cv2.rectangle(rgb_vis, (228, btn_y), (310, btn_y+30), (180,80,0), -1)
    cv2.putText(rgb_vis, "Z: UNDO", (232, btn_y+20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1)
    cv2.putText(rgb_vis, "RGB (click buttons above or press key)", (8, btn_y-5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.35, (180,180,180), 1)
    cv2.putText(ir_vis, "IR Grayscale", (8, ir_vis.shape[0]-10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (180,180,180), 1)

    gap = np.zeros((DISPLAY_H, 10, 3), dtype=np.uint8)
    return np.hstack([rgb_vis, gap, ir_vis])


# 按钮触发标志（在 on_mouse 里设置，主循环里处理）
btn_action = [None]   # 'n', 'c', 'z'


def on_mouse(event, x, y, flags, param):
    global click_state
    if event != cv2.EVENT_LBUTTONDOWN:
        return
    rgb_w_disp = rgb_display.shape[1]

    # 检查是否点击了底部按钮区域（只在 RGB 图一侧）
    if x < rgb_w_disp:
        btn_y = DISPLAY_H - 40
        if btn_y <= y <= btn_y + 30:
            if 8 <= x <= 100:
                btn_action[0] = 'n'
                return
            elif 108 <= x <= 220:
                btn_action[0] = 'c'
                return
            elif 228 <= x <= 310:
                btn_action[0] = 'z'
                return
        # 普通标点（不在按钮区域）
        if click_state == "rgb" and y < btn_y - 5:
            cur_rgb_points.append((x / rgb_scale, y / rgb_scale))
            click_state = "ir"
            print(f"  RGB({x/rgb_scale:.1f},{y/rgb_scale:.1f}) -> 请点 IR")
    else:
        ir_x = x - rgb_w_disp - 10
        if ir_x >= 0 and click_state == "ir":
            cur_ir_points.append((ir_x / ir_scale, y / ir_scale))
            click_state = "rgb"
            n = len(cur_ir_points)
            print(f"  IR({ir_x/ir_scale:.1f},{y/ir_scale:.1f})  第{n}对完成")


def commit_current_frame():
    """把当前帧的点对提交到全局列表"""
    n = min(len(cur_rgb_points), len(cur_ir_points))
    for i in range(n):
        all_rgb_points.append(cur_rgb_points[i])
        all_ir_points.append(cur_ir_points[i])
        frame_labels.append(cur_frame_idx)
    print(f"  [提交] 帧{cur_frame_idx}: {n}对点  累计: {len(all_rgb_points)}对")
    cur_rgb_points.clear()
    cur_ir_points.clear()


def compute_and_save(rgb_file, npy_file):
    """合并所有帧的点对，计算 Homography 并保存"""
    n = len(all_rgb_points)
    if n < 4:
        print(f"[错误] 至少需要 4 对点，当前 {n} 对")
        return False

    src = np.array(all_rgb_points, dtype=np.float32)
    dst = np.array(all_ir_points,  dtype=np.float32)

    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
    if H is None:
        print("[错误] 无法计算 Homography")
        return False

    inliers = int(np.sum(mask))
    print(f"\n[OK] Homography 计算成功")
    print(f"     总点对: {n}  RANSAC内点: {inliers}  外点(剔除): {n-inliers}")

    # 重投影误差报告
    print(f"\n[重投影误差] (越小越好，>3px 的点建议重标)")
    src_h = np.hstack([src, np.ones((n,1))]).T
    proj  = H @ src_h
    proj  = proj[:2] / proj[2]
    errors = np.sqrt(np.sum((proj.T - dst)**2, axis=1))
    for i, (e, m, f) in enumerate(zip(errors, mask.ravel(), frame_labels)):
        status = "OK" if m else "OUTLIER"
        print(f"  点{i+1:2d} [帧{f:4d}]: {e:.2f}px  {status}")
    print(f"  平均误差(内点): {np.mean(errors[mask.ravel()==1]):.2f}px")
    print(f"  最大误差(内点): {np.max(errors[mask.ravel()==1]):.2f}px")

    np.save(OUTPUT_H, H)
    print(f"\n[OK] 已保存: {OUTPUT_H}")

    # 生成验证图
    _make_verify(rgb_file, npy_file, H, CALIB_FRAMES[0])
    return True


def _make_verify(rgb_file, npy_file, H, frame_idx):
    """生成 RGB warp 到 IR 坐标系的叠加验证图"""
    try:
        temp_data = np.load(npy_file)
        ir_fps_ratio = temp_data.shape[0] / max(1, get_rgb_total(rgb_file))
        ir_idx = min(int(frame_idx * ir_fps_ratio), temp_data.shape[0]-1)
        temp_frame = temp_data[ir_idx]
        ir_h, ir_w = temp_frame.shape
        t_min, t_max = temp_frame.min(), temp_frame.max()
        temp_norm = ((temp_frame - t_min) / max(t_max-t_min, 0.1) * 255).astype(np.uint8)
        ir_color = cv2.applyColorMap(temp_norm, cv2.COLORMAP_JET)

        cap = cv2.VideoCapture(rgb_file)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, rgb_full = cap.read()
        cap.release()
        if not ret:
            return

        warped  = cv2.warpPerspective(rgb_full, H, (ir_w, ir_h))
        overlay = cv2.addWeighted(warped, 0.5, ir_color, 0.5, 0)
        big     = cv2.resize(overlay, (ir_w*4, ir_h*4), interpolation=cv2.INTER_NEAREST)
        out_dir = os.path.join(_HERE, "..", "output")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "calibration_verify.png")
        cv2.imwrite(out_path, big)
        print(f"[OK] 验证图已保存: {out_path}")
        print("     RGB 和 IR 内容应基本重合，锅边缘应对齐")
    except Exception as e:
        print(f"[警告] 验证图生成失败: {e}")


def main():
    global click_state, cur_frame_pos, cur_frame_idx

    parser = argparse.ArgumentParser()
    parser.add_argument("--video", default=RGB_FILE)
    parser.add_argument("--npy",   default=NPY_FILE)
    args = parser.parse_args()

    rgb_file = args.video
    npy_file = args.npy

    if not os.path.exists(rgb_file):
        print(f"[错误] 找不到: {rgb_file}")
        return
    if not os.path.exists(npy_file):
        print(f"[错误] 找不到: {npy_file}")
        return

    # 过滤超出范围的帧号
    total = get_rgb_total(rgb_file)
    frame_idx_list.extend([f for f in CALIB_FRAMES if f < total])
    if not frame_idx_list:
        frame_idx_list.append(0)

    print("=" * 60)
    print("  Chef Vision - RGB/IR 多帧标定工具")
    print("=" * 60)
    print(f"  RGB: {rgb_file}")
    print(f"  NPY: {npy_file}")
    print(f"  标定帧: {frame_idx_list}")
    print(f"  输出:   {OUTPUT_H}")
    print("-" * 60)
    print("操作：先点 RGB 角点，再点 IR 同一位置，重复 6~8 次")
    print("快捷键：N=下一帧  C=计算保存  Z=撤销  Q=退出")
    print("=" * 60)

    cur_frame_pos = 0
    cur_frame_idx = frame_idx_list[0]
    rgb_img, ir_img, ir_idx = load_frame(rgb_file, npy_file, cur_frame_idx)
    make_display(rgb_img, ir_img)
    print(f"\n[帧 {cur_frame_pos+1}/{len(frame_idx_list)}] RGB帧{cur_frame_idx} / IR帧{ir_idx}")

    win = "RGB(left) | IR(right)  [N=Next  C=Calc  Z=Undo  Q=Quit]"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(win, on_mouse)

    while True:
        cv2.imshow(win, draw_canvas())
        key = cv2.waitKey(20) & 0xFF

        # 处理鼠标点击按钮
        action = btn_action[0]
        if action:
            btn_action[0] = None
            key = ord(action)   # 复用键盘处理逻辑

        if key in (ord('q'), 27):
            break

        elif key == ord('n'):
            # 提交当前帧，切换到下一帧
            commit_current_frame()
            cur_frame_pos = (cur_frame_pos + 1) % len(frame_idx_list)
            cur_frame_idx = frame_idx_list[cur_frame_pos]
            click_state   = "rgb"
            rgb_img, ir_img, ir_idx = load_frame(rgb_file, npy_file, cur_frame_idx)
            make_display(rgb_img, ir_img)
            print(f"\n[帧 {cur_frame_pos+1}/{len(frame_idx_list)}] RGB帧{cur_frame_idx} / IR帧{ir_idx}")

        elif key == ord('c'):
            commit_current_frame()
            if compute_and_save(rgb_file, npy_file):
                print("\n标定完成！按 Q 退出")

        elif key == ord('z'):
            if click_state == "ir" and len(cur_rgb_points) > len(cur_ir_points):
                p = cur_rgb_points.pop()
                click_state = "rgb"
                print(f"  [撤销] RGB点 ({p[0]:.1f},{p[1]:.1f})")
            elif click_state == "rgb" and cur_ir_points:
                cur_ir_points.pop()
                cur_rgb_points.pop()
                print(f"  [撤销] 第{len(cur_ir_points)+1}对")

    cv2.destroyAllWindows()
    print("退出标定工具")


if __name__ == "__main__":
    main()
