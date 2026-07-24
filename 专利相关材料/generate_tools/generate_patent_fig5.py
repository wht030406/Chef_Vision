from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import math


OUT = Path(r"D:\Chef_Vision\output\patent_figures\fig5_exception_realtime_mechanism.png")
OUT.parent.mkdir(parents=True, exist_ok=True)

W, H = 1800, 1280
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


def diamond(cx, cy, w, h, text, fnt=F_MAIN, fill=FILL, outline=BLACK, width=3):
    pts = [(cx, cy - h / 2), (cx + w / 2, cy), (cx, cy + h / 2), (cx - w / 2, cy)]
    draw.polygon(pts, fill=fill, outline=outline)
    draw.line([pts[0], pts[1], pts[2], pts[3], pts[0]], fill=outline, width=width)
    tw, th = text_size(text, fnt)
    draw.multiline_text(
        (cx - tw / 2, cy - th / 2 - 2),
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


# Main vertical realtime pipeline
box(560, 55, 680, 86, "连续采集 RGB 图像帧与 IR 温度矩阵", F_MAIN)
arrow(900, 141, 900, 195)

box(560, 195, 680, 92, "时间同步、空间配准与缓存队列\n保存最近若干帧区域结果和温度结果", F_SMALL, SOFT)
arrow(900, 287, 900, 345)

box(560, 345, 680, 92, "候选区域生成与温度计算\n按帧序列近实时执行", F_SMALL)
arrow(900, 437, 900, 500)

diamond(900, 570, 500, 140, "当前帧结果\n是否异常？", F_MAIN, SOFT)

# Normal branch
poly_arrow([(900, 640), (900, 705), (620, 705), (620, 770)])
draw.text((640, 672), "否", fill=GRAY, font=F_NOTE)
box(360, 770, 520, 92, "正常输出近实时温度结果\n更新历史区域和温度缓存", F_SMALL)

# Exception branch
poly_arrow([(1150, 570), (1340, 570), (1340, 770)])
draw.text((1190, 535), "是", fill=GRAY, font=F_NOTE)
box(1080, 770, 520, 122, "异常处理策略\n路径降权 / 路径切换 / 短时保持\n异常值剔除 / 输出低置信度标记", F_SMALL)

# Exception detail side boxes
box(75, 365, 345, 88, "RGB 异常\n漂移 / 遮挡 / 面积跳变", F_SMALL)
box(75, 495, 345, 88, "IR 异常\n孤立高温点 / 非食材混入", F_SMALL)
box(75, 625, 345, 88, "时间异常\n帧丢失 / 数据不同步", F_SMALL)

poly_arrow([(420, 409), (510, 409), (510, 570), (650, 570)], GRAY, 2)
poly_arrow([(420, 539), (500, 539), (500, 570), (650, 570)], GRAY, 2)
poly_arrow([(420, 669), (510, 669), (510, 570), (650, 570)], GRAY, 2)

# Merge back to output
draw.line((620, 862, 620, 970), fill=BLACK, width=3)
draw.line((1340, 892, 1340, 970), fill=BLACK, width=3)
draw.line((620, 970, 1340, 970), fill=BLACK, width=3)
arrow(980, 970, 980, 1035)

box(650, 1035, 660, 90, "附带时间戳、置信度、异常标记的温度结果", F_MAIN, SOFT)
arrow(980, 1125, 980, 1180)

box(510, 1180, 940, 70, "输出至温度显示、数据记录、烹饪阶段判断、火力调节或翻炒控制模块", F_SMALL)

draw.text(
    (350, 1260),
    "说明：系统通过缓存、连续性判断、路径降权或短时保持等机制，在异常帧下维持近实时温度结果的连续性和可靠性。",
    fill=GRAY,
    font=F_NOTE,
)

img.save(OUT)
print(OUT)
