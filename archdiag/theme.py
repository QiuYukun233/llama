"""Colour themes. Values are hex strings usable by both SVG and PPTX."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class Theme:
    name: str = "blue"
    background: str = "#FFFFFF"
    node_fill: str = "#E8F0FE"
    node_stroke: str = "#3B5BA9"
    text: str = "#1F2933"
    edge: str = "#4B5563"
    edge_text: str = "#374151"
    label_bg: str = "#FFFFFF"
    group_stroke: str = "#8A96A8"
    group_text: str = "#4B5563"
    group_fills: List[str] = field(default_factory=lambda: ["#F5F7FB", "#EDF1F8", "#E4EAF4"])


THEMES = {
    "blue": Theme(),
    "gray": Theme(name="gray", node_fill="#F3F4F6", node_stroke="#4B5563", edge="#374151",
                  group_fills=["#FAFAFA", "#F3F4F6", "#E5E7EB"]),
    "green": Theme(name="green", node_fill="#E6F4EA", node_stroke="#2E7D4F", edge="#3F5F4A",
                   group_fills=["#F4FAF6", "#E9F5EE", "#DDF0E4"]),
    "warm": Theme(name="warm", node_fill="#FFF3E0", node_stroke="#B5651D", edge="#5F4B3A",
                  group_fills=["#FDF8F2", "#FAF0E4", "#F6E7D6"]),
    "dark": Theme(name="dark", background="#1E2430", node_fill="#2E3A4F", node_stroke="#8FB3FF",
                  text="#F3F4F6", edge="#C9D1E0", edge_text="#E5E7EB", label_bg="#1E2430",
                  group_stroke="#6B7A99", group_text="#C9D1E0",
                  group_fills=["#232B3A", "#283244", "#2D394E"]),
}
DEFAULT_THEME = THEMES["blue"]
