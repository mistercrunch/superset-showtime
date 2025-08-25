"""
🎪 Superset Showtime CLI

Main command-line interface for Apache Superset circus tent environment management.
"""

from typing import Dict, Optional

import typer
from rich.console import Console
from rich.table import Table

from .core.emojis import STATUS_DISPLAY
from .core.github import GitHubError, GitHubInterface
from .core.github_messages import (
    get_aws_console_urls,
)
from .core.pull_request import PullRequest
from .core.show import Show

# Constants
DEFAULT_GITHUB_ACTOR = "unknown"


def _get_service_urls(show: Show) -> Dict[str, str]:
    """Get AWS Console URLs for a service"""
    return get_aws_console_urls(show.ecs_service_name)


def _show_service_urls(show: Show, context: str = "deployment") -> None:
    """Show helpful AWS Console URLs for monitoring service"""
    urls = _get_service_urls(show)
    p(f"\n🎪 [bold blue]Monitor {context} progress:[/bold blue]")
    p(f"📝 Logs: {urls['logs']}")
    p(f"📊 Service: {urls['service']}")
    p("")


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
    no_args_is_help=True,
)

console = Console()
p = console.print  # Shorthand for cleaner code


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
    return "🎪 *Managed by [Superset Showtime](https://github.com/your-org/superset-showtime)*"


@app.command()
def version() -> None:
    """Show version information"""
    from . import __version__

    p(f"🎪 Superset Showtime v{__version__}")


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
) -> None:
    """Create ephemeral environment for PR"""
    try:
        pr = PullRequest.from_id(pr_number)

        # Check if working environment already exists (unless force)
        if pr.current_show and pr.current_show.status not in ["failed"] and not force:
            p(f"🎪 [bold yellow]Environment already exists for PR #{pr_number}[/bold yellow]")
            ip_info = f" at {pr.current_show.ip}" if pr.current_show.ip else ""
            p(f"Current: {pr.current_show.sha}{ip_info} ({pr.current_show.status})")
            p("Use 'showtime sync' to update or 'showtime stop' to clean up first")
            return

        # Handle failed environment replacement
        if pr.current_show and pr.current_show.status == "failed":
            p(f"🎪 [bold orange]Replacing failed environment for PR #{pr_number}[/bold orange]")
            p(f"Failed: {pr.current_show.sha} at {pr.current_show.created_at}")
            p("🔄 Creating new environment...")
        elif pr.current_show:
            p(f"🎪 [bold blue]Creating environment for PR #{pr_number}[/bold blue]")
        else:
            p(f"🎪 [bold green]Creating new environment for PR #{pr_number}[/bold green]")

        if dry_run:
            from .core.pull_request import get_github

            target_sha = sha or get_github().get_latest_commit_sha(pr_number)
            p("🎪 [bold yellow]DRY RUN[/bold yellow] - Would create environment:")
            p(f"  PR: #{pr_number}")
            p(f"  SHA: {target_sha[:7]}")
            p(f"  AWS Service: pr-{pr_number}-{target_sha[:7]}")
            p(f"  TTL: {ttl}")
            return

        # Use PullRequest method for all logic
        result = pr.start_environment(sha=sha, dry_run_github=False, dry_run_aws=dry_run_aws)

        if result.success:
            if result.show:
                p(f"🎪 ✅ Environment created: {result.show.sha}")
            else:
                p("🎪 ✅ Environment created")
        else:
            p(f"🎪 ❌ Failed to create environment: {result.error}")
            raise typer.Exit(1)

    except GitHubError as e:
        p(f"❌ GitHub error: {e}")
        raise typer.Exit(1) from e
    except Exception as e:
        p(f"❌ Error: {e}")
        raise typer.Exit(1) from e


@app.command()
def status(
    pr_number: int = typer.Argument(..., help="PR number to check status for"),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Show detailed information"),
) -> None:
    """Show environment status for PR"""
    try:
        pr = PullRequest.from_id(pr_number)

        # Use PullRequest method for data
        status_data = pr.get_status()

        if status_data["status"] == "no_environment":
            p(f"🎪 No environment found for PR #{pr_number}")
            return

        show_data = status_data["show"]

        # Create status table
        table = Table(title=f"🎪 Environment Status - PR #{pr_number}")
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="white")

        status_emoji = STATUS_DISPLAY
        table.add_row(
            "Status", f"{status_emoji.get(show_data['status'], '❓')} {show_data['status'].title()}"
        )
        table.add_row("Environment", f"`{show_data['sha']}`")
        table.add_row("AWS Service", f"`{show_data['aws_service_name']}`")

        if show_data["ip"]:
            table.add_row("URL", f"http://{show_data['ip']}:8080")
        if show_data["created_at"]:
            table.add_row("Created", show_data["created_at"])

        table.add_row("TTL", show_data["ttl"])

        if show_data["requested_by"]:
            table.add_row("Requested by", f"@{show_data['requested_by']}")

        # Show active triggers
        trigger_labels = [label for label in pr.labels if "showtime-trigger-" in label]
        if trigger_labels:
            trigger_display = ", ".join(trigger_labels)
            table.add_row("Active Triggers", trigger_display)

        if verbose:
            table.add_row("All Labels", ", ".join(pr.circus_labels))

        p(table)

        # Show building environment if exists
        if pr.building_show and pr.building_show.sha != show_data["sha"]:
            p(f"🏗️ [bold yellow]Building new environment:[/bold yellow] {pr.building_show.sha}")

    except GitHubError as e:
        p(f"❌ GitHub error: {e}")
        raise typer.Exit(1) from e
    except Exception as e:
        p(f"❌ Error: {e}")
        raise typer.Exit(1) from e


@app.command()
def stop(
    pr_number: int = typer.Argument(..., help="PR number to stop environment for"),
    force: bool = typer.Option(False, "--force", help="Force cleanup even if errors occur"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done"),
    dry_run_aws: bool = typer.Option(
        False, "--dry-run-aws", help="Skip AWS operations, use mock data"
    ),
    aws_sleep: int = typer.Option(0, "--aws-sleep", help="Seconds to sleep during AWS operations"),
) -> None:
    """Delete environment for PR"""
    try:
        pr = PullRequest.from_id(pr_number)

        if not pr.current_show:
            p(f"🎪 No active environment found for PR #{pr_number}")
            return

        show = pr.current_show
        p(f"🎪 [bold yellow]Stopping environment for PR #{pr_number}...[/bold yellow]")
        p(f"Environment: {show.sha} at {show.ip}")

        if dry_run:
            p("🎪 [bold yellow]DRY RUN[/bold yellow] - Would delete environment:")
            p(f"  AWS Service: {show.aws_service_name}")
            p(f"  ECR Image: {show.aws_image_tag}")
            p(f"  Circus Labels: {len(pr.circus_labels)} labels")
            return

        if not force:
            confirm = typer.confirm(f"Delete environment {show.aws_service_name}?")
            if not confirm:
                p("🎪 Cancelled")
                return

        # Use PullRequest method for all logic
        result = pr.stop_environment(dry_run_github=False, dry_run_aws=dry_run_aws)

        if result.success:
            p("🎪 ✅ Environment stopped and cleaned up!")
        else:
            p(f"🎪 ❌ Failed to stop environment: {result.error}")
            raise typer.Exit(1)

    except GitHubError as e:
        p(f"❌ GitHub error: {e}")
        raise typer.Exit(1) from e
    except Exception as e:
        p(f"❌ Error: {e}")
        raise typer.Exit(1) from e


@app.command()
def list(
    status_filter: Optional[str] = typer.Option(
        None, "--status", help="Filter by status (running, building, etc.)"
    ),
    user: Optional[str] = typer.Option(None, "--user", help="Filter by user"),
) -> None:
    """List all environments"""
    try:
        # Use PullRequest method for data collection
        all_environments = PullRequest.list_all_environments()

        if not all_environments:
            p("🎪 No environments currently running")
            return

        # Apply filters
        filtered_envs = []
        for env in all_environments:
            show_data = env["show"]
            if status_filter and show_data["status"] != status_filter:
                continue
            if user and show_data["requested_by"] != user:
                continue
            filtered_envs.append(env)

        if not filtered_envs:
            filter_msg = ""
            if status_filter:
                filter_msg += f" with status '{status_filter}'"
            if user:
                filter_msg += f" by user '{user}'"
            p(f"🎪 No environments found{filter_msg}")
            return

        # Create table with full terminal width
        table = Table(title="🎪 Environment List", expand=True)
        table.add_column("PR", style="cyan", min_width=6)
        table.add_column("Type", style="white", min_width=8)
        table.add_column("Status", style="white", min_width=12)
        table.add_column("SHA", style="green", min_width=11)
        table.add_column("Created", style="dim white", min_width=12)
        table.add_column("Superset URL", style="blue", min_width=25)
        table.add_column("AWS Logs", style="dim blue", min_width=15)
        table.add_column("TTL", style="yellow", min_width=6)
        table.add_column("User", style="magenta", min_width=10)

        status_emoji = STATUS_DISPLAY

        # Sort by PR number, then by show type (active first, then building, then orphaned)
        type_priority = {"active": 1, "building": 2, "orphaned": 3}
        sorted_envs = sorted(
            filtered_envs,
            key=lambda e: (
                e["pr_number"],
                type_priority.get(e["show"].get("show_type", "orphaned"), 3),
            ),
        )

        for env in sorted_envs:
            show_data = env["show"]
            pr_number = env["pr_number"]

            # Show type with appropriate styling (using single-width chars for alignment)
            show_type = show_data.get("show_type", "orphaned")
            if show_type == "active":
                type_display = "* active"
            elif show_type == "building":
                type_display = "# building"
            else:
                type_display = "! orphaned"

            # Make Superset URL clickable and show full URL
            if show_data["ip"]:
                full_url = f"http://{show_data['ip']}:8080"
                superset_url = f"[link={full_url}]{full_url}[/link]"
            else:
                superset_url = "-"

            # Get AWS service URLs - iTerm2 supports Rich clickable links
            from .core.github_messages import get_aws_console_urls

            aws_urls = get_aws_console_urls(show_data["aws_service_name"])
            aws_logs_link = f"[link={aws_urls['logs']}]View[/link]"

            # Make PR number clickable
            pr_url = f"https://github.com/apache/superset/pull/{pr_number}"
            clickable_pr = f"[link={pr_url}]{pr_number}[/link]"

            # Format creation time for display
            created_display = show_data.get("created_at", "-")
            if created_display and created_display != "-":
                # Convert 2025-08-25T05-18 to more readable format
                try:
                    parts = created_display.replace("T", " ").replace("-", ":")
                    created_display = parts[-8:]  # Show just HH:MM:SS
                except Exception:
                    pass  # Keep original if parsing fails

            table.add_row(
                clickable_pr,
                type_display,
                f"{status_emoji.get(show_data['status'], '❓')} {show_data['status']}",
                show_data["sha"],
                created_display,
                superset_url,
                aws_logs_link,
                show_data["ttl"],
                f"@{show_data['requested_by']}" if show_data["requested_by"] else "-",
            )

        p(table)

    except GitHubError as e:
        p(f"❌ GitHub error: {e}")
        raise typer.Exit(1) from e
    except Exception as e:
        p(f"❌ Error: {e}")
        raise typer.Exit(1) from e


@app.command()
def labels() -> None:
    """🎪 Show complete circus tent label reference"""
    from .core.label_colors import LABEL_DEFINITIONS

    p("🎪 [bold blue]Circus Tent Label Reference[/bold blue]")
    p()

    # User Action Labels (from LABEL_DEFINITIONS)
    p("[bold yellow]🎯 User Action Labels (Add these to GitHub PR):[/bold yellow]")
    trigger_table = Table()
    trigger_table.add_column("Label", style="green")
    trigger_table.add_column("Description", style="dim")

    for label_name, definition in LABEL_DEFINITIONS.items():
        trigger_table.add_row(f"`{label_name}`", definition["description"])

    p(trigger_table)
    p()

    # State Labels
    p("[bold cyan]📊 State Labels (Automatically managed):[/bold cyan]")
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

    p(state_table)
    p()

    # Workflow Examples
    p("[bold magenta]🎪 Complete Workflow Examples:[/bold magenta]")
    p()

    p("[bold]1. Create Environment:[/bold]")
    p("   • Add label: [green]🎪 ⚡ showtime-trigger-start[/green]")
    p("   • Watch for: [blue]🎪 abc123f 🚦 building[/blue] → [green]🎪 abc123f 🚦 running[/green]")
    p("   • Get URL from: [cyan]🎪 abc123f 🌐 52.1.2.3:8080[/cyan] → http://52.1.2.3:8080")
    p()

    p("[bold]2. Freeze Environment (Optional):[/bold]")
    p("   • Add label: [orange]🎪 🧊 showtime-freeze[/orange]")
    p("   • Result: Environment won't auto-update on new commits")
    p("   • Use case: Test specific SHA while continuing development")
    p()

    p("[bold]3. Update to New Commit (Automatic):[/bold]")
    p("   • New commit pushed → Automatic blue-green rolling update")
    p("   • Watch for: [blue]🎪 abc123f 🚦 updating[/blue] → [green]🎪 def456a 🚦 running[/green]")
    p("   • SHA changes: [cyan]🎪 🎯 abc123f[/cyan] → [cyan]🎪 🎯 def456a[/cyan]")
    p()

    p("[bold]4. Clean Up:[/bold]")
    p("   • Add label: [red]🎪 🛑 showtime-trigger-stop[/red]")
    p("   • Result: All 🎪 labels removed, AWS resources deleted")
    p()

    p("[bold]📊 Understanding State:[/bold]")
    p("• [dim]TTL labels show policy (24h, 48h, close) not time remaining[/dim]")
    p("• [dim]Use 'showtime status {pr-id}' to calculate actual time remaining[/dim]")
    p("• [dim]Multiple SHA labels during updates (🎯 active, 🏗️ building)[/dim]")
    p()

    p("[dim]💡 Tip: Only maintainers with write access can add trigger labels[/dim]")


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
) -> None:
    """🎪 Intelligently sync PR to desired state (called by GitHub Actions)"""
    try:
        # Validate required Git SHA unless using --check-only
        if not check_only:
            from .core.git_validation import (
                get_validation_error_message,
                should_skip_validation,
                validate_required_sha,
            )

            if not should_skip_validation():
                is_valid, error_msg = validate_required_sha()
                if not is_valid:
                    p(get_validation_error_message())
                    raise typer.Exit(1)
        # Use singletons - no interface creation needed
        pr = PullRequest.from_id(pr_number)

        # Get target SHA - use provided SHA or default to latest
        if sha:
            target_sha = sha
            p(f"🎪 Using specified SHA: {target_sha[:7]}")
        else:
            from .core.pull_request import get_github

            target_sha = get_github().get_latest_commit_sha(pr_number)
            p(f"🎪 Using latest SHA: {target_sha[:7]}")

        # Get PR state for analysis
        from .core.pull_request import get_github

        pr_data = get_github().get_pr_data(pr_number)
        pr_state = pr_data.get("state", "open")

        if check_only:
            # Analysis mode - just return what's needed
            analysis_result = pr.analyze(target_sha, pr_state)
            p(f"build_needed={str(analysis_result.build_needed).lower()}")
            p(f"sync_needed={str(analysis_result.sync_needed).lower()}")
            p(f"pr_number={pr_number}")
            p(f"target_sha={target_sha}")
            return

        # Execution mode - do the sync
        p(f"🎪 [bold blue]Syncing PR #{pr_number}[/bold blue] (SHA: {target_sha[:7]})")

        # Handle closed PRs specially
        if pr_state == "closed":
            p("🎪 PR is closed - cleaning up environment")
            if pr.current_show:
                stop_result = pr.stop_environment(
                    dry_run_github=dry_run_github, dry_run_aws=dry_run_aws
                )
                if stop_result.success:
                    p("🎪 ✅ Cleanup completed")
                else:
                    p(f"🎪 ❌ Cleanup failed: {stop_result.error}")
            else:
                p("🎪 No environment to clean up")
            return

        # Regular sync for open PRs
        result = pr.sync(
            target_sha,
            dry_run_github=dry_run_github,
            dry_run_aws=dry_run_aws,
            dry_run_docker=dry_run_docker,
        )

        if result.success:
            p(f"🎪 ✅ Sync completed: {result.action_taken}")
        else:
            p(f"🎪 ❌ Sync failed: {result.error}")
            raise typer.Exit(1)

    except GitHubError as e:
        p(f"❌ GitHub error: {e}")
        raise typer.Exit(1) from e
    except Exception as e:
        p(f"❌ Error: {e}")
        raise typer.Exit(1) from e


@app.command()
def handle_sync(pr_number: int) -> None:
    """🎪 Handle new commit sync (called by GitHub Actions on PR synchronize)"""
    try:
        pr = PullRequest.from_id(pr_number)

        # Only sync if there's an active environment
        if not pr.current_show:
            p(f"🎪 No active environment for PR #{pr_number} - skipping sync")
            return

        # Get latest commit SHA
        from .core.pull_request import get_github

        latest_sha = get_github().get_latest_commit_sha(pr_number)

        # Check if update is needed
        if not pr.current_show.needs_update(latest_sha):
            p(f"🎪 Environment already up to date for PR #{pr_number}")
            return

        p(f"🎪 Syncing PR #{pr_number} to commit {latest_sha[:7]}")

        # TODO: Implement rolling update logic
        p("🎪 [bold yellow]Sync logic not yet implemented[/bold yellow]")

    except Exception as e:
        p(f"🎪 [bold red]Error handling sync:[/bold red] {e}")


@app.command()
def setup_labels(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what labels would be created"),
) -> None:
    """🎪 Set up GitHub label definitions with colors and descriptions"""
    try:
        from .core.label_colors import LABEL_DEFINITIONS

        github = GitHubInterface()

        p("🎪 [bold blue]Setting up circus tent label definitions...[/bold blue]")

        created_count = 0
        updated_count = 0

        for label_name, definition in LABEL_DEFINITIONS.items():
            color = definition["color"]
            description = definition["description"]

            if dry_run:
                p(f"🏷️ Would create: [bold]{label_name}[/bold]")
                p(f"   Color: #{color}")
                p(f"   Description: {description}")
            else:
                try:
                    # Try to create or update the label
                    success = github.create_or_update_label(label_name, color, description)
                    if success:
                        created_count += 1
                        p(f"✅ Created: [bold]{label_name}[/bold]")
                    else:
                        updated_count += 1
                        p(f"🔄 Updated: [bold]{label_name}[/bold]")
                except Exception as e:
                    p(f"❌ Failed to create {label_name}: {e}")

        if not dry_run:
            p("\n🎪 [bold green]Label setup complete![/bold green]")
            p(f"   📊 Created: {created_count}")
            p(f"   🔄 Updated: {updated_count}")
            p(
                "\n🎪 [dim]Note: Dynamic labels (with SHA) are created automatically during deployment[/dim]"
            )

    except Exception as e:
        p(f"🎪 [bold red]Error setting up labels:[/bold red] {e}")


@app.command()
def aws_cleanup(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be cleaned"),
    force: bool = typer.Option(False, "--force", help="Delete all showtime AWS resources"),
) -> None:
    """🧹 Clean up orphaned AWS resources without GitHub labels"""
    try:
        from .core.aws import AWSInterface

        aws = AWSInterface()

        p("🔍 [bold blue]Scanning for orphaned AWS resources...[/bold blue]")

        # 1. Get all GitHub PRs with circus labels
        github_services = set()
        try:
            all_pr_numbers = PullRequest.find_all_with_environments()
            p(f"📋 Found {len(all_pr_numbers)} PRs with circus labels:")

            for pr_number in all_pr_numbers:
                pr = PullRequest.from_id(pr_number)
                p(
                    f"  🎪 PR #{pr_number}: {len(pr.shows)} shows, {len(pr.circus_labels)} circus labels"
                )

                for show in pr.shows:
                    service_name = show.ecs_service_name
                    github_services.add(service_name)
                    p(f"    📝 Expected service: {service_name}")

                # Show labels for debugging
                if not pr.shows:
                    p(f"    ⚠️ No shows found, labels: {pr.circus_labels[:3]}...")  # First 3 labels

        except Exception as e:
            p(f"⚠️ GitHub scan failed: {e}")
            github_services = set()

        # 2. Get all AWS ECS services matching showtime pattern
        p("\n☁️ [bold blue]Scanning AWS ECS services...[/bold blue]")
        try:
            aws_services = aws.find_showtime_services()
            p(f"🔍 Found {len(aws_services)} AWS services with pr-* pattern")

            for service in aws_services:
                p(f"  ☁️ AWS: {service}")
        except Exception as e:
            p(f"❌ AWS scan failed: {e}")
            return

        # 3. Find orphaned services
        orphaned = [service for service in aws_services if service not in github_services]

        if not orphaned:
            p("\n✅ [bold green]No orphaned AWS resources found![/bold green]")
            return

        p(f"\n🚨 [bold red]Found {len(orphaned)} orphaned AWS resources:[/bold red]")
        for service in orphaned:
            p(f"  💰 {service} (consuming resources)")

        if dry_run:
            p(f"\n🎪 [bold yellow]DRY RUN[/bold yellow] - Would delete {len(orphaned)} services")
            return

        if not force:
            confirm = typer.confirm(f"Delete {len(orphaned)} orphaned AWS services?")
            if not confirm:
                p("🎪 Cancelled")
                return

        # 4. Delete orphaned resources
        deleted_count = 0
        for service in orphaned:
            p(f"🗑️ Deleting {service}...")
            try:
                # Extract PR number for delete_environment call
                pr_match = service.replace("pr-", "").replace("-service", "")
                parts = pr_match.split("-")
                if len(parts) >= 2:
                    pr_number = int(parts[0])
                    success = aws.delete_environment(service, pr_number)
                    if success:
                        p(f"✅ Deleted {service}")
                        deleted_count += 1
                    else:
                        p(f"❌ Failed to delete {service}")
                else:
                    p(f"❌ Invalid service name format: {service}")
            except Exception as e:
                p(f"❌ Error deleting {service}: {e}")

        p(f"\n🎪 ✅ Cleanup complete: deleted {deleted_count}/{len(orphaned)} services")

    except Exception as e:
        p(f"❌ AWS cleanup failed: {e}")


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
) -> None:
    """🎪 Clean up orphaned or expired environments and labels"""
    try:
        # Parse older_than to hours
        import re

        time_match = re.match(r"(\d+)([hd])", older_than)
        if not time_match:
            p(f"❌ Invalid time format: {older_than}")
            return

        max_age_hours = int(time_match.group(1))
        if time_match.group(2) == "d":
            max_age_hours *= 24

        p(f"🎪 [bold blue]Cleaning environments older than {max_age_hours}h...[/bold blue]")

        # Get all PRs with environments
        pr_numbers = PullRequest.find_all_with_environments()
        if not pr_numbers:
            p("🎪 No environments found to clean")
            return

        cleaned_count = 0
        for pr_number in pr_numbers:
            pr = PullRequest.from_id(pr_number)
            if pr.stop_if_expired(max_age_hours, dry_run):
                cleaned_count += 1

        if cleaned_count > 0:
            p(f"🎪 ✅ Cleaned up {cleaned_count} expired environments")
        else:
            p("🎪 No expired environments found")

    except Exception as e:
        p(f"❌ Cleanup failed: {e}")


@app.command()
def git_check() -> None:
    """🔍 Test Git SHA validation locally"""
    from rich import print as p

    from .core.git_validation import REQUIRED_SHA, validate_required_sha

    p("🔍 [bold blue]Testing Git SHA Validation[/bold blue]")
    p(f"Required SHA: [cyan]{REQUIRED_SHA}[/cyan]")

    try:
        is_valid, error_msg = validate_required_sha()

        if is_valid:
            p(
                "✅ [bold green]Validation PASSED[/bold green] - Required commit found in Git history"
            )
        else:
            p("❌ [bold red]Validation FAILED[/bold red]")
            p(f"Error: {error_msg}")

    except Exception as e:
        p(f"❌ [bold red]Validation ERROR[/bold red]: {e}")


def main() -> None:
    """Main entry point for the CLI"""
    app()


if __name__ == "__main__":
    main()
