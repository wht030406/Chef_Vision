"""
auto_tracking_utils.py - 自动追踪辅助工具

包含：
1. TrackingState - 追踪状态管理
2. check_mask_quality - Mask质量监控
3. auto_recover_tracking - 自动恢复
4. detect_new_food_combined - RGB+IR联合检测新食材
"""

import cv2
import numpy as np


# ══════════════════════════════════════════════════════════════════════════════
# 1. TrackingState - 追踪状态管理类
# ══════════════════════════════════════════════════════════════════════════════

class TrackingState:
    """
    追踪状态管理器
    
    功能：
    - 维护mask质量历史（滑动窗口）
    - 保存最后有效的mask（用于恢复）
    - 保存IR温度历史（用于检测骤降）
    - 追踪目标列表管理
    """
    
    def __init__(self, window_size=3):
        """
        参数：
            window_size: 滑动窗口大小（保留最近N批的mask质量）
        """
        # Mask质量历史：[(batch_idx, mask_ratio), ...]
        self.mask_history = []
        self.window_size = window_size
        
        # 最后有效的mask（用于恢复）
        self.last_valid_mask = None
        self.last_valid_batch = -1
        self.last_valid_ratio = 0.0
        
        # IR温度历史（用于检测骤降）
        self.ir_prev_frame = None
        self.rgb_prev_frame = None
        
        # 追踪目标列表（支持多个食材）
        self.tracked_objects = []  # [{"obj_id": 1, "label": "肉", "added_at_batch": 0}, ...]
        
        # 统计信息
        self.total_batches = 0
        self.recovery_count = 0
        self.new_food_detected_count = 0
    
    def update_mask_quality(self, batch_idx, mask_ratio, mask):
        """
        更新mask质量历史
        
        参数：
            batch_idx: 批次索引
            mask_ratio: mask占比（百分比）
            mask: mask数组（H, W bool）
        """
        self.mask_history.append((batch_idx, mask_ratio))
        
        # 维护滑动窗口
        if len(self.mask_history) > self.window_size:
            self.mask_history.pop(0)
        
        # 更新有效mask（阈值：1%）
        if mask_ratio > 1.0:
            self.last_valid_mask = mask.copy()
            self.last_valid_batch = batch_idx
            self.last_valid_ratio = mask_ratio
        
        self.total_batches = batch_idx + 1
    
    def is_tracking_lost(self, threshold=1.0, consecutive=2):
        """
        判断追踪是否丢失
        
        参数：
            threshold: mask_ratio阈值（百分比）
            consecutive: 连续N批低于阈值才判定为丢失
        
        返回：
            bool: True表示追踪丢失
        """
        if len(self.mask_history) < consecutive:
            return False
        
        # 检查最近N批是否都低于阈值
        recent = [ratio for _, ratio in self.mask_history[-consecutive:]]
        return all(r < threshold for r in recent)
    
    def get_status_summary(self):
        """获取状态摘要（用于日志）"""
        if not self.mask_history:
            return "未开始追踪"
        
        latest_ratio = self.mask_history[-1][1]
        return (f"批次{self.total_batches} | "
                f"当前mask={latest_ratio:.1f}% | "
                f"最后有效={self.last_valid_ratio:.1f}%(批次{self.last_valid_batch}) | "
                f"恢复次数={self.recovery_count} | "
                f"新食材检测={self.new_food_detected_count}")


# ══════════════════════════════════════════════════════════════════════════════
# 2. check_mask_quality - Mask质量监控
# ══════════════════════════════════════════════════════════════════════════════

def check_mask_quality(state, mask, batch_idx):
    """
    检查mask质量并更新状态
    
    参数：
        state: TrackingState实例
        mask: 当前批次末帧的mask（H, W bool）
        batch_idx: 批次索引
    
    返回：
        str: "OK" - 正常
             "WARN" - 质量下降，警告
             "LOST" - 追踪丢失，需要恢复
    """
    mask_ratio = mask.sum() / mask.size * 100
    state.update_mask_quality(batch_idx, mask_ratio, mask)
    
    # 判断追踪状态
    if state.is_tracking_lost(threshold=1.0, consecutive=2):
        return "LOST"
    elif mask_ratio < 0.5:  # 低于0.5%警告
        return "WARN"
    else:
        return "OK"


# ══════════════════════════════════════════════════════════════════════════════
# 3. auto_recover_tracking - 自动恢复
# ══════════════════════════════════════════════════════════════════════════════

def auto_recover_tracking(state, num_points=None):
    """
    从最后有效mask自动生成前景点
    
    策略：
    1. 形态学腐蚀（避免采样到边缘噪点）
    2. 均匀采样N个点（面积自适应）
    3. 不添加背景点（SAM2 memory已有背景记忆）
    
    参数：
        state: TrackingState实例
        num_points: 前景点数量（None=自动计算）
    
    返回：
        fg_points: [[x, y], ...] 前景点列表
        bg_points: [] 背景点列表（空）
        success: bool 是否成功生成
    """
    if state.last_valid_mask is None:
        print("[自动恢复] 失败：无有效mask历史")
        return [], [], False
    
    mask = state.last_valid_mask
    area = mask.sum()
    
    if area == 0:
        print("[自动恢复] 失败：最后有效mask为空")
        return [], [], False
    
    # 形态学腐蚀（kernel大小根据mask面积自适应）
    kernel_size = max(3, min(9, int(np.sqrt(area) / 50)))
    kernel = np.ones((kernel_size, kernel_size), np.uint8)
    eroded = cv2.erode(mask.astype(np.uint8), kernel, iterations=2)
    
    # 提取坐标
    ys, xs = np.where(eroded)
    if len(xs) == 0:
        print("[自动恢复] 腐蚀后mask为空，使用原始mask")
        ys, xs = np.where(mask)
    
    if len(xs) == 0:
        print("[自动恢复] 失败：无有效像素")
        return [], [], False
    
    # 面积自适应采样点数
    if num_points is None:
        num_points = max(10, min(50, int(area / 500)))
    
    # 均匀采样（避免聚集）
    num_points = min(num_points, len(xs))
    indices = np.random.choice(len(xs), num_points, replace=False)
    fg_points = [[int(xs[i]), int(ys[i])] for i in indices]
    
    print(f"[自动恢复] 从批次{state.last_valid_batch}的mask(面积={area}px, "
          f"ratio={state.last_valid_ratio:.1f}%)生成{len(fg_points)}个前景点")
    
    state.recovery_count += 1
    return fg_points, [], True


# ══════════════════════════════════════════════════════════════════════════════
# 4. detect_new_food_combined - RGB+IR联合检测新食材
# ══════════════════════════════════════════════════════════════════════════════

def detect_new_food_combined(rgb_curr, rgb_prev, ir_curr, ir_prev, homography, 
                             rgb_diff_threshold=30, ir_temp_diff_min=3.0,
                             min_area=500, aspect_ratio_max=3.0):
    """
    联合检测：RGB帧差 + IR温度验证
    
    策略：
    1. RGB帧差检测运动区域（主要检测）
    2. 形态学过滤搅拌爪（细长条形）
    3. IR温度验证该区域是否为冷食材（辅助验证）
    
    参数：
        rgb_curr: 当前RGB帧（H, W, 3 BGR）
        rgb_prev: 前一RGB帧（H, W, 3 BGR）
        ir_curr: 当前IR温度帧（H_ir, W_ir float32）
        ir_prev: 前一IR温度帧（H_ir, W_ir float32）
        homography: RGB→IR单应矩阵（3, 3）
        rgb_diff_threshold: RGB帧差阈值
        ir_temp_diff_min: IR温差阈值（新区域比周围冷N度以上）
        min_area: 最小区域面积（像素）
        aspect_ratio_max: 最大长宽比（过滤搅拌爪）
    
    返回：
        detected: bool - 是否检测到新食材
        fg_points: [[x, y], ...] - RGB坐标系的前景点
        label: str - 自动标签
    """
    if rgb_prev is None or ir_prev is None:
        return False, [], ""
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 步骤1：RGB帧差检测（主要检测）
    # ═══════════════════════════════════════════════════════════════════════════
    
    # 转灰度图
    gray_curr = cv2.cvtColor(rgb_curr, cv2.COLOR_BGR2GRAY)
    gray_prev = cv2.cvtColor(rgb_prev, cv2.COLOR_BGR2GRAY)
    
    # 帧差
    diff = cv2.absdiff(gray_curr, gray_prev)
    
    # 阈值分割（运动区域）
    _, motion_mask = cv2.threshold(diff, rgb_diff_threshold, 255, cv2.THRESH_BINARY)
    
    # 形态学处理：去噪 + 填充
    kernel = np.ones((5, 5), np.uint8)
    motion_mask = cv2.morphologyEx(motion_mask, cv2.MORPH_OPEN, kernel)
    motion_mask = cv2.morphologyEx(motion_mask, cv2.MORPH_CLOSE, kernel)
    
    # 连通域分析
    contours, _ = cv2.findContours(motion_mask, cv2.RETR_EXTERNAL, 
                                    cv2.CHAIN_APPROX_SIMPLE)
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 步骤2：过滤搅拌爪（形态学特征）
    # ═══════════════════════════════════════════════════════════════════════════
    
    candidate_regions = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area:  # 太小，噪点
            continue
        
        # 长宽比判断
        x, y, w, h = cv2.boundingRect(cnt)
        aspect_ratio = max(w, h) / (min(w, h) + 1e-6)
        
        # 搅拌爪：细长（ratio > 5）
        # 食材：团状（ratio < 3）
        if aspect_ratio < aspect_ratio_max:
            region_mask = np.zeros_like(motion_mask, dtype=np.uint8)
            cv2.drawContours(region_mask, [cnt], -1, 255, -1)
            candidate_regions.append({
                "contour": cnt,
                "bbox": (x, y, w, h),
                "area": area,
                "mask": region_mask > 0
            })
    
    if not candidate_regions:
        return False, [], ""
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 步骤3：IR温度验证（辅助验证）
    # ═══════════════════════════════════════════════════════════════════════════
    
    verified_regions = []
    for region in candidate_regions:
        # 映射到IR
        rgb_mask = region["mask"]
        ir_mask = map_mask_to_ir(rgb_mask, homography, ir_curr.shape)
        
        if ir_mask.sum() < 50:  # 映射后区域太小
            continue
        
        # 计算该区域的温度
        region_temp = ir_curr[ir_mask].mean()
        
        # 计算周围温度（膨胀mask，膨胀区域-原区域=周围）
        kernel_dilate = np.ones((15, 15), np.uint8)
        ir_mask_dilated = cv2.dilate(ir_mask.astype(np.uint8), kernel_dilate)
        surrounding_mask = (ir_mask_dilated > 0) & (~ir_mask)
        
        if surrounding_mask.sum() < 50:
            continue
        
        surrounding_temp = ir_curr[surrounding_mask].mean()
        
        # 验证条件：新区域温度 < 周围温度 - N°C
        temp_diff = surrounding_temp - region_temp
        
        if temp_diff > ir_temp_diff_min:  # 新食材比锅冷N度以上
            verified_regions.append({
                "rgb_mask": rgb_mask,
                "temp_diff": temp_diff,
                "region_temp": region_temp,
                "surrounding_temp": surrounding_temp
            })
            print(f"[新食材验证] 区域温度={region_temp:.1f}°C, "
                  f"周围温度={surrounding_temp:.1f}°C, "
                  f"温差={temp_diff:.1f}°C [通过]")
    
    if not verified_regions:
        return False, [], ""
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 步骤4：生成前景点
    # ═══════════════════════════════════════════════════════════════════════════
    
    # 合并所有验证通过的区域
    combined_mask = np.zeros_like(motion_mask, dtype=bool)
    for vr in verified_regions:
        combined_mask |= vr["rgb_mask"]
    
    # 形态学腐蚀（避免边缘）
    kernel_erode = np.ones((5, 5), np.uint8)
    eroded = cv2.erode(combined_mask.astype(np.uint8), kernel_erode, iterations=2)
    
    # 均匀采样前景点
    ys, xs = np.where(eroded)
    if len(xs) == 0:
        ys, xs = np.where(combined_mask)
    
    if len(xs) == 0:
        return False, [], ""
    
    num_points = max(15, min(40, len(xs) // 100))
    indices = np.random.choice(len(xs), min(num_points, len(xs)), replace=False)
    fg_points = [[int(xs[i]), int(ys[i])] for i in indices]
    
    # 生成标签
    avg_temp_diff = np.mean([vr["temp_diff"] for vr in verified_regions])
    label = f"新食材(RGB+IR, ΔT={avg_temp_diff:.1f}°C)"
    
    return True, fg_points, label


def map_mask_to_ir(rgb_mask, homography, ir_shape):
    """
    用单应矩阵将RGB mask映射到红外图像坐标系
    
    参数：
        rgb_mask: RGB mask（H, W bool）
        homography: RGB→IR单应矩阵（3, 3）
        ir_shape: IR图像形状（H_ir, W_ir）
    
    返回：
        ir_mask: IR mask（H_ir, W_ir bool）
    """
    H_ir, W_ir = ir_shape
    ys, xs = np.where(rgb_mask)
    if len(xs) == 0:
        return np.zeros(ir_shape, dtype=bool)
    
    pts_rgb = np.stack([xs, ys, np.ones(len(xs))], axis=1).T  # (3, N)
    pts_ir = homography @ pts_rgb
    pts_ir = pts_ir[:2] / pts_ir[2]
    
    xi = np.round(pts_ir[0]).astype(int)
    yi = np.round(pts_ir[1]).astype(int)
    valid = (xi >= 0) & (xi < W_ir) & (yi >= 0) & (yi < H_ir)
    xi, yi = xi[valid], yi[valid]
    
    ir_mask = np.zeros(ir_shape, dtype=bool)
    ir_mask[yi, xi] = True
    return ir_mask
