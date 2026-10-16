"""SVG renderer (no dependencies). Shares all geometry with the PPTX renderer."""
from __future__ import annotations

from typing import Dict, List
from xml.sax.saxutils import escape

from .model import Edge, Graph, Group, Node
from .theme import Theme, DEFAULT_THEME

FONT = '"Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", "Segoe UI", Arial, sans-serif'


def _shape_svg(n: Node, th: Theme) -> str:
    x, y, w, h = n.x, n.y, n.w, n.h
    style = f'fill="{th.node_fill}" stroke="{th.node_stroke}" stroke-width="1.5"'
    s = n.shape
    if s == "rect":
        return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="3" {style}/>'
    if s == "round":
        return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{min(w, h) * 0.18:.1f}" {style}/>'
    if s == "stadium":
        return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{h / 2:.1f}" {style}/>'
    if s == "circle":
        return f'<ellipse cx="{x + w / 2:.1f}" cy="{y + h / 2:.1f}" rx="{w / 2:.1f}" ry="{h / 2:.1f}" {style}/>'
    if s == "diamond":
        pts = f"{x + w / 2:.1f},{y:.1f} {x + w:.1f},{y + h / 2:.1f} {x + w / 2:.1f},{y + h:.1f} {x:.1f},{y + h / 2:.1f}"
        return f'<polygon points="{pts}" {style}/>'
    if s == "hexagon":
        d = min(w * 0.18, h / 2)
        pts = (f"{x + d:.1f},{y:.1f} {x + w - d:.1f},{y:.1f} {x + w:.1f},{y + h / 2:.1f} "
               f"{x + w - d:.1f},{y + h:.1f} {x + d:.1f},{y + h:.1f} {x:.1f},{y + h / 2:.1f}")
        return f'<polygon points="{pts}" {style}/>'
    if s == "parallelogram":
        d = min(w * 0.18, h * 0.5)
        pts = f"{x + d:.1f},{y:.1f} {x + w:.1f},{y:.1f} {x + w - d:.1f},{y + h:.1f} {x:.1f},{y + h:.1f}"
        return f'<polygon points="{pts}" {style}/>'
    if s == "flag":
        d = min(w * 0.12, h * 0.5)
        pts = f"{x:.1f},{y:.1f} {x + w - d:.1f},{y:.1f} {x + w:.1f},{y + h / 2:.1f} {x + w - d:.1f},{y + h:.1f} {x:.1f},{y + h:.1f}"
        return f'<polygon points="{pts}" {style}/>'
    if s == "subroutine":
        d = 7
        return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" {style}/>'
                f'<line x1="{x + d:.1f}" y1="{y:.1f}" x2="{x + d:.1f}" y2="{y + h:.1f}" stroke="{th.node_stroke}" stroke-width="1.5"/>'
                f'<line x1="{x + w - d:.1f}" y1="{y:.1f}" x2="{x + w - d:.1f}" y2="{y + h:.1f}" stroke="{th.node_stroke}" stroke-width="1.5"/>')
    if s == "cylinder":
        ry = min(h * 0.14, 10)
        body = (f'M{x:.1f},{y + ry:.1f} v{h - 2 * ry:.1f} a{w / 2:.1f},{ry:.1f} 0 0 0 {w:.1f},0 '
                f'v{-(h - 2 * ry):.1f} a{w / 2:.1f},{ry:.1f} 0 0 0 {-w:.1f},0 z')
        top = f'<ellipse cx="{x + w / 2:.1f}" cy="{y + ry:.1f}" rx="{w / 2:.1f}" ry="{ry:.1f}" {style}/>'
        return f'<path d="{body}" {style}/>{top}'
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" {style}/>'


def _text(cx: float, cy: float, lines: List[str], fs: float, color: str, line_h: float,
          weight: str = "normal", anchor: str = "middle", dy_offset: float = 0.0) -> str:
    n = len(lines)
    out = [f'<text x="{cx:.1f}" y="{cy:.1f}" font-size="{fs}" font-family=\'{FONT}\' fill="{color}" '
           f'text-anchor="{anchor}" font-weight="{weight}">']
    for i, l in enumerate(lines):
        dy = (i - (n - 1) / 2) * line_h + fs * 0.35 + dy_offset
        out.append(f'<tspan x="{cx:.1f}" y="{cy + dy:.1f}">{escape(l)}</tspan>')
    out.append("</text>")
    return "".join(out)


def _arrow_marker_id(style: str, start: bool) -> str:
    return f"ah-{style}-{'s' if start else 'e'}"


def to_svg(g: Graph, theme: Theme = DEFAULT_THEME, font_size: float = 13, line_h: float = 17) -> str:
    th = theme
    W, H = g.width, g.height
    out: List[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" viewBox="0 0 {W:.0f} {H:.0f}">',
        "<defs>",
        f'<marker id="ah-e" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" orient="auto">'
        f'<path d="M0,0 L10,5 L0,10 z" fill="{th.edge}"/></marker>',
        f'<marker id="ah-s" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="9" markerHeight="9" orient="auto">'
        f'<path d="M10,0 L0,5 L10,10 z" fill="{th.edge}"/></marker>',
        "</defs>",
        f'<rect width="100%" height="100%" fill="{th.background}"/>',
    ]
    if g.title:
        out.append(_text(W / 2, 24, [g.title], font_size + 5, th.text, line_h, weight="bold"))
    # groups: outer first
    for grp in sorted(g.groups.values(), key=lambda x: x.depth):
        if not grp.w:
            continue
        fill = th.group_fills[(grp.depth - 1) % len(th.group_fills)]
        out.append(f'<rect x="{grp.x:.1f}" y="{grp.y:.1f}" width="{grp.w:.1f}" height="{grp.h:.1f}" rx="6" '
                   f'fill="{fill}" stroke="{th.group_stroke}" stroke-width="1.2" stroke-dasharray="6 3"/>')
        out.append(_text(grp.x + 10, grp.y + 8, [grp.label], font_size - 1, th.group_text, line_h,
                         weight="bold", anchor="start", dy_offset=font_size * 0.5))
    for n in g.nodes.values():
        out.append(_shape_svg(n, th))
        out.append(_text(n.cx, n.cy, n.lines, font_size, th.text, line_h))
    for e in g.edges:
        if len(e.points) < 2:
            continue
        d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in e.points)
        dash = ' stroke-dasharray="6 4"' if e.style == "dashed" else ""
        width = 2.6 if e.style == "thick" else 1.6
        me = ' marker-end="url(#ah-e)"' if e.head else ""
        ms = ' marker-start="url(#ah-s)"' if e.tail else ""
        out.append(f'<path d="{d}" fill="none" stroke="{th.edge}" stroke-width="{width}" '
                   f'stroke-linejoin="round"{dash}{me}{ms}/>')
    for e in g.edges:
        if e.label and e.label_pos:
            lx, ly = e.label_pos
            lw, lh = e.label_size
            out.append(f'<rect x="{lx - lw / 2:.1f}" y="{ly - lh / 2:.1f}" width="{lw:.1f}" height="{lh:.1f}" '
                       f'rx="3" fill="{th.label_bg}" stroke="none"/>')
            out.append(_text(lx, ly, e.label.split("\n"), font_size - 2, th.edge_text, font_size + 2))
    out.append("</svg>")
    return "\n".join(out)
