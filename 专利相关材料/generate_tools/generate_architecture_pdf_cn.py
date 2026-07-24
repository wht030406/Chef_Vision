from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "output" / "pdf"
PDF_PATH = OUT_DIR / "chef_vision_整体框架与优化思路.pdf"


def register_fonts():
    pdfmetrics.registerFont(TTFont("MSYH", r"C:\Windows\Fonts\msyh.ttc"))
    pdfmetrics.registerFont(TTFont("MSYH-Bold", r"C:\Windows\Fonts\msyhbd.ttc"))


def make_styles():
    return {
        "title": ParagraphStyle(
            "title",
            fontName="MSYH-Bold",
            fontSize=20,
            leading=24,
            textColor=colors.white,
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            fontName="MSYH",
            fontSize=10.5,
            leading=14,
            textColor=colors.HexColor("#D7E5F2"),
        ),
        "section": ParagraphStyle(
            "section",
            fontName="MSYH-Bold",
            fontSize=15,
            leading=20,
            textColor=colors.HexColor("#162231"),
        ),
        "card_title": ParagraphStyle(
            "card_title",
            fontName="MSYH-Bold",
            fontSize=11.5,
            leading=15,
            textColor=colors.white,
        ),
        "card_body": ParagraphStyle(
            "card_body",
            fontName="MSYH",
            fontSize=9,
            leading=12.5,
            textColor=colors.white,
        ),
        "body": ParagraphStyle(
            "body",
            fontName="MSYH",
            fontSize=10,
            leading=15,
            textColor=colors.HexColor("#324759"),
        ),
        "body_bold": ParagraphStyle(
            "body_bold",
            fontName="MSYH-Bold",
            fontSize=10.5,
            leading=15,
            textColor=colors.HexColor("#223245"),
        ),
        "note": ParagraphStyle(
            "note",
            fontName="MSYH",
            fontSize=9.5,
            leading=14,
            textColor=colors.HexColor("#3C5367"),
        ),
    }


def draw_paragraph(c, text, x, y_top, width, style):
    para = Paragraph(text, style)
    w, h = para.wrap(width, 1000 * mm)
    para.drawOn(c, x, y_top - h)
    return h


def draw_header(c, page_w, page_h, styles, title, subtitle):
    c.setFillColor(colors.HexColor("#122033"))
    c.rect(0, page_h - 34 * mm, page_w, 34 * mm, fill=1, stroke=0)
    draw_paragraph(c, title, 16 * mm, page_h - 12 * mm, page_w - 32 * mm, styles["title"])
    draw_paragraph(c, subtitle, 16 * mm, page_h - 23 * mm, page_w - 32 * mm, styles["subtitle"])


def draw_round_box(c, x, y, w, h, title, body, fill):
    c.setFillColor(fill)
    c.setStrokeColor(fill)
    c.roundRect(x, y, w, h, 6, fill=1, stroke=0)
    c.setFont("MSYH-Bold", 11)
    c.setFillColor(colors.white)
    c.drawString(x + 8, y + h - 18, title)
    c.setFont("MSYH", 9)
    text_y = y + h - 34
    for line in body:
        c.drawString(x + 8, text_y, line)
        text_y -= 12


def draw_arrow(c, x1, y1, x2, y2):
    import math

    c.setStrokeColor(colors.HexColor("#5A7488"))
    c.setLineWidth(1.6)
    c.line(x1, y1, x2, y2)
    angle = math.atan2(y2 - y1, x2 - x1)
    size = 6
    for delta in (2.75, -2.75):
        ax = x2 - size * math.cos(angle + delta)
        ay = y2 - size * math.sin(angle + delta)
        c.line(x2, y2, ax, ay)


def draw_bullet_block(c, x, y_top, width, title, bullets, styles):
    h1 = draw_paragraph(c, title, x, y_top, width, styles["body_bold"])
    cur_y = y_top - h1 - 4
    for item in bullets:
        h = draw_paragraph(c, f"- {item}", x + 4, cur_y, width - 4, styles["body"])
        cur_y -= h + 2
    return cur_y


def page_one(c, page_w, page_h, styles):
    draw_header(
        c,
        page_w,
        page_h,
        styles,
        "Chef Vision 当前整体框架与后续优化思路",
        "这是一份给自己看的整理稿：重点是看清现在项目到了哪、后面最值得先优化什么。",
    )

    draw_paragraph(c, "一、当前系统主链路", 16 * mm, page_h - 46 * mm, 160 * mm, styles["section"])

    x = 25 * mm
    box_w = 155 * mm
    box_h = 21 * mm
    y_positions = [page_h - 78 * mm, page_h - 110 * mm, page_h - 142 * mm, page_h - 174 * mm, page_h - 206 * mm]
    fills = [
        colors.HexColor("#3E6B99"),
        colors.HexColor("#2E8079"),
        colors.HexColor("#55748D"),
        colors.HexColor("#6C7894"),
        colors.HexColor("#8B624C"),
    ]
    cards = [
        ("1. 标注入口", ["LabelFirstFrame.py", "生成 food_labels.json / wok_region.json"]),
        ("2. 运行入口", ["TrackFood.py 读取配置、视频、温度数据", "负责主循环调度与 SAM2 chunk 组织"]),
        ("3. 三条核心能力线", ["RGB 正向追踪：主食材 mask 的连续追踪", "RGB 反向语义：锅底/异常情况下的补偿与校验", "IR 锅区与温度：锅内约束、食材热特征、温度统计"]),
        ("4. 融合与输出", ["temp_fusion.py + projection_utils.py", "把 RGB 区域和 IR 温度信息真正结合起来"]),
        ("5. 最终产物", ["可视化视频、并排合成视频、Excel、温度曲线、调试图"]),
    ]

    for idx, (title, body) in enumerate(cards):
        h = 28 * mm if idx == 2 else box_h
        draw_round_box(c, x, y_positions[idx], box_w, h, title, body, fills[idx])
        if idx < len(cards) - 1:
            start_y = y_positions[idx] - 2
            end_y = y_positions[idx + 1] + (28 * mm if idx + 1 == 2 else box_h) + 2
            draw_arrow(c, x + box_w / 2, start_y, x + box_w / 2, end_y)

    note_y = page_h - 240 * mm
    draw_paragraph(c, "当前最重要的理解：这个项目已经不是“单一 RGB 算法”，而是 <b>RGB 正向 + RGB 反向 + IR 温度线索</b> 共同工作的多模态框架。", 16 * mm, note_y, 175 * mm, styles["note"])
    draw_paragraph(c, "所以后面优化时，不应该只盯某一个 mask，而应该看三条线之间：谁是主逻辑、谁负责兜底、谁提供约束。", 16 * mm, note_y - 15 * mm, 175 * mm, styles["note"])


def page_two(c, page_w, page_h, styles):
    draw_header(
        c,
        page_w,
        page_h,
        styles,
        "二、现在的代码结构已经到了什么程度",
        "这页的重点不是列文件名，而是帮你判断：哪些已经整理好了，哪些还应该谨慎对待。",
    )

    draw_paragraph(c, "已经基本拆开的层", 16 * mm, page_h - 48 * mm, 170 * mm, styles["section"])

    blocks = [
        ("入口与配置层", [
            "track_config.py：统一管理视频路径、温度文件、短跑参数、命令行入口。",
            "label_io.py：统一读取和整理标注结果，主程序不再自己处理这些细节。",
        ]),
        ("算法支撑层", [
            "ir_wok.py：IR 锅区是独立模块了，后面换新方案有明确落脚点。",
            "rgb_forward.py / rgb_inverse.py：两套 RGB 方案的辅助逻辑已经抽出去，不再全部堵在主循环里。",
        ]),
        ("温度与投影层", [
            "temp_fusion.py：温度测量和 IR 食材聚类逻辑集中在这里。",
            "projection_utils.py：专门放 RGB -> IR 的公共投影函数，只负责“使用矩阵”，不负责“计算矩阵”。",
        ]),
        ("输出与表现层", [
            "output_utils.py：Excel、曲线图、合成视频输出。",
            "viz_utils.py：overlay 和底部曲线条这类可视化细节。",
        ]),
    ]

    cur_y = page_h - 62 * mm
    for title, bullets in blocks:
        cur_y = draw_bullet_block(c, 18 * mm, cur_y, 175 * mm, title, bullets, styles)
        cur_y -= 6

    cur_y -= 4
    draw_paragraph(c, "TrackFood.py 现在主要还剩什么", 16 * mm, cur_y, 170 * mm, styles["section"])
    cur_y -= 12
    cur_y = draw_bullet_block(c, 18 * mm, cur_y, 175 * mm, "", [
        "主追踪流程的总调度：什么时候读数据、什么时候进 SAM2、什么时候调用 IR/RGB 各模块。",
        "chunk 组织、视频帧处理、部分核心 helper。",
        "少量还没继续外拆的核心算法函数。",
    ], styles)

    draw_paragraph(c, "当前的现实判断：<b>工程结构已经基本够用了</b>。后续继续硬拆的收益在下降，后面真正决定效果提升的，主要还是算法稳定性。", 16 * mm, cur_y - 8, 175 * mm, styles["note"])


def page_three(c, page_w, page_h, styles):
    draw_header(
        c,
        page_w,
        page_h,
        styles,
        "三、后续优化应该怎么排优先级",
        "按“收益高低 + 现在项目状态”来排，不建议继续机械拆分。",
    )

    draw_paragraph(c, "建议的优化顺序", 16 * mm, page_h - 48 * mm, 170 * mm, styles["section"])

    bullets_1 = [
        "IR 锅区方案：这是当前最值得优先打磨的一块。结构已经准备好了，后面应该把注意力放到方案本身，而不是主程序怎么拆。",
        "优先目标可以定为：第一帧人工给一个严格位于锅内的 IR mask，后续通过 IR 帧间配准估计平移，再整体平移锅区。",
        "这样做的意义是：锅区约束先稳定下来，RGB 正向、RGB 反向和温度统计三条线都会跟着受益。",
    ]
    bullets_2 = [
        "RGB 正向稳定性：重点不是换掉 SAM2，而是把“何时判定异常、何时引入 IR 约束、何时触发补强”梳理得更清楚。",
        "RGB 反向语义：继续保持“只在满足条件时才自动重标”，并保留触发图，方便回看触发是否过多或过少。",
        "IR 温度分割：后面要逐步把“锅底 / 食材 / 背景”的温度划分做成更可比较的方案，不然温度结果容易波动。",
    ]
    bullets_3 = [
        "验证策略：后面每次改算法，尽量都用同一批测试视频短跑 + 完整跑，方便横向比效果，而不是只靠主观感觉。",
        "工程上还能做的小优化有，但不建议优先。比如主循环再细拆一层编排函数，这种事情可以放在算法稳定之后再做。",
    ]

    cur_y = page_h - 62 * mm
    cur_y = draw_bullet_block(c, 18 * mm, cur_y, 175 * mm, "1. 先抓 IR 锅区这条主矛盾", bullets_1, styles)
    cur_y -= 8
    cur_y = draw_bullet_block(c, 18 * mm, cur_y, 175 * mm, "2. 再抓两个 RGB 方案的稳定性", bullets_2, styles)
    cur_y -= 8
    cur_y = draw_bullet_block(c, 18 * mm, cur_y, 175 * mm, "3. 最后补验证和少量工程修整", bullets_3, styles)
    cur_y -= 10

    draw_paragraph(c, "一句话总结：<b>现在最值得做的不是继续拆文件，而是把 IR 锅区方案先稳定下来，再带动 RGB 正向、RGB 反向和温度统计一起变稳。</b>", 16 * mm, cur_y, 175 * mm, styles["note"])


def build_pdf():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    register_fonts()
    styles = make_styles()
    c = canvas.Canvas(str(PDF_PATH), pagesize=A4)
    page_w, page_h = A4

    page_one(c, page_w, page_h, styles)
    c.showPage()
    page_two(c, page_w, page_h, styles)
    c.showPage()
    page_three(c, page_w, page_h, styles)
    c.showPage()
    c.save()


if __name__ == "__main__":
    build_pdf()
