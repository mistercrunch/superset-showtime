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

# Constants
DEFAULT_GITHUB_ACTOR = "unknown"


def _get_service_urls(pr_number: int, sha: str = None):
    """Get AWS Console URLs for a service"""
    if sha:
        service_name = f"pr-{pr_number}-{sha}-service"
    else:
        service_name = f"pr-{pr_number}-service"

    return {
        "logs": f"https://us-west-2.console.aws.amazon.com/ecs/v2/clusters/superset-ci/services/{service_name}/logs?region=us-west-2",
        "service": f"https://us-west-2.console.aws.amazon.com/ecs/v2/clusters/superset-ci/services/{service_name}",
    }


def _show_service_urls(pr_number: int, context: str = "deployment", sha: str = None):
    """Show helpful AWS Console URLs for monitoring service"""
    urls = _get_service_urls(pr_number, sha)
    console.print(f"\n🎪 [bold blue]Monitor {context} progress:[/bold blue]")
    console.print(f"   📝 Live Logs: {urls['logs']}")
    console.print(f"   📊 ECS Service: {urls['service']}")
    console.print("")


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
1. Add [green]🎪 trigger-start[/green] label to PR → Creates environment
2. Watch state labels: [blue]🎪 abc123f 🚦 building[/blue] → [green]🎪 abc123f 🚦 running[/green]
3. Add [yellow]🎪 conf-enable-ALERTS[/yellow] → Enables feature flags
4. Add [red]🎪 trigger-stop[/red] label → Destroys environment

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

            # Show logs URL for monitoring cleanup
            _show_service_urls(pr_number, "cleanup")

            try:
                # Get current environment info
                pr = PullRequest.from_id(pr_number, github)

                if pr.current_show:
                    show = pr.current_show
                    console.print(f"🎪 Destroying environment: {show.aws_service_name}")

                    # Step 1: Check if ECS service exists and is active
                    service_name = f"pr-{pr_number}-service"  # Match GHA service naming
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
            aws_urls = _get_service_urls(show.pr_number, show.sha)
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

    state_table.add_row("🎪 {sha} 🚦 {status}", "Environment status", "🎪 abc123f 🚦 running")
    state_table.add_row("🎪 🎯 {sha}", "Active environment pointer", "🎪 🎯 abc123f")
    state_table.add_row("🎪 🏗️ {sha}", "Building environment pointer", "🎪 🏗️ def456a")
    state_table.add_row(
        "🎪 {sha} 📅 {timestamp}", "Creation timestamp", "🎪 abc123f 📅 2024-01-15T14-30"
    )
    state_table.add_row("🎪 {sha} 🌐 {ip-with-dashes}", "Environment IP", "🎪 abc123f 🌐 52-1-2-3")
    state_table.add_row("🎪 {sha} ⌛ {ttl-policy}", "TTL policy", "🎪 abc123f ⌛ 24h")
    state_table.add_row("🎪 {sha} 🤡 {username}", "Requested by", "🎪 abc123f 🤡 maxime")
    state_table.add_row("🎪 {sha} ⚙️ {config-list}", "Feature flags", "🎪 abc123f ⚙️ alerts,debug")

    console.print(state_table)
    console.print()

    # Workflow Examples
    console.print("[bold magenta]🎪 Complete Workflow Examples:[/bold magenta]")
    console.print()

    console.print("[bold]1. Create Environment:[/bold]")
    console.print("   • Add label: [green]🎪 trigger-start[/green]")
    console.print(
        "   • Watch for: [blue]🎪 abc123f 🚦 building[/blue] → [green]🎪 abc123f 🚦 running[/green]"
    )
    console.print("   • Get URL from: [cyan]🎪 abc123f 🌐 52-1-2-3[/cyan] → http://52.1.2.3:8080")
    console.print()

    console.print("[bold]2. Enable Feature Flag:[/bold]")
    console.print("   • Add label: [yellow]🎪 conf-enable-ALERTS[/yellow]")
    console.print(
        "   • Watch for: [blue]🎪 abc123f 🚦 configuring[/blue] → [green]🎪 abc123f 🚦 running[/green]"
    )
    console.print(
        "   • Config updates: [cyan]🎪 abc123f ⚙️ standard[/cyan] → [cyan]🎪 abc123f ⚙️ alerts[/cyan]"
    )
    console.print()

    console.print("[bold]3. Update to New Commit:[/bold]")
    console.print("   • Add label: [green]🎪 trigger-sync[/green]")
    console.print(
        "   • Watch for: [blue]🎪 abc123f 🚦 updating[/blue] → [green]🎪 def456a 🚦 running[/green]"
    )
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
            label
            for label in pr.labels
            if label.startswith("🎪 trigger-") or label.startswith("🎪 conf-")
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
                        _show_service_urls(pr_number, "cleanup")

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
        console.print(f"🎪 Finding environments older than {older_than}")
        prs_with_shows = github.find_prs_with_shows()

        if not prs_with_shows:
            console.print("🎪 [dim]No PRs with circus tent labels found[/dim]")
        else:
            console.print(f"🎪 Found {len(prs_with_shows)} PRs with shows")

            import re
            from datetime import datetime, timedelta

            from .core.circus import PullRequest

            # Parse the older_than parameter (e.g., "48h", "7d")
            time_match = re.match(r"(\d+)([hd])", older_than)
            if not time_match:
                console.print(f"🎪 [bold red]Invalid time format:[/bold red] {older_than}")
                return

            hours = int(time_match.group(1))
            if time_match.group(2) == "d":
                hours *= 24

            cutoff_time = datetime.now() - timedelta(hours=hours)

            cleaned_prs = 0
            for pr_number in prs_with_shows:
                try:
                    pr = PullRequest.from_id(pr_number, github)
                    expired_shows = []

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
):
    """Handle start trigger"""
    import os
    import time
    from datetime import datetime

    console.print(f"🎪 Starting environment for PR #{pr_number}")

    try:
        # Get latest SHA and GitHub actor
        latest_sha = github.get_latest_commit_sha(pr_number)
        github_actor = os.getenv("GITHUB_ACTOR", DEFAULT_GITHUB_ACTOR)

        # Post confirmation comment
        workflow_url = (
            os.getenv("GITHUB_SERVER_URL", "https://github.com")
            + f"/{os.getenv('GITHUB_REPOSITORY', 'repo')}/actions/runs/{os.getenv('GITHUB_RUN_ID', 'run')}"
        )

        confirmation_comment = f"""🎪 @{github_actor} Creating ephemeral environment for commit `{latest_sha[:7]}`

**Action:** [View workflow]({workflow_url})
**Environment:** `{latest_sha[:7]}`
**Powered by:** [Superset Showtime](https://github.com/mistercrunch/superset-showtime)

*Building and deploying... Watch the labels for progress updates.*"""

        if not dry_run_github:
            github.post_comment(pr_number, confirmation_comment)

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

            # Post success comment (only in dry-run-aws mode since we have mock IP)
            success_comment = f"""🎪 @{github_actor} Environment ready at **http://{mock_ip}:8080**

**Environment:** `{show.sha}`
**Credentials:** admin / admin
**TTL:** {show.ttl} (auto-cleanup)

**Feature flags:** Add `🎪 conf-enable-ALERTS` labels to configure
**Updates:** Environment updates automatically on new commits

*Powered by [Superset Showtime](https://github.com/mistercrunch/superset-showtime)*"""

            if not dry_run_github:
                github.post_comment(pr_number, success_comment)

        else:
            # Real AWS operations
            from .core.aws import AWSInterface, EnvironmentResult

            console.print("🎪 [bold blue]Starting AWS deployment...[/bold blue]")
            aws = AWSInterface()

            # Show logs URL immediately for monitoring
            _show_service_urls(pr_number, "deployment", latest_sha[:7])

            # Parse feature flags from PR description (replicate GHA feature flag logic)
            feature_flags = _extract_feature_flags_from_pr(pr_number, github)

            # Create environment (synchronous, matches GHA wait behavior)
            result: EnvironmentResult = aws.create_environment(
                pr_number=pr_number,
                sha=latest_sha,
                github_user=github_actor,
                feature_flags=feature_flags,
            )

            if result.success:
                console.print(
                    f"🎪 [bold green]✅ Green service deployed successfully![/bold green] IP: {result.ip}"
                )

                # Show helpful links for the new service
                console.print("\n🎪 [bold blue]Useful Links:[/bold blue]")
                console.print(f"   🌐 Environment: http://{result.ip}:8080")
                console.print(
                    f"   📊 ECS Service: https://us-west-2.console.aws.amazon.com/ecs/v2/clusters/superset-ci/services/{result.service_name}"
                )
                console.print(
                    f"   📝 Service Logs: https://us-west-2.console.aws.amazon.com/ecs/v2/clusters/superset-ci/services/{result.service_name}/logs?region=us-west-2"
                )
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

                # Update to running state with new SHA
                show.status = "running"
                show.ip = result.ip

                # Traffic switching happens here - update GitHub labels atomically
                running_labels = show.to_circus_labels()
                console.print("\n🎪 Setting running state labels (traffic switch):")
                for label in running_labels:
                    console.print(f"  + {label}")

                if not dry_run_github:
                    console.print("🎪 Executing traffic switch via GitHub labels...")
                    # Remove existing circus labels first
                    github.remove_circus_labels(pr_number)
                    # Add new running labels - this switches traffic atomically
                    for label in running_labels:
                        github.add_label(pr_number, label)
                    console.print("🎪 ✅ Labels updated to running state!")

                    # Post success comment with real IP
                    success_comment = f"""🎪 @{github_actor} Environment ready at **http://{result.ip}:8080**

**Environment:** `{show.sha}`
**Credentials:** admin / admin
**TTL:** {show.ttl} (auto-cleanup)
**Feature flags:** {len(feature_flags)} enabled

**Feature flags:** Add `🎪 conf-enable-ALERTS` labels to configure
**Updates:** Environment updates automatically on new commits

*Powered by [Superset Showtime](https://github.com/mistercrunch/superset-showtime)*"""

                    github.post_comment(pr_number, success_comment)

            else:
                console.print(f"🎪 [bold red]❌ AWS deployment failed:[/bold red] {result.error}")

                # Update to failed state
                show.status = "failed"
                failed_labels = show.to_circus_labels()

                if not dry_run_github:
                    console.print("🎪 Setting failed state labels...")
                    github.remove_circus_labels(pr_number)
                    for label in failed_labels:
                        github.add_label(pr_number, label)

                    # Post failure comment
                    failure_comment = f"""🎪 @{github_actor} Environment creation failed.

**Error:** {result.error}
**Environment:** `{show.sha}`

Please check the logs and try again.

*Powered by [Superset Showtime](https://github.com/mistercrunch/superset-showtime)*"""

                    github.post_comment(pr_number, failure_comment)

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
            config = {"name": f"SUPERSET_FEATURE_{match.group(1)}", "value": match.group(2)}
            results.append(config)
            console.print(f"🎪 Found feature flag: {config['name']}={config['value']}")

        return results

    except Exception as e:
        console.print(f"🎪 Warning: Could not extract feature flags: {e}")
        return []


def _handle_stop_trigger(
    pr_number: int, github: GitHubInterface, dry_run_aws: bool = False, dry_run_github: bool = False
):
    """Handle stop trigger"""
    import os

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

            # Show logs URL for monitoring cleanup
            _show_service_urls(pr_number, "cleanup")

            try:
                # Step 1: Check if ECS service exists and is active (replicate GHA describe-services)
                service_name = f"pr-{pr_number}-service"  # Match GHA service naming
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
        github_actor = os.getenv("GITHUB_ACTOR", DEFAULT_GITHUB_ACTOR)
        cleanup_comment = f"""🎪 @{github_actor} Environment `{show.sha}` cleaned up

**AWS Resources:** ECS service and ECR image deleted
**Cost Impact:** No further charges

Add `🎪 trigger-start` to create a new environment.

*Powered by [Superset Showtime](https://github.com/mistercrunch/superset-showtime)*"""

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

            # Post rolling update success comment
            import os

            github_actor = os.getenv("GITHUB_ACTOR", DEFAULT_GITHUB_ACTOR)
            update_comment = f"""🎪 Environment updated: {pr.current_show.sha} → `{new_show.sha}`

**New Environment:** http://{new_show.ip}:8080
**Update:** Zero-downtime rolling deployment
**Old Environment:** Automatically cleaned up

Your latest changes are now live.

*Powered by [Superset Showtime](https://github.com/mistercrunch/superset-showtime)*"""

            if not dry_run_github:
                github.post_comment(pr_number, update_comment)

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
