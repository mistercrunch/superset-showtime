"""
🎪 GitHub PR comment templates and messaging utilities

Centralized PR comment functions with type hints and clean formatting.
"""

import os
import textwrap
from typing import Dict, Optional

# AWS Console URL constants
BASE_AWS_URL = "https://us-west-2.console.aws.amazon.com/ecs/v2/clusters/superset-ci/services"
AWS_REGION = "us-west-2"


def get_github_actor() -> str:
    """Get current GitHub actor with fallback"""
    return os.getenv("GITHUB_ACTOR", "unknown")


def get_github_workflow_url() -> str:
    """Get current GitHub Actions workflow URL"""
    return (
        os.getenv("GITHUB_SERVER_URL", "https://github.com")
        + f"/{os.getenv('GITHUB_REPOSITORY', 'repo')}/actions/runs/{os.getenv('GITHUB_RUN_ID', 'run')}"
    )


def get_showtime_footer() -> str:
    """Get consistent Showtime footer for PR comments"""
    return "*Powered by [Superset Showtime](https://github.com/mistercrunch/superset-showtime)*"


def get_aws_console_urls(service_name: str) -> Dict[str, str]:
    """Get AWS Console URLs for a service"""
    return {
        "logs": f"{BASE_AWS_URL}/{service_name}/logs?region={AWS_REGION}",
        "service": f"{BASE_AWS_URL}/{service_name}?region={AWS_REGION}",
        "health": f"{BASE_AWS_URL}/{service_name}/health?region={AWS_REGION}",
    }


# Typed comment functions with clear parameter requirements


def start_comment(show) -> str:
    """Create environment start comment

    Args:
        show: Show object with SHA and other metadata
    """
    return textwrap.dedent(
        f"""
        🎪 @{get_github_actor()} Creating ephemeral environment for commit `{show.short_sha}`

        **Action:** [View workflow]({get_github_workflow_url()})
        **Environment:** `{show.short_sha}`
        **Powered by:** [Superset Showtime](https://github.com/mistercrunch/superset-showtime)

        *Building and deploying... Watch the labels for progress updates.*
    """
    ).strip()


def success_comment(show, feature_count: Optional[int] = None) -> str:
    """Environment success comment

    Args:
        show: Show object with SHA, IP, TTL, etc.
        feature_count: Number of enabled feature flags (optional)
    """
    feature_line = f"**Feature flags:** {feature_count} enabled\n" if feature_count else ""

    return textwrap.dedent(
        f"""
        🎪 @{get_github_actor()} Environment ready at **http://{show.ip}:8080**

        **Environment:** `{show.short_sha}`
        **Credentials:** admin / admin
        **TTL:** {show.ttl} (auto-cleanup)
        {feature_line}
        **Configuration:** Modify feature flags in your PR code for new SHA
        **Updates:** Environment updates automatically on new commits

        {get_showtime_footer()}
    """
    ).strip()


def failure_comment(show, error: str) -> str:
    """Environment failure comment

    Args:
        show: Show object with SHA and metadata
        error: Error message describing what went wrong
    """
    return textwrap.dedent(
        f"""
        🎪 @{get_github_actor()} Environment creation failed.

        **Error:** {error}
        **Environment:** `{show.short_sha}`

        Please check the logs and try again.

        {get_showtime_footer()}
    """
    ).strip()


def cleanup_comment(show) -> str:
    """Environment cleanup comment

    Args:
        show: Show object with SHA and metadata
    """
    return textwrap.dedent(
        f"""
        🎪 @{get_github_actor()} Environment `{show.short_sha}` cleaned up

        **AWS Resources:** ECS service and ECR image deleted
        **Cost Impact:** No further charges

        Add `🎪 ⚡ showtime-trigger-start` to create a new environment.

        {get_showtime_footer()}
    """
    ).strip()


def rolling_start_comment(current_show, new_sha: str) -> str:
    """Rolling update start comment

    Args:
        current_show: Current Show object with SHA and IP
        new_sha: New environment SHA (full SHA, will be truncated)
    """
    from .circus import short_sha

    return textwrap.dedent(
        f"""
        🎪 @{get_github_actor()} Detected new commit - starting rolling update `{current_show.short_sha}` → `{short_sha(new_sha)}`

        **Action:** Zero-downtime blue-green deployment
        **Progress:** [View workflow]({get_github_workflow_url()})
        **Current:** `{current_show.short_sha}` at http://{current_show.ip}:8080
        **New:** `{short_sha(new_sha)}` (building...)

        *New environment will replace current one automatically.*
    """
    ).strip()


def rolling_success_comment(old_show, new_show) -> str:
    """Rolling update success comment

    Args:
        old_show: Previous Show object
        new_show: New Show object with updated IP, SHA, TTL
    """
    return textwrap.dedent(
        f"""
        🎪 @{get_github_actor()} Rolling update complete! `{old_show.short_sha}` → `{new_show.short_sha}`

        **New Environment:** **http://{new_show.ip}:8080**
        **Deployment:** Zero-downtime blue-green deployment
        **Credentials:** admin / admin
        **TTL:** {new_show.ttl} (auto-cleanup)

        Your latest changes are now live.

        {get_showtime_footer()}
    """
    ).strip()


def rolling_failure_comment(current_show, new_sha: str, error: str) -> str:
    """Rolling update failure comment

    Args:
        current_show: Current Show object (still active)
        new_sha: Failed new environment SHA (full SHA, will be truncated)
        error: Error message describing what went wrong
    """
    from .circus import short_sha

    return textwrap.dedent(
        f"""
        🎪 @{get_github_actor()} Rolling update failed `{current_show.short_sha}` → `{short_sha(new_sha)}`

        **Error:** {error}
        **Current:** Environment `{current_show.short_sha}` remains active at http://{current_show.ip}:8080

        Please check the logs and try again with `🎪 ⚡ showtime-trigger-start`.

        {get_showtime_footer()}
    """
    ).strip()
