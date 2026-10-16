"""Data model shared by the parser, layout engine and renderers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Shapes understood by every renderer.
SHAPES = (
    "rect", "round", "stadium", "cylinder", "diamond", "hexagon",
    "circle", "subroutine", "parallelogram", "flag",
)


@dataclass
class Node:
    id: str
    label: str
    shape: str = "rect"
    group: Optional[str] = None      # id of the innermost group, or None
    order: int = 0                    # order of first appearance in the source
    # ---- filled in by the layout engine (abstract px, top-left origin) ----
    layer: int = 0
    col: float = 0.0
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0
    lines: List[str] = field(default_factory=list)

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


@dataclass
class Edge:
    src: str
    dst: str
    label: str = ""
    style: str = "solid"              # solid | dashed | thick
    head: bool = True                 # arrow head at dst
    tail: bool = False                # arrow head at src (bidirectional)
    line_no: int = 0
    # ---- filled in by the layout engine ----
    reversed_for_layout: bool = False
    points: List[tuple] = field(default_factory=list)
    label_pos: Optional[tuple] = None
    label_size: Optional[tuple] = None


@dataclass
class Group:
    id: str
    label: str
    parent: Optional[str] = None
    order: int = 0
    # ---- filled in by the layout engine ----
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0
    depth: int = 0


@dataclass
class Issue:
    level: str                        # "error" | "warning"
    message: str
    line_no: int = 0
    line: str = ""

    def __str__(self) -> str:
        where = f"第 {self.line_no} 行" if self.line_no else "全局"
        tag = "错误" if self.level == "error" else "提示"
        txt = f"[{tag}] {where}: {self.message}"
        if self.line:
            txt += f"\n    > {self.line.strip()}"
        return txt


@dataclass
class Graph:
    direction: str = "TB"             # TB | BT | LR | RL
    title: str = ""
    nodes: Dict[str, Node] = field(default_factory=dict)
    edges: List[Edge] = field(default_factory=list)
    groups: Dict[str, Group] = field(default_factory=dict)
    issues: List[Issue] = field(default_factory=list)
    # ---- filled in by the layout engine ----
    width: float = 0.0
    height: float = 0.0

    # convenience -----------------------------------------------------
    def node(self, nid: str) -> Node:
        return self.nodes[nid]

    def group_of(self, nid: str) -> Optional[str]:
        return self.nodes[nid].group

    def ancestors(self, gid: Optional[str]) -> List[str]:
        """Chain of group ids from `gid` up to the root (inclusive of gid)."""
        out = []
        while gid is not None:
            out.append(gid)
            gid = self.groups[gid].parent
        return out

    def members(self, gid: str) -> List[Node]:
        """All nodes inside group `gid`, including nested groups."""
        return [n for n in self.nodes.values() if gid in self.ancestors(n.group)]

    def children_groups(self, gid: Optional[str]) -> List[Group]:
        return [g for g in self.groups.values() if g.parent == gid]

    @property
    def errors(self) -> List[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> List[Issue]:
        return [i for i in self.issues if i.level == "warning"]
