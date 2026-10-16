"""Deterministic layered layout for architecture / flow diagrams.

Pipeline (all in an abstract top-to-bottom frame; LR/RL/BT are produced by
transposing or mirroring at the end):

1. measure labels → one uniform node size (clean grid)
2. break cycles, assign layers (longest path, sources pulled to successors)
3. barycenter sweeps to reduce crossings → normalised lateral key per node
4. *band layout*: every group owns an exclusive horizontal band inside its
   parent, so a group box can never enclose a foreign node; stacked groups
   (disjoint layer spans) may share columns to stay compact
5. coordinates, group boxes (padding grows with nesting), then edge routing
   (see router.py)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .model import Graph, Group, Node
from . import router


@dataclass
class Options:
    min_node_w: float = 120
    max_node_w: float = 190
    min_node_h: float = 46
    font_size: float = 13
    line_h: float = 17
    pad_x: float = 14
    pad_y: float = 10
    col_gap: float = 44           # minimum horizontal gap between node columns
    layer_gap: float = 64         # vertical gap between layers (edge channel)
    group_pad: float = 14         # base padding of group boxes
    group_title_h: float = 20
    margin: float = 28
    title_h: float = 34
    track_gap: float = 10         # distance between parallel edge segments
    uniform_size: bool = True


# ---------------------------------------------------------------------------
# text measurement (rough, font-independent)
# ---------------------------------------------------------------------------
def char_w(ch: str, fs: float) -> float:
    o = ord(ch)
    if o >= 0x2E80 or 0xFF00 <= o <= 0xFFEF:      # CJK / full-width
        return fs * 1.0
    if ch == " ":
        return fs * 0.3
    if ch.isupper() or ch.isdigit():
        return fs * 0.64
    if ch in "il.,:;'|!":
        return fs * 0.3
    return fs * 0.54


def text_w(s: str, fs: float) -> float:
    return sum(char_w(c, fs) for c in s)


def wrap_text(s: str, fs: float, max_w: float) -> List[str]:
    out: List[str] = []
    for para in s.split("\n"):
        if text_w(para, fs) <= max_w:
            out.append(para)
            continue
        words = para.split(" ") if " " in para else None
        if words and all(text_w(w, fs) <= max_w for w in words):
            line = ""
            for w in words:
                cand = (line + " " + w).strip()
                if text_w(cand, fs) <= max_w or not line:
                    line = cand
                else:
                    out.append(line)
                    line = w
            if line:
                out.append(line)
        else:
            line = ""
            for ch in para:
                if text_w(line + ch, fs) <= max_w or not line:
                    line += ch
                else:
                    out.append(line)
                    line = ch
            if line:
                out.append(line)
    return out or [""]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
@dataclass
class _Band:
    """Layout state of one group (or the virtual root when gid is None)."""
    gid: Optional[str]
    subs: List["_Band"] = field(default_factory=list)
    directs: List[Node] = field(default_factory=list)
    width: int = 0
    off: int = 0                 # offset inside parent band
    abs_off: int = 0
    lo_layer: int = 0
    hi_layer: int = -1
    key: float = 0.0
    rows: List[tuple] = field(default_factory=list)   # (lo, hi, [nodes]) per layer, parent-relative

    def spans(self, layer: int) -> bool:
        return self.lo_layer <= layer <= self.hi_layer

    def overlaps(self, other: "_Band") -> bool:
        return self.lo_layer <= other.hi_layer and other.lo_layer <= self.hi_layer


def _break_cycles(g: Graph, order: List[str]) -> None:
    succ: Dict[str, List[int]] = {n: [] for n in g.nodes}
    for i, e in enumerate(g.edges):
        succ[e.src].append(i)
    WHITE, GREY, BLACK = 0, 1, 2
    color = {n: WHITE for n in g.nodes}

    def dfs(start: str) -> None:
        stack = [(start, iter(succ[start]))]
        color[start] = GREY
        while stack:
            v, it = stack[-1]
            advanced = False
            for ei in it:
                w = g.edges[ei].dst
                if color[w] == GREY:
                    g.edges[ei].reversed_for_layout = True
                elif color[w] == WHITE:
                    color[w] = GREY
                    stack.append((w, iter(succ[w])))
                    advanced = True
                    break
            if not advanced:
                color[v] = BLACK
                stack.pop()

    for n in order:
        if color[n] == WHITE:
            dfs(n)


def _dag_edges(g: Graph) -> List[Tuple[str, str]]:
    return [(e.dst, e.src) if e.reversed_for_layout else (e.src, e.dst) for e in g.edges]


def _assign_layers(g: Graph, order: List[str]) -> None:
    dag = _dag_edges(g)
    preds: Dict[str, List[str]] = {n: [] for n in g.nodes}
    succs: Dict[str, List[str]] = {n: [] for n in g.nodes}
    for a, b in dag:
        preds[b].append(a)
        succs[a].append(b)
    indeg = {n: len(preds[n]) for n in g.nodes}
    layer = {n: 0 for n in g.nodes}
    queue = [n for n in order if indeg[n] == 0]
    seen = 0
    while queue:
        v = queue.pop(0)
        seen += 1
        for w in succs[v]:
            layer[w] = max(layer[w], layer[v] + 1)
            indeg[w] -= 1
            if indeg[w] == 0:
                queue.append(w)
    # pull pure sources down towards their first successor
    for n in order:
        if not preds[n] and succs[n]:
            layer[n] = min(layer[w] for w in succs[n]) - 1
    # isolated nodes: sit at the first row of their group
    connected = {a for a, _ in dag} | {b for _, b in dag}
    for n in order:
        if n in connected:
            continue
        gid = g.nodes[n].group
        if gid is not None:
            mates = [layer[m.id] for m in g.members(gid) if m.id in connected]
            layer[n] = min(mates) if mates else 0
        else:
            layer[n] = 0
    # sinks that share a group line up on the group's bottom row
    # (data stores, external systems ...), which keeps group boxes compact
    for gid in g.groups:
        sinks = [m.id for m in g.members(gid) if m.id in connected and not succs[m.id]]
        if len(sinks) > 1:
            bottom = max(layer[s] for s in sinks)
            for s in sinks:
                layer[s] = bottom
    lo = min(layer.values()) if layer else 0
    for n in g.nodes.values():
        n.layer = layer[n.id] - lo


def _order_layers(g: Graph, order: List[str], sweeps: int = 6) -> Dict[str, float]:
    """Barycenter crossing reduction; returns normalised lateral key per node."""
    dag = _dag_edges(g)
    layers: Dict[int, List[str]] = {}
    for n in order:
        layers.setdefault(g.nodes[n].layer, []).append(n)
    L = max(layers) + 1 if layers else 0
    for k in range(L):
        layers.setdefault(k, [])
    nbrs_up: Dict[str, List[str]] = {n: [] for n in g.nodes}     # neighbours in layer-1
    nbrs_down: Dict[str, List[str]] = {n: [] for n in g.nodes}   # neighbours in layer+1 (or deeper)
    for a, b in dag:
        nbrs_down[a].append(b)
        nbrs_up[b].append(a)
    # keep nodes of the same group adjacent: secondary key = group chain
    gkey = {n.id: tuple(reversed(g.ancestors(n.group))) for n in g.nodes.values()}
    pos = {}

    def refresh():
        for k in range(L):
            cnt = len(layers[k])
            for i, n in enumerate(layers[k]):
                pos[n] = (i + 0.5) / cnt

    refresh()
    for it in range(sweeps):
        rng = range(1, L) if it % 2 == 0 else range(L - 2, -1, -1)
        nb = nbrs_up if it % 2 == 0 else nbrs_down
        for k in rng:
            row = layers[k]
            bary = {}
            for n in row:
                ns = [pos[m] for m in nb[n]]
                bary[n] = sum(ns) / len(ns) if ns else pos[n]
            # group barycenter so that members stay together
            grp_b: Dict[tuple, float] = {}
            for n in row:
                grp_b.setdefault(gkey[n], []).append(bary[n])
            grp_mean = {kk: sum(v) / len(v) for kk, v in grp_b.items()}
            row.sort(key=lambda n: (grp_mean[gkey[n]] if gkey[n] else bary[n], bary[n], pos[n]))
            layers[k] = row
            refresh()
    return pos


def _build_bands(g: Graph, pos: Dict[str, float]) -> _Band:
    bands: Dict[Optional[str], _Band] = {None: _Band(None)}
    for gid in g.groups:
        bands[gid] = _Band(gid)
    for gid, grp in g.groups.items():
        bands[grp.parent if grp.parent in bands else None].subs.append(bands[gid])
    for n in g.nodes.values():
        bands[n.group if n.group in bands else None].directs.append(n)

    def finish(b: _Band) -> None:
        for s in b.subs:
            finish(s)
        nodes = _band_nodes(b)
        if nodes:
            b.lo_layer = min(n.layer for n in nodes)
            b.hi_layer = max(n.layer for n in nodes)
            b.key = sum(pos[n.id] for n in nodes) / len(nodes)
        b.subs = [s for s in b.subs if _band_nodes(s)]       # drop empty groups
        _place_band(b, pos)

    finish(bands[None])
    return bands[None]


def _band_nodes(b: _Band) -> List[Node]:
    out = list(b.directs)
    for s in b.subs:
        out.extend(_band_nodes(s))
    return out


def _place_band(b: _Band, pos: Dict[str, float]) -> None:
    subs = sorted(b.subs, key=lambda s: s.key)
    layers = range(b.lo_layer, b.hi_layer + 1)
    directs_in = {L: sorted([n for n in b.directs if n.layer == L], key=lambda n: pos[n.id]) for L in layers}
    # 1. pack sub-bands left to right; stacked (layer-disjoint) ones may share columns
    placed: List[_Band] = []
    for s in subs:
        o = 0
        for p in placed:
            if p.overlaps(s):
                o = max(o, p.off + p.width)
        s.off = o
        placed.append(s)
    w_pack = max((s.off + s.width for s in subs), default=0)
    need = 0
    for L in layers:
        need = max(need, sum(s.width for s in subs if s.spans(L)) + len(directs_in[L]))
    b.width = max(w_pack, need, 1)
    # 2. centre every sub-band in the window its neighbours leave for it
    for s in subs:
        lo = max((p.off + p.width for p in subs if p is not s and p.overlaps(s) and p.off < s.off), default=0)
        hi = min((p.off for p in subs if p is not s and p.overlaps(s) and p.off > s.off), default=b.width)
        nl = max((sum(1 for d in directs_in[L] if pos[d.id] < s.key) for L in range(s.lo_layer, s.hi_layer + 1)), default=0)
        nr = max((sum(1 for d in directs_in[L] if pos[d.id] >= s.key) for L in range(s.lo_layer, s.hi_layer + 1)), default=0)
        lo2, hi2 = lo + nl, hi - nr
        if hi2 - lo2 >= s.width:
            s.off = lo2 + (hi2 - lo2 - s.width) // 2
    # 3. direct nodes fill the gaps between sub-bands, honouring lateral order
    for L in layers:
        ds = directs_in[L]
        if not ds:
            continue
        spanning = sorted([s for s in subs if s.spans(L)], key=lambda s: s.off)
        gaps: List[Tuple[int, int]] = []
        cursor = 0
        for s in spanning:
            gaps.append((cursor, s.off))
            cursor = s.off + s.width
        gaps.append((cursor, b.width))
        cap = [max(0, hi - lo) for lo, hi in gaps]
        want = [sum(1 for s in spanning if s.key <= pos[d.id]) for d in ds]
        buckets: List[List[Node]] = [[] for _ in gaps]
        for d, w in zip(ds, want):
            buckets[w].append(d)
        for i in range(len(gaps) - 1):               # spill right
            while len(buckets[i]) > cap[i]:
                buckets[i + 1].insert(0, buckets[i].pop())
        for i in range(len(gaps) - 1, 0, -1):        # spill left
            while len(buckets[i]) > cap[i]:
                buckets[i - 1].append(buckets[i].pop(0))
        for (lo, hi), items in zip(gaps, buckets):
            m = len(items)
            if not m:
                continue
            start = lo + (hi - lo - m) / 2
            for i, d in enumerate(items):
                d.col = start + i + 0.5           # centre position, parent-relative
            b.rows.append((lo, hi, items))


def _absolutise(b: _Band, base: int) -> None:
    b.abs_off = base
    for d in b.directs:
        d.col += base
    for s in b.subs:
        _absolutise(s, base + s.off)


def _all_bands(b: _Band) -> List[_Band]:
    out = [b]
    for s in b.subs:
        out.extend(_all_bands(s))
    return out


def _refine_rows(g: Graph, root: _Band, passes: int = 12) -> None:
    """Slide each row of direct nodes toward the barycenter of its neighbours,
    staying inside the gap the band reserved for it (so nothing can collide)."""
    nbrs: Dict[str, List[str]] = {n: [] for n in g.nodes}
    for e in g.edges:
        nbrs[e.src].append(e.dst)
        nbrs[e.dst].append(e.src)
    rows = [(b, lo, hi, items) for b in _all_bands(root) for (lo, hi, items) in b.rows]
    rows.sort(key=lambda r: r[3][0].layer)
    for p in range(passes):
        for b, lo, hi, items in (rows if p % 2 == 0 else rows[::-1]):
            m = len(items)
            wants = []
            for i, d in enumerate(items):
                ns = [g.nodes[x].col for x in nbrs[d.id] if g.nodes[x].layer != d.layer]
                if ns:
                    wants.append(sum(ns) / len(ns) - i - 0.5)
            if not wants:
                continue
            start = sum(wants) / len(wants)
            start = round(start * 2) / 2          # stay on the half-column grid → exact alignment
            start = min(max(start, b.abs_off + lo), b.abs_off + hi - m)
            for i, d in enumerate(items):
                d.col = start + i + 0.5


# ---------------------------------------------------------------------------
# public entry
# ---------------------------------------------------------------------------
def layout(g: Graph, opts: Optional[Options] = None) -> Graph:
    opts = opts or Options()
    if not g.nodes:
        g.width, g.height = 200, 100
        return g
    order = [n.id for n in sorted(g.nodes.values(), key=lambda n: n.order)]
    horizontal = g.direction in ("LR", "RL")

    # ---- 1. node sizes --------------------------------------------------
    fs = opts.font_size
    maxw_text = opts.max_node_w - 2 * opts.pad_x
    for n in g.nodes.values():
        n.lines = wrap_text(n.label, fs, maxw_text)
    widths, heights = [], []
    for n in g.nodes.values():
        tw = max(text_w(l, fs) for l in n.lines)
        extra = 1.0
        if n.shape in ("diamond", "circle", "hexagon"):
            extra = 1.35
        elif n.shape in ("parallelogram", "flag", "cylinder"):
            extra = 1.15
        w = min(max(tw * extra + 2 * opts.pad_x, opts.min_node_w), opts.max_node_w * 1.3)
        h = max(len(n.lines) * opts.line_h * (1.25 if n.shape in ("diamond", "cylinder") else 1.0)
                + 2 * opts.pad_y, opts.min_node_h)
        widths.append(w)
        heights.append(h)
        n.w, n.h = w, h
    if opts.uniform_size:
        W, H = max(widths), max(heights)
        for n in g.nodes.values():
            n.w, n.h = W, H
    # in the abstract frame "w" is the lateral extent and "h" the layer extent
    if horizontal:
        for n in g.nodes.values():
            n.w, n.h = n.h, n.w

    # ---- 2./3. layers + ordering -----------------------------------------
    _break_cycles(g, order)
    _assign_layers(g, order)
    pos = _order_layers(g, order)

    # ---- 4. bands ---------------------------------------------------------
    root = _build_bands(g, pos)
    _absolutise(root, 0)
    _refine_rows(g, root)

    # ---- 5. coordinates ---------------------------------------------------
    depth = {}
    for gid in g.groups:
        depth[gid] = len(g.ancestors(gid))
    max_depth = max(depth.values(), default=0)
    for gid, grp in g.groups.items():
        grp.depth = depth[gid]

    def k_of(gid: str) -> int:
        return max_depth - depth[gid] + 1

    pad = opts.group_pad
    node_w = max(n.w for n in g.nodes.values())
    node_h = max(n.h for n in g.nodes.values())
    col_gap = max(opts.col_gap, 2 * pad * max_depth + 16)
    col_step = node_w + col_gap
    n_layers = max(n.layer for n in g.nodes.values()) + 1

    # per-layer extra space for group borders / titles
    top_extra = [0.0] * n_layers
    bot_extra = [0.0] * n_layers
    group_members: Dict[str, List[Node]] = {gid: g.members(gid) for gid in g.groups}
    for gid, mem in group_members.items():
        if not mem:
            continue
        lo = min(n.layer for n in mem)
        hi = max(n.layer for n in mem)
        k = k_of(gid)
        top_extra[lo] = max(top_extra[lo], (opts.group_title_h + pad) * k)
        bot_extra[hi] = max(bot_extra[hi], pad * k)

    y0 = opts.margin + opts.layer_gap * 0.5
    layer_top = []
    y = y0
    for L in range(n_layers):
        y += top_extra[L]
        layer_top.append(y)
        y += node_h + bot_extra[L] + opts.layer_gap
    x_left = opts.margin + opts.layer_gap * 0.5 + pad * max_depth
    for n in g.nodes.values():
        n.x = x_left + n.col * col_step - n.w / 2
        n.y = layer_top[n.layer] + (node_h - n.h) / 2

    for gid, grp in g.groups.items():
        mem = group_members[gid]
        if not mem:
            grp.w = grp.h = 0
            continue
        k = k_of(gid)
        x1 = min(n.x for n in mem) - pad * k
        x2 = max(n.x + n.w for n in mem) + pad * k
        y1 = min(n.y for n in mem) - (opts.group_title_h + pad) * k
        y2 = max(n.y + n.h for n in mem) + pad * k
        grp.x, grp.y, grp.w, grp.h = x1, y1, x2 - x1, y2 - y1
    # nested boxes: make sure children sit inside parents (sizes may differ)
    for gid in sorted(g.groups, key=lambda x: -depth[x]):
        grp = g.groups[gid]
        if grp.parent and grp.w:
            p = g.groups[grp.parent]
            if p.w:
                kx = pad
                p_x1 = min(p.x, grp.x - kx)
                p_y1 = min(p.y, grp.y - opts.group_title_h - kx)
                p_x2 = max(p.x + p.w, grp.x + grp.w + kx)
                p_y2 = max(p.y + p.h, grp.y + grp.h + kx)
                p.x, p.y, p.w, p.h = p_x1, p_y1, p_x2 - p_x1, p_y2 - p_y1

    # ---- 6. edges -----------------------------------------------------------
    channels = []
    for L in range(n_layers + 1):
        top = (layer_top[L - 1] + node_h + bot_extra[L - 1]) if L > 0 else (y0 - opts.layer_gap)
        bot = (layer_top[L] - top_extra[L]) if L < n_layers else (layer_top[-1] + node_h + bot_extra[-1] + opts.layer_gap)
        channels.append((top, bot))
    router.route_edges(g, channels, opts.track_gap, opts.font_size - 2)

    # ---- 7. canvas, transposition ------------------------------------------
    _finish_frame(g, opts, horizontal)
    return g


def _finish_frame(g: Graph, opts: Options, horizontal: bool) -> None:
    xs, ys = [], []
    for n in g.nodes.values():
        xs += [n.x, n.x + n.w]
        ys += [n.y, n.y + n.h]
    for grp in g.groups.values():
        if grp.w:
            xs += [grp.x, grp.x + grp.w]
            ys += [grp.y, grp.y + grp.h]
    for e in g.edges:
        for (px, py) in e.points:
            xs.append(px)
            ys.append(py)
        if e.label_pos and e.label_size:
            xs += [e.label_pos[0] - e.label_size[0] / 2, e.label_pos[0] + e.label_size[0] / 2]
            ys += [e.label_pos[1] - e.label_size[1] / 2, e.label_pos[1] + e.label_size[1] / 2]
    minx, miny = min(xs) - opts.margin, min(ys) - opts.margin
    maxx, maxy = max(xs) + opts.margin, max(ys) + opts.margin
    mirror = g.direction in ("BT", "RL")

    def tf(x: float, y: float) -> Tuple[float, float]:
        x, y = x - minx, y - miny
        if mirror:
            y = (maxy - miny) - y
        if horizontal:
            x, y = y, x
        return x, y

    for n in g.nodes.values():
        x1, y1 = tf(n.x, n.y)
        x2, y2 = tf(n.x + n.w, n.y + n.h)
        n.x, n.y, n.w, n.h = min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)
    for grp in g.groups.values():
        if grp.w:
            x1, y1 = tf(grp.x, grp.y)
            x2, y2 = tf(grp.x + grp.w, grp.y + grp.h)
            grp.x, grp.y, grp.w, grp.h = min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)
    for e in g.edges:
        e.points = [tf(px, py) for px, py in e.points]
        if e.label_pos:
            e.label_pos = tf(*e.label_pos)
            if horizontal and e.label_size:
                pass  # label box keeps its text orientation
    w, h = maxx - minx, maxy - miny
    if horizontal:
        w, h = h, w
    title_h = opts.title_h if g.title else 0
    if title_h:
        for n in g.nodes.values():
            n.y += title_h
        for grp in g.groups.values():
            grp.y += title_h
        for e in g.edges:
            e.points = [(px, py + title_h) for px, py in e.points]
            if e.label_pos:
                e.label_pos = (e.label_pos[0], e.label_pos[1] + title_h)
        h += title_h
    g.width, g.height = w, h
