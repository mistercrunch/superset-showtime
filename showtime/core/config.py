"""
🎪 Showtime configuration management

Handles configuration for GitHub API, AWS credentials, and showtime settings.
"""

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import yaml
from rich.console import Console
from rich.prompt import Prompt

console = Console()


@dataclass
class ShowtimeConfig:
    """Showtime configuration settings"""

    # GitHub settings
    github_token: str
    github_org: str
    github_repo: str

    # AWS settings
    aws_profile: str = "default"
    aws_region: str = "us-west-2"

    # Circus settings
    default_ttl: str = "24h"
    default_size: str = "standard"

    # ECS settings
    ecs_cluster: str = "superset-ci"
    ecs_task_family: str = "superset-ci"
    ecr_repository: str = "superset-ci"

    @property
    def config_path(self) -> Path:
        """Path to configuration file"""
        config_dir = Path.home() / ".showtime"
        config_dir.mkdir(exist_ok=True)
        return config_dir / "config.yml"

    @classmethod
    def get_config_path(cls) -> Path:
        """Get path to configuration file"""
        config_dir = Path.home() / ".showtime"
        config_dir.mkdir(exist_ok=True)
        return config_dir / "config.yml"

    @classmethod
    def load(cls) -> "ShowtimeConfig":
        """Load configuration from file"""
        config_path = cls.get_config_path()

        if not config_path.exists():
            raise FileNotFoundError(
                f"Configuration file not found at {config_path}. "
                f"Run 'showtime init' to create it."
            )

        with open(config_path) as f:
            data = yaml.safe_load(f)

        return cls(**data)

    def save(self) -> None:
        """Save configuration to file"""
        with open(self.config_path, "w") as f:
            yaml.safe_dump(asdict(self), f, default_flow_style=False)

    @classmethod
    def create_interactive(
        cls,
        github_token: Optional[str] = None,
        aws_profile: Optional[str] = None,
        region: Optional[str] = None,
    ) -> "ShowtimeConfig":
        """Create configuration interactively"""

        console.print("🎪 [bold blue]Welcome to Showtime! Let's set up your circus...[/bold blue]")
        console.print()

        # GitHub configuration
        if not github_token:
            github_token = Prompt.ask(
                "GitHub personal access token", default=os.getenv("GITHUB_TOKEN", ""), password=True
            )

        github_org = Prompt.ask("GitHub organization", default="apache")

        github_repo = Prompt.ask("GitHub repository", default="superset")

        # AWS configuration
        if not aws_profile:
            aws_profile = Prompt.ask("AWS profile", default="default")

        if not region:
            region = Prompt.ask("AWS region", default="us-west-2")

        # Circus settings
        default_ttl = Prompt.ask(
            "Default environment TTL",
            default="24h",
            choices=["24h", "48h", "1w", "close", "manual"],
        )

        default_size = Prompt.ask(
            "Default environment size", default="standard", choices=["standard", "large"]
        )

        # ECS settings (with smart defaults)
        ecs_cluster = Prompt.ask("ECS cluster name", default="superset-ci")

        console.print()
        console.print("🎪 [bold green]Configuration complete![/bold green]")

        return cls(
            github_token=github_token,
            github_org=github_org,
            github_repo=github_repo,
            aws_profile=aws_profile,
            aws_region=region,
            default_ttl=default_ttl,
            default_size=default_size,
            ecs_cluster=ecs_cluster,
        )

    def validate(self) -> bool:
        """Validate configuration settings"""
        errors = []

        if not self.github_token:
            errors.append("GitHub token is required")

        if not self.github_org:
            errors.append("GitHub organization is required")

        if not self.github_repo:
            errors.append("GitHub repository is required")

        if errors:
            console.print("🎪 [bold red]Configuration errors:[/bold red]")
            for error in errors:
                console.print(f"  • {error}")
            return False

        return True
