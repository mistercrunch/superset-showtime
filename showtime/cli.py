"""
🎪 Superset Showtime CLI

Main command-line interface for Apache Superset circus tent environment management.
"""

import subprocess
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .core.circus import PullRequest, Show, short_sha
from .core.emojis import STATUS_DISPLAY
from .core.github import GitHubError, GitHubInterface
from .core.github_messages import (
    building_comment,
    failure_comment,
    get_aws_console_urls,
    rolling_failure_comment,
    rolling_start_comment,
    rolling_success_comment,
    start_comment,
    success_comment,
)

# Constants
DEFAULT_GITHUB_ACTOR = "unknown"


def _get_service_urls(show):
    """Get AWS Console URLs for a service"""
    return get_aws_console_urls(show.ecs_service_name)


def _show_service_urls(show, context: str = "deployment"):
    """Show helpful AWS Console URLs for monitoring service"""
    urls = _get_service_urls(show)
    console.print(f"\n🎪 [bold blue]Monitor {context} progress:[/bold blue]")
    console.print(f"📝 Logs: {urls['logs']}")
    console.print(f"📊 Service: {urls['service']}")
    console.print("")


def _determine_sync_action(pr, pr_state: str, target_sha: str) -> str:
    """Determine what action is needed based on PR state and labels"""

    # 1. Closed PRs always need cleanup
    if pr_state == "closed":
        return "cleanup"

    # 2. Check for explicit trigger labels
    trigger_labels = [label for label in pr.labels if "showtime-trigger-" in label]

    # 3. Check for freeze label (PR-level) - only if no explicit triggers
    freeze_labels = [label for label in pr.labels if "showtime-freeze" in label]
    if freeze_labels and not trigger_labels:
        return "frozen_no_action"  # Frozen and no explicit triggers to override

    if trigger_labels:
        # Explicit triggers take priority
        for trigger in trigger_labels:
            if "showtime-trigger-start" in trigger:
                if pr.current_show:
                    if pr.current_show.needs_update(target_sha):
                        return "rolling_update"  # New commit with existing env
                    else:
                        return "no_action"  # Same commit, no change needed
                else:
                    return "create_environment"  # New environment
            elif "showtime-trigger-stop" in trigger:
                return "destroy_environment"

    # 3. No explicit triggers - check for implicit sync needs
    if pr.current_show:
        if pr.current_show.needs_update(target_sha):
            return "auto_sync"  # Auto-update on new commits
        else:
            return "no_action"  # Everything in sync
    else:
        return "no_action"  # No environment, no triggers


def _schedule_blue_cleanup(pr_number: int, blue_services: list):
    """Schedule cleanup of blue services after successful green deployment"""
    import threading
    import time

    def cleanup_after_delay():
        """Background cleanup of blue services"""
        try:
            # Wait 5 minutes before cleanup
            time.sleep(300)  # 5 minutes

            console.print(
                f"\n🧹 [bold blue]Starting scheduled cleanup of blue services for PR #{pr_number}[/bold blue]"
            )

            from .core.aws import AWSInterface

            aws = AWSInterface()

            for blue_svc in blue_services:
                service_name = blue_svc["service_name"]
                console.print(f"🗑️ Cleaning up blue service: {service_name}")

                try:
                    # Delete ECS service
                    if aws._delete_ecs_service(service_name):
                        # Delete ECR image
                        pr_match = service_name.split("-")
                        if len(pr_match) >= 2:
                            pr_num = pr_match[1]
                            image_tag = f"pr-{pr_num}-ci"  # Legacy format for old services
                            aws._delete_ecr_image(image_tag)

                        console.print(f"✅ Cleaned up blue service: {service_name}")
                    else:
                        console.print(f"⚠️ Failed to clean up: {service_name}")

                except Exception as e:
                    console.print(f"❌ Cleanup error for {service_name}: {e}")

            console.print("🧹 ✅ Blue service cleanup completed")

        except Exception as e:
            console.print(f"❌ Background cleanup failed: {e}")

    # Start cleanup in background thread
    cleanup_thread = threading.Thread(target=cleanup_after_delay, daemon=True)
    cleanup_thread.start()
    console.print("🕐 Background cleanup scheduled")


app = typer.Typer(
    name="showtime",
    help="""🎪 Apache Superset ephemeral environment management

[bold]GitHub Label Workflow:[/bold]
1. Add [green]🎪 ⚡ showtime-trigger-start[/green] label to PR → Creates environment
2. Watch state labels: [blue]🎪 abc123f 🚦 building[/blue] → [green]🎪 abc123f 🚦 running[/green]
3. Add [orange]🎪 🧊 showtime-freeze[/orange] → Freezes environment from auto-sync
4. Add [red]🎪 🛑 showtime-trigger-stop[/red] label → Destroys environment

[bold]Reading State Labels:[/bold]
• [green]🎪 abc123f 🚦 running[/green] - Environment status
• [blue]🎪 🎯 abc123f[/blue] - Active environment pointer
• [cyan]🎪 abc123f 🌐 52-1-2-3[/cyan] - Environment IP (http://52.1.2.3:8080)
• [yellow]🎪 abc123f ⌛ 24h[/yellow] - TTL policy
• [magenta]🎪 abc123f 🤡 maxime[/magenta] - Who requested (clown!)

[dim]CLI commands work with existing environments or dry-run new ones.[/dim]""",
    rich_markup_mode="rich",
)

console = Console()


def _get_github_workflow_url() -> str:
    """Get current GitHub Actions workflow URL"""
    import os

    return (
        os.getenv("GITHUB_SERVER_URL", "https://github.com")
        + f"/{os.getenv('GITHUB_REPOSITORY', 'repo')}/actions/runs/{os.getenv('GITHUB_RUN_ID', 'run')}"
    )


def _get_github_actor() -> str:
    """Get current GitHub actor with fallback"""
    import os

    return os.getenv("GITHUB_ACTOR", DEFAULT_GITHUB_ACTOR)


def _get_showtime_footer() -> str:
    """Get consistent Showtime footer for PR comments"""
    return "{_get_showtime_footer()}"


def _validate_non_active_state(pr: PullRequest) -> bool:
    """Check if PR is in a state where new work can begin

    Args:
        pr: PullRequest object with current state

    Returns:
        True if safe to start new work, False if another job is already active
    """
    if pr.current_show:
        active_states = ["building", "built", "deploying", "running", "updating"]
        if pr.current_show.status in active_states:
            return False  # Already active
    return True  # Safe to proceed


def _atomic_claim_environment(
    pr_number: int, target_sha: str, github: GitHubInterface, dry_run: bool = False
) -> bool:
    """Atomically claim environment for this job using compare-and-swap pattern

    Args:
        pr_number: PR number to claim
        target_sha: Target commit SHA
        github: GitHub interface for label operations
        dry_run: If True, simulate operations

    Returns:
        True if successfully claimed, False if another job already active or no triggers
    """
    from datetime import datetime

    try:
        # 1. CHECK: Load current PR state
        pr = PullRequest.from_id(pr_number, github)

        # 2. VALIDATE: Ensure non-active state (compare part of compare-and-swap)
        if not _validate_non_active_state(pr):
            current_state = pr.current_show.status if pr.current_show else "unknown"
            console.print(
                f"🎪 Environment already active (state: {current_state}) - another job is running"
            )
            return False

        # 3. FIND TRIGGERS: Must have triggers to claim
        trigger_labels = [label for label in pr.labels if "showtime-trigger-" in label]
        if not trigger_labels:
            console.print("🎪 No trigger labels found - nothing to claim")
            return False

        # 4. VALIDATE TRIGGER-SPECIFIC STATE REQUIREMENTS
        for trigger_label in trigger_labels:
            if "showtime-trigger-start" in trigger_label:
                # Start trigger: should NOT already be building/running
                if pr.current_show and pr.current_show.status in [
                    "building",
                    "built",
                    "deploying",
                    "running",
                ]:
                    console.print(
                        f"🎪 Start trigger invalid - environment already {pr.current_show.status}"
                    )
                    return False
            elif "showtime-trigger-stop" in trigger_label:
                # Stop trigger: should HAVE an active environment
                if not pr.current_show or pr.current_show.status in ["failed"]:
                    console.print("🎪 Stop trigger invalid - no active environment to stop")
                    return False

        console.print(f"🎪 Claiming environment for PR #{pr_number} SHA {target_sha[:7]}")
        console.print(f"🎪 Found {len(trigger_labels)} valid trigger(s) to process")

        if dry_run:
            console.print(
                "🎪 [bold yellow]DRY-RUN[/bold yellow] - Would atomically claim environment"
            )
            return True

        # 4. ATOMIC SWAP: Remove triggers + Set building state (swap part)
        console.print("🎪 Executing atomic claim (remove triggers + set building)...")

        # Remove all trigger labels first
        for trigger_label in trigger_labels:
            console.print(f"  🗑️ Removing trigger: {trigger_label}")
            github.remove_label(pr_number, trigger_label)

        # Immediately set building state to claim the environment
        building_show = Show(
            pr_number=pr_number,
            sha=short_sha(target_sha),
            status="building",
            created_at=datetime.utcnow().strftime("%Y-%m-%dT%H-%M"),
            ttl="24h",
            requested_by=_get_github_actor(),
        )

        # Clear any stale state and set building labels atomically
        github.remove_circus_labels(pr_number)
        for label in building_show.to_circus_labels():
            github.add_label(pr_number, label)

        console.print("🎪 ✅ Environment claimed successfully")
        return True

    except Exception as e:
        console.print(f"🎪 ❌ Failed to claim environment: {e}")
        return False


def _build_docker_image(pr_number: int, sha: str, dry_run: bool = False) -> bool:
    """Build Docker image directly without supersetbot dependency

    Args:
        pr_number: PR number for tagging
        sha: Full commit SHA
        dry_run: If True, print command but don't execute

    Returns:
        True if build succeeded, False if failed
    """
    tag = f"apache/superset:pr-{pr_number}-{short_sha(sha)}-ci"

    cmd = [
        "docker",
        "buildx",
        "build",
        "--push",
        "--load",
        "--platform",
        "linux/amd64",
        "--target",
        "ci",
        "--build-arg",
        "PY_VER=3.10-slim-bookworm",
        "--build-arg",
        "INCLUDE_CHROMIUM=false",
        "--build-arg",
        "LOAD_EXAMPLES_DUCKDB=true",
        "-t",
        tag,
        ".",
    ]

    console.print(f"🐳 Building Docker image: {tag}")
    if dry_run:
        console.print(f"🎪 [bold yellow]DRY-RUN[/bold yellow] - Would run: {' '.join(cmd)}")
        return True

    try:
        console.print(f"🎪 Running: {' '.join(cmd)}")
        console.print("🎪 Streaming Docker build output...")

        # Stream output in real-time for better user experience
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
        )

        # Stream output line by line
        for line in process.stdout:
            console.print(f"🐳 {line.rstrip()}")

        # Wait for completion with timeout
        try:
            return_code = process.wait(timeout=3600)  # 60 min timeout
        except subprocess.TimeoutExpired:
            process.kill()
            console.print("🎪 ❌ Docker build timed out after 60 minutes")
            return False

        if return_code == 0:
            console.print(f"🎪 ✅ Docker build succeeded: {tag}")
            return True
        else:
            console.print(f"🎪 ❌ Docker build failed with exit code: {return_code}")
            return False
    except Exception as e:
        console.print(f"🎪 ❌ Docker build error: {e}")
        return False


def _set_state_internal(
    state: str,
    pr_number: int,
    show: Show,
    github: GitHubInterface,
    dry_run_github: bool = False,
    error_msg: Optional[str] = None,
) -> None:
    """Internal helper to set state and handle comments/labels

    Used by sync and other commands to set final state transitions
    """
    console.print(f"🎪 Setting state to '{state}' for PR #{pr_number} SHA {show.sha}")

    # Update show state
    show.status = state

    # Handle state-specific logic
    comment_text = None

    if state == "building":
        comment_text = building_comment(show)
        console.print("🎪 Posting building comment...")

    elif state == "running":
        comment_text = success_comment(show)
        console.print("🎪 Posting success comment...")

    elif state == "failed":
        error_message = error_msg or "Build or deployment failed"
        comment_text = failure_comment(show, error_message)
        console.print("🎪 Posting failure comment...")

    elif state in ["built", "deploying"]:
        console.print(f"🎪 Silent state change to '{state}' - no comment posted")

    # Post comment if needed
    if comment_text and not dry_run_github:
        github.post_comment(pr_number, comment_text)
        console.print("🎪 ✅ Comment posted!")
    elif comment_text:
        console.print("🎪 [bold yellow]DRY-RUN-GITHUB[/bold yellow] - Would post comment")

    # Set state labels
    state_labels = show.to_circus_labels()

    if not dry_run_github:
        github.remove_circus_labels(pr_number)
        for label in state_labels:
            github.add_label(pr_number, label)
        console.print("🎪 ✅ Labels updated!")
    else:
        console.print("🎪 [bold yellow]DRY-RUN-GITHUB[/bold yellow] - Would update labels")


@app.command()
def version():
    """Show version information"""
    from . import __version__

    console.print(f"🎪 Superset Showtime v{__version__}")


@app.command()
def set_state(
    state: str = typer.Argument(
        ..., help="State to set (building, built, deploying, running, failed)"
    ),
    pr_number: int = typer.Argument(..., help="PR number to update"),
    sha: Optional[str] = typer.Option(None, "--sha", help="Specific commit SHA (default: latest)"),
    error_msg: Optional[str] = typer.Option(
        None, "--error-msg", help="Error message for failed state"
    ),
    dry_run_github: bool = typer.Option(
        False, "--dry-run-github", help="Skip GitHub operations, show what would happen"
    ),
):
    """🎪 Set environment state (generic state transition command)

    States:
    • building - Docker image is being built (posts comment)
    • built - Docker build complete, ready for deployment (silent)
    • deploying - AWS deployment in progress (silent)
    • running - Environment is live and ready (posts success comment)
    • failed - Build or deployment failed (posts error comment)
    """
    from datetime import datetime

    try:
        github = GitHubInterface()

        # Get SHA - use provided SHA or default to latest
        if sha:
            target_sha = sha
            console.print(f"🎪 Using specified SHA: {target_sha[:7]}")
        else:
            target_sha = github.get_latest_commit_sha(pr_number)
            console.print(f"🎪 Using latest SHA: {target_sha[:7]}")

        # Validate state
        valid_states = ["building", "built", "deploying", "running", "failed"]
        if state not in valid_states:
            console.print(f"❌ Invalid state: {state}. Must be one of: {', '.join(valid_states)}")
            raise typer.Exit(1)

        # Get GitHub actor
        github_actor = _get_github_actor()

        # Create or update show object
        show = Show(
            pr_number=pr_number,
            sha=short_sha(target_sha),
            status=state,
            created_at=datetime.utcnow().strftime("%Y-%m-%dT%H-%M"),
            ttl="24h",
            requested_by=github_actor,
        )

        # Use internal helper to set state
        _set_state_internal(state, pr_number, show, github, dry_run_github, error_msg)

        console.print(f"🎪 [bold green]State successfully set to '{state}'[/bold green]")

    except GitHubError as e:
        console.print(f"❌ GitHub error: {e}")
        raise typer.Exit(1) from e
    except Exception as e:
        console.print(f"❌ Error: {e}")
        raise typer.Exit(1) from e


@app.command()
def start(
    pr_number: int = typer.Argument(..., help="PR number to create environment for"),
    sha: Optional[str] = typer.Option(None, "--sha", help="Specific commit SHA (default: latest)"),
    ttl: Optional[str] = typer.Option("24h", help="Time to live (24h, 48h, 1w, close)"),
    size: Optional[str] = typer.Option("standard", help="Environment size (standard, large)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done"),
    dry_run_aws: bool = typer.Option(
        False, "--dry-run-aws", help="Skip AWS operations, use mock data"
    ),
    aws_sleep: int = typer.Option(0, "--aws-sleep", help="Seconds to sleep during AWS operations"),
    image_tag: Optional[str] = typer.Option(
        None, "--image-tag", help="Override ECR image tag (e.g., pr-34764-ci)"
    ),
    docker_tag: Optional[str] = typer.Option(
        None, "--docker-tag", help="Override Docker image tag (e.g., pr-34639-9a82c20-ci, latest)"
    ),
    force: bool = typer.Option(
        False, "--force", help="Force re-deployment by deleting existing service"
    ),
):
    """Create ephemeral environment for PR"""
    try:
        github = GitHubInterface()

        # Get SHA - use provided SHA or default to latest
        if not sha:
            sha = github.get_latest_commit_sha(pr_number)
            console.print(f"🎪 Using latest SHA: {sha[:7]}")
        else:
            console.print(f"🎪 Using specified SHA: {sha[:7]}")

        if dry_run:
            console.print("🎪 [bold yellow]DRY RUN[/bold yellow] - Would create environment:")
            console.print(f"  PR: #{pr_number}")
            console.print(f"  SHA: {sha[:7]}")
            console.print(f"  AWS Service: pr-{pr_number}-{sha[:7]}")
            console.print(f"  TTL: {ttl}")
            console.print("  Labels to add:")
            console.print("    🎪 🚦 building")
            console.print(f"    🎪 🎯 {sha[:7]}")
            console.print(f"    🎪 ⌛ {ttl}")
            return

        # Check if environment already exists
        pr = PullRequest.from_id(pr_number, github)
        if pr.current_show:
            console.print(
                f"🎪 [bold yellow]Environment already exists for PR #{pr_number}[/bold yellow]"
            )
            console.print(f"Current: {pr.current_show.sha} at {pr.current_show.ip}")
            console.print("Use 'showtime sync' to update or 'showtime stop' to clean up first")
            return

        # Create environment using trigger handler logic
        console.print(f"🎪 [bold blue]Creating environment for PR #{pr_number}...[/bold blue]")
        _handle_start_trigger(
            pr_number, github, dry_run_aws, (dry_run or False), aws_sleep, docker_tag, force
        )

    except GitHubError as e:
        console.print(f"🎪 [bold red]GitHub error:[/bold red] {e.message}")
    except Exception as e:
        console.print(f"🎪 [bold red]Error:[/bold red] {e}")


@app.command()
def status(
    pr_number: int = typer.Argument(..., help="PR number to check status for"),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Show detailed information"),
):
    """Show environment status for PR"""
    try:
        github = GitHubInterface()

        pr = PullRequest.from_id(pr_number, github)

        if not pr.has_shows():
            console.print(f"🎪 No environment found for PR #{pr_number}")
            return

        show = pr.current_show
        if not show:
            console.print(f"🎪 No active environment for PR #{pr_number}")
            if pr.building_show:
                console.print(f"🏗️ Building environment: {pr.building_show.sha}")
            return

        # Create status table
        table = Table(title=f"🎪 Environment Status - PR #{pr_number}")
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="white")

        status_emoji = STATUS_DISPLAY

        table.add_row("Status", f"{status_emoji.get(show.status, '❓')} {show.status.title()}")
        table.add_row("Environment", f"`{show.sha}`")
        table.add_row("AWS Service", f"`{show.aws_service_name}`")

        if show.ip:
            table.add_row("URL", f"http://{show.ip}:8080")

        if show.created_at:
            table.add_row("Created", show.created_at)

        table.add_row("TTL", show.ttl)

        if show.requested_by:
            table.add_row("Requested by", f"@{show.requested_by}")

        if verbose:
            table.add_row("All Labels", ", ".join(pr.circus_labels))

        console.print(table)

        # Show building environment if exists
        if pr.building_show and pr.building_show != show:
            console.print(
                f"🏗️ [bold yellow]Building new environment:[/bold yellow] {pr.building_show.sha}"
            )

    except GitHubError as e:
        console.print(f"🎪 [bold red]GitHub error:[/bold red] {e.message}")
    except Exception as e:
        console.print(f"🎪 [bold red]Error:[/bold red] {e}")


@app.command()
def stop(
    pr_number: int = typer.Argument(..., help="PR number to stop environment for"),
    force: bool = typer.Option(False, "--force", help="Force cleanup even if errors occur"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done"),
    dry_run_aws: bool = typer.Option(
        False, "--dry-run-aws", help="Skip AWS operations, use mock data"
    ),
    aws_sleep: int = typer.Option(0, "--aws-sleep", help="Seconds to sleep during AWS operations"),
):
    """Delete environment for PR"""
    try:
        github = GitHubInterface()

        pr = PullRequest.from_id(pr_number, github)

        if not pr.current_show:
            console.print(f"🎪 No active environment found for PR #{pr_number}")
            return

        show = pr.current_show
        console.print(f"🎪 [bold yellow]Stopping environment for PR #{pr_number}...[/bold yellow]")
        console.print(f"Environment: {show.sha} at {show.ip}")

        if dry_run:
            console.print("🎪 [bold yellow]DRY RUN[/bold yellow] - Would delete environment:")
            console.print(f"  AWS Service: {show.aws_service_name}")
            console.print(f"  ECR Image: {show.aws_image_tag}")
            console.print(f"  Circus Labels: {len(pr.circus_labels)} labels")
            return

        if not force:
            confirm = typer.confirm(f"Delete environment {show.aws_service_name}?")
            if not confirm:
                console.print("🎪 Cancelled")
                return

        if dry_run_aws:
            console.print("🎪 [bold yellow]DRY-RUN-AWS[/bold yellow] - Would delete AWS resources:")
            console.print(f"  - ECS service: {show.aws_service_name}")
            console.print(f"  - ECR image: {show.aws_image_tag}")
            if aws_sleep > 0:
                import time

                console.print(f"🎪 Sleeping {aws_sleep}s to simulate AWS cleanup...")
                time.sleep(aws_sleep)
            console.print("🎪 [bold green]Mock AWS cleanup complete![/bold green]")
        else:
            # Real AWS cleanup
            from .core.aws import AWSInterface

            console.print("🎪 [bold blue]Starting AWS cleanup...[/bold blue]")
            aws = AWSInterface()

            try:
                # Get current environment info
                pr = PullRequest.from_id(pr_number, github)

                if pr.current_show:
                    show = pr.current_show

                    # Show logs URL for monitoring cleanup
                    _show_service_urls(show, "cleanup")
                    console.print(f"🎪 Destroying environment: {show.aws_service_name}")

                    # Step 1: Check if ECS service exists and is active
                    service_name = show.ecs_service_name
                    console.print(f"🎪 Checking ECS service: {service_name}")

                    service_exists = aws._service_exists(service_name)

                    if service_exists:
                        console.print(f"🎪 Found active ECS service: {service_name}")

                        # Step 2: Delete ECS service
                        console.print("🎪 Deleting ECS service...")
                        success = aws._delete_ecs_service(service_name)

                        if success:
                            console.print("🎪 ✅ ECS service deleted successfully")

                            # Step 3: Delete ECR image tag
                            image_tag = f"pr-{pr_number}-ci"  # Match GHA image tag format
                            console.print(f"🎪 Deleting ECR image tag: {image_tag}")

                            ecr_success = aws._delete_ecr_image(image_tag)

                            if ecr_success:
                                console.print("🎪 ✅ ECR image deleted successfully")
                            else:
                                console.print("🎪 ⚠️ ECR image deletion failed (may not exist)")

                            console.print(
                                "🎪 [bold green]✅ AWS cleanup completed successfully![/bold green]"
                            )

                        else:
                            console.print("🎪 [bold red]❌ ECS service deletion failed[/bold red]")

                    else:
                        console.print(f"🎪 No active ECS service found: {service_name}")
                        console.print("🎪 ✅ No AWS resources to clean up")
                else:
                    console.print(f"🎪 No active environment found for PR #{pr_number}")

            except Exception as e:
                console.print(f"🎪 [bold red]❌ AWS cleanup failed:[/bold red] {e}")

        # Remove circus labels
        github.remove_circus_labels(pr_number)

        console.print("🎪 [bold green]Environment stopped and labels cleaned up![/bold green]")

    except GitHubError as e:
        console.print(f"🎪 [bold red]GitHub error:[/bold red] {e.message}")
    except Exception as e:
        console.print(f"🎪 [bold red]Error:[/bold red] {e}")


@app.command()
def list(
    status_filter: Optional[str] = typer.Option(
        None, "--status", help="Filter by status (running, building, etc.)"
    ),
    user: Optional[str] = typer.Option(None, "--user", help="Filter by user"),
):
    """List all environments"""
    try:
        github = GitHubInterface()

        # Find all PRs with circus tent labels
        pr_numbers = github.find_prs_with_shows()

        if not pr_numbers:
            console.print("🎪 No environments currently running")
            return

        # Collect all shows
        all_shows = []
        for pr_number in pr_numbers:
            pr = PullRequest.from_id(pr_number, github)
            for show in pr.shows:
                # Apply filters
                if status_filter and show.status != status_filter:
                    continue
                if user and show.requested_by != user:
                    continue
                all_shows.append(show)

        if not all_shows:
            filter_msg = ""
            if status_filter:
                filter_msg += f" with status '{status_filter}'"
            if user:
                filter_msg += f" by user '{user}'"
            console.print(f"🎪 No environments found{filter_msg}")
            return

        # Create table with full terminal width
        table = Table(title="🎪 Environment List", expand=True)
        table.add_column("PR", style="cyan", min_width=6)
        table.add_column("Status", style="white", min_width=12)
        table.add_column("SHA", style="green", min_width=11)
        table.add_column("Superset URL", style="blue", min_width=25)
        table.add_column("AWS Logs", style="dim blue", min_width=15)
        table.add_column("TTL", style="yellow", min_width=6)
        table.add_column("User", style="magenta", min_width=10)

        status_emoji = STATUS_DISPLAY

        for show in sorted(all_shows, key=lambda s: s.pr_number):
            # Make Superset URL clickable and show full URL
            if show.ip:
                full_url = f"http://{show.ip}:8080"
                superset_url = f"[link={full_url}]{full_url}[/link]"
            else:
                superset_url = "-"

            # Get AWS service URLs - iTerm2 supports Rich clickable links
            aws_urls = _get_service_urls(show)
            aws_logs_link = f"[link={aws_urls['logs']}]View[/link]"

            # Make PR number clickable
            pr_url = f"https://github.com/apache/superset/pull/{show.pr_number}"
            clickable_pr = f"[link={pr_url}]{show.pr_number}[/link]"

            table.add_row(
                clickable_pr,
                f"{status_emoji.get(show.status, '❓')} {show.status}",
                show.sha,
                superset_url,
                aws_logs_link,
                show.ttl,
                f"@{show.requested_by}" if show.requested_by else "-",
            )

        console.print(table)

    except GitHubError as e:
        console.print(f"🎪 [bold red]GitHub error:[/bold red] {e.message}")
    except Exception as e:
        console.print(f"🎪 [bold red]Error:[/bold red] {e}")


@app.command()
def labels():
    """🎪 Show complete circus tent label reference"""
    from .core.label_colors import LABEL_DEFINITIONS

    console.print("🎪 [bold blue]Circus Tent Label Reference[/bold blue]")
    console.print()

    # User Action Labels (from LABEL_DEFINITIONS)
    console.print("[bold yellow]🎯 User Action Labels (Add these to GitHub PR):[/bold yellow]")
    trigger_table = Table()
    trigger_table.add_column("Label", style="green")
    trigger_table.add_column("Description", style="dim")

    for label_name, definition in LABEL_DEFINITIONS.items():
        trigger_table.add_row(f"`{label_name}`", definition["description"])

    console.print(trigger_table)
    console.print()

    # State Labels
    console.print("[bold cyan]📊 State Labels (Automatically managed):[/bold cyan]")
    state_table = Table()
    state_table.add_column("Label", style="cyan")
    state_table.add_column("Meaning", style="white")
    state_table.add_column("Example", style="dim")

    state_table.add_row("🎪 {sha} 🚦 {status}", "Environment status", "🎪 abc123f 🚦 running")
    state_table.add_row("🎪 🎯 {sha}", "Active environment pointer", "🎪 🎯 abc123f")
    state_table.add_row("🎪 🏗️ {sha}", "Building environment pointer", "🎪 🏗️ def456a")
    state_table.add_row(
        "🎪 {sha} 📅 {timestamp}", "Creation timestamp", "🎪 abc123f 📅 2024-01-15T14-30"
    )
    state_table.add_row("🎪 {sha} 🌐 {ip-with-dashes}", "Environment IP", "🎪 abc123f 🌐 52-1-2-3")
    state_table.add_row("🎪 {sha} ⌛ {ttl-policy}", "TTL policy", "🎪 abc123f ⌛ 24h")
    state_table.add_row("🎪 {sha} 🤡 {username}", "Requested by", "🎪 abc123f 🤡 maxime")

    console.print(state_table)
    console.print()

    # Workflow Examples
    console.print("[bold magenta]🎪 Complete Workflow Examples:[/bold magenta]")
    console.print()

    console.print("[bold]1. Create Environment:[/bold]")
    console.print("   • Add label: [green]🎪 ⚡ showtime-trigger-start[/green]")
    console.print(
        "   • Watch for: [blue]🎪 abc123f 🚦 building[/blue] → [green]🎪 abc123f 🚦 running[/green]"
    )
    console.print(
        "   • Get URL from: [cyan]🎪 abc123f 🌐 52.1.2.3:8080[/cyan] → http://52.1.2.3:8080"
    )
    console.print()

    console.print("[bold]2. Freeze Environment (Optional):[/bold]")
    console.print("   • Add label: [orange]🎪 🧊 showtime-freeze[/orange]")
    console.print("   • Result: Environment won't auto-update on new commits")
    console.print("   • Use case: Test specific SHA while continuing development")
    console.print()

    console.print("[bold]3. Update to New Commit (Automatic):[/bold]")
    console.print("   • New commit pushed → Automatic blue-green rolling update")
    console.print(
        "   • Watch for: [blue]🎪 abc123f 🚦 updating[/blue] → [green]🎪 def456a 🚦 running[/green]"
    )
    console.print("   • SHA changes: [cyan]🎪 🎯 abc123f[/cyan] → [cyan]🎪 🎯 def456a[/cyan]")
    console.print()

    console.print("[bold]4. Clean Up:[/bold]")
    console.print("   • Add label: [red]🎪 🛑 showtime-trigger-stop[/red]")
    console.print("   • Result: All 🎪 labels removed, AWS resources deleted")
    console.print()

    console.print("[bold]📊 Understanding State:[/bold]")
    console.print("• [dim]TTL labels show policy (24h, 48h, close) not time remaining[/dim]")
    console.print("• [dim]Use 'showtime status {pr-id}' to calculate actual time remaining[/dim]")
    console.print("• [dim]Multiple SHA labels during updates (🎯 active, 🏗️ building)[/dim]")
    console.print()

    console.print("[dim]💡 Tip: Only maintainers with write access can add trigger labels[/dim]")


@app.command()
def test_lifecycle(
    pr_number: int,
    dry_run_aws: bool = typer.Option(
        True, "--dry-run-aws/--real-aws", help="Use mock AWS operations"
    ),
    dry_run_github: bool = typer.Option(
        True, "--dry-run-github/--real-github", help="Use mock GitHub operations"
    ),
    aws_sleep: int = typer.Option(10, "--aws-sleep", help="Seconds to sleep during AWS operations"),
):
    """🎪 Test full environment lifecycle with mock triggers"""

    console.print(f"🎪 [bold blue]Testing full lifecycle for PR #{pr_number}[/bold blue]")
    console.print(
        f"AWS: {'DRY-RUN' if dry_run_aws else 'REAL'}, GitHub: {'DRY-RUN' if dry_run_github else 'REAL'}"
    )
    console.print()

    try:
        github = GitHubInterface()

        console.print("🎪 [bold]Step 1: Simulate trigger-start[/bold]")
        _handle_start_trigger(pr_number, github, dry_run_aws, dry_run_github, aws_sleep, None)

        console.print()
        console.print("🎪 [bold]Step 2: Simulate config update[/bold]")
        console.print("🎪 [dim]Config changes now done via code commits, not labels[/dim]")

        console.print()
        console.print("🎪 [bold]Step 3: Simulate trigger-sync (new commit)[/bold]")
        _handle_sync_trigger(pr_number, github, dry_run_aws, dry_run_github, aws_sleep)

        console.print()
        console.print("🎪 [bold]Step 4: Simulate trigger-stop[/bold]")
        _handle_stop_trigger(pr_number, github, dry_run_aws, dry_run_github)

        console.print()
        console.print("🎪 [bold green]Full lifecycle test complete![/bold green]")

    except Exception as e:
        console.print(f"🎪 [bold red]Lifecycle test failed:[/bold red] {e}")


@app.command()
def sync(
    pr_number: int,
    sha: Optional[str] = typer.Option(None, "--sha", help="Specific commit SHA (default: latest)"),
    check_only: bool = typer.Option(
        False, "--check-only", help="Check what actions are needed without executing"
    ),
    dry_run_aws: bool = typer.Option(
        False, "--dry-run-aws", help="Skip AWS operations, use mock data"
    ),
    dry_run_github: bool = typer.Option(
        False, "--dry-run-github", help="Skip GitHub label operations"
    ),
    dry_run_docker: bool = typer.Option(
        False, "--dry-run-docker", help="Skip Docker build, use mock success"
    ),
    aws_sleep: int = typer.Option(
        0, "--aws-sleep", help="Seconds to sleep during AWS operations (for testing)"
    ),
    docker_tag: Optional[str] = typer.Option(
        None, "--docker-tag", help="Override Docker image tag (e.g., pr-34639-9a82c20-ci, latest)"
    ),
):
    """🎪 Intelligently sync PR to desired state (called by GitHub Actions)"""
    try:
        github = GitHubInterface()
        pr = PullRequest.from_id(pr_number, github)

        # Get PR metadata for state-based decisions
        pr_data = github.get_pr_data(pr_number)
        pr_state = pr_data.get("state", "open")  # open, closed

        # Get SHA - use provided SHA or default to latest
        if sha:
            target_sha = sha
            console.print(f"🎪 Using specified SHA: {target_sha[:7]}")
        else:
            target_sha = github.get_latest_commit_sha(pr_number)
            console.print(f"🎪 Using latest SHA: {target_sha[:7]}")

        # Determine what actions are needed
        action_needed = _determine_sync_action(pr, pr_state, target_sha)

        if check_only:
            # Output simple results for GitHub Actions
            build_needed = action_needed in ["create_environment", "rolling_update", "auto_sync"]
            sync_needed = action_needed != "no_action"

            console.print(f"build_needed={str(build_needed).lower()}")
            console.print(f"sync_needed={str(sync_needed).lower()}")
            console.print(f"pr_number={pr_number}")
            console.print(f"target_sha={target_sha}")
            return

        # Default behavior: execute the sync (directive command)
        # Use --check-only to override this and do read-only analysis
        if not check_only:
            console.print(
                f"🎪 [bold blue]Syncing PR #{pr_number}[/bold blue] (SHA: {target_sha[:7]})"
            )
            console.print(f"🎪 Action needed: {action_needed}")

            # For trigger-based actions, use atomic claim to prevent race conditions
            if action_needed in ["create_environment", "rolling_update", "destroy_environment"]:
                if not _atomic_claim_environment(pr_number, target_sha, github, dry_run_github):
                    console.print("🎪 Unable to claim environment - exiting")
                    return
                console.print("🎪 ✅ Environment claimed - proceeding with work")

            # Execute based on determined action
            if action_needed == "cleanup":
                console.print("🎪 PR is closed - cleaning up environment")
                if pr.current_show:
                    _handle_stop_trigger(pr_number, github, dry_run_aws, dry_run_github)
                else:
                    console.print("🎪 No environment to clean up")
                return

            elif action_needed in ["create_environment", "rolling_update"]:
                # These require Docker build + deployment
                console.print(f"🎪 Starting {action_needed} workflow")

                # Post building comment (atomic claim already set building state)
                if action_needed == "create_environment":
                    console.print("🎪 Posting building comment...")
                elif action_needed == "rolling_update":
                    console.print("🎪 Posting rolling update comment...")

                # Build Docker image
                build_success = _build_docker_image(pr_number, target_sha, dry_run_docker)
                if not build_success:
                    _set_state_internal(
                        "failed",
                        pr_number,
                        Show(
                            pr_number=pr_number,
                            sha=short_sha(target_sha),
                            status="failed",
                            requested_by=_get_github_actor(),
                        ),
                        github,
                        dry_run_github,
                        "Docker build failed",
                    )
                    return

                # Continue with AWS deployment (reuse existing logic)
                _handle_start_trigger(
                    pr_number,
                    github,
                    dry_run_aws,
                    dry_run_github,
                    aws_sleep,
                    docker_tag,
                    force=True,
                )
                return

            elif action_needed == "destroy_environment":
                console.print("🎪 Destroying environment")
                _handle_stop_trigger(pr_number, github, dry_run_aws, dry_run_github)
                return

            elif action_needed == "auto_sync":
                console.print("🎪 Auto-sync on new commit")
                # This also requires build + deployment
                build_success = _build_docker_image(pr_number, target_sha, dry_run_docker)
                if build_success:
                    _handle_sync_trigger(pr_number, github, dry_run_aws, dry_run_github, aws_sleep)
                else:
                    console.print("🎪 ❌ Auto-sync failed due to build failure")
                return

            else:
                console.print(f"🎪 No action needed ({action_needed})")
                return

        console.print(
            f"🎪 [bold blue]Syncing PR #{pr_number}[/bold blue] (state: {pr_state}, SHA: {target_sha[:7]})"
        )
        console.print(f"🎪 Action needed: {action_needed}")

        # Execute the determined action
        if action_needed == "cleanup":
            console.print("🎪 PR is closed - cleaning up environment")
            if pr.current_show:
                _handle_stop_trigger(pr_number, github, dry_run_aws, dry_run_github)
            else:
                console.print("🎪 No environment to clean up")
            return

        # 2. Find explicit trigger labels
        trigger_labels = [label for label in pr.labels if "showtime-trigger-" in label]

        # 3. Handle explicit triggers first
        if trigger_labels:
            console.print(f"🎪 Processing {len(trigger_labels)} explicit trigger(s)")

            for trigger in trigger_labels:
                console.print(f"🎪 Processing: {trigger}")

                # Remove trigger label immediately (atomic operation)
                if not dry_run_github:
                    github.remove_label(pr_number, trigger)
                else:
                    console.print(
                        f"🎪 [bold yellow]DRY-RUN-GITHUB[/bold yellow] - Would remove: {trigger}"
                    )

                # Process the trigger
                if "showtime-trigger-start" in trigger:
                    _handle_start_trigger(
                        pr_number, github, dry_run_aws, dry_run_github, aws_sleep, docker_tag
                    )
                elif "showtime-trigger-stop" in trigger:
                    _handle_stop_trigger(pr_number, github, dry_run_aws, dry_run_github)

            console.print("🎪 All explicit triggers processed!")
            return

        # 4. No explicit triggers - check for implicit sync needs
        console.print("🎪 No explicit triggers found - checking for implicit sync needs")

        if pr.current_show:
            # Environment exists - check if it needs updating
            if pr.current_show.needs_update(target_sha):
                console.print(
                    f"🎪 Environment outdated ({pr.current_show.sha} → {target_sha[:7]}) - auto-syncing"
                )
                _handle_sync_trigger(pr_number, github, dry_run_aws, dry_run_github, aws_sleep)
            else:
                console.print(f"🎪 Environment is up to date ({pr.current_show.sha})")
        else:
            console.print(f"🎪 No environment exists for PR #{pr_number} - no action needed")
            console.print("🎪 💡 Add '🎪 trigger-start' label to create an environment")

    except Exception as e:
        console.print(f"🎪 [bold red]Error processing triggers:[/bold red] {e}")


@app.command()
def handle_sync(pr_number: int):
    """🎪 Handle new commit sync (called by GitHub Actions on PR synchronize)"""
    try:
        github = GitHubInterface()
        pr = PullRequest.from_id(pr_number, github)

        # Only sync if there's an active environment
        if not pr.current_show:
            console.print(f"🎪 No active environment for PR #{pr_number} - skipping sync")
            return

        # Get latest commit SHA
        latest_sha = github.get_latest_commit_sha(pr_number)

        # Check if update is needed
        if not pr.current_show.needs_update(latest_sha):
            console.print(f"🎪 Environment already up to date for PR #{pr_number}")
            return

        console.print(f"🎪 Syncing PR #{pr_number} to commit {latest_sha[:7]}")

        # TODO: Implement rolling update logic
        console.print("🎪 [bold yellow]Sync logic not yet implemented[/bold yellow]")

    except Exception as e:
        console.print(f"🎪 [bold red]Error handling sync:[/bold red] {e}")


@app.command()
def setup_labels(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what labels would be created"),
):
    """🎪 Set up GitHub label definitions with colors and descriptions"""
    try:
        from .core.label_colors import LABEL_DEFINITIONS

        github = GitHubInterface()

        console.print("🎪 [bold blue]Setting up circus tent label definitions...[/bold blue]")

        created_count = 0
        updated_count = 0

        for label_name, definition in LABEL_DEFINITIONS.items():
            color = definition["color"]
            description = definition["description"]

            if dry_run:
                console.print(f"🏷️ Would create: [bold]{label_name}[/bold]")
                console.print(f"   Color: #{color}")
                console.print(f"   Description: {description}")
            else:
                try:
                    # Try to create or update the label
                    success = github.create_or_update_label(label_name, color, description)
                    if success:
                        created_count += 1
                        console.print(f"✅ Created: [bold]{label_name}[/bold]")
                    else:
                        updated_count += 1
                        console.print(f"🔄 Updated: [bold]{label_name}[/bold]")
                except Exception as e:
                    console.print(f"❌ Failed to create {label_name}: {e}")

        if not dry_run:
            console.print("\n🎪 [bold green]Label setup complete![/bold green]")
            console.print(f"   📊 Created: {created_count}")
            console.print(f"   🔄 Updated: {updated_count}")
            console.print(
                "\n🎪 [dim]Note: Dynamic labels (with SHA) are created automatically during deployment[/dim]"
            )

    except Exception as e:
        console.print(f"🎪 [bold red]Error setting up labels:[/bold red] {e}")


@app.command()
def cleanup(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be cleaned"),
    older_than: str = typer.Option(
        "48h", "--older-than", help="Clean environments older than this (ignored if --respect-ttl)"
    ),
    respect_ttl: bool = typer.Option(
        False, "--respect-ttl", help="Use individual TTL labels instead of global --older-than"
    ),
    max_age: Optional[str] = typer.Option(
        None, "--max-age", help="Maximum age limit when using --respect-ttl (e.g., 7d)"
    ),
    cleanup_labels: bool = typer.Option(
        True,
        "--cleanup-labels/--no-cleanup-labels",
        help="Also cleanup SHA-based label definitions from repository",
    ),
):
    """🎪 Clean up orphaned or expired environments and labels"""
    try:
        github = GitHubInterface()

        # Step 1: Clean up expired AWS ECS services
        console.print("🎪 [bold blue]Checking AWS ECS services for cleanup...[/bold blue]")

        from .core.aws import AWSInterface

        aws = AWSInterface()

        try:
            expired_services = aws.find_expired_services(older_than)

            if expired_services:
                console.print(f"🎪 Found {len(expired_services)} expired ECS services")

                for service_info in expired_services:
                    service_name = service_info["service_name"]
                    pr_number = service_info["pr_number"]
                    age_hours = service_info["age_hours"]

                    if dry_run:
                        console.print(
                            f"🎪 [yellow]Would delete service {service_name} (PR #{pr_number}, {age_hours:.1f}h old)[/yellow]"
                        )
                        console.print(
                            f"🎪 [dim]Monitor at: https://us-west-2.console.aws.amazon.com/ecs/v2/clusters/superset-ci/services/{service_name}/logs?region=us-west-2[/dim]"
                        )
                    else:
                        console.print(
                            f"🎪 Deleting expired service {service_name} (PR #{pr_number}, {age_hours:.1f}h old)"
                        )
                        # Create minimal Show object for URL generation
                        from .core.circus import Show

                        temp_show = Show(
                            pr_number=pr_number, sha=service_name.split("-")[2], status="cleanup"
                        )
                        _show_service_urls(temp_show, "cleanup")

                        # Delete ECS service
                        if aws._delete_ecs_service(service_name):
                            # Delete ECR image
                            image_tag = f"pr-{pr_number}-ci"
                            aws._delete_ecr_image(image_tag)
                            console.print(f"🎪 ✅ Cleaned up {service_name}")
                        else:
                            console.print(f"🎪 ❌ Failed to clean up {service_name}")
            else:
                console.print("🎪 [dim]No expired ECS services found[/dim]")

        except Exception as e:
            console.print(f"🎪 [bold red]AWS cleanup failed:[/bold red] {e}")

        # Step 2: Find and clean up expired environments from PRs
        if respect_ttl:
            console.print("🎪 Finding environments expired based on individual TTL labels")
        else:
            console.print(f"🎪 Finding environments older than {older_than}")
        prs_with_shows = github.find_prs_with_shows()

        if not prs_with_shows:
            console.print("🎪 [dim]No PRs with circus tent labels found[/dim]")
        else:
            console.print(f"🎪 Found {len(prs_with_shows)} PRs with shows")

            import re
            from datetime import datetime, timedelta

            from .core.circus import PullRequest, get_effective_ttl, parse_ttl_days

            # Parse max_age if provided (safety ceiling)
            max_age_days = None
            if max_age:
                max_age_days = parse_ttl_days(max_age)

            cleaned_prs = 0
            for pr_number in prs_with_shows:
                try:
                    pr = PullRequest.from_id(pr_number, github)
                    expired_shows = []

                    if respect_ttl:
                        # Use individual TTL labels
                        effective_ttl_days = get_effective_ttl(pr)

                        if effective_ttl_days is None:
                            # "never" label found - skip cleanup
                            console.print(
                                f"🎪 [blue]PR #{pr_number} marked as 'never expire' - skipping[/blue]"
                            )
                            continue

                        # Apply max_age ceiling if specified
                        if max_age_days and effective_ttl_days > max_age_days:
                            console.print(
                                f"🎪 [yellow]PR #{pr_number} TTL ({effective_ttl_days}d) exceeds max-age ({max_age_days}d)[/yellow]"
                            )
                            effective_ttl_days = max_age_days

                        cutoff_time = datetime.now() - timedelta(days=effective_ttl_days)
                        console.print(
                            f"🎪 PR #{pr_number} effective TTL: {effective_ttl_days} days"
                        )

                    else:
                        # Use global older_than parameter (current behavior)
                        time_match = re.match(r"(\d+)([hd])", older_than)
                        if not time_match:
                            console.print(
                                f"🎪 [bold red]Invalid time format:[/bold red] {older_than}"
                            )
                            return

                        hours = int(time_match.group(1))
                        if time_match.group(2) == "d":
                            hours *= 24

                        cutoff_time = datetime.now() - timedelta(hours=hours)

                    # Check all shows in the PR for expiration
                    for show in pr.shows:
                        if show.created_at:
                            try:
                                # Parse timestamp (format: 2024-01-15T14-30)
                                show_time = datetime.fromisoformat(
                                    show.created_at.replace("-", ":")
                                )
                                if show_time < cutoff_time:
                                    expired_shows.append(show)
                            except (ValueError, AttributeError):
                                # If we can't parse the timestamp, consider it expired
                                expired_shows.append(show)

                    if expired_shows:
                        if dry_run:
                            console.print(
                                f"🎪 [yellow]Would clean {len(expired_shows)} expired shows from PR #{pr_number}[/yellow]"
                            )
                            for show in expired_shows:
                                console.print(f"   - SHA {show.sha} ({show.status})")
                        else:
                            console.print(
                                f"🎪 Cleaning {len(expired_shows)} expired shows from PR #{pr_number}"
                            )

                            # Remove circus labels for expired shows
                            current_labels = github.get_circus_labels(pr_number)
                            labels_to_keep = []

                            for label in current_labels:
                                # Keep labels that don't belong to expired shows
                                should_keep = True
                                for expired_show in expired_shows:
                                    if expired_show.sha in label:
                                        should_keep = False
                                        break
                                if should_keep:
                                    labels_to_keep.append(label)

                            # Update PR labels
                            github.remove_circus_labels(pr_number)
                            for label in labels_to_keep:
                                github.add_label(pr_number, label)

                            cleaned_prs += 1

                except Exception as e:
                    console.print(f"🎪 [red]Error processing PR #{pr_number}:[/red] {e}")

            if not dry_run and cleaned_prs > 0:
                console.print(f"🎪 [green]Cleaned up environments from {cleaned_prs} PRs[/green]")

        # Step 2: Clean up SHA-based label definitions from repository
        if cleanup_labels:
            console.print("🎪 Finding SHA-based labels in repository")
            sha_labels = github.cleanup_sha_labels(dry_run=dry_run)

            if sha_labels:
                if dry_run:
                    console.print(
                        f"🎪 [yellow]Would delete {len(sha_labels)} SHA-based label definitions:[/yellow]"
                    )
                    for label in sha_labels[:10]:  # Show first 10
                        console.print(f"   - {label}")
                    if len(sha_labels) > 10:
                        console.print(f"   ... and {len(sha_labels) - 10} more")
                else:
                    console.print(
                        f"🎪 [green]Deleted {len(sha_labels)} SHA-based label definitions[/green]"
                    )
            else:
                console.print("🎪 [dim]No SHA-based labels found to clean[/dim]")

    except Exception as e:
        console.print(f"🎪 [bold red]Error during cleanup:[/bold red] {e}")


# Helper functions for trigger processing
def _handle_start_trigger(
    pr_number: int,
    github: GitHubInterface,
    dry_run_aws: bool = False,
    dry_run_github: bool = False,
    aws_sleep: int = 0,
    docker_tag_override: Optional[str] = None,
    force: bool = False,
):
    """Handle start trigger"""
    import time
    from datetime import datetime

    console.print(f"🎪 Starting environment for PR #{pr_number}")

    try:
        # Get latest SHA and GitHub actor
        latest_sha = github.get_latest_commit_sha(pr_number)
        github_actor = _get_github_actor()

        # Create new show
        show = Show(
            pr_number=pr_number,
            sha=short_sha(latest_sha),
            status="building",
            created_at=datetime.utcnow().strftime("%Y-%m-%dT%H-%M"),
            ttl="24h",
            requested_by=github_actor,
        )

        console.print(f"🎪 Creating environment {show.aws_service_name}")

        # Post confirmation comment
        confirmation_comment = start_comment(show)

        if not dry_run_github:
            github.post_comment(pr_number, confirmation_comment)

        # Set building state labels
        building_labels = show.to_circus_labels()
        console.print("🎪 Setting building state labels:")
        for label in building_labels:
            console.print(f"  + {label}")

        # Set building labels
        if not dry_run_github:
            # Actually set the labels for real testing
            console.print("🎪 Setting labels on GitHub...")
            # Remove existing circus labels first
            github.remove_circus_labels(pr_number)
            # Add new labels one by one
            for label in building_labels:
                github.add_label(pr_number, label)
            console.print("🎪 ✅ Labels set on GitHub!")
        else:
            console.print("🎪 [bold yellow]DRY-RUN-GITHUB[/bold yellow] - Would set labels")

        if dry_run_aws:
            console.print("🎪 [bold yellow]DRY-RUN-AWS[/bold yellow] - Skipping AWS operations")
            if aws_sleep > 0:
                console.print(f"🎪 Sleeping {aws_sleep}s to simulate AWS build time...")
                time.sleep(aws_sleep)

            # Mock successful deployment
            mock_ip = "52.1.2.3"
            console.print(
                f"🎪 [bold green]Mock AWS deployment successful![/bold green] IP: {mock_ip}"
            )

            # Update to running state
            show.status = "running"
            show.ip = mock_ip

            running_labels = show.to_circus_labels()
            console.print("🎪 Setting running state labels:")
            for label in running_labels:
                console.print(f"  + {label}")

            # Set running labels
            if not dry_run_github:
                console.print("🎪 Updating to running state...")
                # Remove existing circus labels first
                github.remove_circus_labels(pr_number)
                # Add new running labels
                for label in running_labels:
                    github.add_label(pr_number, label)
                console.print("🎪 ✅ Labels updated to running state!")
            else:
                console.print(
                    "🎪 [bold yellow]DRY-RUN-GITHUB[/bold yellow] - Would update to running state"
                )

            # Post success comment (only in dry-run-aws mode since we have mock IP)
            # Create mock show with IP for success comment
            mock_show = Show(
                pr_number=show.pr_number,
                sha=show.sha,
                status="running",
                ip=mock_ip,
                ttl=show.ttl,
                requested_by=show.requested_by,
            )
            success_comment_text = success_comment(mock_show)

            if not dry_run_github:
                github.post_comment(pr_number, success_comment_text)

        else:
            # Real AWS operations
            from .core.aws import AWSInterface, EnvironmentResult

            console.print("🎪 [bold blue]Starting AWS deployment...[/bold blue]")
            aws = AWSInterface()

            # Show logs URL immediately for monitoring
            _show_service_urls(show, "deployment")

            # Parse feature flags from PR description (replicate GHA feature flag logic)
            feature_flags = _extract_feature_flags_from_pr(pr_number, github)

            # Create environment (synchronous, matches GHA wait behavior)
            result: EnvironmentResult = aws.create_environment(
                pr_number=pr_number,
                sha=latest_sha,
                github_user=github_actor,
                feature_flags=feature_flags,
                image_tag_override=docker_tag_override,
                force=force,
            )

            if result.success:
                console.print(
                    f"🎪 [bold green]✅ Green service deployed successfully![/bold green] IP: {result.ip}"
                )

                # Show helpful links for the new service
                console.print("\n🎪 [bold blue]Useful Links:[/bold blue]")
                console.print(f"   🌐 Environment: http://{result.ip}:8080")

                # Use centralized URL generation
                urls = _get_service_urls(show)
                console.print(f"   📊 ECS Service: {urls['service']}")
                console.print(f"   📝 Service Logs: {urls['logs']}")
                console.print(f"   🏥 Health Checks: {urls['health']}")
                console.print(
                    f"   🔍 GitHub PR: https://github.com/apache/superset/pull/{pr_number}"
                )
                console.print(
                    "\n🎪 [dim]Note: Superset takes 2-3 minutes to initialize after container starts[/dim]"
                )

                # Blue-Green Traffic Switch: Update GitHub labels to point to new service
                console.print(
                    f"\n🎪 [bold blue]Switching traffic to green service {latest_sha[:7]}...[/bold blue]"
                )

                # Check for existing services to show blue-green transition
                from .core.aws import AWSInterface

                aws = AWSInterface()
                existing_services = aws._find_pr_services(pr_number)

                if len(existing_services) > 1:
                    console.print("🔄 Blue-Green Deployment:")
                    blue_services = []
                    for svc in existing_services:
                        if svc["sha"] == latest_sha[:7]:
                            console.print(
                                f"   🟢 Green: {svc['service_name']} (NEW - receiving traffic)"
                            )
                        else:
                            console.print(
                                f"   🔵 Blue: {svc['service_name']} (OLD - will be cleaned up in 5 minutes)"
                            )
                            blue_services.append(svc)

                    # Schedule cleanup of blue services
                    if blue_services:
                        console.print(
                            f"\n🧹 Scheduling cleanup of {len(blue_services)} blue service(s) in 5 minutes..."
                        )
                        _schedule_blue_cleanup(pr_number, blue_services)

                # Update show with deployment result
                show.ip = result.ip

                # Use internal helper to set running state (posts success comment)
                console.print("\n🎪 Traffic switching to running state:")
                _set_state_internal("running", pr_number, show, github, dry_run_github)

            else:
                console.print(f"🎪 [bold red]❌ AWS deployment failed:[/bold red] {result.error}")

                # Use internal helper to set failed state (posts failure comment)
                _set_state_internal("failed", pr_number, show, github, dry_run_github, result.error)

    except Exception as e:
        console.print(f"🎪 [bold red]Start trigger failed:[/bold red] {e}")


def _extract_feature_flags_from_pr(pr_number: int, github: GitHubInterface) -> list:
    """Extract feature flags from PR description (replicate GHA eval-feature-flags step)"""
    import re

    try:
        # Get PR description
        pr_data = github.get_pr_data(pr_number)
        description = pr_data.get("body") or ""

        # Replicate exact GHA regex pattern: FEATURE_(\w+)=(\w+)
        pattern = r"FEATURE_(\w+)=(\w+)"
        results = []

        for match in re.finditer(pattern, description):
            feature_config = {"name": f"SUPERSET_FEATURE_{match.group(1)}", "value": match.group(2)}
            results.append(feature_config)
            console.print(
                f"🎪 Found feature flag: {feature_config['name']}={feature_config['value']}"
            )

        return results

    except Exception as e:
        console.print(f"🎪 Warning: Could not extract feature flags: {e}")
        return []


def _handle_stop_trigger(
    pr_number: int, github: GitHubInterface, dry_run_aws: bool = False, dry_run_github: bool = False
):
    """Handle stop trigger"""

    console.print(f"🎪 Stopping environment for PR #{pr_number}")

    try:
        pr = PullRequest.from_id(pr_number, github)

        if not pr.current_show:
            console.print(f"🎪 No active environment found for PR #{pr_number}")
            return

        show = pr.current_show
        console.print(f"🎪 Destroying environment: {show.aws_service_name}")

        if dry_run_aws:
            console.print("🎪 [bold yellow]DRY-RUN-AWS[/bold yellow] - Would delete AWS resources")
            console.print(f"  - ECS service: {show.aws_service_name}")
            console.print(f"  - ECR image: {show.aws_image_tag}")
        else:
            # Real AWS cleanup (replicate ephemeral-env-pr-close.yml logic)
            from .core.aws import AWSInterface

            console.print("🎪 [bold blue]Starting AWS cleanup...[/bold blue]")
            aws = AWSInterface()

            try:
                # Show logs URL for monitoring cleanup
                _show_service_urls(show, "cleanup")

                # Step 1: Check if ECS service exists and is active (replicate GHA describe-services)
                service_name = show.ecs_service_name
                console.print(f"🎪 Checking ECS service: {service_name}")

                service_exists = aws._service_exists(service_name)

                if service_exists:
                    console.print(f"🎪 Found active ECS service: {service_name}")

                    # Step 2: Delete ECS service (replicate GHA delete-service)
                    console.print("🎪 Deleting ECS service...")
                    success = aws._delete_ecs_service(service_name)

                    if success:
                        console.print("🎪 ✅ ECS service deleted successfully")

                        # Step 3: Delete ECR image tag (replicate GHA batch-delete-image)
                        image_tag = f"pr-{pr_number}-ci"  # Match GHA image tag format
                        console.print(f"🎪 Deleting ECR image tag: {image_tag}")

                        ecr_success = aws._delete_ecr_image(image_tag)

                        if ecr_success:
                            console.print("🎪 ✅ ECR image deleted successfully")
                        else:
                            console.print("🎪 ⚠️ ECR image deletion failed (may not exist)")

                        console.print(
                            "🎪 [bold green]✅ AWS cleanup completed successfully![/bold green]"
                        )

                    else:
                        console.print("🎪 [bold red]❌ ECS service deletion failed[/bold red]")

                else:
                    console.print(f"🎪 No active ECS service found: {service_name}")
                    console.print("🎪 ✅ No AWS resources to clean up")

            except Exception as e:
                console.print(f"🎪 [bold red]❌ AWS cleanup failed:[/bold red] {e}")

        # Remove all circus labels for this PR
        console.print(f"🎪 Removing all circus labels for PR #{pr_number}")
        if not dry_run_github:
            github.remove_circus_labels(pr_number)

        # Post cleanup comment
        github_actor = _get_github_actor()
        cleanup_comment = f"""🎪 @{github_actor} Environment `{show.sha}` cleaned up

**AWS Resources:** ECS service and ECR image deleted
**Cost Impact:** No further charges

Add `🎪 trigger-start` to create a new environment.

{_get_showtime_footer()}"""

        if not dry_run_github:
            github.post_comment(pr_number, cleanup_comment)

        console.print("🎪 [bold green]Environment stopped![/bold green]")

    except Exception as e:
        console.print(f"🎪 [bold red]Stop trigger failed:[/bold red] {e}")


def _handle_sync_trigger(
    pr_number: int,
    github: GitHubInterface,
    dry_run_aws: bool = False,
    dry_run_github: bool = False,
    aws_sleep: int = 0,
):
    """Handle sync trigger"""
    import time
    from datetime import datetime

    console.print(f"🎪 Syncing environment for PR #{pr_number}")

    try:
        pr = PullRequest.from_id(pr_number, github)

        if not pr.current_show:
            console.print(f"🎪 No active environment for PR #{pr_number}")
            return

        latest_sha = github.get_latest_commit_sha(pr_number)

        if not pr.current_show.needs_update(latest_sha):
            console.print(f"🎪 Environment already up to date: {pr.current_show.sha}")
            return

        console.print(f"🎪 Rolling update: {pr.current_show.sha} → {latest_sha[:7]}")

        # Create new show for building
        new_show = Show(
            pr_number=pr_number,
            sha=latest_sha[:7],
            status="building",
            created_at=datetime.utcnow().strftime("%Y-%m-%dT%H-%M"),
            ttl=pr.current_show.ttl,
            requested_by=pr.current_show.requested_by,
        )

        console.print(f"🎪 Building new environment: {new_show.aws_service_name}")

        if dry_run_aws:
            console.print("🎪 [bold yellow]DRY-RUN-AWS[/bold yellow] - Mocking rolling update")
            if aws_sleep > 0:
                console.print(f"🎪 Sleeping {aws_sleep}s to simulate build + deploy...")
                time.sleep(aws_sleep)

            # Mock successful update
            new_show.status = "running"
            new_show.ip = "52.4.5.6"  # New mock IP

            console.print("🎪 [bold green]Mock rolling update complete![/bold green]")
            console.print(f"🎪 Traffic switched to {new_show.sha} at {new_show.ip}")

            # Post rolling update success comment
            update_comment = f"""🎪 Environment updated: {pr.current_show.sha} → `{new_show.sha}`

**New Environment:** http://{new_show.ip}:8080
**Update:** Zero-downtime rolling deployment
**Old Environment:** Automatically cleaned up

Your latest changes are now live.

{_get_showtime_footer()}"""

            if not dry_run_github:
                github.post_comment(pr_number, update_comment)

        else:
            # Real rolling update - use same blue-green deployment logic

            from .core.aws import AWSInterface, EnvironmentResult

            console.print("🎪 [bold blue]Starting real rolling update...[/bold blue]")

            # Post rolling update start comment
            start_comment_text = rolling_start_comment(pr.current_show, latest_sha)

            if not dry_run_github:
                github.post_comment(pr_number, start_comment_text)

            aws = AWSInterface()

            # Get feature flags from PR description
            feature_flags = _extract_feature_flags_from_pr(pr_number, github)
            github_actor = _get_github_actor()

            # Use blue-green deployment (create_environment handles existing services)
            result: EnvironmentResult = aws.create_environment(
                pr_number=pr_number,
                sha=latest_sha,
                github_user=github_actor,
                feature_flags=feature_flags,
                force=False,  # Don't force - let blue-green handle it
            )

            if result.success:
                console.print(
                    f"🎪 [bold green]✅ Rolling update complete![/bold green] New IP: {result.ip}"
                )

                # Update labels to point to new service
                pr.refresh_labels(github)
                new_show = pr.get_show_by_sha(latest_sha)
                if new_show:
                    new_show.status = "running"
                    new_show.ip = result.ip

                    # Update GitHub labels
                    github.remove_circus_labels(pr_number)
                    for label in new_show.to_circus_labels():
                        github.add_label(pr_number, label)

                    console.print("🎪 ✅ Labels updated to point to new environment")

                    # Post rolling update success comment
                    success_comment_text = rolling_success_comment(pr.current_show, new_show)

                    if not dry_run_github:
                        github.post_comment(pr_number, success_comment_text)
            else:
                console.print(f"🎪 [bold red]❌ Rolling update failed:[/bold red] {result.error}")

                # Post rolling update failure comment
                failure_comment_text = rolling_failure_comment(
                    pr.current_show, latest_sha, result.error
                )

                if not dry_run_github:
                    github.post_comment(pr_number, failure_comment_text)

    except Exception as e:
        console.print(f"🎪 [bold red]Sync trigger failed:[/bold red] {e}")


def main():
    """Main entry point for the CLI"""
    app()


if __name__ == "__main__":
    main()
