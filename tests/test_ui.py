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
    # card > row > icon + body(title, subtitle) + the "more actions" button
    assert tags == ["div", "div", "span", "div", "div", "div", "button"]
    # It survives as visible text, which is the point.
    assert "&lt;img src=x onerror=alert(1)&gt;" in rendered


def test_hostile_subtitle_and_icon_are_escaped(rendered):
    # Three escaped copies: icon, title, subtitle. Plus the id, which appears
    # in data-target for the tap and data-more for the action sheet.
    assert rendered.count("&lt;img") == 5


def test_target_id_lands_in_a_data_attribute(rendered):
    """Not in an inline handler: attribute + JS is two parsers, one escape."""
    assert "data-target=" in rendered
    assert "data-more=" in rendered
    assert "onclick=" not in rendered


def test_row_tap_runs_the_primary_action(rendered):
    """Focusing a window is one tap, not a drill-down and then a button."""
    assert 'data-action="focus"' in rendered


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


# --- the autoplay banner ----------------------------------------------------

@pytest.fixture(scope="module")
def rendered_youtube() -> str:
    return _render("youtube")


def test_autoplay_banner_renders_note_and_fix(rendered_youtube):
    """The warning is useless if the action that fixes it is not next to it."""
    assert 'class="banner"' in rendered_youtube
    assert 'data-action="fix_autoplay"' in rendered_youtube
    assert 'data-confirm="1"' in rendered_youtube


def test_autoplay_banner_escapes_its_text(rendered_youtube):
    from html.parser import HTMLParser

    tags = []

    class Collector(HTMLParser):
        def handle_starttag(self, tag, attrs):
            tags.append(tag)

    Collector().feed(rendered_youtube.split("SIGNATURE:")[0])
    assert "img" not in tags
    assert "&lt;img src=x onerror=alert(1)&gt;" in rendered_youtube


def test_youtube_signature_tracks_the_note(rendered_youtube):
    """The view is pinned against state polls so typing survives; the banner is
    the one field that must still get through, or it would never clear itself."""
    signature = rendered_youtube.split("SIGNATURE:")[1].strip()
    assert signature.startswith("youtube|youtube:search|")
    assert "Firefox blocks autoplay" in signature


def test_search_box_survives_the_banner(rendered_youtube):
    assert 'id="youtubeSearch"' in rendered_youtube
    assert 'id="youtubeList"' in rendered_youtube


# --- the home dashboard -----------------------------------------------------
# The overhaul's whole claim is fewer taps, so what the home screen offers
# without being tapped is worth pinning down.

@pytest.fixture(scope="module")
def rendered_home() -> str:
    return _render("home")


def test_home_puts_transport_on_screen(rendered_home):
    """Pause is one tap from opening the page, not three."""
    assert 'data-action="play_pause"' in rendered_home
    assert 'data-action="next"' in rendered_home
    assert 'data-action="prev"' in rendered_home
    # Playing, so the primary button shows pause rather than play.
    assert "⏸" in rendered_home


def test_home_carries_volume_and_quick_actions(rendered_home):
    assert 'data-action="volume"' in rendered_home
    assert 'data-action="mute"' in rendered_home
    assert 'class="tile"' in rendered_home


def test_home_progress_is_painted_not_rebuilt(rendered_home):
    """Position never enters the signature; the bar is written to the DOM."""
    assert 'data-progress-for="mpris:vlc"' in rendered_home
    assert "progress-fill" in rendered_home


def test_home_escapes_player_metadata(rendered_home):
    from html.parser import HTMLParser

    tags = []

    class Collector(HTMLParser):
        def handle_starttag(self, tag, attrs):
            tags.append(tag)

    Collector().feed(rendered_home)
    assert "img" not in tags
    assert "&lt;img src=x onerror=alert(1)&gt;" in rendered_home
