"""
RGB / IR 像素对齐标定工具
功能：
  1. 从 RGB 视频和温度矩阵各取一帧，并排显示
  2. 鼠标左键分别在两图上点击同一物体的角点（4~8 对）
  3. 自动计算 Homography 矩阵 H（RGB坐标 → IR坐标）
  4. 保存 homography.npy，后续所有对齐自动加载使用

操作说明：
  - 先在左图（RGB）上点击一个角点
  - 再在右图（IR）上点击同一个角点
  - 重复 4~8 次（至少 4 对）
  - 按 C 键计算并保存
  - 按 Z 键撤销上一个点
  - 按 Q 键退出

使用方法：
  python Calibrate.py
"""

import numpy as np
import cv2
import os

# ============================================================
# 配置
# ============================================================
_HERE    = os.path.dirname(os.path.abspath(__file__))
RGB_FILE = os.path.join(_HERE, "..", "data",   "rgb_20260427_114305.mp4")
NPY_FILE = os.path.join(_HERE, "..", "data",   "temp_20260427_114341.npy")
OUTPUT_H = os.path.join(_HERE, "..", "data",   "homography.npy")

# 取第几帧用于标定（选一个特征清晰的帧）
FRAME_IDX = 0

# 显示窗口缩放比例（IR 原始 256×192，RGB 640×480，统一显示高度）
DISPLAY_H = 480  # 显示高度（像素）

# ============================================================
# 全局状态
# ============================================================
rgb_points = []   # RGB 图上点击的点列表（原始像素坐标）
ir_points  = []   # IR 图上点击的点列表（原始像素坐标）
click_state = "rgb"  # 当前等待点击的图：rgb 或 ir

rgb_display = None  # 显示用的 RGB 图（缩放后）
ir_display  = None  # 显示用的 IR 热力图（缩放后）
rgb_scale   = 1.0   # RGB 显示缩放比
ir_scale    = 1.0   # IR 显示缩放比

rgb_orig_size = (640, 480)   # RGB 原始分辨率 (w, h)
ir_orig_size  = (256, 192)   # IR 原始分辨率 (w, h)


def load_frames():
    """加载 RGB 帧和 IR 热力图"""
    global rgb_orig_size, ir_orig_size

    # 加载 IR 帧
    temp_data = np.load(NPY_FILE)
    fidx = min(FRAME_IDX, temp_data.shape[0] - 1)
    temp_frame = temp_data[fidx]  # (192, 256)
    ir_orig_size = (temp_frame.shape[1], temp_frame.shape[0])  # (w, h)

    # IR 转热力图（jet colormap）
    t_min, t_max = temp_frame.min(), temp_frame.max()
    temp_norm = ((temp_frame - t_min) / max(t_max - t_min, 0.1) * 255).astype(np.uint8)
    ir_img = cv2.applyColorMap(temp_norm, cv2.COLORMAP_JET)

    # 加载 RGB 帧
    cap = cv2.VideoCapture(RGB_FILE)
    rgb_img = None
    for i in range(fidx + 1):
        ret, frame = cap.read()
        if ret:
            rgb_img = frame
    cap.release()

    if rgb_img is None:
        raise RuntimeError("无法读取 RGB 帧")
    rgb_orig_size = (rgb_img.shape[1], rgb_img.shape[0])  # (w, h)

    return rgb_img, ir_img


def make_display_images(rgb_img, ir_img):
    """将两张图缩放到统一高度，方便并排显示"""
    global rgb_display, ir_display, rgb_scale, ir_scale

    # RGB 缩放
    rgb_h, rgb_w = rgb_img.shape[:2]
    rgb_scale = DISPLAY_H / rgb_h
    rgb_display = cv2.resize(rgb_img, (int(rgb_w * rgb_scale), DISPLAY_H))

    # IR 缩放
    ir_h, ir_w = ir_img.shape[:2]
    ir_scale = DISPLAY_H / ir_h
    ir_display = cv2.resize(ir_img, (int(ir_w * ir_scale), DISPLAY_H),
                            interpolation=cv2.INTER_NEAREST)


def draw_canvas():
    """绘制当前标定状态的画布"""
    rgb_vis = rgb_display.copy()
    ir_vis  = ir_display.copy()

    # 画已标注的点
    colors = [(0,255,0),(0,200,255),(255,100,0),(200,0,200),(0,255,255),
              (255,255,0),(255,0,100),(100,255,100)]

    for i, (p_rgb, p_ir) in enumerate(zip(rgb_points, ir_points)):
        c = colors[i % len(colors)]
        # RGB 图上的点（缩放到显示坐标）
        dp_rgb = (int(p_rgb[0] * rgb_scale), int(p_rgb[1] * rgb_scale))
        cv2.circle(rgb_vis, dp_rgb, 6, c, -1)
        cv2.putText(rgb_vis, str(i+1), (dp_rgb[0]+8, dp_rgb[1]-5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, c, 1)

        # IR 图上的点（缩放到显示坐标）
        dp_ir = (int(p_ir[0] * ir_scale), int(p_ir[1] * ir_scale))
        cv2.circle(ir_vis, dp_ir, 6, c, -1)
        cv2.putText(ir_vis, str(i+1), (dp_ir[0]+8, dp_ir[1]-5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, c, 1)

    # 画未配对的 RGB 点（等待 IR 点）
    if len(rgb_points) > len(ir_points):
        p = rgb_points[-1]
        dp = (int(p[0] * rgb_scale), int(p[1] * rgb_scale))
        cv2.circle(rgb_vis, dp, 6, (255,255,255), -1)
        cv2.putText(rgb_vis, str(len(rgb_points)), (dp[0]+8, dp[1]-5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1)

    # 状态文字
    n_pairs = min(len(rgb_points), len(ir_points))
    if click_state == "rgb":
        tip = f"[{n_pairs} pairs] Click RGB point ({len(rgb_points)+1})"
        cv2.putText(rgb_vis, tip, (8, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0,255,0), 2)
    else:
        tip = f"[{n_pairs} pairs] Click IR point ({len(ir_points)+1})"
        cv2.putText(ir_vis, tip, (8, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0,255,255), 2)

    # 快捷键提示
    hint = "C=Calc&Save  Z=Undo  Q=Quit"
    cv2.putText(rgb_vis, hint, (8, rgb_vis.shape[0]-10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200,200,200), 1)

    # 标题
    cv2.putText(rgb_vis, "RGB (left-click to mark)", (8, rgb_vis.shape[0]-30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180,180,180), 1)
    cv2.putText(ir_vis,  "IR Heatmap (left-click to mark)", (8, ir_vis.shape[0]-30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180,180,180), 1)

    # 拼接
    gap = np.zeros((DISPLAY_H, 10, 3), dtype=np.uint8)
    canvas = np.hstack([rgb_vis, gap, ir_vis])
    return canvas


def on_mouse(event, x, y, flags, param):
    """鼠标回调"""
    global click_state
    if event != cv2.EVENT_LBUTTONDOWN:
        return

    rgb_w_disp = rgb_display.shape[1]

    if x < rgb_w_disp:
        # 点击在 RGB 区域
        if click_state == "rgb":
            orig_x = x / rgb_scale
            orig_y = y / rgb_scale
            rgb_points.append((orig_x, orig_y))
            click_state = "ir"
            print(f"  RGB 点 {len(rgb_points)}: ({orig_x:.1f}, {orig_y:.1f})  → 请在 IR 图点击对应位置")
    else:
        # 点击在 IR 区域（减去 gap 宽度）
        ir_x = x - rgb_w_disp - 10
        if ir_x < 0:
            return
        if click_state == "ir":
            orig_x = ir_x / ir_scale
            orig_y = y / ir_scale
            ir_points.append((orig_x, orig_y))
            click_state = "rgb"
            n = min(len(rgb_points), len(ir_points))
            print(f"  IR  点 {len(ir_points)}: ({orig_x:.1f}, {orig_y:.1f})  ✓ 第 {n} 对完成")


def compute_and_save():
    """计算 Homography 并保存"""
    n = min(len(rgb_points), len(ir_points))
    if n < 4:
        print(f"[错误] 至少需要 4 对点，当前只有 {n} 对，请继续标注")
        return False

    src = np.array(rgb_points[:n], dtype=np.float32)
    dst = np.array(ir_points[:n],  dtype=np.float32)

    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    if H is None:
        print("[错误] 无法计算 Homography，请检查点是否正确")
        return False

    inliers = np.sum(mask)
    print(f"\n[OK] Homography 计算成功")
    print(f"     使用 {n} 对点，其中 {inliers} 对为内点（RANSAC）")
    print(f"     H 矩阵:\n{H}")

    np.save(OUTPUT_H, H)
    print(f"[OK] 已保存: {OUTPUT_H}")

    # 验证：把 RGB 图 warp 到 IR 坐标系，叠加显示
    ir_h, ir_w = ir_orig_size[1], ir_orig_size[0]
    rgb_full = None
    cap = cv2.VideoCapture(RGB_FILE)
    for i in range(FRAME_IDX + 1):
        ret, f = cap.read()
        if ret:
            rgb_full = f
    cap.release()

    if rgb_full is not None:
        warped = cv2.warpPerspective(rgb_full, H, (ir_w, ir_h))
        temp_data = np.load(NPY_FILE)
        temp_frame = temp_data[min(FRAME_IDX, temp_data.shape[0]-1)]
        t_min, t_max = temp_frame.min(), temp_frame.max()
        temp_norm = ((temp_frame - t_min) / max(t_max - t_min, 0.1) * 255).astype(np.uint8)
        ir_color = cv2.applyColorMap(temp_norm, cv2.COLORMAP_JET)

        # 50% 透明叠加
        overlay = cv2.addWeighted(warped, 0.5, ir_color, 0.5, 0)
        overlay_large = cv2.resize(overlay, (ir_w*3, ir_h*3), interpolation=cv2.INTER_NEAREST)
        _out_verify = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output", "calibration_verify.png")
        cv2.imwrite(_out_verify, overlay_large)
        print(f"[OK] 对齐验证图已保存: {_out_verify}")
        print("     查看该图：RGB和IR内容应该基本重合，边缘应该对齐")

    return True


def main():
    global click_state

    print("=" * 55)
    print("  Chef Vision - RGB/IR 标定工具")
    print("=" * 55)
    print(f"  RGB 文件: {RGB_FILE}")
    print(f"  NPY 文件: {NPY_FILE}")
    print(f"  输出文件: {OUTPUT_H}")
    print("-" * 55)
    print("操作步骤：")
    print("  1. 先点击左图（RGB）中某个清晰角点")
    print("  2. 再点击右图（IR）中同一位置")
    print("  3. 重复 4~8 次")
    print("  4. 按 C 计算并保存")
    print("  快捷键：C=计算保存  Z=撤销  Q=退出")
    print("=" * 55)

    # 加载图像
    rgb_img, ir_img = load_frames()
    make_display_images(rgb_img, ir_img)

    # 创建窗口
    win = "RGB(left) | IR(right)  [C=Calc  Z=Undo  Q=Quit]"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(win, on_mouse)

    while True:
        canvas = draw_canvas()
        cv2.imshow(win, canvas)
        key = cv2.waitKey(20) & 0xFF

        if key == ord('q') or key == 27:
            break
        elif key == ord('c'):
            if compute_and_save():
                print("\n标定完成！按 Q 退出")
        elif key == ord('z'):
            # 撤销
            if click_state == "ir" and len(rgb_points) > len(ir_points):
                removed = rgb_points.pop()
                click_state = "rgb"
                print(f"  [撤销] RGB 点 ({removed[0]:.1f}, {removed[1]:.1f})")
            elif click_state == "rgb" and len(ir_points) > 0:
                removed_ir  = ir_points.pop()
                removed_rgb = rgb_points.pop()
                print(f"  [撤销] 第 {len(rgb_points)+1} 对点")

    cv2.destroyAllWindows()
    print("退出标定工具")


if __name__ == "__main__":
    if not os.path.exists(RGB_FILE):
        print(f"[错误] 找不到 RGB 文件: {RGB_FILE}")
        print("请修改脚本顶部的 RGB_FILE 变量")
    elif not os.path.exists(NPY_FILE):
        print(f"[错误] 找不到 NPY 文件: {NPY_FILE}")
        print("请修改脚本顶部的 NPY_FILE 变量")
    else:
        main()
