"""
🎪 Superset Showtime CLI

Main command-line interface for Apache Superset circus tent environment management.
"""

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .core.circus import PullRequest, Show
from .core.emojis import STATUS_DISPLAY
from .core.github import GitHubError, GitHubInterface

app = typer.Typer(
    name="showtime",
    help="""🎪 Apache Superset ephemeral environment management

[bold]GitHub Label Workflow:[/bold]
1. Add [green]🎪 trigger-start[/green] label to PR → Creates environment
2. Watch state labels: [blue]🎪 🚦 building[/blue] → [green]🎪 🚦 running[/green]
3. Add [yellow]🎪 conf-enable-ALERTS[/yellow] → Enables feature flags
4. Add [red]🎪 trigger-stop[/red] label → Destroys environment

[bold]Reading State Labels:[/bold]
• [green]🎪 🚦 running[/green] - Environment status
• [blue]🎪 🎯 abc123f[/blue] - Active environment SHA
• [cyan]🎪 🌐 52-1-2-3[/cyan] - Environment IP (http://52.1.2.3:8080)
• [yellow]🎪 ⌛ 24h[/yellow] - TTL policy
• [magenta]🎪 🤡 maxime[/magenta] - Who requested (clown!)

[dim]CLI commands work with existing environments or dry-run new ones.[/dim]""",
    rich_markup_mode="rich",
)
console = Console()


@app.command()
def start(
    pr_number: int = typer.Argument(..., help="PR number to create environment for"),
    sha: Optional[str] = typer.Option(None, help="Specific commit SHA (default: latest)"),
    ttl: Optional[str] = typer.Option("24h", help="Time to live (24h, 48h, 1w, close)"),
    size: Optional[str] = typer.Option("standard", help="Environment size (standard, large)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done"),
    dry_run_aws: bool = typer.Option(
        False, "--dry-run-aws", help="Skip AWS operations, use mock data"
    ),
    aws_sleep: int = typer.Option(0, "--aws-sleep", help="Seconds to sleep during AWS operations"),
):
    """Create ephemeral environment for PR"""
    try:
        github = GitHubInterface()

        # Get latest SHA if not provided
        if not sha:
            sha = github.get_latest_commit_sha(pr_number)

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
        _handle_start_trigger(pr_number, github, dry_run_aws, (dry_run or False), aws_sleep)

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

        if show.config != "standard":
            table.add_row("Configuration", show.config)

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
        else:
            # TODO: Implement real AWS cleanup
            console.print("🎪 [bold yellow]Real AWS cleanup not yet implemented[/bold yellow]")

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

        # Create table
        table = Table(title="🎪 Environment List")
        table.add_column("PR", style="cyan")
        table.add_column("Status", style="white")
        table.add_column("Environment", style="green")
        table.add_column("URL", style="blue")
        table.add_column("TTL", style="yellow")
        table.add_column("User", style="magenta")

        status_emoji = STATUS_DISPLAY

        for show in sorted(all_shows, key=lambda s: s.pr_number):
            url = f"http://{show.ip}:8080" if show.ip else "-"

            table.add_row(
                str(show.pr_number),
                f"{status_emoji.get(show.status, '❓')} {show.status}",
                show.sha,
                url,
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

    console.print("🎪 [bold blue]Circus Tent Label Reference[/bold blue]")
    console.print()

    # Trigger Labels
    console.print("[bold yellow]🎯 Trigger Labels (Add these to GitHub PR):[/bold yellow]")
    trigger_table = Table()
    trigger_table.add_column("Label", style="green")
    trigger_table.add_column("Action", style="white")
    trigger_table.add_column("Description", style="dim")

    trigger_table.add_row(
        "🎪 trigger-start", "Create environment", "Builds and deploys ephemeral environment"
    )
    trigger_table.add_row(
        "🎪 trigger-stop", "Destroy environment", "Cleans up AWS resources and removes labels"
    )
    trigger_table.add_row(
        "🎪 trigger-sync", "Update environment", "Updates to latest commit with zero downtime"
    )
    trigger_table.add_row(
        "🎪 conf-enable-ALERTS", "Enable feature flag", "Enables SUPERSET_FEATURE_ALERTS=True"
    )
    trigger_table.add_row(
        "🎪 conf-disable-DASHBOARD_RBAC",
        "Disable feature flag",
        "Disables SUPERSET_FEATURE_DASHBOARD_RBAC=False",
    )

    console.print(trigger_table)
    console.print()

    # State Labels
    console.print("[bold cyan]📊 State Labels (Automatically managed):[/bold cyan]")
    state_table = Table()
    state_table.add_column("Label", style="cyan")
    state_table.add_column("Meaning", style="white")
    state_table.add_column("Example", style="dim")

    state_table.add_row("🎪 🚦 {status}", "Environment status", "🎪 🚦 running")
    state_table.add_row("🎪 🎯 {sha}", "Active environment SHA", "🎪 🎯 abc123f")
    state_table.add_row("🎪 🏗️ {sha}", "Building environment SHA", "🎪 🏗️ def456a")
    state_table.add_row("🎪 📅 {timestamp}", "Creation timestamp", "🎪 📅 2024-01-15T14-30")
    state_table.add_row("🎪 🌐 {ip-with-dashes}", "Environment IP", "🎪 🌐 52-1-2-3")
    state_table.add_row("🎪 ⌛ {ttl-policy}", "TTL policy", "🎪 ⌛ 24h")
    state_table.add_row("🎪 🤡 {username}", "Requested by", "🎪 🤡 maxime")
    state_table.add_row("🎪 ⚙️ {config-list}", "Feature flags", "🎪 ⚙️ alerts,debug")

    console.print(state_table)
    console.print()

    # Workflow Examples
    console.print("[bold magenta]🎪 Complete Workflow Examples:[/bold magenta]")
    console.print()

    console.print("[bold]1. Create Environment:[/bold]")
    console.print("   • Add label: [green]🎪 trigger-start[/green]")
    console.print("   • Watch for: [blue]🎪 🚦 building[/blue] → [green]🎪 🚦 running[/green]")
    console.print("   • Get URL from: [cyan]🎪 🌐 52-1-2-3[/cyan] → http://52.1.2.3:8080")
    console.print()

    console.print("[bold]2. Enable Feature Flag:[/bold]")
    console.print("   • Add label: [yellow]🎪 conf-enable-ALERTS[/yellow]")
    console.print("   • Watch for: [blue]🎪 🚦 configuring[/blue] → [green]🎪 🚦 running[/green]")
    console.print("   • Config updates: [cyan]🎪 ⚙️ standard[/cyan] → [cyan]🎪 ⚙️ alerts[/cyan]")
    console.print()

    console.print("[bold]3. Update to New Commit:[/bold]")
    console.print("   • Add label: [green]🎪 trigger-sync[/green]")
    console.print("   • Watch for: [blue]🎪 🚦 updating[/blue] → [green]🎪 🚦 running[/green]")
    console.print("   • SHA changes: [cyan]🎪 🎯 abc123f[/cyan] → [cyan]🎪 🎯 def456a[/cyan]")
    console.print()

    console.print("[bold]4. Clean Up:[/bold]")
    console.print("   • Add label: [red]🎪 trigger-stop[/red]")
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
        _handle_start_trigger(pr_number, github, dry_run_aws, dry_run_github, aws_sleep)

        console.print()
        console.print("🎪 [bold]Step 2: Simulate conf-enable-ALERTS[/bold]")
        _handle_config_trigger(
            pr_number, "🎪 conf-enable-ALERTS", github, dry_run_aws, dry_run_github
        )

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
def handle_trigger(
    pr_number: int,
    dry_run_aws: bool = typer.Option(
        False, "--dry-run-aws", help="Skip AWS operations, use mock data"
    ),
    dry_run_github: bool = typer.Option(
        False, "--dry-run-github", help="Skip GitHub label operations"
    ),
    aws_sleep: int = typer.Option(
        0, "--aws-sleep", help="Seconds to sleep during AWS operations (for testing)"
    ),
):
    """🎪 Process trigger labels (called by GitHub Actions)"""
    try:
        github = GitHubInterface()
        pr = PullRequest.from_id(pr_number, github)

        # Find trigger labels
        trigger_labels = [
            l for l in pr.labels if l.startswith("🎪 trigger-") or l.startswith("🎪 conf-")
        ]

        if not trigger_labels:
            console.print(f"🎪 No trigger labels found for PR #{pr_number}")
            return

        console.print(f"🎪 Processing {len(trigger_labels)} trigger(s) for PR #{pr_number}")

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
            if trigger == "🎪 trigger-start":
                _handle_start_trigger(pr_number, github, dry_run_aws, dry_run_github, aws_sleep)
            elif trigger == "🎪 trigger-stop":
                _handle_stop_trigger(pr_number, github, dry_run_aws, dry_run_github)
            elif trigger == "🎪 trigger-sync":
                _handle_sync_trigger(pr_number, github, dry_run_aws, dry_run_github, aws_sleep)
            elif trigger.startswith("🎪 conf-"):
                _handle_config_trigger(pr_number, trigger, github, dry_run_aws, dry_run_github)

        console.print("🎪 All triggers processed!")

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
def cleanup(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be cleaned"),
    older_than: str = typer.Option(
        "48h", "--older-than", help="Clean environments older than this"
    ),
):
    """🎪 Clean up orphaned or expired environments"""
    try:
        github = GitHubInterface()

        if dry_run:
            console.print(
                f"🎪 [bold yellow]DRY RUN[/bold yellow] - Would clean environments older than {older_than}"
            )
            # TODO: Implement dry-run orphan detection
            console.print("🎪 Orphan detection not yet implemented")
            return

        console.print(f"🎪 Cleaning up environments older than {older_than}")
        # TODO: Implement actual cleanup
        console.print("🎪 [bold yellow]Cleanup logic not yet implemented[/bold yellow]")

    except Exception as e:
        console.print(f"🎪 [bold red]Error during cleanup:[/bold red] {e}")


# Helper functions for trigger processing
def _handle_start_trigger(
    pr_number: int,
    github: GitHubInterface,
    dry_run_aws: bool = False,
    dry_run_github: bool = False,
    aws_sleep: int = 0,
):
    """Handle start trigger"""
    import os
    import time
    from datetime import datetime

    console.print(f"🎪 Starting environment for PR #{pr_number}")

    try:
        # Get latest SHA and GitHub actor
        latest_sha = github.get_latest_commit_sha(pr_number)
        # TODO: Get actual GitHub actor from GHA context
        github_actor = os.getenv("GITHUB_ACTOR", "")  # Empty if unknown

        # Create new show
        show = Show(
            pr_number=pr_number,
            sha=latest_sha[:7],
            status="building",
            created_at=datetime.utcnow().strftime("%Y-%m-%dT%H-%M"),
            ttl="24h",
            requested_by=github_actor,
            config="standard",
        )

        console.print(f"🎪 Creating environment {show.aws_service_name}")

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

        else:
            # TODO: Real AWS operations
            console.print("🎪 [bold yellow]Real AWS logic not yet implemented[/bold yellow]")

    except Exception as e:
        console.print(f"🎪 [bold red]Start trigger failed:[/bold red] {e}")


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
            # TODO: Real AWS cleanup
            console.print("🎪 [bold yellow]Real AWS cleanup not yet implemented[/bold yellow]")

        # Remove all circus labels for this PR
        console.print(f"🎪 Removing all circus labels for PR #{pr_number}")
        # TODO: Actually remove labels
        # github.remove_circus_labels(pr_number)

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
            config=pr.current_show.config,
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

        else:
            # TODO: Real rolling update
            console.print("🎪 [bold yellow]Real rolling update not yet implemented[/bold yellow]")

    except Exception as e:
        console.print(f"🎪 [bold red]Sync trigger failed:[/bold red] {e}")


def _handle_config_trigger(
    pr_number: int,
    trigger: str,
    github: GitHubInterface,
    dry_run_aws: bool = False,
    dry_run_github: bool = False,
):
    """Handle configuration trigger"""
    from .core.circus import merge_config, parse_configuration_command

    console.print(f"🎪 Configuring environment for PR #{pr_number}: {trigger}")

    try:
        command = parse_configuration_command(trigger)
        if not command:
            console.print(f"🎪 [bold red]Invalid config trigger:[/bold red] {trigger}")
            return

        pr = PullRequest.from_id(pr_number, github)

        if not pr.current_show:
            console.print(f"🎪 No active environment for PR #{pr_number}")
            return

        show = pr.current_show
        console.print(f"🎪 Applying config: {command} to {show.aws_service_name}")

        # Update configuration
        new_config = merge_config(show.config, command)
        console.print(f"🎪 Config: {show.config} → {new_config}")

        if dry_run_aws:
            console.print("🎪 [bold yellow]DRY-RUN-AWS[/bold yellow] - Would update feature flags")
            console.print(f"  Command: {command}")
            console.print(f"  New config: {new_config}")
        else:
            # TODO: Real feature flag update
            console.print(
                "🎪 [bold yellow]Real feature flag update not yet implemented[/bold yellow]"
            )

        # Update config in labels
        show.config = new_config
        updated_labels = show.to_circus_labels()
        console.print("🎪 Updating config labels")

        # TODO: Actually update labels
        # github.set_labels(pr_number, updated_labels)

        console.print("🎪 [bold green]Configuration updated![/bold green]")

    except Exception as e:
        console.print(f"🎪 [bold red]Config trigger failed:[/bold red] {e}")


def main():
    """Main entry point for the CLI"""
    app()


if __name__ == "__main__":
    main()
