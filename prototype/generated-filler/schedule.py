"""PROTOTYPE, throwaway: B-style schedule display, the whole Airing as multi-frame stills (issue #13).

Run:  python prototype/generated-filler/schedule.py  -> out/schedule-<n>.png
Each Airing gets its own frames (UTC start times differ per Airing); the upcoming Slot is highlighted,
earlier ones dimmed. ROWS items per frame, each frame aired 10 s.
"""
from cards import W, H, OUT, font, fit
from PIL import Image, ImageDraw

ROWS = 6
AMBER, BG, DIM, TXT = "#e0a526", "#0b0d12", "#4a4e5a", "#d8dbe3"

# One 8 h Airing starting 14:00 UTC; (start, name, subtitle). Filler is not listed.
AIRING = [
    ("14:00", "Star Trek: The Next Generation", "S3 · E15 · Yesterday's Enterprise"),
    ("14:46", "M*A*S*H", "S5 · E2"),
    ("15:12", "M*A*S*H", "S5 · E3"),
    ("15:38", "Master and Commander: The Far Side of the World", "Feature film"),
    ("17:58", "The Office", "S2 · E8 · Performance Review"),
    ("18:22", "The Office", "S2 · E9 · Email Surveillance"),
    ("18:46", "Band of Brothers", "E3 · Carentan"),
    ("19:54", "Top Gun", "Feature film"),
    ("21:50", "Cheers", "S4 · E1"),
]
UPCOMING = 4  # index of the Slot that plays after this Break


def frame(rows, first_index, page, pages):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 24, H), fill=AMBER)
    d.text((140, 90), "TODAY ON PORTLAND TV", font=font("bold", 48), fill=AMBER)
    d.text((W - 140, 90), f"14:00–22:00 UTC   {page}/{pages}", font=font("sans", 36), fill=DIM, anchor="ra")
    y = 200
    for i, (t, n, s) in enumerate(rows, first_index):
        past, up = i < UPCOMING, i == UPCOMING
        if up:
            d.rectangle((110, y - 14, W - 110, y + 104), fill="#1b1f29")
            d.rectangle((110, y - 14, 122, y + 104), fill=AMBER)
        c = DIM if past else ("white" if up else TXT)
        d.text((160, y), t, font=font("bold", 52), fill=AMBER if up else c)
        d.text((400, y), n, font=fit(d, n, "bold", 52, W - 820), fill=c)
        d.text((400, y + 62), s, font=font("sans", 30), fill=DIM if past else "#8a8f9c")
        if up:
            d.text((W - 160, y + 10), "UP NEXT", font=font("bold", 36), fill=AMBER, anchor="ra")
        y += 120
    d.text((W - 140, H - 110), "PORTLAND TV", font=font("bold", 40), fill=AMBER, anchor="ra")
    return im


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    pages = [AIRING[i:i + ROWS] for i in range(0, len(AIRING), ROWS)]
    for p, rows in enumerate(pages):
        frame(rows, p * ROWS, p + 1, len(pages)).save(OUT / f"schedule-{p + 1}.png")
    print("wrote", len(pages), "frames")
