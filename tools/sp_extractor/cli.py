"""CLI interface for sp_extractor: automated SharePoint 2019 artifact downloader."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from sp_extractor.client import SharePointClient, SharePointClientError
    from sp_extractor.extractor import SharePointExtractor
    from sp_extractor.naming import resolve_output_dir
else:
    from .client import SharePointClient, SharePointClientError
    from .extractor import SharePointExtractor
    from .naming import resolve_output_dir


logger = logging.getLogger("sp_extractor")


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SharePoint 2019 extractor: exports metadata, schemas, and Nintex .nwf workflows for APEX migration."
    )
    parser.add_argument(
        "url_pos",
        nargs="?",
        metavar="URL",
        help="SharePoint site URL (e.g. https://sp.domain.local/sites/dora)",
    )
    parser.add_argument(
        "--url",
        dest="url_opt",
        help="SharePoint site URL (alternative to positional argument)",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Destination directory. If omitted, automatically creates DaneZeSkryptu_nnn (001, 002, ...)",
    )
    parser.add_argument(
        "--base-dir",
        default=".",
        help="Base directory for scanning existing DaneZeSkryptu_nnn directories (default: .)",
    )
    parser.add_argument(
        "-u",
        "--username",
        help="Username for NTLM authentication. If omitted, uses current Windows SSO credentials.",
    )
    parser.add_argument(
        "-p",
        "--password",
        help="Password for NTLM authentication.",
    )
    parser.add_argument(
        "-d",
        "--domain",
        help="Domain for NTLM authentication.",
    )
    parser.add_argument(
        "--include-data",
        action="store_true",
        help="Also export row data items (20_dane_*.json) from lists.",
    )
    parser.add_argument(
        "--include-permissions",
        action="store_true",
        help="Also export permission assignments (30_*).",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable SSL certificate verification.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable detailed debug logging.",
    )

    parsed = parser.parse_args(args)
    url = parsed.url_opt or parsed.url_pos
    if not url:
        parser.error("SharePoint site URL is required (pass as positional argument or via --url).")
    parsed.url = url
    return parsed


def main(args: list[str] | None = None) -> int:
    parsed = parse_args(args)

    log_level = logging.DEBUG if parsed.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    out_dir = resolve_output_dir(
        output=parsed.output,
        base_dir=parsed.base_dir,
        create=True,
    )

    print("=" * 65)
    print("  SharePoint 2019 Artifact & Nintex Workflow Extractor")
    print("=" * 65)
    print(f"Target site URL : {parsed.url}")
    print(f"Output directory: {out_dir.resolve()}")
    if parsed.username:
        print(f"Auth mode       : NTLM ({parsed.domain + '\\' if parsed.domain else ''}{parsed.username})")
    else:
        print("Auth mode       : Windows SSO / SSPI (Current logon session)")
    print(f"Include row data: {parsed.include_data}")
    print("=" * 65)

    try:
        client = SharePointClient(
            base_url=parsed.url,
            username=parsed.username,
            password=parsed.password,
            domain=parsed.domain,
            verify_ssl=not parsed.insecure,
        )
        extractor = SharePointExtractor(
            client=client,
            output_dir=out_dir,
            include_data=parsed.include_data,
            include_permissions=parsed.include_permissions,
        )
        manifest = extractor.run()

        print("-" * 65)
        print("Ekstrakcja zakończona sukcesem!")
        print(f"Pobrano definicji list    : {manifest.get('lists_count', 0)}")
        print(f"Znaleziono workflow Nintex: {manifest.get('workflows_count', 0)}")
        print(f"Katalog z plikami         : {out_dir.resolve()}")
        print(f"Plik manifestu            : {out_dir / 'extraction_manifest.json'}")
        print("-" * 65)
        return 0

    except SharePointClientError as e:
        logger.error("Błąd połączenia z SharePoint: %s", e)
        return 1
    except Exception as e:
        logger.exception("Nieoczekiwany błąd podczas ekstrakcji: %s", e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
