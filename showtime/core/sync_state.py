"""
🎪 Sync State - Typed state management for sync operations

Provides structured state tracking with proper typing for analysis and debugging.
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional


class ActionNeeded(Enum):
    """Actions that sync can take"""

    NO_ACTION = "no_action"
    CREATE_ENVIRONMENT = "create_environment"
    ROLLING_UPDATE = "rolling_update"
    AUTO_SYNC = "auto_sync"
    DESTROY_ENVIRONMENT = "destroy_environment"
    BLOCKED = "blocked"


class AuthStatus(Enum):
    """Authorization check results"""

    AUTHORIZED = "authorized"
    DENIED_INSUFFICIENT_PERMS = "denied_insufficient_perms"
    DENIED_404 = "denied_404"
    ALLOWED_NO_ACTOR = "allowed_no_actor"
    SKIPPED_NOT_ACTIONS = "skipped_not_actions"
    ERROR = "error"


class BlockedReason(Enum):
    """Why an operation is blocked"""

    EXISTING_BLOCKED_LABEL = "existing_blocked_label"
    AUTHORIZATION_FAILED = "authorization_failed"
    NOT_BLOCKED = "not_blocked"


@dataclass
class SyncState:
    """Complete state information for a sync operation"""

    # Core sync decision
    action_needed: ActionNeeded
    build_needed: bool
    sync_needed: bool
    target_sha: str

    # Authorization info
    github_actor: str
    is_github_actions: bool
    permission_level: str
    auth_status: AuthStatus

    # Blocking info
    blocked_reason: BlockedReason = BlockedReason.NOT_BLOCKED

    # Context info
    trigger_labels: Optional[List[str]] = None
    target_show_status: Optional[str] = None
    has_previous_shows: bool = False
    action_reason: str = ""

    # Error details (if any)
    auth_error: Optional[str] = None

    def __post_init__(self) -> None:
        """Initialize default values"""
        if self.trigger_labels is None:
            self.trigger_labels = []

    @property
    def is_blocked(self) -> bool:
        """Check if operation is blocked"""
        return self.action_needed == ActionNeeded.BLOCKED

    @property
    def is_authorized(self) -> bool:
        """Check if actor is authorized"""
        return self.auth_status == AuthStatus.AUTHORIZED

    def to_gha_stdout(self, pr_number: int) -> str:
        """Generate GitHub Actions compatible stdout with k=v pairs"""
        lines = [
            f"build_needed={str(self.build_needed).lower()}",
            f"sync_needed={str(self.sync_needed).lower()}",
            f"pr_number={pr_number}",
            f"target_sha={self.target_sha}",
            f"action_needed={self.action_needed.value}",
            f"github_actor={self.github_actor}",
            f"permission_level={self.permission_level}",
            f"auth_status={self.auth_status.value}",
        ]

        # Add blocking info if relevant
        if self.is_blocked:
            lines.append(f"blocked_reason={self.blocked_reason.value}")

        # Add context info for debugging
        if self.trigger_labels:
            lines.append(f"trigger_labels={','.join(self.trigger_labels)}")

        if self.target_show_status:
            lines.append(f"target_show_status={self.target_show_status}")

        lines.append(f"has_previous_shows={str(self.has_previous_shows).lower()}")

        if self.action_reason:
            lines.append(f"action_reason={self.action_reason}")

        # Add error info if present
        if self.auth_error:
            lines.append(f"auth_error={self.auth_error}")

        return "\n".join(lines)

    def to_debug_summary(self) -> str:
        """Generate human-readable debug summary"""
        status = "🚫 BLOCKED" if self.is_blocked else "✅ AUTHORIZED"

        summary = [
            f"🎪 Sync State Summary: {status}",
            f"   Action: {self.action_needed.value} ({self.action_reason})",
            f"   Actor: {self.github_actor} ({self.permission_level})",
            f"   Auth: {self.auth_status.value}",
        ]

        if self.is_blocked:
            summary.append(f"   Blocked: {self.blocked_reason.value}")

        if self.trigger_labels:
            summary.append(f"   Triggers: {', '.join(self.trigger_labels)}")

        return "\n".join(summary)
