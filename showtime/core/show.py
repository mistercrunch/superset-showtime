"""
🎪 Show class - Individual ephemeral environment management

Single environment operations: Docker build, AWS deployment, state transitions.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


# Import interfaces for singleton access
# Note: These will be imported when the module loads, creating singletons
def get_interfaces():  # type: ignore
    """Lazy-load interfaces to avoid circular imports"""
    from .aws import AWSInterface
    from .github import GitHubInterface

    return GitHubInterface(), AWSInterface()


@dataclass
class Show:
    """Single ephemeral environment state from circus labels"""

    pr_number: int
    sha: str  # 7-char commit SHA
    status: str  # building, built, deploying, running, updating, failed
    ip: Optional[str] = None  # Environment IP address
    created_at: Optional[str] = None  # ISO timestamp
    ttl: str = "24h"  # 24h, 48h, close, etc.
    requested_by: Optional[str] = None  # GitHub username

    @property
    def aws_service_name(self) -> str:
        """Deterministic ECS service name: pr-{pr_number}-{sha}"""
        return f"pr-{self.pr_number}-{self.sha}"

    @property
    def ecs_service_name(self) -> str:
        """ECS service name with -service suffix"""
        return f"{self.aws_service_name}-service"

    @property
    def aws_image_tag(self) -> str:
        """Deterministic Docker image tag: pr-{pr_number}-{sha}-ci"""
        return f"pr-{self.pr_number}-{self.sha}-ci"

    @property
    def short_sha(self) -> str:
        """Return the short SHA (already short)"""
        return self.sha

    @property
    def is_running(self) -> bool:
        """Check if environment is currently running"""
        return self.status == "running"

    @property
    def is_building(self) -> bool:
        """Check if environment is currently building"""
        return self.status == "building"

    @property
    def is_built(self) -> bool:
        """Check if environment is built (Docker complete, ready for deploy)"""
        return self.status == "built"

    @property
    def is_deploying(self) -> bool:
        """Check if environment is currently deploying to AWS"""
        return self.status == "deploying"

    @property
    def is_updating(self) -> bool:
        """Check if environment is currently updating"""
        return self.status == "updating"

    def needs_update(self, latest_sha: str) -> bool:
        """Check if environment needs update to latest SHA"""
        return self.sha != latest_sha[:7]

    def is_expired(self, max_age_hours: int) -> bool:
        """Check if this environment is expired based on age"""
        if not self.created_at:
            return False

        try:
            from datetime import datetime, timedelta

            created_time = datetime.fromisoformat(self.created_at.replace("-", ":"))
            expiry_time = created_time + timedelta(hours=max_age_hours)
            return datetime.now() > expiry_time
        except (ValueError, AttributeError):
            return False  # If we can't parse, assume not expired

    def to_circus_labels(self) -> List[str]:
        """Convert show state to circus tent emoji labels (per-SHA format)"""
        from .emojis import CIRCUS_PREFIX, MEANING_TO_EMOJI

        if not self.created_at:
            self.created_at = datetime.utcnow().strftime("%Y-%m-%dT%H-%M")

        labels = [
            f"{CIRCUS_PREFIX} {self.sha} {MEANING_TO_EMOJI['status']} {self.status}",  # SHA-first status
            f"{CIRCUS_PREFIX} {self.sha} {MEANING_TO_EMOJI['created_at']} {self.created_at}",  # SHA-first timestamp
            f"{CIRCUS_PREFIX} {self.sha} {MEANING_TO_EMOJI['ttl']} {self.ttl}",  # SHA-first TTL
        ]

        if self.ip:
            labels.append(f"{CIRCUS_PREFIX} {self.sha} {MEANING_TO_EMOJI['ip']} {self.ip}:8080")

        if self.requested_by:
            labels.append(
                f"{CIRCUS_PREFIX} {self.sha} {MEANING_TO_EMOJI['requested_by']} {self.requested_by}"
            )

        return labels

    def build_docker(self, dry_run: bool = False) -> None:
        """Build Docker image for this environment (atomic operation)"""
        if not dry_run:
            self._build_docker_image()  # Raises on failure

    def deploy_aws(self, dry_run: bool = False) -> None:
        """Deploy to AWS (atomic operation)"""
        github, aws = get_interfaces()

        if not dry_run:
            result = aws.create_environment(
                pr_number=self.pr_number,
                sha=self.sha + "0" * (40 - len(self.sha)),  # Convert to full SHA
                github_user=self.requested_by or "unknown",
            )

            if not result.success:
                raise Exception(f"AWS deployment failed: {result.error}")

            # Update with deployment results
            self.ip = result.ip
        else:
            # Mock successful deployment for dry-run
            self.ip = "52.1.2.3"

    def stop(self, dry_run_github: bool = False, dry_run_aws: bool = False) -> None:
        """Stop this environment (cleanup AWS resources)

        Raises:
            Exception: On cleanup failure
        """
        github, aws = get_interfaces()

        # Delete AWS resources (pure technical work)
        if not dry_run_aws:
            success = aws.delete_environment(self.aws_service_name, self.pr_number)
            if not success:
                raise Exception(f"Failed to delete AWS service: {self.aws_service_name}")

        # No comments - PullRequest handles that!

    def _build_docker_image(self) -> None:
        """Build Docker image for this environment"""
        import os
        import subprocess

        tag = f"apache/superset:pr-{self.pr_number}-{self.sha}-ci"

        # Detect if running in CI environment
        is_ci = bool(os.getenv("GITHUB_ACTIONS") or os.getenv("CI"))

        # Build command without final path
        cmd = [
            "docker",
            "buildx",
            "build",
            "--push",
            "--platform",
            "linux/amd64",
            "--target",
            "showtime",
            "--build-arg",
            "INCLUDE_CHROMIUM=false",
            "--build-arg",
            "LOAD_EXAMPLES_DUCKDB=true",
            "-t",
            tag,
        ]

        # Add caching based on environment
        if is_ci:
            # Full registry caching in CI (Docker driver supports it)
            cmd.extend(
                [
                    "--cache-from",
                    "type=registry,ref=apache/superset-cache:showtime",
                    "--cache-to",
                    "type=registry,mode=max,ref=apache/superset-cache:showtime",
                ]
            )
            print("🐳 CI environment: Using full registry caching")
        else:
            # Local build: cache-from only (no cache export)
            cmd.extend(
                [
                    "--cache-from",
                    "type=registry,ref=apache/superset-cache:showtime",
                ]
            )
            print("🐳 Local environment: Using cache-from only (no export)")

        # Add --load only when explicitly requested for local testing
        force_load = os.getenv("DOCKER_LOAD", "false").lower() == "true"

        if force_load:
            cmd.append("--load")
            print("🐳 Will load image to local Docker daemon (DOCKER_LOAD=true)")
        else:
            print("🐳 Push-only build (no local load) - faster for CI/deployment")

        # Add build context path last
        cmd.append(".")

        print(f"🐳 Building Docker image: {tag}")
        print(f"🐳 Command: {' '.join(cmd)}")

        # Stream output in real-time
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
        )

        if process.stdout:
            for line in process.stdout:
                print(f"🐳 {line.rstrip()}")

        return_code = process.wait(timeout=3600)
        if return_code != 0:
            raise Exception(f"Docker build failed with exit code: {return_code}")

    @classmethod
    def from_circus_labels(cls, pr_number: int, labels: List[str], sha: str) -> Optional["Show"]:
        """Create Show from circus tent labels for specific SHA"""
        show_data = {
            "pr_number": pr_number,
            "sha": sha,
            "status": "building",  # default
        }

        for label in labels:
            if not label.startswith("🎪"):
                continue

            parts = label.split(" ")
            if len(parts) < 3:
                continue

            # Per-SHA format: 🎪 {sha} {emoji} {value}
            if parts[1] == sha:  # This label is for our SHA
                emoji = parts[2]
                value = " ".join(parts[3:]) if len(parts) > 3 else ""

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

        # Return Show if we found any status labels for this SHA
        # For list purposes, we want to show ALL environments, even orphaned ones
        has_status = any(label.startswith(f"🎪 {sha} 🚦 ") for label in labels)
        if has_status:
            return cls(**show_data)  # type: ignore[arg-type]

        return None


def short_sha(full_sha: str) -> str:
    """Convert full SHA to short SHA (7 chars)"""
    return full_sha[:7]
