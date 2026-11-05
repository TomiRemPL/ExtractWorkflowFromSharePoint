import subprocess
import sys
from pathlib import Path

from tools.nwf_report.html_builder import _generate_html, build_html_manual


def test_portal_includes_application_information_dialog():
    html = _generate_html([])

    assert '<title>SharePoint Nintex Workflow Migration Portal</title>' in html
    assert '<h1 class="hero-title">Centrum migracji Nintex Workflow</h1>' in html
    assert html.count('id="about-btn"') == 1
    assert 'aria-haspopup="dialog" aria-controls="about-dialog">O aplikacji</button>' in html
    assert html.count('id="about-dialog"') == 1
    assert 'aria-labelledby="about-title" aria-describedby="about-info"' in html
    assert '<p>REMBIASZ GRC Tech Solutions Tomasz Rembiasz, NIP: 8871550162</p>' in html
    assert '<p>Aplikacja powstała dla Credit-Agricole Bank Polska S.A.</p>' in html
    assert '<p>Wersja: 3.0</p>' in html
    assert '<form method="dialog">' in html
    assert 'type="submit" autofocus>Zamknij</button>' in html
    assert "aboutDialog.showModal()" in html
    assert "if (event.key === 'Escape')" in html
    assert "aboutDialog.close()" in html
    assert "aboutDialog.addEventListener('close', () => aboutButton.focus())" in html
    assert html.index("aboutDialog.showModal()") < html.index("<!-- Skrypt Mermaid -->")


def test_build_html_manual_persists_application_information(tmp_path):
    path = build_html_manual([], tmp_path / "portal.html")

    assert path.read_text(encoding="utf-8") == _generate_html([])


def test_portal_toolbar_keeps_only_search_and_preserves_report_sections():
    html = _generate_html([])
    toolbar = html.split('<nav class="sticky-nav">', 1)[1].split("</nav>", 1)[0]

    assert toolbar.count('id="global-search"') == 1
    assert 'type="search"' in toolbar
    assert 'aria-label="Wyszukiwarka"' in toolbar
    assert "<button" not in toolbar
    assert "nav-btn" not in html
    assert "nav-links" not in html
    for section in (
        "sec-inventory",
        "sec-flows",
        "sec-fields",
        "sec-contract",
        "sec-apex",
        "sec-apex-workflows",
        "sec-checklist",
    ):
        assert f'<section id="{section}">' in html


def test_report_cli_imports_when_started_as_script(tmp_path):
    script = Path(__file__).resolve().parents[1] / "generate_report.py"

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "--input" in result.stdout
    assert "--output" in result.stdout
