"""Generate DocOps hackathon pitch deck as .pptx"""

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

# ── Colours ──────────────────────────────────────────────────────────────────
TEAL       = RGBColor(0x14, 0xB8, 0xA6)
DARK_TEAL  = RGBColor(0x0E, 0x8C, 0x7D)
DARK_BG    = RGBColor(0x0F, 0x17, 0x2A)
WHITE      = RGBColor(0xFF, 0xFF, 0xFF)
LIGHT_GRAY = RGBColor(0xBB, 0xBB, 0xBB)
MID_GRAY   = RGBColor(0x88, 0x88, 0x88)
AMBER      = RGBColor(0xF5, 0x9E, 0x0B)

prs = Presentation()
prs.slide_width  = Inches(13.333)
prs.slide_height = Inches(7.5)
W = prs.slide_width
H = prs.slide_height


def _dark_bg(slide):
    """Fill slide background with dark colour."""
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = DARK_BG


def _add_text(slide, left, top, width, height, text, *,
              font_size=18, bold=False, color=WHITE, align=PP_ALIGN.LEFT,
              font_name="Calibri", line_spacing=1.2):
    """Helper to add a text box."""
    txBox = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    tf = txBox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = text
    p.font.size = Pt(font_size)
    p.font.bold = bold
    p.font.color.rgb = color
    p.font.name = font_name
    p.alignment = align
    p.space_after = Pt(0)
    p.line_spacing = Pt(font_size * line_spacing)
    return tf


def _add_para(tf, text, *, font_size=18, bold=False, color=WHITE,
              align=PP_ALIGN.LEFT, font_name="Calibri", space_before=0):
    """Append a paragraph to an existing text frame."""
    p = tf.add_paragraph()
    p.text = text
    p.font.size = Pt(font_size)
    p.font.bold = bold
    p.font.color.rgb = color
    p.font.name = font_name
    p.alignment = align
    p.space_before = Pt(space_before)
    return p


def _teal_accent(slide, top, height=0.06):
    """Thin teal accent bar."""
    shape = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0.8), Inches(top), Inches(2), Inches(height)
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = TEAL
    shape.line.fill.background()


def _bullet_list(slide, left, top, width, height, items, *,
                 font_size=20, color=WHITE, bullet_color=TEAL):
    """Add a bulleted list."""
    txBox = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    tf = txBox.text_frame
    tf.word_wrap = True
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = item
        p.font.size = Pt(font_size)
        p.font.color.rgb = color
        p.font.name = "Calibri"
        p.space_before = Pt(8)
        p.level = 0
        # bullet
        p.bullet = True
    return tf


# ═══════════════════════════════════════════════════════════════════════════
# SLIDE 1 — Title
# ═══════════════════════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
_dark_bg(slide)

# Big teal rectangle accent top-right
shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(8), Inches(0), Inches(5.333), Inches(7.5))
shape.fill.solid()
shape.fill.fore_color.rgb = TEAL
shape.line.fill.background()

_add_text(slide, 1, 1.8, 7, 1.2, "DocOps", font_size=72, bold=True, color=WHITE)
_teal_accent(slide, 3.2)
_add_text(slide, 0.8, 3.5, 7, 0.8, "Documents don't just get read. They get run.",
          font_size=28, color=LIGHT_GRAY)
_add_text(slide, 0.8, 5.5, 7, 0.5, "Golden Grippers  |  Zurich Physical Hack 2026",
          font_size=16, color=MID_GRAY)

# Right-side label
_add_text(slide, 8.5, 2.5, 4, 2.5,
          "PDF → Parse → Plan → See → Act",
          font_size=30, bold=True, color=DARK_BG, align=PP_ALIGN.CENTER)


# ═══════════════════════════════════════════════════════════════════════════
# SLIDE 2 — The Problem
# ═══════════════════════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
_dark_bg(slide)

_add_text(slide, 0.8, 0.6, 10, 0.8, "The Problem", font_size=40, bold=True, color=TEAL)
_teal_accent(slide, 1.4)

_add_text(slide, 0.8, 1.8, 11, 0.8,
          "SOPs collect dust.  Datasheets get skimmed.",
          font_size=30, bold=True, color=WHITE)

_bullet_list(slide, 1.0, 2.8, 11, 3.5, [
    "Engineers manually interpret 100-page datasheets to set up tests",
    "Verification steps are error-prone, tedious, and unscalable",
    "Robot arms exist — but programming them per-task is slow",
    "No bridge between documentation and physical action",
], font_size=22)


# ═══════════════════════════════════════════════════════════════════════════
# SLIDE 3 — The Insight
# ═══════════════════════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
_dark_bg(slide)

_add_text(slide, 1, 2.0, 11, 1.5,
          "What if your documentation\nwas executable?",
          font_size=48, bold=True, color=WHITE, align=PP_ALIGN.CENTER)

_add_text(slide, 1, 4.2, 11, 1,
          "Drop a PDF.  Get a robot that follows it.",
          font_size=30, color=TEAL, align=PP_ALIGN.CENTER)


# ═══════════════════════════════════════════════════════════════════════════
# SLIDE 4 — Live Demo Flow
# ═══════════════════════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
_dark_bg(slide)

_add_text(slide, 0.8, 0.6, 10, 0.8, "Live Demo", font_size=40, bold=True, color=TEAL)
_teal_accent(slide, 1.4)

steps = [
    ("1", "Upload an Arduino Uno datasheet (PDF)"),
    ("2", '"Verify the 5V pin outputs correct voltage"'),
    ("3", "AI reads the doc → extracts specs (4.8 – 5.2 V)"),
    ("4", "Builds a step-by-step verification plan"),
    ("5", "VLM localizes the 5V pin on live camera"),
    ("6", "Robot arm probes it — autonomously"),
]

for i, (num, desc) in enumerate(steps):
    y = 1.9 + i * 0.85
    # Number circle
    shape = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(1.0), Inches(y), Inches(0.55), Inches(0.55))
    shape.fill.solid()
    shape.fill.fore_color.rgb = TEAL
    shape.line.fill.background()
    tf = shape.text_frame
    tf.paragraphs[0].text = num
    tf.paragraphs[0].font.size = Pt(20)
    tf.paragraphs[0].font.bold = True
    tf.paragraphs[0].font.color.rgb = DARK_BG
    tf.paragraphs[0].alignment = PP_ALIGN.CENTER
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    # Text
    _add_text(slide, 1.8, y + 0.05, 10, 0.5, desc, font_size=22, color=WHITE)


# ═══════════════════════════════════════════════════════════════════════════
# SLIDE 5 — The Pipeline
# ═══════════════════════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
_dark_bg(slide)

_add_text(slide, 0.8, 0.6, 10, 0.8, "The Pipeline", font_size=40, bold=True, color=TEAL)
_teal_accent(slide, 1.4)

pipeline = ["PDF", "Parse", "Search", "Plan", "See", "Act"]
tools    = ["Docling", "Docling", "RAG", "Gemini 2.0", "VLM", "SO-ARM100"]
x_start = 1.0
box_w = 1.7
gap = 0.35

for i, (stage, tool) in enumerate(zip(pipeline, tools)):
    x = x_start + i * (box_w + gap)
    # Box
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(2.5), Inches(box_w), Inches(1.2))
    shape.fill.solid()
    shape.fill.fore_color.rgb = TEAL
    shape.line.fill.background()
    tf = shape.text_frame
    tf.paragraphs[0].text = stage
    tf.paragraphs[0].font.size = Pt(24)
    tf.paragraphs[0].font.bold = True
    tf.paragraphs[0].font.color.rgb = DARK_BG
    tf.paragraphs[0].alignment = PP_ALIGN.CENTER
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE

    # Tool label below
    _add_text(slide, x, 3.9, box_w, 0.4, tool,
              font_size=14, color=MID_GRAY, align=PP_ALIGN.CENTER)

    # Arrow between boxes
    if i < len(pipeline) - 1:
        ax = x + box_w
        _add_text(slide, ax - 0.05, 2.7, gap + 0.1, 0.8, "→",
                  font_size=28, color=LIGHT_GRAY, align=PP_ALIGN.CENTER)

# Subtitle
_add_text(slide, 0.8, 5.0, 11, 0.6,
          "End-to-end: from unstructured PDF to physical robot action",
          font_size=20, color=LIGHT_GRAY, align=PP_ALIGN.CENTER)


# ═══════════════════════════════════════════════════════════════════════════
# SLIDE 6 — Tech Stack
# ═══════════════════════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
_dark_bg(slide)

_add_text(slide, 0.8, 0.6, 10, 0.8, "Tech Stack", font_size=40, bold=True, color=TEAL)
_teal_accent(slide, 1.4)

rows = [
    ("Parse",  "Extract specs, pins, safety warnings, diagrams", "Docling"),
    ("Think",  "Generate verified task plans with pass/fail criteria", "Gemini 2.0 Flash"),
    ("Search", "RAG over parsed document knowledge base",         "Embedding + Vector search"),
    ("See",    "Locate components + tool tip on live camera",     "VLM Keypoints"),
    ("Move",   "6-DOF arm with IK/FK, speed control, 3D twin",   "SO-ARM100 + URDF"),
    ("UI",     "Real-time dashboard with streaming pipeline",     "Next.js + Three.js"),
]

for i, (layer, what, how) in enumerate(rows):
    y = 1.9 + i * 0.82
    # Layer label
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(y), Inches(1.5), Inches(0.6))
    shape.fill.solid()
    shape.fill.fore_color.rgb = TEAL if i % 2 == 0 else DARK_TEAL
    shape.line.fill.background()
    tf = shape.text_frame
    tf.paragraphs[0].text = layer
    tf.paragraphs[0].font.size = Pt(18)
    tf.paragraphs[0].font.bold = True
    tf.paragraphs[0].font.color.rgb = DARK_BG
    tf.paragraphs[0].alignment = PP_ALIGN.CENTER
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE

    # Description
    _add_text(slide, 2.6, y + 0.05, 5.5, 0.5, what, font_size=18, color=WHITE)
    # Tool
    _add_text(slide, 8.3, y + 0.05, 4.5, 0.5, how, font_size=16, color=MID_GRAY)


# ═══════════════════════════════════════════════════════════════════════════
# SLIDE 7 — The UI (placeholder for screenshots)
# ═══════════════════════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
_dark_bg(slide)

_add_text(slide, 0.8, 0.6, 10, 0.8, "The Interface", font_size=40, bold=True, color=TEAL)
_teal_accent(slide, 1.4)

features = [
    "Task execution with streaming pipeline progress",
    "Knowledge base with parsed docs & diagrams",
    "Live camera feed with keypoint overlay",
    "3D URDF simulator mirroring real arm",
    "IK/FK arm control with speed slider",
    'One-click "Deploy to Robot"',
]

_bullet_list(slide, 1.0, 1.8, 5.5, 4.5, features, font_size=20)

# Placeholder boxes for screenshots
for i, label in enumerate(["Task View", "3D Sim", "Camera"]):
    x = 7.5
    y = 1.8 + i * 1.8
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(4.8), Inches(1.5))
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor(0x1A, 0x25, 0x3A)
    shape.line.color.rgb = MID_GRAY
    shape.line.width = Pt(1)
    tf = shape.text_frame
    tf.paragraphs[0].text = f"[ {label} screenshot ]"
    tf.paragraphs[0].font.size = Pt(16)
    tf.paragraphs[0].font.color.rgb = MID_GRAY
    tf.paragraphs[0].alignment = PP_ALIGN.CENTER
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE


# ═══════════════════════════════════════════════════════════════════════════
# SLIDE 8 — Why It Matters
# ═══════════════════════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
_dark_bg(slide)

_add_text(slide, 0.8, 0.6, 10, 0.8, "Why It Matters", font_size=40, bold=True, color=TEAL)
_teal_accent(slide, 1.4)

cards = [
    ("Quality",   "Machine-verified against spec,\nnot human memory"),
    ("Speed",     "Minutes, not hours\nper test point"),
    ("Safety",    "AI surfaces warnings\nbefore the probe touches"),
    ("Scalable",  "New doc = new capability,\nzero reprogramming"),
]

for i, (title, desc) in enumerate(cards):
    x = 0.8 + i * 3.1
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(2.2), Inches(2.8), Inches(3.5))
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor(0x1A, 0x25, 0x3A)
    shape.line.color.rgb = TEAL
    shape.line.width = Pt(2)

    # Title in box
    _add_text(slide, x + 0.3, 2.6, 2.2, 0.6, title,
              font_size=24, bold=True, color=TEAL, align=PP_ALIGN.CENTER)
    # Description
    _add_text(slide, x + 0.3, 3.5, 2.2, 2, desc,
              font_size=18, color=LIGHT_GRAY, align=PP_ALIGN.CENTER)


# ═══════════════════════════════════════════════════════════════════════════
# SLIDE 9 — Future Vision
# ═══════════════════════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
_dark_bg(slide)

_add_text(slide, 0.8, 0.6, 10, 0.8, "Future Vision", font_size=40, bold=True, color=TEAL)
_teal_accent(slide, 1.4)

_bullet_list(slide, 1.0, 2.0, 11, 4, [
    "Closed-loop: read measurement → compare to spec → decide next step",
    "Multi-arm orchestration for complex assemblies",
    "Factory floor deployment with fleet management",
    "Any robot, any document, any task",
], font_size=24)


# ═══════════════════════════════════════════════════════════════════════════
# SLIDE 10 — Closing
# ═══════════════════════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
_dark_bg(slide)

# Big teal rectangle accent bottom
shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(5.5), W, Inches(2))
shape.fill.solid()
shape.fill.fore_color.rgb = TEAL
shape.line.fill.background()

_add_text(slide, 1, 1.5, 11, 1.2, "DocOps", font_size=72, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
_add_text(slide, 1, 3.0, 11, 0.8,
          "From datasheet to done.  Zero code.  One PDF.",
          font_size=30, color=LIGHT_GRAY, align=PP_ALIGN.CENTER)

_add_text(slide, 1, 5.8, 11, 0.8,
          "Live demo available  ·  Golden Grippers  ·  Zurich Physical Hack 2026",
          font_size=20, bold=True, color=DARK_BG, align=PP_ALIGN.CENTER)


# ═══════════════════════════════════════════════════════════════════════════
out = r"c:\Users\jekatrinaj\Downloads\goldenGrippers\zurich_physical_hack\DocOps_Pitch.pptx"
prs.save(out)
print(f"✅ Saved to {out}")
