from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import math


OUT = Path(r"D:\Chef_Vision\output\patent_figures\fig4_multipath_temperature_calculation_output.png")
OUT.parent.mkdir(parents=True, exist_ok=True)

W, H = 1900, 1420
img = Image.new("RGB", (W, H), "white")
draw = ImageDraw.Draw(img)


def font(size: int) -> ImageFont.FreeTypeFont:
    for p in [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\simsun.ttc",
    ]:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


F_MAIN = font(25)
F_SMALL = font(21)
F_NOTE = font(17)

BLACK = (35, 35, 35)
GRAY = (105, 105, 105)
FILL = (252, 252, 252)
SOFT = (248, 248, 248)


def text_size(text: str, fnt: ImageFont.FreeTypeFont):
    box = draw.multiline_textbbox((0, 0), text, font=fnt, spacing=8, align="center")
    return box[2] - box[0], box[3] - box[1]


def box(x, y, w, h, text, fnt=F_MAIN, fill=FILL, outline=BLACK, width=3):
    draw.rounded_rectangle((x, y, x + w, y + h), radius=12, fill=fill, outline=outline, width=width)
    tw, th = text_size(text, fnt)
    draw.multiline_text(
        (x + w / 2 - tw / 2, y + h / 2 - th / 2 - 2),
        text,
        fill=BLACK,
        font=fnt,
        spacing=8,
        align="center",
    )


def arrow(x1, y1, x2, y2, color=BLACK, width=3):
    draw.line((x1, y1, x2, y2), fill=color, width=width)
    ang = math.atan2(y2 - y1, x2 - x1)
    size = 14
    a1 = ang + math.pi * 0.82
    a2 = ang - math.pi * 0.82
    p1 = (x2 + size * math.cos(a1), y2 + size * math.sin(a1))
    p2 = (x2 + size * math.cos(a2), y2 + size * math.sin(a2))
    draw.polygon([(x2, y2), p1, p2], fill=color)


def poly_arrow(points, color=BLACK, width=3):
    for a, b in zip(points[:-2], points[1:-1]):
        draw.line((*a, *b), fill=color, width=width)
    arrow(*points[-2], *points[-1], color=color, width=width)


# Candidate inputs
box(90, 70, 470, 88, "第一食材候选区域\nRGB 正向路径生成", F_SMALL)
box(715, 70, 470, 88, "第二食材候选区域\nIR 温度物理路径生成", F_SMALL)
box(1340, 70, 470, 88, "第三食材候选区域\nRGB 反向语义辅助生成", F_SMALL)

# Merge line
draw.line((325, 158, 325, 215), fill=BLACK, width=3)
draw.line((950, 158, 950, 215), fill=BLACK, width=3)
draw.line((1575, 158, 1575, 215), fill=BLACK, width=3)
draw.line((325, 215, 1575, 215), fill=BLACK, width=3)
arrow(950, 215, 950, 265)

box(520, 265, 860, 112, "多路径一致性校验模块\n面积范围 / 位置关系 / 重叠程度 / 温度分布 / 非食材区域", F_SMALL, SOFT)
arrow(950, 377, 950, 430)

box(520, 430, 860, 105, "纠偏、剔除、融合或择优模块\n对漂移区域、异常面积区域、混入非食材区域进行修正", F_SMALL)
arrow(950, 535, 950, 590)

box(650, 590, 600, 82, "最终食材区域", F_MAIN)
arrow(950, 672, 950, 725)

box(610, 725, 680, 94, "映射至 IR 红外温度矩阵\n提取最终食材区域对应温度值", F_SMALL, SOFT)
arrow(950, 819, 950, 875)

box(520, 875, 860, 112, "温度值处理与统计计算\n异常值剔除 / 分位数筛选 / 平滑滤波 / 时间序列平滑", F_SMALL)
arrow(950, 987, 950, 1045)

box(610, 1045, 680, 95, "食材表面温度结果\n平均温度 / 中位温度 / 最高温度 / 分位温度 / 变化趋势", F_SMALL, SOFT)

# Output branches
draw.line((950, 1140, 950, 1195), fill=BLACK, width=3)
draw.line((250, 1195, 1650, 1195), fill=BLACK, width=3)

out_y = 1245
box(80, out_y, 340, 75, "温度显示\n数据记录", F_SMALL)
box(550, out_y, 340, 75, "烹饪阶段判断\n报警提示", F_SMALL)
box(1020, out_y, 340, 75, "火力调节\n加热功率控制", F_SMALL)
box(1490, out_y, 340, 75, "翻炒动作调整\n闭环控制接口", F_SMALL)

arrow(250, 1195, 250, out_y)
arrow(720, 1195, 720, out_y)
arrow(1190, 1195, 1190, out_y)
arrow(1650, 1195, 1650, out_y)

draw.text(
    (470, 1360),
    "说明：候选区域经多路径校验后确定最终食材区域，再映射至 IR 温度矩阵计算食材表面温度并输出至显示、记录或控制模块。",
    fill=GRAY,
    font=F_NOTE,
)

img.save(OUT)
print(OUT)
