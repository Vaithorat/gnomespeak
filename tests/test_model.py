"""Tests for data models."""

from vt.model import Action, Target, Snapshot


def test_action_creation():
    """Test Action creation and serialization."""
    action = Action(id="play_pause", label="Pause", kind="button")
    d = action.to_dict()
    assert d["id"] == "play_pause"
    assert d["label"] == "Pause"
    assert d["kind"] == "button"


def test_action_slider():
    """Test slider action."""
    action = Action(id="volume", label="Volume (50%)", kind="slider", value=0.5)
    d = action.to_dict()
    assert d["value"] == 0.5


def test_target_creation():
    """Test Target creation."""
    target = Target(
        id="mpris:firefox",
        kind="player",
        title="Cars 2",
        status="playing",
        position=100.0,
        length=600.0,
    )
    assert target.id == "mpris:firefox"
    assert target.position == 100.0


def test_target_with_actions():
    """Test Target with actions."""
    target = Target(
        id="system:audio",
        kind="system",
        title="Audio",
        actions=[
            Action(id="volume", label="Volume", kind="slider", value=0.8),
            Action(id="mute", label="Mute"),
        ],
    )
    d = target.to_dict()
    assert len(d["actions"]) == 2
    assert d["actions"][0]["kind"] == "slider"


def test_snapshot_creation():
    """Test Snapshot creation."""
    snapshot = Snapshot()
    assert snapshot.targets == []
    assert snapshot.ts > 0

    snapshot.targets = [
        Target(id="test", kind="system", title="Test"),
    ]
    d = snapshot.to_dict()
    assert len(d["targets"]) == 1
    assert "ts" in d
