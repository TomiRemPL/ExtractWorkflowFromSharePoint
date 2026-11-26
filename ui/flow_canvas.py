"""Interaktywny edytor wizualny grafu (HTML/SVG + przeciąganie węzłów i łączenie portów)."""
from __future__ import annotations

import json
from typing import Any

from nicegui import ui

from core.automation_service import NODE_TITLES, resolve_alias_list_id, resolve_field_label
from tools.sp_automation.catalog import Catalog

_FLOW_ASSETS = """
<style>
  .dora-flow-wrap {
    position: relative;
    width: 100%;
    height: 520px;
    overflow: auto;
    border: 1px solid #cbd5e1;
    border-radius: 0.75rem;
    background-color: #f8fafc;
    background-image: radial-gradient(#cbd5e1 1px, transparent 1px);
    background-size: 20px 20px;
    user-select: none;
  }
  .dora-flow-stage {
    position: relative;
    width: 1800px;
    height: 1100px;
  }
  .dora-flow-svg {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
  }
  .dora-flow-svg .dora-edge-hit {
    pointer-events: stroke;
    cursor: pointer;
  }
  .dora-node {
    position: absolute;
    width: 176px;
    min-height: 68px;
    background: #ffffff;
    border: 2px solid #94a3b8;
    border-radius: 0.65rem;
    box-shadow: 0 2px 6px rgba(15, 23, 42, 0.08);
    cursor: grab;
    transition: box-shadow 0.12s ease, border-color 0.12s ease;
    font-family: inherit;
  }
  .dora-node:active { cursor: grabbing; }
  .dora-node.selected {
    border-color: #1d4ed8 !important;
    box-shadow: 0 0 0 3px rgba(29, 78, 216, 0.2);
  }
  .dora-node-hdr {
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 700;
    border-bottom: 1px solid #e2e8f0;
    border-radius: 0.5rem 0.5rem 0 0;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .dora-node-body {
    padding: 6px 10px;
    font-size: 12px;
    color: #1e293b;
    word-break: break-word;
  }
  .dora-port-in, .dora-port-out {
    position: absolute;
    width: 14px;
    height: 14px;
    border-radius: 9999px;
    background: #ffffff;
    border: 2px solid #475569;
    cursor: crosshair;
    z-index: 5;
  }
  .dora-port-in {
    left: -8px;
    top: 50%;
    transform: translateY(-50%);
  }
  .dora-port-in:hover { background: #dbeafe; border-color: #1d4ed8; }
  .dora-port-out {
    right: -8px;
  }
  .dora-port-out:hover, .dora-port-out.linking {
    background: #2563eb;
    border-color: #1e40af;
    transform: scale(1.2);
  }
  .dora-port-lbl {
    position: absolute;
    right: 10px;
    font-size: 10px;
    font-weight: 600;
    color: #475569;
    pointer-events: none;
  }
</style>
<script>
window.DoraFlow = window.DoraFlow || {
  state: { nodes: [], edges: [], layout: {}, selectedId: null, linking: null },
  colors: {
    start:     { border: '#059669', hdrBg: '#ecfdf5', hdrFg: '#065f46' },
    lookup:    { border: '#2563eb', hdrBg: '#eff6ff', hdrFg: '#1e40af' },
    condition: { border: '#d97706', hdrBg: '#fffbeb', hdrFg: '#92400e' },
    assign:    { border: '#4f46e5', hdrBg: '#eef2ff', hdrFg: '#3730a3' },
    merge:     { border: '#7c3aed', hdrBg: '#f5f3ff', hdrFg: '#5b21b6' },
    skip:      { border: '#64748b', hdrBg: '#f1f5f9', hdrFg: '#334155' },
    end:       { border: '#e11d48', hdrBg: '#fff1f2', hdrFg: '#9f1239' }
  },
    render(containerId, payload) {
    const root = document.getElementById(containerId);
    if (!root) return;
    if (payload) {
      this.state.nodes = payload.nodes || [];
      this.state.edges = payload.edges || [];
      this.state.layout = payload.layout || {};
      this.state.selectedId = payload.selectedId || null;
      this.state.titles = payload.titles || {};
      this.state.subtitles = payload.subtitles || {};
    }
    root.innerHTML = '';
    const stage = document.createElement('div');
    stage.className = 'dora-flow-stage';
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'dora-flow-svg');
    stage.appendChild(svg);
    root.appendChild(stage);

    const statusBadge = document.getElementById(containerId + '-hint');
    const updateHint = (txt) => { if (statusBadge) statusBadge.textContent = txt; };

    const getPos = (id, idx) => {
      const p = this.state.layout[id];
      if (p && typeof p.x === 'number' && typeof p.y === 'number') return { x: p.x, y: p.y };
      return { x: 80 + (idx % 4) * 240, y: 80 + Math.floor(idx / 4) * 140 };
    };

    const nodeEls = {};
    const nodePos = {};
    this.state.nodes.forEach((n, idx) => {
      nodePos[n.id] = getPos(n.id, idx);
    });

    const drawEdges = () => {
      svg.innerHTML = `
        <defs>
          <marker id="dora-arrow" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
            <polygon points="0 0, 10 3.5, 0 7" fill="#64748b"></polygon>
          </marker>
        </defs>`;
      this.state.edges.forEach((e, idx) => {
        const p1 = nodePos[e.from];
        const p2 = nodePos[e.to];
        if (!p1 || !p2) return;
        const fromNode = this.state.nodes.find(n => n.id === e.from);
        let yOff = 34;
        if (fromNode && fromNode.type === 'condition') {
          yOff = e.port === 'false' ? 50 : 22;
        }
        const x1 = p1.x + 176;
        const y1 = p1.y + yOff;
        const x2 = p2.x;
        const y2 = p2.y + 34;
        const dx = Math.max(50, Math.abs(x2 - x1) * 0.5);
        const d = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;

        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', d);
        path.setAttribute('fill', 'none');
        path.setAttribute('stroke', e.port === 'false' ? '#dc2626' : (e.port === 'true' ? '#16a34a' : '#64748b'));
        path.setAttribute('stroke-width', '2');
        path.setAttribute('marker-end', 'url(#dora-arrow)');
        svg.appendChild(path);

        const hit = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        hit.setAttribute('d', d);
        hit.setAttribute('fill', 'none');
        hit.setAttribute('stroke', 'transparent');
        hit.setAttribute('stroke-width', '14');
        hit.setAttribute('class', 'dora-edge-hit');
        hit.innerHTML = `<title>Kliknij, aby usunąć połączenie ${e.from} → ${e.to}</title>`;
        hit.addEventListener('click', (ev) => {
          ev.stopPropagation();
          emitEvent('dora_flow_edge_delete', { index: idx });
        });
        svg.appendChild(hit);

        if (e.port) {
          const tx = (x1 + x2) / 2;
          const ty = (y1 + y2) / 2 - 6;
          const lbl = document.createElementNS('http://www.w3.org/2000/svg', 'text');
          lbl.setAttribute('x', tx);
          lbl.setAttribute('y', ty);
          lbl.setAttribute('font-size', '11');
          lbl.setAttribute('font-weight', '700');
          lbl.setAttribute('fill', e.port === 'false' ? '#b91c1c' : '#15803d');
          lbl.textContent = e.port;
          svg.appendChild(lbl);
        }
      });
    };

    this.state.nodes.forEach((n, idx) => {
      const pos = nodePos[n.id];
      const c = this.colors[n.type] || { border: '#64748b', hdrBg: '#f8fafc', hdrFg: '#334155' };
      const el = document.createElement('div');
      el.className = 'dora-node' + (this.state.selectedId === n.id ? ' selected' : '');
      el.style.left = pos.x + 'px';
      el.style.top = pos.y + 'px';
      el.style.borderColor = c.border;

      const title = (this.state.titles && this.state.titles[n.type]) || n.type;
      const subtitle = (this.state.subtitles && this.state.subtitles[n.id]) || n.id;

      const hdr = document.createElement('div');
      hdr.className = 'dora-node-hdr';
      hdr.style.background = c.hdrBg;
      hdr.style.color = c.hdrFg;
      const titleSpan = document.createElement('span');
      titleSpan.textContent = title;
      const typeSpan = document.createElement('span');
      typeSpan.style.opacity = '0.7';
      typeSpan.textContent = n.type;
      hdr.appendChild(titleSpan);
      hdr.appendChild(typeSpan);
      const body = document.createElement('div');
      body.className = 'dora-node-body';
      body.textContent = subtitle;
      el.appendChild(hdr);
      el.appendChild(body);

      // Input port (for non-start nodes)
      if (n.type !== 'start') {
        const pin = document.createElement('div');
        pin.className = 'dora-port-in';
        pin.title = 'Port wejściowy (kliknij, aby zakończyć połączenie)';
        pin.addEventListener('click', (ev) => {
          ev.stopPropagation();
          if (this.state.linking && this.state.linking.from !== n.id) {
            const link = this.state.linking;
            this.state.linking = null;
            updateHint('Przeciągaj węzły, kliknij węzeł aby edytować, lub kliknij port wyjściowy (●) aby połączyć.');
            emitEvent('dora_flow_edge_add', { from: link.from, to: n.id, port: link.port });
          }
        });
        el.appendChild(pin);
      }

      // Output ports
      const ports = n.type === 'condition'
        ? [{ name: 'true', top: '20px' }, { name: 'false', top: '46px' }]
        : (n.type === 'end' || n.type === 'skip' ? [] : [{ name: 'next', top: '34px' }]);

      ports.forEach(pt => {
        const pout = document.createElement('div');
        pout.className = 'dora-port-out';
        pout.style.top = pt.top;
        pout.style.transform = 'translateY(-50%)';
        pout.title = pt.name ? `Port wyjściowy: ${pt.name} (kliknij i wskaż węzeł docelowy)` : 'Port wyjściowy (kliknij i wskaż węzeł docelowy)';
        pout.addEventListener('click', (ev) => {
          ev.stopPropagation();
          this.state.linking = { from: n.id, port: pt.name };
          pout.classList.add('linking');
          updateHint(`Łączenie z "${n.id}"${pt.name ? ' [' + pt.name + ']' : ''} — kliknij węzeł docelowy.`);
        });
        el.appendChild(pout);
        if (pt.name) {
          const plbl = document.createElement('span');
          plbl.className = 'dora-port-lbl';
          plbl.style.top = (parseInt(pt.top, 10) - 7) + 'px';
          plbl.textContent = pt.name;
          el.appendChild(plbl);
        }
      });

      // Dragging + Click select / finish link
      let dragging = false, moved = false, startX = 0, startY = 0, origX = pos.x, origY = pos.y;
      el.addEventListener('mousedown', (ev) => {
        if (ev.target.classList.contains('dora-port-out') || ev.target.classList.contains('dora-port-in')) return;
        dragging = true;
        moved = false;
        startX = ev.clientX;
        startY = ev.clientY;
        origX = nodePos[n.id].x;
        origY = nodePos[n.id].y;
        const onMove = (mev) => {
          if (!dragging) return;
          const dx = mev.clientX - startX;
          const dy = mev.clientY - startY;
          if (Math.abs(dx) > 3 || Math.abs(dy) > 3) moved = true;
          const nx = Math.max(10, Math.round(origX + dx));
          const ny = Math.max(10, Math.round(origY + dy));
          nodePos[n.id] = { x: nx, y: ny };
          el.style.left = nx + 'px';
          el.style.top = ny + 'px';
          drawEdges();
        };
        const onUp = () => {
          if (!dragging) return;
          dragging = false;
          window.removeEventListener('mousemove', onMove);
          window.removeEventListener('mouseup', onUp);
          if (moved) {
            emitEvent('dora_flow_node_move', { id: n.id, x: nodePos[n.id].x, y: nodePos[n.id].y });
          } else if (this.state.linking && this.state.linking.from !== n.id && n.type !== 'start') {
            const link = this.state.linking;
            this.state.linking = null;
            updateHint('Przeciągaj węzły, kliknij węzeł aby edytować, lub kliknij port wyjściowy (●) aby połączyć.');
            emitEvent('dora_flow_edge_add', { from: link.from, to: n.id, port: link.port });
          } else {
            this.state.linking = null;
            emitEvent('dora_flow_node_select', { id: n.id });
          }
        };
        window.addEventListener('mousemove', onMove);
        window.addEventListener('mouseup', onUp);
      });

      nodeEls[n.id] = el;
      stage.appendChild(el);
    });

    stage.addEventListener('click', () => {
      if (this.state.linking) {
        this.state.linking = null;
        updateHint('Przeciągaj węzły, kliknij węzeł aby edytować, lub kliknij port wyjściowy (●) aby połączyć.');
      }
    });

    drawEdges();
  }
};
</script>
"""


def register_flow_assets() -> None:
    """Rejestruje style i skrypt interaktywnego edytora przepływu w nagłówku strony."""
    ui.add_head_html(_FLOW_ASSETS, shared=True)


def _node_subtitle(node: dict[str, Any], graph: dict[str, Any], catalog: Catalog | None) -> str:
    nid = str(node.get("id") or "")
    kind = str(node.get("type") or "")
    if kind == "lookup" and node.get("as"):
        return f"{nid} ({node['as']})"
    if kind == "condition" and isinstance(node.get("condition"), dict) and node["condition"].get("op"):
        return f"{nid} [{node['condition']['op']}]"
    if kind == "assign" and node.get("field_id"):
        alias = str(node.get("alias") or "source")
        list_id = resolve_alias_list_id(graph, catalog, alias)
        label = resolve_field_label(catalog, str(node["field_id"]), list_id)
        if label:
            return f"{nid} → {label}"
    return nid


def build_flow_payload(
    graph: dict[str, Any],
    selected_id: str | None = None,
    catalog: Catalog | None = None,
) -> dict[str, Any]:
    """Buduje bezpieczny ładunek JSON do wyrenderowania płótna flow."""
    nodes = graph.get("nodes") or []
    subtitles = {
        str(n["id"]): _node_subtitle(n, graph, catalog)
        for n in nodes
        if isinstance(n, dict) and n.get("id")
    }
    return {
        "nodes": nodes,
        "edges": graph.get("edges") or [],
        "layout": graph.get("layout") or {},
        "selectedId": selected_id,
        "titles": NODE_TITLES,
        "subtitles": subtitles,
    }


def render_flow_canvas(
    container_id: str,
    graph: dict[str, Any],
    selected_id: str | None = None,
    catalog: Catalog | None = None,
) -> None:
    """Aktualizuje płótno flow po stronie przeglądarki."""
    payload = json.dumps(build_flow_payload(graph, selected_id, catalog), ensure_ascii=False)
    ui.run_javascript(f"window.DoraFlow && window.DoraFlow.render({json.dumps(container_id)}, {payload});")
