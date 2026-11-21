"""Widok grafu powiązań list, niezależny od sposobu pobrania metadanych."""

from __future__ import annotations

import math
import tkinter as tk
from collections import Counter
from dataclasses import dataclass
from tkinter import ttk
from typing import Callable


@dataclass(frozen=True)
class MapNode:
    key: str
    title: str
    external: bool = False


@dataclass(frozen=True)
class MapEdge:
    key: str
    source: str
    target: str
    label: str


class RelationMap(ttk.Frame):
    """Interaktywny graf; szczegóły krawędzi są prezentowane poza płótnem."""

    def __init__(
        self,
        parent: tk.Misc,
        on_node: Callable[[str], None],
        on_edge: Callable[[str], None],
    ) -> None:
        super().__init__(parent)
        self.on_node = on_node
        self.on_edge = on_edge
        self.canvas = tk.Canvas(self, background="white", highlightthickness=0, height=260)
        horizontal = ttk.Scrollbar(self, orient=tk.HORIZONTAL, command=self.canvas.xview)
        vertical = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=horizontal.set, yscrollcommand=vertical.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

    def show(self, nodes: list[MapNode], edges: list[MapEdge]) -> None:
        self.canvas.delete("all")
        if not nodes:
            self.canvas.create_text(
                20, 20, anchor=tk.NW,
                text="Wybierz listy, aby zobaczyć relacje.",
                fill="#555555",
            )
            self.canvas.configure(scrollregion=(0, 0, 500, 300))
            return

        # A regular grid keeps the map usable for any exported site.
        columns = min(3, len(nodes))
        width, height = 220, 62
        dx, dy = 320, 150
        positions = {
            node.key: (150 + (index % columns) * dx, 55 + (index // columns) * dy)
            for index, node in enumerate(nodes)
        }
        counts = Counter((edge.source, edge.target) for edge in edges)
        offsets: Counter[tuple[str, str]] = Counter()
        for index, edge in enumerate(edges, 1):
            if edge.source not in positions or edge.target not in positions:
                continue
            start = positions[edge.source]
            end = positions[edge.target]
            tag = f"edge{index}"
            if start == end:
                x, y = start
                self.canvas.create_line(
                    [x + width / 2, y, x + width / 2 + 40, y - 45, x + 20, y - height / 2],
                    smooth=True, arrow=tk.LAST, fill="#486881", width=2, tags=(tag,),
                )
                label_x, label_y = x + width / 2 + 24, y - 35
            else:
                vx, vy = end[0] - start[0], end[1] - start[1]
                scale = min((width / 2) / abs(vx) if vx else math.inf,
                            (height / 2) / abs(vy) if vy else math.inf)
                sx, sy = start[0] + vx * scale, start[1] + vy * scale
                ex, ey = end[0] - vx * scale, end[1] - vy * scale
                length = math.hypot(vx, vy)
                pair = (edge.source, edge.target)
                offset = (offsets[pair] - (counts[pair] - 1) / 2) * 28
                offsets[pair] += 1
                mx = (sx + ex) / 2 - vy / length * offset
                my = (sy + ey) / 2 + vx / length * offset
                self.canvas.create_line(
                    [sx, sy, mx, my, ex, ey], smooth=True, arrow=tk.LAST,
                    fill="#486881", width=2, tags=(tag,),
                )
                label_x, label_y = mx, my
            self.canvas.create_oval(
                label_x - 12, label_y - 10, label_x + 12, label_y + 10,
                fill="white", outline="#486881", tags=(tag,),
            )
            self.canvas.create_text(label_x, label_y, text=str(index), fill="#23465c", tags=(tag,))
            self.canvas.tag_bind(tag, "<Button-1>", lambda _event, key=edge.key: self.on_edge(key))

        for index, node in enumerate(nodes):
            x, y = positions[node.key]
            tag = f"node{index}"
            self.canvas.create_rectangle(
                x - width / 2, y - height / 2, x + width / 2, y + height / 2,
                fill="#eef3f6" if node.external else "#dceefd",
                outline="#607d8b" if node.external else "#22638a",
                width=2, tags=(tag,),
            )
            self.canvas.create_text(x, y, text=node.title, width=width - 16, tags=(tag,))
            self.canvas.tag_bind(tag, "<Button-1>", lambda _event, key=node.key: self.on_node(key))

        rows = (len(nodes) + columns - 1) // columns
        self.canvas.configure(scrollregion=(0, 0, columns * dx + 30, rows * dy + 20))
