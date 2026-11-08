"""Card renderer: the broadcast-style "next up" still, plus its content record."""
import os
import re

from PIL import Image, ImageDraw, ImageFont

from portlandtv import library, store

AMBER, BG, RULE, DIM, SUB, TXT = "#e0a526", "#0b0d12", "#2a2e38", "#6b7080", "#a8acb8", "#d8dbe3"
RELEASE_TAG = re.compile(
    r"\b(?:\d{3,4}[pi]|4k|uhd|hdr|web(?:-?dl|rip)?|hdtv|dvdrip|b[dr]rip|blu-?ray|remux"
    r"|x26[45]|h ?26[45]|hevc|avc|xvid|aac|ac3|e?ac-?3|dts|ddp?\d?|flac|mp3"
    r"|repack|(?-i:PROPER|INTERNAL))\b", re.I)  # uppercase only: "The Proper Way" is a title
FONTS = {"sans": "DejaVuSans.ttf", "bold": "DejaVuSans-Bold.ttf"}


def describe(path, show_of, movies=()):
    """{name, subtitle} for an item path; `show_of` maps episode paths to show names,
    `movies` holds the movie paths."""
    stem = os.path.splitext(os.path.basename(path))[0]
    if path in movies:
        return {"name": stem, "subtitle": "Feature film"}
    if path not in show_of:
        return {"name": stem, "subtitle": ""}
    sxe = library.file_episode(stem)
    if not sxe:
        return {"name": show_of[path], "subtitle": ""}
    # the season the episode airs under, so a Season folder wins over the file name
    sub = f"Season {library.episode_key(path)[0]} · Episode {sxe[1]}"
    # release-style names: dots/underscores are spaces, and the first release tag ends the title
    title = re.sub(r"[._]+", " ", stem[sxe[2]:])
    title = RELEASE_TAG.split(title, 1)[0].strip(" -")
    return {"name": show_of[path], "subtitle": f"{sub} · {title}" if title else sub}


class _Frame:
    """A blank PORTLAND TV frame; the layout is drawn for 1920x1080 and scaled by `s`."""

    def __init__(self, size):
        self.W, self.H = size
        self.s = self.H / 1080
        self.im = Image.new("RGB", size, BG)
        self.d = ImageDraw.Draw(self.im)
        self.d.rectangle((0, 0, round(24 * self.s), self.H), fill=AMBER)

    def font(self, kind, px):
        return ImageFont.truetype(FONTS[kind], max(1, round(px * self.s)))

    def line(self, xy, text, kind, px, max_w, fill):
        """Draw text on one line within max_w: shrink it, and below 12 px cut it with "…"."""
        limit = max_w * self.s
        while px > 12 and self.d.textlength(text, font=self.font(kind, px)) > limit:
            px -= 2
        font = self.font(kind, px)
        if self.d.textlength(text, font=font) > limit:
            while text and self.d.textlength(text + "…", font=font) > limit:
                text = text[:-1]
            text = text.rstrip() + "…"
        self.d.text(xy, text, font=font, fill=fill)

    def save(self, path, record):
        """Add the wordmark; write the PNG and its content record beside it."""
        x = round(140 * self.s)
        self.d.text((self.W - x, self.H - 110 * self.s), "PORTLAND TV",
                    font=self.font("bold", 40), fill=AMBER, anchor="ra")
        store.write_atomic(path, lambda f: self.im.save(f, "PNG"))
        store.write_json(os.path.splitext(path)[0] + ".json", record)


def render_schedule(path, record, size):
    """Write one schedule display frame: `record` holds heading, range, page and rows
    ({time, name, subtitle, state: aired | up_next | later})."""
    f = _Frame(size)
    W, s, d, font, line = f.W, f.s, f.d, f.font, f.line
    x = round(140 * s)
    d.text((x, 90 * s), record["heading"], font=font("bold", 48), fill=AMBER)
    d.text((W - x, 90 * s), f"{record['range']}   {record['page']}", font=font("sans", 36),
           fill=DIM, anchor="ra")
    y = 200
    for row in record["rows"]:
        aired, up = row["state"] == "aired", row["state"] == "up_next"
        if up:
            d.rectangle((110 * s, (y - 14) * s, W - 110 * s, (y + 104) * s), fill="#1b1f29")
            d.rectangle((110 * s, (y - 14) * s, 122 * s, (y + 104) * s), fill=AMBER)
            d.text((W - 160 * s, (y + 10) * s), "UP NEXT", font=font("bold", 36), fill=AMBER,
                   anchor="ra")
        c = DIM if aired else ("white" if up else TXT)
        d.text((160 * s, y * s), row["time"], font=font("bold", 52), fill=AMBER if up else c)
        line((400 * s, y * s), row["name"], "bold", 52, W / s - 820, c)
        line((400 * s, (y + 62) * s), row["subtitle"], "sans", 30, W / s - 820,
             DIM if aired else SUB)
        y += 120
    f.save(path, record)


def render(path, items, size):
    """Write the card for `items` (up next, then up to two more; none = plain card)."""
    f = _Frame(size)
    W, s, d, font, line = f.W, f.s, f.d, f.font, f.line
    x, wide = round(140 * s), W / s - 280
    if items:
        nxt = items[0]
        d.text((x, 260 * s), "UP NEXT", font=font("bold", 48), fill=AMBER)
        line((x, 330 * s), nxt["name"], "bold", 112, wide, "white")
        line((x, 480 * s), nxt["subtitle"], "sans", 48, wide, SUB)
    if items[1:]:
        d.line((x, 640 * s, W - x, 640 * s), fill=RULE, width=max(1, round(3 * s)))
        d.text((x, 680 * s), "THEN", font=font("bold", 36), fill=DIM)
        col = (wide - 60) / 2
        for i, it in enumerate(items[1:3]):
            cx = x + i * (col + 60) * s
            line((cx, 740 * s), it["name"], "bold", 44, col, TXT)
            line((cx, 800 * s), it["subtitle"], "sans", 30, col, DIM)
    f.save(path, {"up_next": items[0] if items else None, "then": list(items[1:3])})
