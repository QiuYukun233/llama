"""Orthogonal edge routing on top of the layered layout.

Everything here works in the abstract top-to-bottom frame: layers are rows,
edges leave a node through the bottom (or top, for upward edges) and run
horizontally inside the *channel* between two rows.  Edges spanning several
rows use a free vertical *corridor* between columns.  Parallel segments in
the same channel/corridor are spread onto separate tracks so lines never
overlap, and ports along a node side are spread so arrows never share a tip.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .model import Edge, Graph, Node

Point = Tuple[float, float]
INF = float("inf")


def _center(ch: Tuple[float, float]) -> float:
    return (ch[0] + ch[1]) / 2


def _text_w(s: str, fs: float) -> float:
    from .layout import text_w
    return text_w(s, fs)


# ---------------------------------------------------------------------------
def route_edges(g: Graph, channels: List[Tuple[float, float]], track_gap: float, label_fs: float) -> None:
    nodes = g.nodes
    n_layers = len(channels) - 1
    rows: Dict[int, List[Node]] = {L: [] for L in range(n_layers)}
    for n in nodes.values():
        rows[n.layer].append(n)
    for L in rows:
        rows[L].sort(key=lambda n: n.x)

    # ---- 1. decide sides & collect port requests ------------------------
    # plan[i] = (kind, side_u, side_v)   kind: down | up | same_h | same_top
    plan: List[Tuple[str, str, str]] = []
    requests: Dict[Tuple[str, str], List[Tuple[int, str, float]]] = {}

    def req(nid: str, side: str, ei: int, end: str, other: float) -> None:
        requests.setdefault((nid, side), []).append((ei, end, other))

    for ei, e in enumerate(g.edges):
        u, v = nodes[e.src], nodes[e.dst]
        if u.layer < v.layer:
            plan.append(("down", "bottom", "top"))
            req(u.id, "bottom", ei, "src", v.cx)
            req(v.id, "top", ei, "dst", u.cx)
        elif u.layer > v.layer:
            plan.append(("up", "top", "bottom"))
            req(u.id, "top", ei, "src", v.cx)
            req(v.id, "bottom", ei, "dst", u.cx)
        else:
            row = rows[u.layer]
            lo, hi = sorted((u.cx, v.cx))
            between = any(lo < n.cx < hi for n in row if n is not u and n is not v)
            if not between:
                if u.cx <= v.cx:
                    plan.append(("same_h", "right", "left"))
                    req(u.id, "right", ei, "src", v.cy)
                    req(v.id, "left", ei, "dst", u.cy)
                else:
                    plan.append(("same_h", "left", "right"))
                    req(u.id, "left", ei, "src", v.cy)
                    req(v.id, "right", ei, "dst", u.cy)
            else:
                plan.append(("same_top", "top", "top"))
                req(u.id, "top", ei, "src", v.cx)
                req(v.id, "top", ei, "dst", u.cx)

    # ---- 2. spread ports along each side ----------------------------------
    port: Dict[Tuple[int, str], Point] = {}
    for (nid, side), entries in requests.items():
        n = nodes[nid]
        horizontal_side = side in ("top", "bottom")
        c = n.cx if horizontal_side else n.cy
        extent = n.w if horizontal_side else n.h
        tol = 0.75
        left = sorted([t for t in entries if t[2] < c - tol], key=lambda t: t[2])
        aligned = sorted([t for t in entries if abs(t[2] - c) <= tol], key=lambda t: t[0])
        right = sorted([t for t in entries if t[2] > c + tol], key=lambda t: t[2])
        spacing = min(track_gap * 1.2, extent * 0.7 / max(1, len(entries)))
        m = len(aligned)
        offs: Dict[Tuple[int, str], float] = {}
        for i, t in enumerate(aligned):
            offs[(t[0], t[1])] = (i - (m - 1) / 2) * spacing
        for i, t in enumerate(left):
            offs[(t[0], t[1])] = -((m - 1) / 2 + (len(left) - i)) * spacing
        for i, t in enumerate(right):
            offs[(t[0], t[1])] = ((m - 1) / 2 + i + 1) * spacing
        lim = extent / 2 - 3
        mx = max((abs(o) for o in offs.values()), default=0)
        if mx > lim > 0:
            offs = {k: o * lim / mx for k, o in offs.items()}
        for key, off in offs.items():
            if side == "bottom":
                port[key] = (n.cx + off, n.y + n.h)
            elif side == "top":
                port[key] = (n.cx + off, n.y)
            elif side == "right":
                port[key] = (n.x + n.w, n.cy + off)
            else:
                port[key] = (n.x, n.cy + off)

    # ---- 3. raw routes -------------------------------------------------------
    corridor_segs: List[Tuple[int, int]] = []        # (edge idx, point idx of corridor start)
    for ei, e in enumerate(g.edges):
        u, v = nodes[e.src], nodes[e.dst]
        kind, _, _ = plan[ei]
        (px, py), (qx, qy) = port[(ei, "src")], port[(ei, "dst")]
        pts: List[Point] = [(px, py)]
        if kind in ("down", "up"):
            if kind == "down":
                lu, lv = u.layer, v.layer
                t1 = _center(channels[lu + 1])
                t2 = _center(channels[lv])
                mids = range(lu + 1, lv)
            else:
                lu, lv = u.layer, v.layer
                t1 = _center(channels[lu])
                t2 = _center(channels[lv + 1])
                mids = range(lv + 1, lu)
            if abs(px - qx) <= 0.75 and not mids:
                pts.append((px, qy))
            elif not mids:
                pts += [(px, t1), (qx, t1), (qx, qy)]
            else:
                cx = _choose_corridor(g, rows, list(mids), u, v, px, qx)
                if abs(cx - px) <= 0.75:
                    pts += [(px, t2), (qx, t2), (qx, qy)]
                    if abs(px - qx) <= 0.75:
                        pts = [(px, py), (px, qy)]
                elif abs(cx - qx) <= 0.75:
                    pts += [(px, t1), (qx, t1), (qx, qy)]
                else:
                    pts += [(px, t1), (cx, t1), (cx, t2), (qx, t2), (qx, qy)]
                    corridor_segs.append((ei, 2))
        elif kind == "same_h":
            if abs(py - qy) <= 0.75:
                pts.append((qx, py))
            else:
                mx = (px + qx) / 2
                pts += [(mx, py), (mx, qy), (qx, qy)]
        else:  # same_top
            t = _center(channels[u.layer])
            pts += [(px, t), (qx, t), (qx, qy)]
        e.points = pts

    # ---- 4. spread parallel segments onto tracks -----------------------------
    _spread_horizontal(g, channels, track_gap)
    _spread_vertical(g, corridor_segs, track_gap)

    # ---- 5. clean up & labels ------------------------------------------------
    for e in g.edges:
        e.points = _simplify(e.points)
        if e.label:
            _place_label(e, label_fs)


# ---------------------------------------------------------------------------
def _choose_corridor(g: Graph, rows, mids: List[int], u: Node, v: Node, px: float, qx: float) -> float:
    margin = 8.0
    occupied: List[Tuple[float, float]] = []
    for L in mids:
        for n in rows[L]:
            occupied.append((n.x - margin, n.x + n.w + margin))
    inside = set(g.ancestors(u.group)) | set(g.ancestors(v.group))
    for gid, grp in g.groups.items():
        if gid in inside or not grp.w:
            continue
        mem = g.members(gid)
        if any(min(n.layer for n in mem) <= L <= max(n.layer for n in mem) for L in mids):
            occupied.append((grp.x - margin, grp.x + grp.w + margin))
    occupied.sort()
    merged: List[List[float]] = []
    for a, b in occupied:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    free: List[Tuple[float, float]] = []
    cur = -INF
    for a, b in merged:
        free.append((cur, a))
        cur = b
    free.append((cur, INF))
    pad = 4.0

    def ok(x: float) -> bool:
        return any(a + pad <= x <= b - pad for a, b in free)

    if ok(px):
        return px
    if ok(qx):
        return qx
    target = (px + qx) / 2
    best, best_d = None, INF
    for a, b in free:
        if a == -INF and b == INF:
            cand = target
        elif a == -INF:
            cand = min(target, b - pad)
        elif b == INF:
            cand = max(target, a + pad)
        elif b - a > 2 * pad + 2:
            cand = min(max(target, a + pad), b - pad)
        else:
            cand = (a + b) / 2
        d = abs(cand - target)
        if d < best_d:
            best, best_d = cand, d
    return best if best is not None else target


def _spread_horizontal(g: Graph, channels, track_gap: float) -> None:
    # group horizontal channel segments by their y
    by_y: Dict[float, List[Tuple[int, int]]] = {}
    for ei, e in enumerate(g.edges):
        for i in range(len(e.points) - 1):
            (x1, y1), (x2, y2) = e.points[i], e.points[i + 1]
            if abs(y1 - y2) < 1e-6 and abs(x1 - x2) > 1e-6:
                by_y.setdefault(round(y1, 3), []).append((ei, i))
    for y, segs in by_y.items():
        ch = next((c for c in channels if abs(_center(c) - y) < 1e-3), None)
        if ch is None or len(segs) < 2:
            continue
        segs.sort(key=lambda s: min(g.edges[s[0]].points[s[1]][0], g.edges[s[0]].points[s[1] + 1][0]))
        tracks: List[float] = []            # last x2 per track
        assign: List[int] = []
        for ei, i in segs:
            x1, x2 = sorted((g.edges[ei].points[i][0], g.edges[ei].points[i + 1][0]))
            for t, last in enumerate(tracks):
                if last + track_gap * 0.8 < x1:
                    tracks[t] = x2
                    assign.append(t)
                    break
            else:
                tracks.append(x2)
                assign.append(len(tracks) - 1)
        T = len(tracks)
        if T < 2:
            continue
        avail = max(ch[1] - ch[0] - 10, 4)
        gap = min(track_gap, avail / (T - 1))
        for (ei, i), t in zip(segs, assign):
            ny = y + (t - (T - 1) / 2) * gap
            pts = g.edges[ei].points
            pts[i] = (pts[i][0], ny)
            pts[i + 1] = (pts[i + 1][0], ny)


def _spread_vertical(g: Graph, corridor_segs: List[Tuple[int, int]], track_gap: float) -> None:
    by_x: Dict[float, List[Tuple[int, int]]] = {}
    for ei, i in corridor_segs:
        x = g.edges[ei].points[i][0]
        by_x.setdefault(round(x, 3), []).append((ei, i))
    for x, segs in by_x.items():
        if len(segs) < 2:
            continue
        segs.sort(key=lambda s: min(g.edges[s[0]].points[s[1]][1], g.edges[s[0]].points[s[1] + 1][1]))
        tracks: List[float] = []
        assign: List[int] = []
        for ei, i in segs:
            y1, y2 = sorted((g.edges[ei].points[i][1], g.edges[ei].points[i + 1][1]))
            for t, last in enumerate(tracks):
                if last + 1 < y1:
                    tracks[t] = y2
                    assign.append(t)
                    break
            else:
                tracks.append(y2)
                assign.append(len(tracks) - 1)
        T = len(tracks)
        if T < 2:
            continue
        gap = min(track_gap, 28 / (T - 1))
        for (ei, i), t in zip(segs, assign):
            nx = x + (t - (T - 1) / 2) * gap
            pts = g.edges[ei].points
            pts[i] = (nx, pts[i][1])
            pts[i + 1] = (nx, pts[i + 1][1])


def _simplify(pts: List[Point]) -> List[Point]:
    out: List[Point] = []
    for p in pts:
        if out and abs(out[-1][0] - p[0]) < 1e-6 and abs(out[-1][1] - p[1]) < 1e-6:
            continue
        out.append(p)
    changed = True
    while changed and len(out) > 2:
        changed = False
        for i in range(1, len(out) - 1):
            (ax, ay), (bx, by), (cx, cy) = out[i - 1], out[i], out[i + 1]
            if (abs(ax - bx) < 1e-6 and abs(bx - cx) < 1e-6) or (abs(ay - by) < 1e-6 and abs(by - cy) < 1e-6):
                del out[i]
                changed = True
                break
    return out


def _place_label(e: Edge, fs: float) -> None:
    pts = e.points
    best, best_len = 0, -1.0
    for i in range(len(pts) - 1):
        (x1, y1), (x2, y2) = pts[i], pts[i + 1]
        length = abs(x2 - x1) + abs(y2 - y1)
        if length > best_len + 1e-6:
            best, best_len = i, length
    (x1, y1), (x2, y2) = pts[best], pts[best + 1]
    e.label_pos = ((x1 + x2) / 2, (y1 + y2) / 2)
    lines = e.label.split("\n")
    w = max(_text_w(l, fs) for l in lines) + 10
    h = len(lines) * (fs + 4) + 4
    e.label_size = (w, h)
