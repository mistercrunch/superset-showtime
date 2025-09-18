"""Service name parsing and generation utilities."""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ServiceName:
    """
    Handles ECS service name parsing and generation.

    Service names follow the pattern: pr-{pr_number}-{sha}-service
    Where sha can be either full or short (7 chars).

    Examples:
        pr-34868-service (legacy, no SHA)
        pr-34868-abc123f-service (with short SHA)
        pr-34868-abc123f456def-service (with full SHA)
    """

    pr_number: int
    sha: Optional[str] = None

    @classmethod
    def from_service_name(cls, service_name: str) -> "ServiceName":
        """
        Parse a service name into its components.

        Args:
            service_name: ECS service name like "pr-34868-abc123f-service"

        Returns:
            ServiceName instance with parsed components
        """
        # Remove -service suffix if present
        base_name = service_name.replace("-service", "")

        # Parse pattern: pr-{number}[-{sha}]
        match = re.match(r"pr-(\d+)(?:-([a-f0-9]+))?", base_name)
        if not match:
            raise ValueError(f"Invalid service name format: {service_name}")

        pr_number = int(match.group(1))
        sha = match.group(2)  # May be None for legacy services

        return cls(pr_number=pr_number, sha=sha)

    @classmethod
    def from_base_name(cls, base_name: str, pr_number: int) -> "ServiceName":
        """
        Create from base name (without pr- prefix and -service suffix).

        Args:
            base_name: Name like "pr-34868-abc123f"
            pr_number: PR number for validation

        Returns:
            ServiceName instance
        """
        # Remove pr- prefix if present
        if base_name.startswith("pr-"):
            base_name = base_name[3:]

        # Parse pattern: {number}[-{sha}]
        parts = base_name.split("-", 1)
        parsed_pr = int(parts[0])

        if parsed_pr != pr_number:
            raise ValueError(f"PR number mismatch: expected {pr_number}, got {parsed_pr}")

        sha = parts[1] if len(parts) > 1 else None

        return cls(pr_number=pr_number, sha=sha)

    @property
    def base_name(self) -> str:
        """Get base name without -service suffix (e.g., pr-34868-abc123f)"""
        if self.sha:
            return f"pr-{self.pr_number}-{self.sha}"
        return f"pr-{self.pr_number}"

    @property
    def service_name(self) -> str:
        """Get full ECS service name (e.g., pr-34868-abc123f-service)"""
        return f"{self.base_name}-service"

    @property
    def image_tag(self) -> str:
        """Get Docker image tag (e.g., pr-34868-abc123f-ci)"""
        if not self.sha:
            raise ValueError("SHA is required for image tag")
        return f"{self.base_name}-ci"

    @property
    def short_sha(self) -> Optional[str]:
        """Get short SHA (first 7 chars) if available"""
        if self.sha:
            return self.sha[:7]
        return None

    def __str__(self) -> str:
        """String representation returns the full service name"""
        return self.service_name
