"""PROTOTYPE, throwaway: four radically different "next up" cards for Generated Filler.

Question (issue #13): what should the still at the end of a Break look like?
Run:  python prototype/generated-filler/cards.py   -> writes out/<variant>-<sample>.png + out/sheet.png

Fonts: on the laptop these would be DejaVu Sans / DejaVu Sans Mono (apt fonts-dejavu-core);
here we fall back to whatever is on this machine.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
OUT = Path(__file__).parent / "out"

FONT_DIRS = [Path("/usr/share/fonts/truetype/dejavu"), Path("C:/Windows/Fonts")]
FONTS = {
    "sans": ["DejaVuSans.ttf", "arial.ttf"],
    "bold": ["DejaVuSans-Bold.ttf", "arialbd.ttf"],
    "mono": ["DejaVuSansMono.ttf", "consola.ttf"],
    "monob": ["DejaVuSansMono-Bold.ttf", "consolab.ttf"],
}


def font(kind, size):
    for d in FONT_DIRS:
        for name in FONTS[kind]:
            if (d / name).exists():
                return ImageFont.truetype(str(d / name), size)
    return ImageFont.load_default(size)


# What the generator knows about the next items: show name from the folder, season/episode
# from the path, an episode title only if the filename carries one. Cards never show clock times.
SAMPLES = {
    "episode": [
        {"kind": "episode", "show": "Star Trek: The Next Generation", "season": 3, "episode": 15, "title": "Yesterday's Enterprise"},
        {"kind": "movie", "title": "Master and Commander: The Far Side of the World"},
        {"kind": "episode", "show": "M*A*S*H", "season": 5, "episode": 2, "title": None},
    ],
    "movie": [
        {"kind": "movie", "title": "Master and Commander: The Far Side of the World"},
        {"kind": "episode", "show": "M*A*S*H", "season": 5, "episode": 2, "title": None},
        {"kind": "episode", "show": "Star Trek: The Next Generation", "season": 3, "episode": 16, "title": "The Offspring"},
    ],
}


def name(item):
    return item["show"] if item["kind"] == "episode" else item["title"]


def sub(item):
    if item["kind"] == "movie":
        return "Feature film"
    s = f"Season {item['season']} · Episode {item['episode']}"
    return f"{s} · {item['title']}" if item["title"] else s


def fit(draw, text, kind, size, max_w):
    """Shrink until the text fits on one line; prototype-grade wrapping."""
    while size > 20 and draw.textlength(text, font=font(kind, size)) > max_w:
        size -= 4
    return font(kind, size)


# A: the baseline from issue #10, plain text on a colour.
def variant_a(items):
    im = Image.new("RGB", (W, H), "#14325c")
    d = ImageDraw.Draw(im)
    nxt = items[0]
    d.text((W / 2, 380), "NEXT UP", font=font("bold", 64), fill="#9fb7d9", anchor="mm")
    d.text((W / 2, 520), name(nxt), font=fit(d, name(nxt), "bold", 120, W - 200), fill="white", anchor="mm")
    d.text((W / 2, 650), sub(nxt), font=fit(d, sub(nxt), "sans", 52, W - 200), fill="#cfdcef", anchor="mm")
    return im


# B: broadcast style, title hard left, a "then" rail below, channel bug in the corner.
def variant_b(items):
    im = Image.new("RGB", (W, H), "#0b0d12")
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 24, H), fill="#e0a526")
    d.text((140, 260), "UP NEXT", font=font("bold", 48), fill="#e0a526")
    d.text((140, 330), name(items[0]), font=fit(d, name(items[0]), "bold", 112, W - 280), fill="white")
    d.text((140, 480), sub(items[0]), font=fit(d, sub(items[0]), "sans", 48, W - 280), fill="#a8acb8")
    d.line((140, 640, W - 140, 640), fill="#2a2e38", width=3)
    d.text((140, 680), "THEN", font=font("bold", 36), fill="#6b7080")
    x = 140
    for it in items[1:]:
        d.text((x, 740), name(it), font=fit(d, name(it), "bold", 44, 780), fill="#d8dbe3")
        d.text((x, 800), sub(it), font=fit(d, sub(it), "sans", 30, 780), fill="#6b7080")
        x += 840
    d.text((W - 140, H - 110), "PORTLAND TV", font=font("bold", 40), fill="#e0a526", anchor="ra")
    return im


# C: a schedule display, the Airing as a list with the next item highlighted (order, not times).
def variant_c(items):
    im = Image.new("RGB", (W, H), "#f2efe6")
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, W, 150), fill="#1d2b3a")
    d.text((120, 75), "PORTLAND TV  ·  COMING UP", font=font("bold", 56), fill="#f2efe6", anchor="lm")
    y = 230
    for i, it in enumerate(items):
        hi = i == 0
        if hi:
            d.rectangle((80, y - 20, W - 80, y + 230), fill="#1d2b3a")
        fg, sf = ("#ffffff", "#c9d3dd") if hi else ("#1d2b3a", "#6b6558")
        d.text((140, y), "NEXT" if hi else f"{i + 1}.", font=font("bold", 40), fill="#e07a26" if hi else sf)
        d.text((340, y - 6), name(it), font=fit(d, name(it), "bold", 84 if hi else 56, W - 500), fill=fg)
        d.text((340, y + (120 if hi else 80)), sub(it), font=fit(d, sub(it), "sans", 40 if hi else 32, W - 500), fill=sf)
        y += 300 if hi else 190
    return im


# D: ship's-teletype nod to USS Portland, monospace, green on black, like a plan-of-the-day printout.
def variant_d(items):
    im = Image.new("RGB", (W, H), "#050805")
    d = ImageDraw.Draw(im)
    g, dim = "#5dff7a", "#2c7a3a"
    m = font("mono", 44)
    lines = [
        ("FM: PORTLAND TV", dim),
        ("TO: ALL HANDS", dim),
        ("SUBJ: NEXT ON THE CHANNEL", dim),
        ("", g),
        ("1. " + name(items[0]).upper(), g),
        ("   " + sub(items[0]).upper(), g),
        ("", g),
        ("2. FOLLOWED BY:", dim),
    ] + [("   - " + name(it).upper(), dim) for it in items[1:]] + [("", g), ("BT", dim)]
    y = 150
    for text, c in lines:
        f = font("monob", 64) if text.startswith("1.") else m
        if text.startswith("1."):
            f = fit(d, text, "monob", 64, W - 280)
        d.text((140, y), text, font=f, fill=c)
        y += 84 if text.startswith("1.") else 62
    return im


VARIANTS = {"A-plain": variant_a, "B-broadcast": variant_b, "C-schedule": variant_c, "D-teletype": variant_d}

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    thumbs = []
    for vname, fn in VARIANTS.items():
        for sname, items in SAMPLES.items():
            im = fn(items)
            im.save(OUT / f"{vname}-{sname}.png")
            thumbs.append(im.resize((W // 4, H // 4)))
    sheet = Image.new("RGB", (W // 4 * 2 + 30, (H // 4 + 10) * len(VARIANTS) + 10), "#888")
    for i, t in enumerate(thumbs):
        sheet.paste(t, (10 + (i % 2) * (W // 4 + 10), 10 + (i // 2) * (H // 4 + 10)))
    sheet.save(OUT / "sheet.png")
    print("wrote", len(thumbs), "cards to", OUT)
