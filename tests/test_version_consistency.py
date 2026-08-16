import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "1.2.0"


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_release_version_is_consistent():
    metadata = re.search(
        r"(?m)^version:\s*v(?P<version>\d+\.\d+\.\d+)\s*$",
        _read("metadata.yaml"),
    )
    registration = re.search(
        r'@register\(.*?"(?P<version>\d+\.\d+\.\d+)",',
        _read("main.py"),
        re.DOTALL,
    )
    page = re.search(
        r'id="verTag">v(?P<version>\d+\.\d+\.\d+)<',
        _read("pages/style-manager/index.html"),
    )

    assert metadata is not None
    assert registration is not None
    assert page is not None
    assert {
        metadata.group("version"),
        registration.group("version"),
        page.group("version"),
    } == {EXPECTED_VERSION}
