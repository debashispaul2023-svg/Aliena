"""Extract the 20 emotion images from assets/reference/aliena_emotion_sheet_v2.png.

The sheet is an RGBA PNG whose characters are ALREADY cut out (transparent
background in the alpha channel; a faint haze below alpha 33 is kept as glow). Connected
alpha regions are grouped per character (hair + hands + clothing + floating
effects such as hearts, '??', sparkles), and each group is written untouched
onto one common transparent canvas with PAD px of padding. Pixels are never
resized, recoloured or discarded; the validator proves that all opaque pixels
(alpha >= ALPHA_MIN) of the sheet end up in exactly one output.
Build-time tool (Pillow, numpy, scipy). The runtime never loads the sheet.
"""
import json, os, sys
import numpy as np
from PIL import Image
from scipy import ndimage as ndi

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHEET = os.path.join(ROOT, "assets", "reference", "aliena_emotion_sheet_v2.png")
OUT = os.path.join(ROOT, "assets", "aliena", "emotions")
COLS, ROWS, PAD = 5, 4, 24
ALPHA_MIN = 200          # body/effect pixels; below this is soft haze/glow (kept only as halo)
HALO_PX = 18             # faint glow pixels (alpha 1..32) within this distance of a group are kept with it
CLUSTER_PX = 14          # floating effect pieces closer than 2x this belong together
OPEN_R = 5               # opening radius that cuts thin bridges between touching characters
NAMES = [
    ["normal", "happy", "laugh", "sad", "angry"],
    ["thinking", "surprised", "shy", "sleepy", "excited"],
    ["confused", "embarrassed", "pouting", "wink", "cute"],
    ["calm", "talking", "pondering", "joyful", "shocked"],
]


def group_characters(alpha):
    """Return (label_map, groups, centroids, sizes). label_map labels every solid pixel;
    groups maps a character's main label -> all labels (effects, fringe) that belong to it."""
    solid = alpha >= ALPHA_MIN
    # characters in a column touch each other along thin hair/outline bridges: an opening
    # removes the bridges, leaving one big body per character.
    yy, xx = np.ogrid[-OPEN_R:OPEN_R + 1, -OPEN_R:OPEN_R + 1]
    disc = (xx * xx + yy * yy) <= OPEN_R * OPEN_R
    bodies = ndi.binary_opening(solid, structure=disc)
    blab, bn = ndi.label(bodies)
    bsizes = np.array(ndi.sum(bodies, blab, range(1, bn + 1)))
    mains = [int(i) + 1 for i in np.argsort(bsizes)[::-1][: COLS * ROWS]]
    if bn < COLS * ROWS or bsizes[[m - 1 for m in mains]].min() < 5000:
        raise SystemExit(f"cannot find {COLS * ROWS} characters (body sizes: {sorted(bsizes)[-24:]})")
    keep = np.isin(blab, mains)
    blab = np.where(keep, blab, 0)
    lab = blab.copy()
    # everything solid that is not a body (effects, outline fringe, bridges) -> leftover pieces
    left = solid & (lab == 0)
    llab, ln = ndi.label(left, structure=np.ones((3, 3)))
    boxes = ndi.find_objects(llab)
    bboxes = {m: ndi.find_objects((blab == m).astype(int))[0] for m in mains}
    def bdist(a, b):
        ya, xa = a; yb, xb = b
        return np.hypot(max(xb.start - xa.stop, xa.start - xb.stop, 0), max(yb.start - ya.stop, ya.start - yb.stop, 0))
    def inside_frac(piece_slice_mask, m, grow=12):
        ys, xs = np.where(piece_slice_mask)
        y, x = bboxes[m]
        ok = (ys >= y.start - grow) & (ys < y.stop + grow) & (xs >= x.start - grow) & (xs < x.stop + grow)
        return ok.mean()
    floating = []
    for i in range(1, ln + 1):
        piece = llab == i
        ring = ndi.binary_dilation(piece, structure=np.ones((3, 3)), iterations=2) & (blab > 0)
        if ring.any():                      # touches body/bodies: join the one whose box holds the piece
            cands = [int(o) for o in np.unique(blab[ring])]
            counts = {int(o): int((blab[ring] == o).sum()) for o in cands}
            lab[piece] = max(cands, key=lambda m: (round(inside_frac(piece, m), 2), counts[m]))
        else:
            floating.append(i)
    # floating effects ('??', hearts, sparkles): cluster pieces that sit close together, then give the
    # whole cluster to the body nearest to any of its pieces
    if floating:
        fm = np.isin(llab, floating)
        clab, cn = ndi.label(ndi.binary_dilation(fm, structure=np.ones((3, 3)), iterations=CLUSTER_PX))
        for c in range(1, cn + 1):
            pieces = [i for i in floating if (clab[llab == i] == c).any()]
            m = min(mains, key=lambda m: min(bdist(boxes[i - 1], bboxes[m]) for i in pieces))
            for i in pieces:
                lab[llab == i] = m
    groups = {m: [m] for m in mains}
    sizes = np.zeros(max(mains) + 1)
    cents = np.zeros((max(mains), 2))
    for m in mains:
        sizes[m] = (lab == m).sum()
        cents[m - 1] = ndi.center_of_mass(blab == m)
    return lab, groups, cents, sizes


def main():
    img = Image.open(SHEET).convert("RGBA")
    arr = np.array(img)
    H, W = arr.shape[:2]
    lab, groups, cents, sizes = group_characters(arr[..., 3])
    chars = []
    for main_id, members in groups.items():
        solid_g = np.isin(lab, members)
        others = (lab > 0) & ~solid_g
        mask = (ndi.binary_dilation(solid_g, structure=np.ones((3, 3)), iterations=HALO_PX)
                & (arr[..., 3] > 0) & ~others) | solid_g
        ys, xs = np.where(mask)
        my, mx = np.where(lab == main_id)
        chars.append(dict(main=main_id, mask=mask, solid=solid_g, box=(xs.min(), ys.min(), xs.max() + 1, ys.max() + 1),
                          cx=(mx.min() + mx.max()) / 2, bottom=my.max() + 1, cy=cents[main_id - 1][0]))
    # reading order: 4 rows by vertical centre, then left to right
    chars.sort(key=lambda c: c["cy"])
    ordered = []
    for r in range(ROWS):
        row = sorted(chars[r * COLS:(r + 1) * COLS], key=lambda c: c["cx"])
        ordered += row
    # one shared canvas: anchor = bottom-centre of the main body, so the face stays put between emotions
    L = max(c["cx"] - c["box"][0] for c in ordered); R = max(c["box"][2] - c["cx"] for c in ordered)
    T = max(c["bottom"] - c["box"][1] for c in ordered); B = max(c["box"][3] - c["bottom"] for c in ordered)
    cw, ch = int(np.ceil(L + R)) + 2 * PAD, int(np.ceil(T + B)) + 2 * PAD
    ax, ay = int(round(L)) + PAD, int(round(T)) + PAD
    os.makedirs(OUT, exist_ok=True)
    manifest = {"sheet": "assets/reference/aliena_emotion_sheet_v2.png", "canvas": [cw, ch],
                "anchor_bottom_center": [ax, ay], "padding": PAD, "emotions": {}}
    for k, c in enumerate(ordered):
        r, col = divmod(k, COLS)
        name = NAMES[r][col]
        out = np.zeros((ch, cw, 4), np.uint8)
        x0, y0, x1, y1 = c["box"]
        dx, dy = int(round(ax - (c["cx"] - x0))) , int(round(ay - (c["bottom"] - y0)))
        sub = arr[y0:y1, x0:x1].copy()
        sub[~c["mask"][y0:y1, x0:x1]] = 0
        out[dy:dy + (y1 - y0), dx:dx + (x1 - x0)] = sub
        Image.fromarray(out, "RGBA").save(os.path.join(OUT, name + ".png"), optimize=True)
        manifest["emotions"][name] = {"file": f"{name}.png", "row": r + 1, "col": col + 1,
                                      "source_box": [int(x0), int(y0), int(x1), int(y1)],
                                      "body_pixels": int(c["solid"].sum())}
    with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(len(ordered), "emotions, canvas", (cw, ch))


if __name__ == "__main__":
    sys.exit(main())
