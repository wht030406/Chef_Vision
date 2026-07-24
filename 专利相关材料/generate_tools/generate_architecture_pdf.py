from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "output" / "pdf"
TMP_DIR = ROOT / "tmp" / "pdfs"
PDF_PATH = OUT_DIR / "chef_vision_architecture_overview.pdf"


def register_fonts():
    pdfmetrics.registerFont(TTFont("MSYH", r"C:\Windows\Fonts\msyh.ttc"))
    pdfmetrics.registerFont(TTFont("MSYH-Bold", r"C:\Windows\Fonts\msyhbd.ttc"))


def draw_round_box(c, x, y, w, h, title, body_lines, fill_color, title_color=colors.white):
    c.setFillColor(fill_color)
    c.setStrokeColor(fill_color)
    c.roundRect(x, y, w, h, 6, fill=1, stroke=0)

    c.setFont("MSYH-Bold", 11)
    c.setFillColor(title_color)
    c.drawString(x + 8, y + h - 18, title)

    c.setFont("MSYH", 8.5)
    c.setFillColor(colors.white)
    line_y = y + h - 34
    for line in body_lines:
        c.drawString(x + 8, line_y, line)
        line_y -= 11


def draw_arrow(c, x1, y1, x2, y2, color=colors.HexColor("#4F6D7A")):
    c.setStrokeColor(color)
    c.setLineWidth(1.5)
    c.line(x1, y1, x2, y2)

    import math
    angle = math.atan2(y2 - y1, x2 - x1)
    size = 6
    a1 = angle + math.pi * 0.85
    a2 = angle - math.pi * 0.85
    c.line(x2, y2, x2 + size * math.cos(a1), y2 + size * math.sin(a1))
    c.line(x2, y2, x2 + size * math.cos(a2), y2 + size * math.sin(a2))


def draw_bullet_lines(c, x, y, title, lines, max_width=170 * mm):
    c.setFont("MSYH-Bold", 10.5)
    c.setFillColor(colors.HexColor("#1F2D3D"))
    c.drawString(x, y, title)

    c.setFont("MSYH", 8.8)
    yy = y - 14
    for line in lines:
        c.setFillColor(colors.HexColor("#304455"))
        wrapped = simpleSplit(f"- {line}", "MSYH", 8.8, max_width)
        for row in wrapped:
            c.drawString(x + 8, yy, row)
            yy -= 11
    return yy


def build_pdf():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    register_fonts()

    c = canvas.Canvas(str(PDF_PATH), pagesize=A4)
    page_w, page_h = A4

    margin = 16 * mm

    c.setFillColor(colors.HexColor("#0E1B2A"))
    c.rect(0, page_h - 42 * mm, page_w, 42 * mm, fill=1, stroke=0)

    c.setFont("MSYH-Bold", 19)
    c.setFillColor(colors.white)
    c.drawString(margin, page_h - 20 * mm, "Chef Vision Current Architecture")

    c.setFont("MSYH", 10)
    c.setFillColor(colors.HexColor("#D5E4F2"))
    c.drawString(margin, page_h - 28 * mm, "Current decoupled workflow after modular refactoring")
    c.drawString(margin, page_h - 34 * mm, "Focus: RGB forward / RGB inverse / IR thermal clustering collaboration")

    flow_top = page_h - 63 * mm
    box_w = 50 * mm
    box_h = 24 * mm
    gap = 11 * mm
    x_positions = [
        margin,
        margin + box_w + gap,
        margin + 2 * (box_w + gap),
    ]

    draw_round_box(
        c, x_positions[0], flow_top, box_w, box_h,
        "1. Labeling Input",
        ["LabelFirstFrame.py", "food_labels.json", "wok_region.json"],
        colors.HexColor("#2F5D8A"),
    )
    draw_round_box(
        c, x_positions[1], flow_top, box_w, box_h,
        "2. Main Orchestration",
        ["TrackFood.py", "video + temp loading", "SAM2 chunk tracking loop"],
        colors.HexColor("#2D7C78"),
    )
    draw_round_box(
        c, x_positions[2], flow_top, box_w, box_h,
        "3. Output Delivery",
        ["xlsx / curve / combined video", "output_utils.py", "viz_utils.py"],
        colors.HexColor("#8A5A44"),
    )

    draw_arrow(c, x_positions[0] + box_w, flow_top + box_h / 2, x_positions[1] - 4, flow_top + box_h / 2)
    draw_arrow(c, x_positions[1] + box_w, flow_top + box_h / 2, x_positions[2] - 4, flow_top + box_h / 2)

    second_row_y = flow_top - 38 * mm
    small_w = 40 * mm
    small_h = 22 * mm
    small_gap = 6 * mm
    row2_x = [
        margin,
        margin + (small_w + small_gap),
        margin + 2 * (small_w + small_gap),
        margin + 3 * (small_w + small_gap),
    ]

    draw_round_box(
        c, row2_x[0], second_row_y, small_w, small_h,
        "track_config.py",
        ["runtime args", "video / temp / short run"],
        colors.HexColor("#526D82"),
    )
    draw_round_box(
        c, row2_x[1], second_row_y, small_w, small_h,
        "label_io.py",
        ["load and normalize", "food / bottom keyframes"],
        colors.HexColor("#526D82"),
    )
    draw_round_box(
        c, row2_x[2], second_row_y, small_w, small_h,
        "ir_wok.py",
        ["IR wok mask", "legacy / static / frame_shift"],
        colors.HexColor("#526D82"),
    )
    draw_round_box(
        c, row2_x[3], second_row_y, small_w, small_h,
        "temp_fusion.py",
        ["temperature measure", "IR food clustering"],
        colors.HexColor("#526D82"),
    )

    third_row_y = second_row_y - 31 * mm
    row3_x = [
        margin + 20 * mm,
        margin + 20 * mm + (small_w + small_gap),
        margin + 20 * mm + 2 * (small_w + small_gap),
    ]

    draw_round_box(
        c, row3_x[0], third_row_y, small_w, small_h,
        "rgb_forward.py",
        ["forward SAM2 support", "reset / reinforce logic"],
        colors.HexColor("#7A8FA6"),
    )
    draw_round_box(
        c, row3_x[1], third_row_y, small_w, small_h,
        "rgb_inverse.py",
        ["inverse semantic support", "bottom auto relabel logic"],
        colors.HexColor("#7A8FA6"),
    )
    draw_round_box(
        c, row3_x[2], third_row_y, small_w, small_h,
        "projection_utils.py",
        ["shared RGB -> IR map", "uses homography.npy"],
        colors.HexColor("#7A8FA6"),
    )

    center_x = x_positions[1] + box_w / 2
    center_y = flow_top
    for target_x in [row2_x[0] + small_w / 2, row2_x[1] + small_w / 2, row2_x[2] + small_w / 2, row2_x[3] + small_w / 2]:
        draw_arrow(c, center_x, center_y, target_x, second_row_y + small_h + 2)
    for target_x in [row3_x[0] + small_w / 2, row3_x[1] + small_w / 2, row3_x[2] + small_w / 2]:
        draw_arrow(c, center_x, center_y, target_x, third_row_y + small_h + 2)

    c.showPage()

    c.setFillColor(colors.HexColor("#0E1B2A"))
    c.rect(0, page_h - 26 * mm, page_w, 26 * mm, fill=1, stroke=0)
    c.setFont("MSYH-Bold", 17)
    c.setFillColor(colors.white)
    c.drawString(margin, page_h - 16 * mm, "Module Summary And Current Position")

    left_x = margin
    top_y = page_h - 38 * mm

    y_left = draw_bullet_lines(c, left_x, top_y, "Core workflow", [
        "Manual labeling initializes RGB food, RGB bottom, and IR wok region.",
        "TrackFood.py now acts as the orchestrator instead of holding every utility.",
        "RGB forward, RGB inverse, and IR thermal signals work as complementary paths.",
    ])
    y_left = draw_bullet_lines(c, left_x, y_left - 8, "Current strengths", [
        "Multi-modal constraints improve usability over a single RGB-only pipeline.",
        "Temperature curves, Excel logs, and combined videos are produced in one run.",
        "IR wok region logic is isolated, so future strategy changes are safer to test.",
    ])
    draw_bullet_lines(c, left_x, y_left - 8, "Current limitation", [
        "Tracking precision is usable but not yet fully stable in highly dynamic scenes.",
        "The next high-value work should focus on algorithm stability rather than more refactoring.",
    ])

    y_right = draw_bullet_lines(c, left_x, y_left - 60, "Key module roles", [
        "track_config.py: runtime path and parameter entry.",
        "label_io.py: standardized label loading.",
        "ir_wok.py: IR wok region strategy hub.",
        "rgb_forward.py / rgb_inverse.py: two RGB-side support strategies.",
        "temp_fusion.py: all temperature-related measurements.",
        "projection_utils.py: shared RGB-to-IR projection based on homography.",
        "output_utils.py + viz_utils.py: presentation layer and deliverables.",
    ])
    draw_bullet_lines(c, left_x, y_right - 8, "Main program status", [
        "TrackFood.py is much cleaner than before, but it is still the core scheduler.",
        "Infrastructure cleanup is mostly done; future gains now come from algorithm tuning.",
    ])

    c.showPage()
    c.save()


if __name__ == "__main__":
    build_pdf()
