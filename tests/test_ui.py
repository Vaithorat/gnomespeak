"""Tests for the web UI's escaping.

Window titles and MPRIS metadata are whatever the user happens to have open, so
they reach the page as untrusted text. These run the real render functions under
node with DOM stubs rather than asserting on the source text.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

UI = Path(__file__).parent.parent / "vt" / "ui" / "index.html"
HARNESS = Path(__file__).parent / "js" / "render_harness.mjs"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is required to run the UI script"
)


def _render(mode: str) -> str:
    result = subprocess.run(
        ["node", str(HARNESS), str(UI), mode],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.fixture(scope="module")
def rendered() -> str:
    return _render("category")


@pytest.fixture(scope="module")
def rendered_apps() -> str:
    return _render("installed")


def test_hostile_title_is_escaped(rendered):
    """A window titled "<img src=x onerror=...>" must not become an element."""
    from html.parser import HTMLParser

    tags = []

    class Collector(HTMLParser):
        def handle_starttag(self, tag, attrs):
            tags.append(tag)

    Collector().feed(rendered)

    assert "img" not in tags, "the payload was parsed as markup"
    assert tags == ["div", "span", "span", "span"]
    # It survives as visible text, which is the point.
    assert "&lt;img src=x onerror=alert(1)&gt;" in rendered


def test_hostile_subtitle_and_icon_are_escaped(rendered):
    # Three escaped copies: icon, title, subtitle. Plus one in the id attribute.
    assert rendered.count("&lt;img") == 4


def test_target_id_lands_in_a_data_attribute(rendered):
    """Not in an inline handler: attribute + JS is two parsers, one escape."""
    assert "data-nav=" in rendered
    assert "onclick=" not in rendered


def test_no_data_carrying_inline_handlers_remain():
    """Inline handlers may stay only where they pass no interpolated data."""
    source = UI.read_text()
    for line_no, line in enumerate(source.splitlines(), 1):
        if "onclick=" in line or "oninput=" in line:
            assert "${" not in line, f"interpolated inline handler at index.html:{line_no}"


# --- the installed-apps list ------------------------------------------------

def test_installed_app_names_are_escaped(rendered_apps):
    """A .desktop file is text anyone can drop in ~/.local/share/applications."""
    from html.parser import HTMLParser

    tags = []

    class Collector(HTMLParser):
        def handle_starttag(self, tag, attrs):
            tags.append(tag)

    Collector().feed(rendered_apps)

    assert "img" not in tags, "the payload was parsed as markup"
    assert "&lt;img src=x onerror=alert(1)&gt;" in rendered_apps


def test_installed_rows_launch_through_a_data_attribute(rendered_apps):
    assert 'data-action="launch"' in rendered_apps
    assert "onclick=" not in rendered_apps
