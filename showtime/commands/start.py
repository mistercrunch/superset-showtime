"""
🎪 Start show command - Create ephemeral environments
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class StartResult:
    """Result of starting a show"""

    success: bool
    url: Optional[str] = None
    error: Optional[str] = None


def start_show(
    pr_number: int, sha: Optional[str] = None, ttl: str = "24h", size: str = "standard"
) -> StartResult:
    """
    Start the show! Create ephemeral environment for PR

    Args:
        pr_number: PR number to create environment for
        sha: Specific commit SHA (default: latest)
        ttl: Time to live (24h, 48h, 1w, close)
        size: Environment size (standard, large)

    Returns:
        StartResult with success status and details
    """
    # TODO: Implement environment creation
    # 1. Get latest SHA if not provided
    # 2. Create circus labels
    # 3. Build Docker image
    # 4. Deploy to ECS
    # 5. Update labels with running state

    return StartResult(success=False, error="Not yet implemented")
