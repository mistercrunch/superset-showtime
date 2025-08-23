"""
🎪 Circus tent emoji label parsing and state management

Core logic for parsing GitHub labels with circus tent emoji patterns.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from .github import GitHubInterface


@dataclass
class Show:
    """Single ephemeral environment state from circus labels"""

    pr_number: int
    sha: str  # 7-char commit SHA
    status: str  # building, running, updating, failed
    ip: Optional[str] = None  # Environment IP address
    created_at: Optional[str] = None  # ISO timestamp
    ttl: str = "24h"  # 24h, 48h, close, etc.
    requested_by: Optional[str] = None  # GitHub username

    @property
    def aws_service_name(self) -> str:
        """Deterministic ECS service name: pr-{pr_number}-{sha}"""
        return f"pr-{self.pr_number}-{self.sha}"

    @property
    def aws_image_tag(self) -> str:
        """Deterministic ECR image tag: pr-{pr_number}-{sha}-ci"""
        return f"pr-{self.pr_number}-{self.sha}-ci"

    @property
    def is_active(self) -> bool:
        """Check if this is the currently active show"""
        return self.status == "running"

    @property
    def is_building(self) -> bool:
        """Check if environment is currently building"""
        return self.status == "building"

    @property
    def is_updating(self) -> bool:
        """Check if environment is currently updating"""
        return self.status == "updating"

    def needs_update(self, latest_sha: str) -> bool:
        """Check if environment needs update to latest SHA"""
        return self.sha != latest_sha[:7]

    def to_circus_labels(self) -> List[str]:
        """Convert show state to circus tent emoji labels (per-SHA format)"""
        if not self.created_at:
            self.created_at = datetime.utcnow().strftime("%Y-%m-%dT%H-%M")

        labels = [
            f"🎪 {self.sha} 🚦 {self.status}",  # SHA-first status
            f"🎪 🎯 {self.sha}",  # Active pointer (no value)
            f"🎪 {self.sha} 📅 {self.created_at}",  # SHA-first timestamp
            f"🎪 {self.sha} ⌛ {self.ttl}",  # SHA-first TTL
        ]

        if self.ip:
            labels.append(f"🎪 {self.sha} 🌐 {self.ip}:8080")

        if self.requested_by:
            labels.append(f"🎪 {self.sha} 🤡 {self.requested_by}")

        return labels

    @classmethod
    def from_circus_labels(cls, pr_number: int, labels: List[str], sha: str) -> Optional["Show"]:
        """Create Show from circus tent labels for specific SHA"""
        show_data = {
            "pr_number": pr_number,
            "sha": sha,
            "status": "building",  # default
        }

        for label in labels:
            if not label.startswith("🎪 "):
                continue

            parts = label.split(" ", 3)  # Split into 4 parts for per-SHA format

            if len(parts) == 3:  # Old format: 🎪 🎯 sha
                emoji, value = parts[1], parts[2]
                if emoji == "🎯" and value == sha:  # Active pointer
                    pass  # This SHA is active
            elif len(parts) == 4:  # SHA-first format: 🎪 sha 🚦 status
                label_sha, emoji, value = parts[1], parts[2], parts[3]

                if label_sha != sha:  # Only process labels for this SHA
                    continue

                if emoji == "🚦":  # Status
                    show_data["status"] = value
                elif emoji == "📅":  # Timestamp
                    show_data["created_at"] = value
                elif emoji == "🌐":  # IP with port
                    show_data["ip"] = value.replace(":8080", "")  # Remove port for storage
                elif emoji == "⌛":  # TTL
                    show_data["ttl"] = value
                elif emoji == "🤡":  # User (clown!)
                    show_data["requested_by"] = value

        # Only return Show if we found relevant labels for this SHA
        if any(label.endswith(f" {sha}") for label in labels if "🎯" in label or "🏗️" in label):
            return cls(**show_data)

        return None


class PullRequest:
    """GitHub PR with its shows parsed from circus labels"""

    def __init__(self, pr_number: int, labels: List[str]):
        self.pr_number = pr_number
        self.labels = labels
        self._shows = self._parse_shows_from_labels()

    @property
    def shows(self) -> List[Show]:
        """All shows found in labels"""
        return self._shows

    @property
    def current_show(self) -> Optional[Show]:
        """The currently active show (from 🎯 label)"""
        # Find the SHA that's marked as active (🎯)
        active_sha = None
        for label in self.labels:
            if label.startswith("🎪 🎯 "):
                active_sha = label.split(" ")[2]
                break

        if not active_sha:
            return None

        # Find the show with that SHA
        for show in self.shows:
            if show.sha == active_sha:
                return show

        return None

    @property
    def building_show(self) -> Optional[Show]:
        """Show currently being built (from 🏗️ label)"""
        building_sha = None
        for label in self.labels:
            if label.startswith("🎪 🏗️ "):
                building_sha = label.split(" ")[2]
                break

        if not building_sha:
            return None

        for show in self.shows:
            if show.sha == building_sha:
                return show

        return None

    @property
    def circus_labels(self) -> List[str]:
        """All circus tent labels"""
        return [label for label in self.labels if label.startswith("🎪 ")]

    def has_shows(self) -> bool:
        """Check if PR has any shows"""
        return len(self.shows) > 0

    def get_show_by_sha(self, sha: str) -> Optional[Show]:
        """Get specific show by SHA"""
        for show in self.shows:
            if show.sha == sha[:7]:
                return show
        return None

    def _parse_shows_from_labels(self) -> List[Show]:
        """Parse all shows from circus labels"""
        shows = []

        # Find all unique SHAs mentioned in labels
        shas = set()
        for label in self.labels:
            if label.startswith("🎪 🎯 ") or label.startswith("🎪 🏗️ "):
                sha = label.split(" ")[2]
                shas.add(sha)

        # Create Show object for each SHA
        for sha in shas:
            show = Show.from_circus_labels(self.pr_number, self.labels, sha)
            if show:
                shows.append(show)

        return shows

    @classmethod
    def from_id(cls, pr_number: int, github: "GitHubInterface") -> "PullRequest":
        """Load PR with current labels from GitHub"""
        labels = github.get_labels(pr_number)
        return cls(pr_number, labels)

    def refresh_labels(self, github: "GitHubInterface") -> None:
        """Refresh labels from GitHub and reparse shows"""
        self.labels = github.get_labels(self.pr_number)
        self._shows = self._parse_shows_from_labels()


def parse_ttl_days(ttl_str: str) -> Optional[float]:
    """Parse TTL string to days"""
    import re

    if ttl_str == "never":
        return None  # Never expire

    if ttl_str == "close":
        return None  # Special handling needed

    # Parse number + unit: 24h, 7d, 2w, etc.
    match = re.match(r"(\d+(?:\.\d+)?)(h|d|w)", ttl_str.lower())
    if not match:
        return 2.0  # Default 2 days if invalid

    value = float(match.group(1))
    unit = match.group(2)

    if unit == "h":
        return value / 24.0  # Hours to days
    elif unit == "d":
        return value  # Already in days
    elif unit == "w":
        return value * 7.0  # Weeks to days

    return 2.0  # Default


def get_effective_ttl(pr) -> Optional[float]:
    """Get effective TTL in days for a PR (handles multiple labels, conflicts)"""
    ttl_labels = []

    # Find all TTL labels for all shows
    for show in pr.shows:
        if show.ttl:
            ttl_days = parse_ttl_days(show.ttl)
            if ttl_days is None:  # "never" or "close"
                if show.ttl == "never":
                    return None  # Never expire takes precedence
                # For "close", continue checking others
            else:
                ttl_labels.append(ttl_days)

    if not ttl_labels:
        return 2.0  # Default 2 days

    # Use longest duration if multiple labels
    return max(ttl_labels)
