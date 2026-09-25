"""Generator nowoczesnego, interaktywnego portalu migracji workflow Nintex -> dowolny system / Oracle APEX."""
from __future__ import annotations

import json
from pathlib import Path


def _generate_html(workflows_data: list[dict]) -> str:
    """Generuje kompletny, responsywny kod HTML ze wsparciem Dark/Light mode, Mermaid i interaktywnym inspektorem."""
    json_payload = json.dumps(workflows_data, ensure_ascii=False, indent=2)

    return f"""<!doctype html>
<html lang="pl" class="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SharePoint Nintex Workflow Migration Portal</title>
  <style>
    :root {{
      --bg: #0f172a;
      --bg-surface: #1e293b;
      --bg-surface-elevated: #334155;
      --bg-card: #1e293b;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --text-dim: #64748b;
      --border: #334155;
      --border-focus: #38bdf8;
      --primary: #38bdf8;
      --primary-hover: #0284c7;
      --primary-bg: rgba(56, 189, 248, 0.12);
      --accent-blue: #38bdf8;
      --accent-green: #34d399;
      --accent-amber: #fbbf24;
      --accent-purple: #c084fc;
      --accent-red: #f87171;
      --shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5), 0 8px 10px -6px rgba(0, 0, 0, 0.5);
      --font-sans: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      --font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
    }}

    html.light {{
      --bg: #f8fafc;
      --bg-surface: #ffffff;
      --bg-surface-elevated: #f1f5f9;
      --bg-card: #ffffff;
      --text: #0f172a;
      --text-muted: #475569;
      --text-dim: #94a3b8;
      --border: #e2e8f0;
      --border-focus: #0284c7;
      --primary: #0284c7;
      --primary-hover: #0369a1;
      --primary-bg: rgba(2, 132, 199, 0.08);
      --accent-blue: #0284c7;
      --accent-green: #059669;
      --accent-amber: #d97706;
      --accent-purple: #7c3aed;
      --accent-red: #dc2626;
      --shadow: 0 10px 25px -5px rgba(15, 23, 42, 0.08), 0 8px 10px -6px rgba(15, 23, 42, 0.04);
    }}

    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      background: var(--bg);
      color: var(--text);
      font-family: var(--font-sans);
      font-size: 15px;
      line-height: 1.6;
      transition: background 0.2s, color 0.2s;
    }}

    .container {{
      max-width: 1440px;
      margin: 0 auto;
      padding: 0 24px;
    }}

    /* Header & Hero */
    header.hero {{
      background: linear-gradient(180deg, var(--bg-surface) 0%, var(--bg) 100%);
      border-bottom: 1px solid var(--border);
      padding: 40px 0 32px;
    }}
    .hero-top {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 16px;
    }}
    .badge-pill {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 12px;
      border-radius: 9999px;
      background: var(--primary-bg);
      color: var(--primary);
      font-size: 0.8rem;
      font-weight: 600;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      border: 1px solid rgba(56, 189, 248, 0.25);
    }}
    .theme-toggle {{
      background: var(--bg-surface);
      border: 1px solid var(--border);
      color: var(--text);
      padding: 6px 14px;
      border-radius: 8px;
      cursor: pointer;
      font-size: 0.85rem;
      font-weight: 500;
      display: flex;
      align-items: center;
      gap: 6px;
      transition: all 0.15s;
    }}
    .theme-toggle:hover {{
      border-color: var(--primary);
      color: var(--primary);
    }}
    h1.hero-title {{
      font-size: clamp(1.8rem, 3.5vw, 2.8rem);
      font-weight: 800;
      letter-spacing: -0.025em;
      line-height: 1.2;
      margin-bottom: 12px;
    }}
    p.hero-desc {{
      font-size: 1.05rem;
      color: var(--text-muted);
      max-width: 860px;
    }}

    /* Navbar / Toolbar */
    .sticky-nav {{
      position: sticky;
      top: 0;
      z-index: 40;
      background: rgba(15, 23, 42, 0.85);
      backdrop-filter: blur(12px);
      border-bottom: 1px solid var(--border);
      padding: 12px 0;
    }}
    html.light .sticky-nav {{
      background: rgba(248, 250, 252, 0.9);
    }}
    .nav-inner {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
    }}
    .nav-links {{
      display: flex;
      gap: 8px;
      overflow-x: auto;
    }}
    .nav-btn {{
      background: transparent;
      border: 1px solid transparent;
      color: var(--text-muted);
      padding: 8px 14px;
      border-radius: 6px;
      font-weight: 600;
      font-size: 0.9rem;
      cursor: pointer;
      transition: all 0.15s;
      white-space: nowrap;
    }}
    .nav-btn:hover {{
      color: var(--text);
      background: var(--bg-surface);
    }}
    .nav-btn.active {{
      color: var(--primary);
      background: var(--primary-bg);
      border-color: var(--primary);
    }}
    .search-box {{
      position: relative;
      flex: 1;
      max-width: 380px;
      min-width: 240px;
    }}
    .search-box input {{
      width: 100%;
      background: var(--bg-surface);
      border: 1px solid var(--border);
      color: var(--text);
      padding: 8px 14px 8px 36px;
      border-radius: 8px;
      font-size: 0.9rem;
      outline: none;
      transition: border 0.15s;
    }}
    .search-box input:focus {{
      border-color: var(--primary);
    }}
    .search-box svg {{
      position: absolute;
      left: 10px;
      top: 50%;
      transform: translateY(-50%);
      width: 16px;
      height: 16px;
      fill: var(--text-dim);
    }}

    /* Main layout & Metrics */
    main {{
      padding: 36px 0 80px;
    }}
    section {{
      margin-bottom: 64px;
      scroll-margin-top: 80px;
    }}
    .section-title {{
      font-size: 1.5rem;
      font-weight: 700;
      margin-bottom: 20px;
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .section-title span.number {{
      color: var(--primary);
      font-family: var(--font-mono);
      font-size: 1.1rem;
    }}

    .metrics-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin-bottom: 28px;
    }}
    .metric-card {{
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 20px;
      box-shadow: var(--shadow);
    }}
    .metric-val {{
      font-size: 2.2rem;
      font-weight: 800;
      color: var(--primary);
      font-family: var(--font-mono);
      line-height: 1;
      margin-bottom: 8px;
    }}
    .metric-label {{
      font-size: 0.88rem;
      color: var(--text-muted);
      font-weight: 500;
    }}

    /* Workflow Tabs */
    .wf-switcher {{
      display: flex;
      gap: 8px;
      min-width: 0;
      overflow-x: auto;
      overflow-y: hidden;
      padding-bottom: 12px;
      margin-bottom: 20px;
      border-bottom: 1px solid var(--border);
      scrollbar-width: auto;
      overscroll-behavior-inline: contain;
    }}
    .wf-tab {{
      padding: 10px 18px;
      background: var(--bg-surface);
      border: 1px solid var(--border);
      color: var(--text-muted);
      border-radius: 8px;
      cursor: pointer;
      flex: 0 0 auto;
      font-weight: 600;
      font-size: 0.92rem;
      white-space: nowrap;
      transition: all 0.15s;
    }}
    .wf-tab:hover {{
      color: var(--text);
      border-color: var(--text-dim);
    }}
    .wf-tab.active {{
      background: var(--primary-bg);
      color: var(--primary);
      border-color: var(--primary);
    }}

    /* Split Screen: Flowchart & Inspector */
    .split-view {{
      display: grid;
      grid-template-columns: 1fr 420px;
      gap: 24px;
      align-items: start;
    }}
    @media (max-width: 1080px) {{
      .split-view {{
        grid-template-columns: 1fr;
      }}
    }}

    .flow-container {{
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 24px;
      position: relative;
      min-height: 520px;
      box-shadow: var(--shadow);
      min-width: 0;
    }}
    .flow-toolbar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      margin-bottom: 16px;
      padding-bottom: 12px;
      border-bottom: 1px solid var(--border);
    }}
    .flow-hint {{
      min-width: 0;
      font-size: 0.85rem;
      color: var(--text-muted);
      display: flex;
      align-items: center;
      gap: 6px;
    }}
    .flow-controls {{
      display: inline-flex;
      flex: 0 0 auto;
      align-items: center;
      gap: 4px;
    }}
    .flow-control {{
      width: 32px;
      height: 30px;
      padding: 0;
      background: var(--bg-surface-elevated);
      border: 1px solid var(--border);
      border-radius: 5px;
      color: var(--text);
      cursor: pointer;
      font-size: 1rem;
      line-height: 1;
    }}
    .flow-control:hover {{
      color: var(--primary);
      border-color: var(--primary);
    }}
    .flow-zoom-label {{
      min-width: 48px;
      color: var(--text-muted);
      font-family: var(--font-mono);
      font-size: 0.75rem;
      text-align: center;
    }}
    .mermaid-wrapper {{
      height: min(68vh, 720px);
      min-height: 360px;
      overflow: auto;
      padding: 12px 0;
      text-align: left;
      scrollbar-width: auto;
      overscroll-behavior: contain;
      touch-action: none;
      cursor: grab;
    }}
    .mermaid-wrapper.is-panning {{
      cursor: grabbing;
    }}
    .mermaid-wrapper svg {{
      display: block;
      max-width: none;
      min-width: 0;
      width: max-content;
      height: auto;
      transform-origin: 0 0;
      user-select: none;
      pointer-events: auto;
      overflow: visible;
    }}
    /* Mermaid interactive tile styling */
    .mermaid-wrapper .node {{
      cursor: pointer;
      transition: filter 0.15s, transform 0.15s;
    }}
    .mermaid-wrapper .node:hover {{
      filter: drop-shadow(0 0 8px var(--primary));
    }}
    .mermaid-wrapper .node.selected rect,
    .mermaid-wrapper .node.selected polygon {{
      stroke: var(--primary) !important;
      stroke-width: 3px !important;
      filter: drop-shadow(0 0 10px var(--primary));
    }}

    /* Inspector Panel */
    .inspector-panel {{
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 24px;
      position: sticky;
      top: 80px;
      box-shadow: var(--shadow);
      display: flex;
      flex-direction: column;
      gap: 16px;
      max-height: calc(100vh - 110px);
      overflow-y: auto;
    }}
    .inspector-header {{
      display: flex;
      justify-content: space-between;
      align-items: start;
      gap: 12px;
      padding-bottom: 14px;
      border-bottom: 1px solid var(--border);
    }}
    .inspector-badge {{
      display: inline-block;
      font-size: 0.72rem;
      font-weight: 700;
      text-transform: uppercase;
      padding: 2px 8px;
      border-radius: 4px;
      background: var(--primary-bg);
      color: var(--primary);
      border: 1px solid var(--primary);
    }}
    .inspector-title {{
      font-size: 1.15rem;
      font-weight: 700;
      line-height: 1.3;
      margin-top: 4px;
    }}
    .inspector-field-group {{
      display: flex;
      flex-direction: column;
      gap: 6px;
    }}
    .inspector-field-group label {{
      font-size: 0.78rem;
      font-weight: 700;
      text-transform: uppercase;
      color: var(--text-dim);
      letter-spacing: 0.05em;
    }}
    .inspector-box {{
      background: var(--bg-surface-elevated);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px 12px;
      font-size: 0.9rem;
    }}
    .tag-badge {{
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 3px 7px;
      border-radius: 4px;
      font-size: 0.75rem;
      font-family: var(--font-mono);
      font-weight: 600;
      border: 1px solid;
    }}
    .tag-read {{
      background: rgba(52, 211, 153, 0.1);
      color: var(--accent-green);
      border-color: rgba(52, 211, 153, 0.3);
    }}
    .tag-write {{
      background: rgba(251, 191, 36, 0.1);
      color: var(--accent-amber);
      border-color: rgba(251, 191, 36, 0.3);
    }}
    .tag-list {{
      background: rgba(56, 189, 248, 0.1);
      color: var(--accent-blue);
      border-color: rgba(56, 189, 248, 0.3);
    }}
    .code-box {{
      font-family: var(--font-mono);
      font-size: 0.82rem;
      background: #090d16;
      color: #38bdf8;
      padding: 12px;
      border-radius: 6px;
      border: 1px solid var(--border);
      overflow-x: auto;
      white-space: pre-wrap;
    }}

    /* Data Dictionary Table */
    .card-table {{
      width: 100%;
      border-collapse: collapse;
      text-align: left;
      font-size: 0.88rem;
      margin-top: 12px;
    }}
    .card-table th {{
      padding: 10px 14px;
      background: var(--bg-surface-elevated);
      color: var(--text-muted);
      font-weight: 600;
      text-transform: uppercase;
      font-size: 0.76rem;
      letter-spacing: 0.05em;
      border-bottom: 1px solid var(--border);
    }}
    .card-table td {{
      padding: 12px 14px;
      border-bottom: 1px solid var(--border);
      vertical-align: middle;
    }}
    .copy-btn {{
      background: transparent;
      border: 1px solid var(--border);
      color: var(--text-dim);
      padding: 3px 7px;
      border-radius: 4px;
      font-size: 0.75rem;
      cursor: pointer;
      transition: all 0.15s;
    }}
    .copy-btn:hover {{
      color: var(--primary);
      border-color: var(--primary);
    }}

    /* Universal REST & APEX Guides */
    .docs-card {{
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 24px;
      margin-bottom: 20px;
      box-shadow: var(--shadow);
    }}
    .grid-2 {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
      gap: 20px;
    }}
    .callout {{
      padding: 14px 18px;
      border-radius: 8px;
      border-left: 4px solid;
      background: var(--bg-surface-elevated);
      margin: 14px 0;
      font-size: 0.92rem;
    }}
    .callout-info {{
      border-left-color: var(--accent-blue);
    }}
    .callout-warn {{
      border-left-color: var(--accent-amber);
    }}

    /* Toast */
    #toast {{
      position: fixed;
      bottom: 24px;
      right: 24px;
      background: var(--primary);
      color: #0f172a;
      font-weight: 700;
      font-size: 0.88rem;
      padding: 10px 18px;
      border-radius: 8px;
      box-shadow: var(--shadow);
      opacity: 0;
      transform: translateY(12px);
      transition: all 0.2s;
      pointer-events: none;
      z-index: 100;
    }}
    #toast.show {{
      opacity: 1;
      transform: translateY(0);
    }}
  </style>
</head>
<body>

  <!-- HERO -->
  <header class="hero">
    <div class="container">
      <div class="hero-top">
        <span class="badge-pill">Architektura migracji &middot; SharePoint &rarr; Docelowy system</span>
        <button id="theme-btn" class="theme-toggle" type="button">
          <span id="theme-icon">&#9790;</span>
          <span id="theme-text">Tryb jasny</span>
        </button>
      </div>
      <h1 class="hero-title">Centrum migracji Nintex Workflow</h1>
      <p class="hero-desc">
        Interaktywny portal techniczny wspierający przeniesienie logiki biznesowej SharePoint Nintex na dowolny silnik procesowy (w szczególności <strong>Oracle APEX Flow / PL/SQL</strong>) lub mikroserwisy REST.
      </p>
    </div>
  </header>

  <!-- STICKY NAVBAR -->
  <nav class="sticky-nav">
    <div class="container nav-inner">
      <div class="nav-links">
        <button class="nav-btn active" data-target="sec-inventory">Inwentaryzacja</button>
        <button class="nav-btn" data-target="sec-flows">Interaktywny diagram &amp; Inspektor</button>
        <button class="nav-btn" data-target="sec-fields">Słownik pól &amp; lookupy</button>
        <button class="nav-btn" data-target="sec-contract">Uniwersalny kontrakt REST</button>
        <button class="nav-btn" data-target="sec-apex">Oracle APEX &amp; PL/SQL</button>
        <button class="nav-btn" data-target="sec-checklist">Checklist wdrożeniowy</button>
      </div>
      <div class="search-box">
        <svg viewBox="0 0 24 24"><path d="M10 18a7.952 7.952 0 0 0 4.897-1.688l4.396 4.396 1.414-1.414-4.396-4.396A7.952 7.952 0 0 0 18 10c0-4.411-3.589-8-8-8s-8 3.589-8 8 3.589 8 8 8zm0-14c3.309 0 6 2.691 6 6s-2.691 6-6 6-6-2.691-6-6 2.691-6 6-6z"/></svg>
        <input type="search" id="global-search" placeholder="Szukaj akcji, pola, InternalName..." aria-label="Wyszukiwarka">
      </div>
    </div>
  </nav>

  <main class="container">

    <!-- SEKOR 1: INWENTARYZACJA -->
    <section id="sec-inventory">
      <h2 class="section-title"><span class="number">01.</span> Pulpit Inwentaryzacji</h2>
      <div class="metrics-grid">
        <div class="metric-card">
          <div class="metric-val" id="metric-wf-count">0</div>
          <div class="metric-label">Przetworzone przepływy Nintex</div>
        </div>
        <div class="metric-card">
          <div class="metric-val" id="metric-actions-count">0</div>
          <div class="metric-label">Akcje i reguły biznesowe</div>
        </div>
        <div class="metric-card">
          <div class="metric-val" id="metric-lists-count">0</div>
          <div class="metric-label">Listy SharePoint powiązane</div>
        </div>
        <div class="metric-card">
          <div class="metric-val" id="metric-fields-count">0</div>
          <div class="metric-label">Unikalne pola w regułach</div>
        </div>
      </div>
    </section>

    <!-- SEKCJA 2: INTERAKTYWNY DIAGRAM & INSPEKTOR -->
    <section id="sec-flows">
      <h2 class="section-title"><span class="number">02.</span> Eksplorator przepływu &amp; Inspektor kafelka</h2>

      <!-- Przełącznik aktywnego workflow -->
      <div class="wf-switcher" id="wf-tabs"></div>

      <div class="split-view">
        <!-- Lewy panel: Diagram -->
        <div class="flow-container">
          <div class="flow-toolbar">
            <span class="flow-hint">&#128070; Kliknij węzeł, aby zobaczyć szczegóły. Przeciągnij diagram lub użyj zoomu.</span>
            <div class="flow-controls" aria-label="Sterowanie diagramem">
              <button id="flow-zoom-out" class="flow-control" type="button" title="Pomniejsz" aria-label="Pomniejsz diagram">−</button>
              <span id="flow-zoom-label" class="flow-zoom-label">100%</span>
              <button id="flow-zoom-in" class="flow-control" type="button" title="Powiększ" aria-label="Powiększ diagram">+</button>
              <button id="flow-reset" class="flow-control" type="button" title="Resetuj widok" aria-label="Resetuj widok diagramu">↺</button>
            </div>
            <span id="active-wf-tag" class="tag-badge tag-list"></span>
          </div>
          <div class="mermaid-wrapper">
            <div id="mermaid-graph" class="mermaid"></div>
          </div>
        </div>

        <!-- Prawy panel: Inspektor kafelka -->
        <aside class="inspector-panel" id="inspector">
          <div class="inspector-header">
            <div>
              <span id="ins-type-badge" class="inspector-badge">Akcja</span>
              <h3 id="ins-title" class="inspector-title">Wybierz kafelek na diagramie</h3>
            </div>
            <span id="ins-node-id" class="tag-badge tag-read">ID: -</span>
          </div>

          <div class="inspector-field-group">
            <label>Cel biznesowy / Rola w procesie</label>
            <div id="ins-summary" class="inspector-box">Kliknij dowolny węzeł na schemacie po lewej stronie, aby przeanalizować warunki, modyfikowane pola i kod docelowy.</div>
          </div>

          <div class="inspector-field-group" id="group-condition" style="display:none;">
            <label>Warunek logiczny (Podstawa wykonania)</label>
            <div id="ins-condition" class="inspector-box code-box"></div>
          </div>

          <div class="inspector-field-group">
            <label>Pobierane pola wejściowe (Read)</label>
            <div id="ins-reads" class="inspector-box">-</div>
          </div>

          <div class="inspector-field-group">
            <label>Modyfikowane pola wyjściowe (Write)</label>
            <div id="ins-writes" class="inspector-box">-</div>
          </div>

          <div class="inspector-field-group">
            <label>Wskazówka implementacyjna (Uniwersalna)</label>
            <div id="ins-hint-univ" class="inspector-box">-</div>
          </div>

          <div class="inspector-field-group">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
              <label style="margin:0;">Implementacja PL/SQL (pakiet SHP_API)</label>
              <button class="copy-btn" id="copy-step-plsql" type="button" style="padding:2px 8px; font-size:0.75rem;">Kopiuj</button>
            </div>
            <div id="ins-hint-apex" class="code-box" style="white-space:pre-wrap; font-family:Consolas,monospace; font-size:0.8rem; max-height:220px; overflow-y:auto;">-</div>
          </div>

          <details>
            <summary style="font-size:0.8rem; font-weight:600; cursor:pointer; color:var(--text-muted);">Surowe parametry techniczne XML</summary>
            <div id="ins-raw" class="code-box" style="margin-top:8px;">-</div>
          </details>
        </aside>
      </div>

      <!-- Karta: Kompletna procedura PL/SQL dla wybranego workflow -->
      <div class="docs-card" style="margin-top:20px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; flex-wrap:wrap; gap:10px;">
          <div>
            <h3 style="margin:0 0 4px;" id="wf-plsql-title">Kompletna procedura orkiestracji PL/SQL (pakiet SHP_API)</h3>
            <p style="color:var(--text-muted); font-size:0.88rem; margin:0;">
              Gotowy do skompilowania w Oracle APEX szkielet procedury orkiestrujący wybrany workflow za pośrednictwem pakietu <code>SHP_API</code>.
            </p>
          </div>
          <button class="copy-btn" id="copy-full-plsql-btn" type="button" style="padding:8px 16px; font-weight:600;">Kopiuj całą procedurę PL/SQL</button>
        </div>
        <pre id="wf-plsql-procedure" class="code-box" style="max-height:420px; overflow:auto; font-family:Consolas,monospace; font-size:0.82rem; line-height:1.45;"></pre>
      </div>
    </section>

    <!-- SEKCJA 3: SŁOWNIK PÓL -->
    <section id="sec-fields">
      <h2 class="section-title"><span class="number">03.</span> Słownik pól i identyfikatory techniczne</h2>
      <div class="docs-card">
        <p style="color:var(--text-muted); margin-bottom:12px;">
          Tabela mapowania SharePoint <code>InternalName</code> na czytelne nazwy biznesowe. Użyj przycisku <strong>Kopiuj</strong>, aby pobrać identyfikator do zapytań SQL lub REST.
        </p>
        <div style="overflow-x:auto;">
          <table class="card-table" id="fields-table">
            <thead>
              <tr>
                <th>Nazwa biznesowa</th>
                <th>SharePoint InternalName</th>
                <th>Lista źródłowa</th>
                <th>Odczyt</th>
                <th>Zapis</th>
                <th>Akcja</th>
              </tr>
            </thead>
            <tbody></tbody>
          </table>
        </div>
      </div>
    </section>

    <!-- SEKCJA 4: UNIWERSALNY KONTRAKT REST -->
    <section id="sec-contract">
      <h2 class="section-title"><span class="number">04.</span> Uniwersalny kontrakt integracyjny REST</h2>
      <div class="grid-2">
        <div class="docs-card">
          <h3>Wywołanie procesu (POST)</h3>
          <p style="color:var(--text-muted); font-size:0.88rem; margin:8px 0 12px;">Standardowy endpoint dla systemów zewnętrznych (np. APEX, Camunda, ERP).</p>
          <div class="code-box">POST /api/v1/workflows/&#123;workflowKey&#125;/runs
Authorization: Bearer &lt;token&gt;
Idempotency-Key: &lt;unique-uuid&gt;
Content-Type: application/json

&#123;
  "itemId": 1234,
  "executionMode": "sync",
  "correlationId": "WF-REQ-2026-0091"
&#125;</div>
        </div>
        <div class="docs-card">
          <h3>Odpowiedź (200 OK / 202 Accepted)</h3>
          <p style="color:var(--text-muted); font-size:0.88rem; margin:8px 0 12px;">Odpowiedź synchroniczna z listą zmodyfikowanych pól lub asynchroniczna z adresem statusu.</p>
          <div class="code-box">HTTP/1.1 200 OK
Content-Type: application/json

&#123;
  "runId": "run_981ab2",
  "status": "COMPLETED",
  "changedFields": [
    "Us_x0142_uga_x0020_kwalifikowana",
    "Us_x0142_uga_x0020_krytyczna_x000"
  ],
  "finishedAt": "2026-09-18T16:00:00Z"
&#125;</div>
        </div>
      </div>
    </section>

    <!-- SEKCJA 5: ORACLE APEX / PL/SQL -->
    <section id="sec-apex">
      <h2 class="section-title"><span class="number">05.</span> Architektura wdrożenia w Oracle APEX &amp; pakiet SHP_API</h2>
      <div class="docs-card">
        <h3>Wzorzec orkiestracji w Flows for APEX i pakietach PL/SQL</h3>
        <p style="color:var(--text-muted); margin:8px 0 16px;">
          W środowisku Oracle APEX integracja z SharePoint SE 2019 realizowana jest bezpośrednio z bazy danych za pośrednictwem dedykowanego pakietu <code>SHP_API</code> (autoryzacja NTLMv2, obsługa transakcji REST MERGE/POST/GET).
        </p>

        <div class="code-box">-- Wzorzec orkiestracji procesu w PL/SQL za pomocą pakietu SHP_API
create or replace procedure pkg_workflow_migration.execute_qualification(
    p_item_id in number
) is
    c_site_url  constant varchar2(400) := 'https://sharepoint.domain.com/sites/...';
    l_item_json clob;
    l_resp      clob;
    l_is_ict    varchar2(10) := 'Nie';
begin
    apex_debug.info('Start kwalifikacji dla elementu: ' || p_item_id);

    -- 1. Pobranie danych elementu z SharePoint przez pakiet SHP_API
    l_item_json := shp_api.get_list_item(
        p_site_url   => c_site_url,
        p_list_title => 'Kwalifikacja Usług',
        p_item_id    => p_item_id
    );

    -- 2. Warunek bramki logicznej (odpowiednik DT01)
    if json_value(l_item_json, '$.data.DT_x002e_01') = 'Tak' then
        l_is_ict := 'Tak';
    else
        l_is_ict := 'Nie';
    end if;

    -- 3. Zapis wyniku do SharePoint przez SHP_API (MERGE z kontrolą ETag)
    l_resp := shp_api.update_list_item(
        p_site_url    => c_site_url,
        p_list_title  => 'Kwalifikacja Usług',
        p_item_id     => p_item_id,
        p_fields_json => json_object('Us_x0142_uga_x0020_kwalifikowana' value l_is_ict)
    );

    apex_debug.info('Zakończono kwalifikację dla elementu: ' || p_item_id);
end;</div>
      </div>
    </section>

    <!-- SEKCJA 6: CHECKLIST -->
    <section id="sec-checklist">
      <h2 class="section-title"><span class="number">06.</span> Kryteria odbioru i checklist wdrożenia</h2>
      <div class="docs-card">
        <ul style="list-style:none; display:grid; grid-template-columns:repeat(auto-fit, minmax(280px, 1fr)); gap:12px;">
          <li>&#9989; <strong>Weryfikacja kodowania:</strong> Eksporty CSV/JSON czytane jako UTF-8/UTF-16.</li>
          <li>&#9989; <strong>Współbieżność:</strong> Obsługa nagłówków ETag / optymistycznego blokowania.</li>
          <li>&#9989; <strong>Idempotencja:</strong> Ponowne wywołanie z tym samym kluczem nie duplikuje danych.</li>
          <li>&#9989; <strong>Audit Log:</strong> Zapis każdego przejścia procesu do tabeli historii wykonania.</li>
        </ul>
      </div>
    </section>

  </main>

  <div id="toast">Skopiowano do schowka!</div>

  <!-- Baza danych zebranych z parsera NWF osadzona jako JSON -->
  <script id="workflows-data" type="application/json">
{json_payload}
  </script>

  <!-- Skrypt Mermaid -->
  <script type="module">
    import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';

    const isLight = document.documentElement.classList.contains('light');
    mermaid.initialize({{
      startOnLoad: false,
      securityLevel: 'strict',
      theme: isLight ? 'default' : 'dark',
      themeVariables: {{
        primaryColor: isLight ? '#e0f2fe' : '#1e293b',
        primaryTextColor: isLight ? '#0f172a' : '#f8fafc',
        primaryBorderColor: '#38bdf8',
        lineColor: isLight ? '#94a3b8' : '#64748b'
      }}
    }});

    window._mermaid = mermaid;
    window.dispatchEvent(new CustomEvent('mermaidReady'));
  </script>

  <!-- Logika aplikacji i interakcji -->
  <script>
    (function() {{
      const rawData = document.getElementById('workflows-data').textContent;
      const workflows = JSON.parse(rawData);

      let activeIndex = 0;
      let activeNodeId = null;
      let activeWorkflow = null;

      // Elementy UI
      const wfTabsContainer = document.getElementById('wf-tabs');
      const mermaidContainer = document.getElementById('mermaid-graph');
      const activeWfTag = document.getElementById('active-wf-tag');
      const fieldsTbody = document.querySelector('#fields-table tbody');
      const toast = document.getElementById('toast');
      const mermaidWrapper = document.querySelector('.mermaid-wrapper');
      const zoomLabel = document.getElementById('flow-zoom-label');

      const viewState = {{
        scale: 1,
        minScale: 0.35,
        maxScale: 2.5,
        offsetX: 0,
        offsetY: 0,
        pointerId: null,
        startX: 0,
        startY: 0,
        startOffsetX: 0,
        startOffsetY: 0,
        startNodeEl: null,
        moved: false
      }};

      function updateZoomLabel() {{
        zoomLabel.textContent = String(Math.round(viewState.scale * 100)) + '%';
      }}

      function applyViewTransform() {{
        const svg = mermaidContainer.querySelector('svg');
        if (!svg) return;
        svg.style.transform = `translate(${{viewState.offsetX}}px, ${{viewState.offsetY}}px) scale(${{viewState.scale}})`;
        updateZoomLabel();
      }}

      function resetDiagramView() {{
        viewState.scale = 1;
        viewState.offsetX = 0;
        viewState.offsetY = 0;
        mermaidWrapper.scrollLeft = 0;
        mermaidWrapper.scrollTop = 0;
        applyViewTransform();
      }}

      function fitDiagramToViewport() {{
        const svg = mermaidContainer.querySelector('svg');
        if (!svg) {{
          resetDiagramView();
          return;
        }}
        const viewBox = svg.viewBox && svg.viewBox.baseVal;
        const diagramWidth = viewBox && viewBox.width ? viewBox.width : svg.getBoundingClientRect().width;
        const diagramHeight = viewBox && viewBox.height ? viewBox.height : svg.getBoundingClientRect().height;
        svg.style.width = Math.ceil(diagramWidth) + 'px';
        svg.style.height = Math.ceil(diagramHeight) + 'px';
        svg.style.overflow = 'visible';
        const availableWidth = Math.max(1, mermaidWrapper.clientWidth - 24);
        viewState.scale = Math.min(1, Math.max(viewState.minScale, availableWidth / Math.max(1, diagramWidth)));
        viewState.offsetX = 0;
        viewState.offsetY = 0;
        mermaidWrapper.scrollLeft = 0;
        mermaidWrapper.scrollTop = 0;
        applyViewTransform();
      }}

      function zoomDiagram(delta, clientX, clientY) {{
        const svg = mermaidContainer.querySelector('svg');
        if (!svg) return;
        const nextScale = Math.min(viewState.maxScale, Math.max(viewState.minScale, viewState.scale + delta));
        if (nextScale === viewState.scale) return;
        const rect = mermaidWrapper.getBoundingClientRect();
        const focusX = clientX - rect.left;
        const focusY = clientY - rect.top;
        const ratio = nextScale / viewState.scale;
        viewState.offsetX = focusX - (focusX - viewState.offsetX) * ratio;
        viewState.offsetY = focusY - (focusY - viewState.offsetY) * ratio;
        viewState.scale = nextScale;
        applyViewTransform();
      }}

      document.getElementById('flow-zoom-in').addEventListener('click', () => zoomDiagram(0.1, mermaidWrapper.clientWidth / 2, mermaidWrapper.clientHeight / 2));
      document.getElementById('flow-zoom-out').addEventListener('click', () => zoomDiagram(-0.1, mermaidWrapper.clientWidth / 2, mermaidWrapper.clientHeight / 2));
      document.getElementById('flow-reset').addEventListener('click', resetDiagramView);

      mermaidWrapper.addEventListener('wheel', (event) => {{
        event.preventDefault();
        zoomDiagram(event.deltaY < 0 ? 0.1 : -0.1, event.clientX, event.clientY);
      }}, {{ passive: false }});

      mermaidWrapper.addEventListener('pointerdown', (event) => {{
        if (event.button !== 0) return;
        viewState.pointerId = event.pointerId;
        viewState.startX = event.clientX;
        viewState.startY = event.clientY;
        viewState.startOffsetX = viewState.offsetX;
        viewState.startOffsetY = viewState.offsetY;
        viewState.startNodeEl = event.target.closest ? event.target.closest('.node') : null;
        viewState.moved = false;
        mermaidWrapper.setPointerCapture(event.pointerId);
      }});

      mermaidWrapper.addEventListener('pointermove', (event) => {{
        if (event.pointerId !== viewState.pointerId) return;
        const deltaX = event.clientX - viewState.startX;
        const deltaY = event.clientY - viewState.startY;
        if (Math.abs(deltaX) + Math.abs(deltaY) > 4) viewState.moved = true;
        viewState.offsetX = viewState.startOffsetX + deltaX;
        viewState.offsetY = viewState.startOffsetY + deltaY;
        mermaidWrapper.classList.toggle('is-panning', viewState.moved);
        applyViewTransform();
      }});

      function stopPanning(event) {{
        if (event.pointerId !== viewState.pointerId) return;
        viewState.pointerId = null;
        mermaidWrapper.classList.remove('is-panning');
        setTimeout(() => {{ viewState.moved = false; }}, 0);
      }}

      mermaidWrapper.addEventListener('pointerup', (event) => {{
        const wasPanning = viewState.moved;
        const pointEl = document.elementFromPoint(event.clientX, event.clientY);
        const nodeEl = (pointEl && pointEl.closest ? pointEl.closest('.node') : null) || viewState.startNodeEl;
        stopPanning(event);
        viewState.startNodeEl = null;
        if (wasPanning || !activeWorkflow) return;
        if (!nodeEl || !mermaidWrapper.contains(nodeEl)) return;
        const nodeId = resolveMermaidNodeId(nodeEl, activeWorkflow);
        if (!nodeId) {{
          console.warn('Nie rozpoznano identyfikatora węzła Mermaid:', nodeEl.id || nodeEl.textContent);
          return;
        }}
        mermaidWrapper.querySelectorAll('.node').forEach(n => n.classList.remove('selected'));
        nodeEl.classList.add('selected');
        inspectNode(activeWorkflow, nodeId);
        if (window.matchMedia('(max-width: 1080px)').matches) {{
          document.getElementById('inspector').scrollIntoView({{ behavior: 'smooth', block: 'start' }});
        }}
      }});
      mermaidWrapper.addEventListener('pointercancel', stopPanning);

      // Metryki
      document.getElementById('metric-wf-count').textContent = workflows.length;
      const totalActions = workflows.reduce((acc, w) => acc + w.actions_count, 0);
      document.getElementById('metric-actions-count').textContent = totalActions;

      const listsSet = new Set();
      const fieldsSet = new Set();
      workflows.forEach(w => {{
        if (w.source_list_name) listsSet.add(w.source_list_name);
        w.other_lists.forEach(l => listsSet.add(l));
        w.fields.forEach(f => fieldsSet.add(f.internal_name));
      }});
      document.getElementById('metric-lists-count').textContent = listsSet.size;
      document.getElementById('metric-fields-count').textContent = fieldsSet.size;

      // Funkcja renderujaca zakladki
      function renderTabs() {{
        wfTabsContainer.innerHTML = '';
        workflows.forEach((wf, idx) => {{
          const btn = document.createElement('button');
          btn.className = 'wf-tab' + (idx === activeIndex ? ' active' : '');
          btn.textContent = wf.title;
          btn.addEventListener('click', () => {{
            activeIndex = idx;
            renderTabs();
            renderActiveWorkflow();
            document.getElementById('sec-flows').scrollIntoView({{ behavior: 'smooth', block: 'start' }});
          }});
          wfTabsContainer.appendChild(btn);
        }});
      }}

      function filterWorkflowTabs(query) {{
        const q = query.toLowerCase().trim();
        const matchesWorkflow = (wf) => {{
          if (!q) return true;
          const searchable = [
            wf.title,
            wf.description,
            wf.source_list_name,
            ...(wf.other_lists || []),
            ...(wf.fields || []).flatMap(f => [f.display_name, f.internal_name]),
            ...(wf.steps || []).flatMap(s => [s.label, s.summary, s.short_type, s.condition_text])
          ].filter(Boolean).join(' ').toLowerCase();
          return searchable.includes(q);
        }};

        const matchingIndexes = workflows
          .map((wf, idx) => matchesWorkflow(wf) ? idx : -1)
          .filter(idx => idx >= 0);
        wfTabsContainer.querySelectorAll('.wf-tab').forEach((tab, idx) => {{
          tab.style.display = matchingIndexes.includes(idx) ? '' : 'none';
        }});
        return matchingIndexes;
      }}

      // Renderowanie aktywnego workflow
      async function renderActiveWorkflow() {{
        const wf = workflows[activeIndex];
        activeWorkflow = wf;
        activeWfTag.textContent = 'Lista: ' + wf.source_list_name;

        // Render Mermaid
        if (window._mermaid) {{
          mermaidContainer.replaceChildren();
          mermaidContainer.removeAttribute('data-processed');
          mermaidContainer.textContent = wf.mermaid_code;
          try {{
            await window._mermaid.run({{ nodes: [mermaidContainer] }});
            fitDiagramToViewport();
            bindMermaidInteractivity(wf);
          }} catch (e) {{
            console.error('Mermaid render error:', e);
            resetDiagramView();
          }}
        }}

        // Renderowanie tabeli pol
        renderFieldsTable(wf);

        // Aktualizacja kompletnej procedury PL/SQL
        const wfPlsqlTitle = document.getElementById('wf-plsql-title');
        if (wfPlsqlTitle) wfPlsqlTitle.textContent = 'Kompletna procedura PL/SQL: ' + wf.title;
        const wfPlsqlProc = document.getElementById('wf-plsql-procedure');
        if (wfPlsqlProc) wfPlsqlProc.textContent = wf.plsql_procedure || '-- Brak kodu procedury';

        // Reset inspektora
        resetInspector();
      }}

      // Podpinanie klikniec i dymkow w wygenerowanym SVG
      function resolveMermaidNodeId(nodeEl, wf) {{
        const knownIds = new Set((wf.steps || []).map(step => step.node_id).filter(Boolean));
        const candidates = [
          nodeEl.id || '',
          nodeEl.getAttribute('data-id') || '',
          nodeEl.getAttribute('data-node') || '',
          nodeEl.getAttribute('aria-label') || '',
        ].filter(Boolean);

        for (const candidate of candidates) {{
          if (knownIds.has(candidate)) return candidate;
          const directMatch = candidate.match(/(?:^|[-_])(start|stop|n\\d+)(?:[-_]|$)/);
          if (directMatch && knownIds.has(directMatch[1])) return directMatch[1];
        }}

        return Array.from(knownIds).find(id => candidates.some(candidate => candidate.includes(id))) || null;
      }}

      function bindMermaidInteractivity(wf) {{
        const svg = mermaidContainer.querySelector('svg');
        if (!svg) return;

        const nodes = svg.querySelectorAll('.node');
        nodes.forEach(nodeEl => {{
          const nodeId = resolveMermaidNodeId(nodeEl, wf);

          if (nodeId) {{
            nodeEl.style.cursor = 'pointer';
          }} else {{
            console.warn('Nie rozpoznano identyfikatora węzła Mermaid:', nodeEl.id || nodeEl.textContent);
          }}
        }});
      }}

      function inspectNode(wf, nodeId) {{
        activeNodeId = nodeId;
        const step = wf.steps.find(s => s.node_id === nodeId);
        if (!step) {{
          console.warn('Nie znaleziono danych dla węzła Mermaid:', nodeId);
          showToast('Brak danych dla wybranego węzła');
          return;
        }}

        document.getElementById('ins-node-id').textContent = 'KROK ' + nodeId;
        document.getElementById('ins-type-badge').textContent = step.short_type || 'Akcja';
        document.getElementById('ins-title').textContent = step.label || step.summary;
        document.getElementById('ins-summary').textContent = step.summary || 'Brak opisu.';

        const condGroup = document.getElementById('group-condition');
        if (step.condition_text) {{
          condGroup.style.display = 'flex';
          document.getElementById('ins-condition').textContent = step.condition_text;
        }} else {{
          condGroup.style.display = 'none';
        }}

        // Reads
        const readsBox = document.getElementById('ins-reads');
        if (step.reads && step.reads.length > 0) {{
          readsBox.innerHTML = step.reads.map(r =>
            `<span class="tag-badge tag-read">&#128269; ${{r.display_name}} (<code>${{r.internal_name}}</code>)</span>`
          ).join(' ');
        }} else {{
          readsBox.textContent = 'Brak (nie odczytuje pól)';
        }}

        // Writes
        const writesBox = document.getElementById('ins-writes');
        if (step.writes && step.writes.length > 0) {{
          writesBox.innerHTML = step.writes.map(w =>
            `<span class="tag-badge tag-write">&#9998; ${{w.display_name}} (<code>${{w.internal_name}}</code>)</span>`
          ).join(' ');
        }} else {{
          writesBox.textContent = 'Brak (nie zapisuje pól)';
        }}

        // Hints
        document.getElementById('ins-hint-univ').textContent = step.hint_universal || 'Brak dedykowanej wskazówki.';
        document.getElementById('ins-hint-apex').textContent = step.plsql_code || step.hint_apex || '-- Standardowa procedura PL/SQL.';

        // Raw
        document.getElementById('ins-raw').textContent = (step.technical_lines && step.technical_lines.length > 0)
          ? step.technical_lines.join('\\n')
          : 'Brak szczegółowych parametrów.';
      }}

      function resetInspector() {{
        document.getElementById('ins-node-id').textContent = 'ID: -';
        document.getElementById('ins-type-badge').textContent = 'Informacja';
        document.getElementById('ins-title').textContent = 'Wybierz kafelek na diagramie';
        document.getElementById('ins-summary').textContent = 'Kliknij dowolny węzeł na schemacie, aby zobaczyć powiązane pola SharePoint, warunki i wzorce kodu.';
        document.getElementById('group-condition').style.display = 'none';
        document.getElementById('ins-reads').textContent = '-';
        document.getElementById('ins-writes').textContent = '-';
        document.getElementById('ins-hint-univ').textContent = '-';
        document.getElementById('ins-hint-apex').textContent = '-';
        document.getElementById('ins-raw').textContent = '-';
      }}

      function renderFieldsTable(wf) {{
        fieldsTbody.innerHTML = '';
        wf.fields.forEach(f => {{
          const tr = document.createElement('tr');
          tr.innerHTML = `
            <td><strong>${{f.display_name}}</strong></td>
            <td><code>${{f.internal_name}}</code></td>
            <td><span class="tag-badge tag-list">${{f.list_name || wf.source_list_name}}</span></td>
            <td>${{f.is_read ? '<span class="tag-badge tag-read">TAK</span>' : '-'}}</td>
            <td>${{f.is_written ? '<span class="tag-badge tag-write">TAK</span>' : '-'}}</td>
            <td><button class="copy-btn" data-copy="${{f.internal_name}}">Kopiuj</button></td>
          `;
          fieldsTbody.appendChild(tr);
        }});

        // Obsluga kopiowania
        fieldsTbody.querySelectorAll('.copy-btn').forEach(btn => {{
          btn.addEventListener('click', () => {{
            const val = btn.dataset.copy;
            navigator.clipboard.writeText(val).then(() => {{
              showToast('Skopiowano: ' + val);
            }});
          }});
        }});

        // Obsluga kopiowania procedury i kroku PL/SQL
        const copyStepBtn = document.getElementById('copy-step-plsql');
        if (copyStepBtn) {{
          copyStepBtn.addEventListener('click', () => {{
            const code = document.getElementById('ins-hint-apex').textContent;
            if (code && code !== '-') {{
              navigator.clipboard.writeText(code).then(() => {{
                showToast('Skopiowano kod kroku PL/SQL!');
              }});
            }}
          }});
        }}

        const copyFullBtn = document.getElementById('copy-full-plsql-btn');
        if (copyFullBtn) {{
          copyFullBtn.addEventListener('click', () => {{
            const code = document.getElementById('wf-plsql-procedure').textContent;
            if (code) {{
              navigator.clipboard.writeText(code).then(() => {{
                showToast('Skopiowano całą procedurę PL/SQL!');
              }});
            }}
          }});
        }}
      }}

      function showToast(msg) {{
        toast.textContent = msg;
        toast.classList.add('show');
        setTimeout(() => toast.classList.remove('show'), 2000);
      }}

      // Przelacznik motywu (Dark / Light)
      const themeBtn = document.getElementById('theme-btn');
      const themeIcon = document.getElementById('theme-icon');
      const themeText = document.getElementById('theme-text');

      themeBtn.addEventListener('click', () => {{
        const isDark = document.documentElement.classList.toggle('dark');
        document.documentElement.classList.toggle('light', !isDark);
        themeIcon.innerHTML = isDark ? '&#9790;' : '&#9788;';
        themeText.textContent = isDark ? 'Tryb jasny' : 'Tryb ciemny';
        renderActiveWorkflow();
      }});

      // Globalna wyszukiwarka
      const searchInput = document.getElementById('global-search');
      searchInput.addEventListener('input', (e) => {{
        const q = e.target.value.toLowerCase().trim();
        const matchingIndexes = filterWorkflowTabs(q);

        const rows = fieldsTbody.querySelectorAll('tr');
        rows.forEach(r => {{
          const text = r.textContent.toLowerCase();
          r.style.display = (!q || text.includes(q)) ? '' : 'none';
        }});

        // Nawigacja sekcji z uwzględnieniem sticky headera.
        document.querySelectorAll('.nav-btn').forEach(btn => {{
          btn.addEventListener('click', () => {{
            const target = document.getElementById(btn.dataset.target);
            if (!target) return;
            document.querySelectorAll('.nav-btn').forEach(item => item.classList.remove('active'));
            btn.classList.add('active');
            target.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
          }});
        }});

        if (q && matchingIndexes.length > 0 && !matchingIndexes.includes(activeIndex)) {{
          activeIndex = matchingIndexes[0];
          renderTabs();
          filterWorkflowTabs(q);
          renderActiveWorkflow();
        }} else if (!q) {{
          renderTabs();
          renderFieldsTable(workflows[activeIndex]);
        }}
      }});

      // Inicjalizacja
      window.addEventListener('mermaidReady', () => {{
        renderTabs();
        renderActiveWorkflow();
      }});
      if (window._mermaid) {{
        renderTabs();
        renderActiveWorkflow();
      }}
    }})();
  </script>
</body>
</html>"""


def build_html_manual(workflows_data: list[dict], output_path: str | Path) -> Path:
    """Zapisuje kompletny plik HTML manuala migracji do wskazanego pliku docelowego."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    html_content = _generate_html(workflows_data)
    path.write_text(html_content, encoding="utf-8")
    return path
