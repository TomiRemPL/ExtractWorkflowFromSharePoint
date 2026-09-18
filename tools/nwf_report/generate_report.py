"""CLI: generuje raporty Markdown z opisem dzialania workflow Nintex (.nwf).

Uzycie:
    py generate_report.py --input DaneZeSkryptu --output out
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from nwf_report.action_catalog import UNKNOWN_TYPES_SEEN
    from nwf_report.html_builder import build_html_manual
    from nwf_report.metadata_loader import FieldResolver, load_site_metadata
    from nwf_report.nwf_parser import iter_actions, parse_nwf
    from nwf_report.report_builder import build_report, build_workflow_data
else:
    from .action_catalog import UNKNOWN_TYPES_SEEN
    from .html_builder import build_html_manual
    from .metadata_loader import FieldResolver, load_site_metadata
    from .nwf_parser import iter_actions, parse_nwf
    from .report_builder import build_report, build_workflow_data


def _safe_filename(name: str) -> str:
    return "".join(c if c.isalnum() or c in " _-." else "_" for c in name).strip()


def _build_walkthrough(items: list[dict], unknown_types: set[str]) -> str:
    total = len(items)
    successful = sum(1 for it in items if it.get("status") == "OK")
    failed = total - successful

    lines = [
        "# Podsumowanie przetwarzania przepływów pracy (Walkthrough)",
        "",
        "Raport podsumowujący przebieg generowania dokumentacji z plików `.nwf`.",
        "",
        "## Statystyki wykonania",
        "",
        f"- **Liczba znalezionych plików `.nwf`:** {total}",
        f"- **Pomyślnie przetworzone:** {successful}",
        f"- **Błędy parsowania:** {failed}",
        f"- **Nierozpoznane typy akcji:** {len(unknown_types)}",
        "",
        "## Wykaz przepływów",
        "",
        "| Lp. | Workflow | Plik źródłowy | Lista źródłowa | Liczba akcji | Raport Markdown | Status |",
        "|---|---|---|---|---|---|---|",
    ]

    for idx, it in enumerate(items, start=1):
        report_link = f"[{it['out_name']}]({it['out_name']})" if it.get("out_name") != "-" else "-"
        lines.append(
            f"| {idx} | {it['title']} | `{it['nwf_name']}` | {it['source_list']} | {it['actions_count']} | {report_link} | {it['status']} |"
        )

    if unknown_types:
        lines.append("")
        lines.append("## Typy akcji bez dedykowanego opisu (do uzupełnienia)")
        lines.append("")
        for t in sorted(unknown_types):
            lines.append(f"- `{t}`")

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generator raportow Markdown z plikow .nwf (Nintex Workflow)")
    parser.add_argument("--input", required=True, help="Katalog z plikami .nwf i metadanymi JSON (DaneZeSkryptu)")
    parser.add_argument("--output", required=True, help="Katalog docelowy na raporty Markdown")
    args = parser.parse_args()

    input_dir = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    site_metadata = load_site_metadata(input_dir)

    nwf_files = sorted(input_dir.glob("*.nwf"))
    if not nwf_files:
        print(f"Brak plikow .nwf w {input_dir}", file=sys.stderr)
        sys.exit(1)

    index_lines = ["# Raporty workflow Nintex", ""]
    summary_items: list[dict] = []
    workflows_data: list[dict] = []

    for nwf_path in nwf_files:
        try:
            wf = parse_nwf(nwf_path)
        except Exception as exc:  # nie przerywaj calego batcha z powodu jednego uszkodzonego pliku
            print(f"BLAD parsowania {nwf_path.name}: {exc}", file=sys.stderr)
            summary_items.append({
                "nwf_name": nwf_path.name,
                "title": "-",
                "source_list": "-",
                "out_name": "-",
                "actions_count": 0,
                "status": f"BŁĄD: {exc}",
            })
            continue

        resolver = FieldResolver(wf.list_references, site_metadata, source_list_id=(wf.source_list.list_id if wf.source_list else ""))
        report_md = build_report(wf, resolver)
        wf_data = build_workflow_data(wf, resolver)
        workflows_data.append(wf_data)

        out_name = _safe_filename(wf.title or nwf_path.stem) + ".md"
        (output_dir / out_name).write_text(report_md, encoding="utf-8")
        src_list = wf.source_list
        src_name = src_list.list_name if src_list else "?"
        index_lines.append(
            f"- [{wf.title}]({out_name}) — lista: {src_name}"
        )
        actions_count = len(list(iter_actions(wf.actions)))
        summary_items.append({
            "nwf_name": nwf_path.name,
            "title": wf.title or nwf_path.stem,
            "source_list": src_name,
            "out_name": out_name,
            "actions_count": actions_count,
            "status": "OK",
        })
        print(f"OK: {nwf_path.name} -> {out_name}")

    if UNKNOWN_TYPES_SEEN:
        index_lines.append("")
        index_lines.append("## Typy akcji bez dedykowanego opisu (do uzupełnienia w action_catalog.py)")
        index_lines.append("")
        for t in sorted(UNKNOWN_TYPES_SEEN):
            index_lines.append(f"- `{t}`")

    (output_dir / "index.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")

    walkthrough_md = _build_walkthrough(summary_items, UNKNOWN_TYPES_SEEN)
    (output_dir / "walkthrough.md").write_text(walkthrough_md, encoding="utf-8")

    # Generowanie interaktywnego portalu manuala migracji w formacie HTML
    if workflows_data:
        html_out_path = output_dir / "workflow-migration-manual.html"
        build_html_manual(workflows_data, html_out_path)
        print(f"OK: Wygenerowano portal HTML -> {html_out_path.name}")

    print(f"Gotowe. Raporty, portal HTML oraz walkthrough zapisano w: {output_dir}")


if __name__ == "__main__":
    main()
