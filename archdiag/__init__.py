"""archdiag — let any LLM draw clean architecture / flow diagrams.

The model only writes *what* exists (boxes, groups, arrows) in a tiny
Mermaid-like text or JSON; this package decides *where* everything goes and
how every arrow is routed, then emits PPTX / SVG.

    import archdiag
    archdiag.render("graph TD\\n A[Web] --> B[API] --> C[(DB)]", "arch.pptx")

    # inside an existing python-pptx deck
    archdiag.add_to_slide(slide, text, left, top, width, height)
"""
from __future__ import annotations

from typing import List, Optional

from .layout import Options, layout
from .model import Graph, Issue
from .parser import parse
from .theme import DEFAULT_THEME, THEMES, Theme

__all__ = ["parse", "layout", "render", "check", "add_to_slide", "to_svg", "to_pptx",
           "build", "Options", "Graph", "Issue", "Theme", "THEMES", "DEFAULT_THEME"]
__version__ = "0.1.0"


def check(text: str) -> List[Issue]:
    """Parse only; return problems (errors first) for feeding back to the model."""
    g = parse(text)
    return sorted(g.issues, key=lambda i: (i.level != "error", i.line_no))


def build(text: str, direction: Optional[str] = None, options: Optional[Options] = None,
          aspect: float = 16 / 9) -> Graph:
    """Parse + layout. Raises ValueError with all messages if there are errors.

    direction: TB / LR / BT / RL to override the source, or "auto" to pick the
    orientation (TB or LR) that fills a canvas of the given aspect ratio best.
    """
    g = parse(text)
    if g.errors:
        raise ValueError("\n".join(str(i) for i in g.errors))
    if direction and direction.lower() == "auto":
        import copy
        best, best_fit = None, -1.0
        for d in ("TB", "LR"):
            cand = copy.deepcopy(g)
            cand.direction = d
            layout(cand, options)
            fit = min(aspect / (cand.width / cand.height), (cand.width / cand.height) / aspect)
            if fit > best_fit:
                best, best_fit = cand, fit
        return best
    if direction:
        g.direction = direction.upper().replace("TD", "TB")
    return layout(g, options)


def to_svg(text_or_graph, theme: Theme = DEFAULT_THEME, **kw) -> str:
    from .render_svg import to_svg as _svg
    g = text_or_graph if isinstance(text_or_graph, Graph) else build(text_or_graph, **kw)
    return _svg(g, theme=theme)


def to_pptx(text_or_graph, path: Optional[str] = None, theme: Theme = DEFAULT_THEME, direction=None, **kw):
    from .render_pptx import to_pptx as _pptx
    g = text_or_graph if isinstance(text_or_graph, Graph) else build(text_or_graph, direction=direction)
    return _pptx(g, path, theme=theme, **kw)


def add_to_slide(slide, text_or_graph, left, top, width, height, theme: Theme = DEFAULT_THEME, **kw):
    """Draw the diagram into a box (EMU) on an existing python-pptx slide."""
    from .render_pptx import add_diagram
    g = text_or_graph if isinstance(text_or_graph, Graph) else build(text_or_graph)
    return add_diagram(slide, g, left, top, width, height, theme=theme, **kw)


def render(text: str, out_path: str, theme=None, direction: Optional[str] = None, **kw) -> Graph:
    """Render to .pptx / .svg / .png / .json depending on the extension."""
    th = THEMES.get(theme, DEFAULT_THEME) if isinstance(theme, str) or theme is None else theme
    g = build(text, direction=direction)
    ext = out_path.lower().rsplit(".", 1)[-1]
    if ext == "pptx":
        to_pptx(g, out_path, theme=th, **kw)
    elif ext == "svg":
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(to_svg(g, theme=th))
    elif ext == "png":
        from .raster import svg_to_png
        svg_to_png(to_svg(g, theme=th), out_path)
    elif ext == "json":
        import json
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(to_dict(g), f, ensure_ascii=False, indent=2)
    else:
        raise ValueError(f"不支持的输出格式 .{ext}（支持 pptx / svg / png / json）")
    return g


def to_dict(g: Graph) -> dict:
    """Layout result as plain data (for other renderers / debugging)."""
    return {
        "direction": g.direction, "title": g.title, "width": g.width, "height": g.height,
        "nodes": [{"id": n.id, "label": n.label, "shape": n.shape, "group": n.group,
                   "x": n.x, "y": n.y, "w": n.w, "h": n.h} for n in g.nodes.values()],
        "groups": [{"id": gr.id, "label": gr.label, "parent": gr.parent,
                    "x": gr.x, "y": gr.y, "w": gr.w, "h": gr.h} for gr in g.groups.values() if gr.w],
        "edges": [{"from": e.src, "to": e.dst, "label": e.label, "style": e.style,
                   "head": e.head, "tail": e.tail, "points": e.points, "label_pos": e.label_pos}
                  for e in g.edges],
        "issues": [{"level": i.level, "line": i.line_no, "message": i.message} for i in g.issues],
    }
