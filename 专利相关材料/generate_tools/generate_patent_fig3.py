from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


OUT = Path(r"D:\Chef_Vision\output\patent_figures\fig3_multi_path_food_candidate_generation.png")
OUT.parent.mkdir(parents=True, exist_ok=True)

W, H = 1900, 1280
img = Image.new("RGB", (W, H), "white")
draw = ImageDraw.Draw(img)


def font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\simsun.ttc",
    ]
    for p in candidates:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


F_MAIN = font(26)
F_SMALL = font(22)
F_NOTE = font(18)

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
    import math

    ang = math.atan2(y2 - y1, x2 - x1)
    size = 14
    a1 = ang + math.pi * 0.82
    a2 = ang - math.pi * 0.82
    p1 = (x2 + size * math.cos(a1), y2 + size * math.sin(a1))
    p2 = (x2 + size * math.cos(a2), y2 + size * math.sin(a2))
    draw.polygon([(x2, y2), p1, p2], fill=color)


def poly_arrow(points, color=BLACK, width=3):
    if len(points) < 2:
        return
    for a, b in zip(points[:-2], points[1:-1]):
        draw.line((*a, *b), fill=color, width=width)
    arrow(*points[-2], *points[-1], color=color, width=width)


# Top input
box(610, 55, 680, 88, "同步配准后的 RGB 图像 + IR 温度矩阵", F_MAIN)

# Three path headers
path_y = 240
box(90, path_y, 470, 100, "RGB 正向食材区域生成路径", F_MAIN)
box(715, path_y, 470, 100, "IR 温度物理区域生成路径", F_MAIN)
box(1340, path_y, 470, 100, "RGB 反向语义辅助区域生成路径", F_MAIN)

# Split arrows from top
draw.line((950, 143, 950, 190), fill=BLACK, width=3)
draw.line((325, 190, 1575, 190), fill=BLACK, width=3)
arrow(325, 190, 325, path_y)
arrow(950, 190, 950, path_y)
arrow(1575, 190, 1575, path_y)

# Method boxes in each lane
box(90, 430, 470, 132, "AI 图像分割 / 视频目标分割\nSAM2 或同类模型\n结合运动连续性更新掩膜", F_SMALL, SOFT)
box(715, 430, 470, 132, "温度阈值 / 自适应阈值\n温度双峰 / 聚类分割\nK-means 作为辅助备选", F_SMALL, SOFT)
box(1340, 430, 470, 132, "识别锅底、锅壁、搅拌结构\n从锅内有效区域中扣除\n间接获得食材候选范围", F_SMALL, SOFT)

arrow(325, 340, 325, 430)
arrow(950, 340, 950, 430)
arrow(1575, 340, 1575, 430)

# Candidate outputs
box(90, 655, 470, 90, "第一食材候选区域", F_MAIN)
box(715, 655, 470, 90, "第二食材候选区域", F_MAIN)
box(1340, 655, 470, 90, "第三食材候选区域", F_MAIN)

arrow(325, 562, 325, 655)
arrow(950, 562, 950, 655)
arrow(1575, 562, 1575, 655)

# Fusion / correction
box(520, 855, 860, 108, "多路径一致性校验、纠偏与择优模块\n根据面积范围、位置关系、重叠程度、温度分布特征进行判断", F_SMALL)

poly_arrow([(325, 745), (325, 810), (760, 810), (760, 855)])
poly_arrow([(950, 745), (950, 855)])
poly_arrow([(1575, 745), (1575, 810), (1140, 810), (1140, 855)])

# Final result
box(650, 1062, 600, 88, "最终食材区域", F_MAIN)
arrow(950, 963, 950, 1062)

box(650, 1185, 600, 65, "进入食材表面温度计算", F_SMALL)
arrow(950, 1150, 950, 1185)

# Small side labels, not too much text.
draw.text((150, 775), "视觉语义与轮廓优势", fill=GRAY, font=F_NOTE)
draw.text((820, 775), "温度物理依据", fill=GRAY, font=F_NOTE)
draw.text((1420, 775), "非食材区域排除", fill=GRAY, font=F_NOTE)

img.save(OUT)
print(OUT)
