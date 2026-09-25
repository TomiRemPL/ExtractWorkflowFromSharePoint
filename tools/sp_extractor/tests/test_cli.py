"""Unit tests for sp_extractor CLI parsing and execution."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from tools.sp_extractor.cli import parse_args, main


def test_parse_args_positional():
    args = parse_args(["https://sp.corp.local/sites/dora"])
    assert args.url == "https://sp.corp.local/sites/dora"
    assert args.output is None
    assert args.include_data is False


def test_parse_args_options():
    args = parse_args([
        "--url", "https://sp.corp.local/sites/dora",
        "-o", "MyCustomFolder",
        "-u", "user1",
        "-p", "secret",
        "-d", "DOMAIN",
        "--include-data",
    ])
    assert args.url == "https://sp.corp.local/sites/dora"
    assert args.output == "MyCustomFolder"
    assert args.username == "user1"
    assert args.password == "secret"
    assert args.domain == "DOMAIN"
    assert args.include_data is True


def test_parse_args_missing_url():
    with pytest.raises(SystemExit):
        parse_args([])


@patch("tools.sp_extractor.cli.SharePointClient")
@patch("tools.sp_extractor.cli.SharePointExtractor")
def test_main_success(mock_extractor_cls, mock_client_cls, tmp_path: Path):
    mock_extractor = MagicMock()
    mock_extractor.run.return_value = {
        "lists_count": 5,
        "workflows_count": 2,
    }
    mock_extractor_cls.return_value = mock_extractor

    exit_code = main([
        "https://sp.corp.local/sites/dora",
        "--output", str(tmp_path / "OutputTest"),
    ])
    assert exit_code == 0
    mock_extractor.run.assert_called_once()

