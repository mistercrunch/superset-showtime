"""
Tests for circus tent emoji label parsing
"""

from showtime.core.circus import (
    PullRequest,
    Show,
)


def test_show_from_circus_labels():
    """Test creating Show from circus tent labels"""
    labels = [
        "🎪 abc123f 🚦 running",
        "🎪 🎯 abc123f",
        "🎪 abc123f 📅 2024-01-15T14-30",
        "🎪 abc123f 🌐 52.1.2.3:8080",  # New format with dots and port
        "🎪 abc123f ⌛ 24h",
        "🎪 abc123f 🤡 maxime",
        "some-other-label",  # Should be ignored
    ]

    show = Show.from_circus_labels(1234, labels, "abc123f")

    assert show is not None
    assert show.status == "running"
    assert show.sha == "abc123f"
    assert show.created_at == "2024-01-15T14-30"
    assert show.ip == "52.1.2.3"  # Port removed during parsing
    assert show.ttl == "24h"
    assert show.requested_by == "maxime"


def test_pullrequest_during_update():
    """Test PullRequest with multiple shows during update"""
    labels = [
        "🎪 abc123f 🚦 running",  # Old active
        "🎪 def456a 🚦 building",  # New building
        "🎪 🎯 abc123f",  # Active pointer
        "🎪 🏗️ def456a",  # Building pointer
    ]

    pr = PullRequest(1234, labels)

    assert len(pr.shows) == 2
    assert pr.current_show is not None
    assert pr.current_show.sha == "abc123f"
    assert pr.building_show is not None
    assert pr.building_show.sha == "def456a"


def test_pullrequest_empty():
    """Test PullRequest with no circus labels"""
    labels = ["bug", "enhancement", "documentation"]

    pr = PullRequest(1234, labels)

    assert len(pr.shows) == 0
    assert pr.current_show is None
    assert not pr.has_shows()


def test_show_to_circus_labels():
    """Test converting Show to circus tent labels"""
    show = Show(
        pr_number=1234,
        sha="abc123f",
        status="running",
        ip="52.1.2.3",
        created_at="2024-01-15T14-30",
        ttl="48h",
        requested_by="maxime",
    )

    labels = show.to_circus_labels()

    expected = [
        "🎪 abc123f 🚦 running",
        "🎪 🎯 abc123f",
        "🎪 abc123f 📅 2024-01-15T14-30",
        "🎪 abc123f 🌐 52.1.2.3:8080",  # IP with dots and port
        "🎪 abc123f ⌛ 48h",
        "🎪 abc123f 🤡 maxime",
    ]

    # Check all expected labels are present
    for expected_label in expected:
        assert expected_label in labels


def test_show_properties():
    """Test Show utility properties"""
    show = Show(pr_number=1234, sha="abc123f", status="running")

    assert show.is_active is True
    assert show.is_updating is False
    assert show.needs_update("def456a1234567") is True
    assert show.needs_update("abc123f1234567") is False
    assert show.aws_service_name == "pr-1234-abc123f"
    assert show.aws_image_tag == "pr-1234-abc123f-ci"
