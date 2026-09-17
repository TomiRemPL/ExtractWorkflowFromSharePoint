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
    from nwf_report.metadata_loader import FieldResolver, load_site_metadata
    from nwf_report.nwf_parser import parse_nwf
    from nwf_report.report_builder import build_report
else:
    from .action_catalog import UNKNOWN_TYPES_SEEN
    from .metadata_loader import FieldResolver, load_site_metadata
    from .nwf_parser import parse_nwf
    from .report_builder import build_report


def _safe_filename(name: str) -> str:
    return "".join(c if c.isalnum() or c in " _-." else "_" for c in name).strip()


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
    for nwf_path in nwf_files:
        try:
            wf = parse_nwf(nwf_path)
        except Exception as exc:  # nie przerywaj calego batcha z powodu jednego uszkodzonego pliku
            print(f"BLAD parsowania {nwf_path.name}: {exc}", file=sys.stderr)
            continue
        resolver = FieldResolver(wf.list_references, site_metadata, source_list_id=(wf.source_list.list_id if wf.source_list else ""))
        report_md = build_report(wf, resolver)
        out_name = _safe_filename(wf.title or nwf_path.stem) + ".md"
        (output_dir / out_name).write_text(report_md, encoding="utf-8")
        src_list = wf.source_list
        index_lines.append(
            f"- [{wf.title}]({out_name}) — lista: {src_list.list_name if src_list else '?'}"
        )
        print(f"OK: {nwf_path.name} -> {out_name}")

    if UNKNOWN_TYPES_SEEN:
        index_lines.append("")
        index_lines.append("## Typy akcji bez dedykowanego opisu (do uzupełnienia w action_catalog.py)")
        index_lines.append("")
        for t in sorted(UNKNOWN_TYPES_SEEN):
            index_lines.append(f"- `{t}`")

    (output_dir / "index.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    print(f"Gotowe. Raporty zapisano w: {output_dir}")


if __name__ == "__main__":
    main()
