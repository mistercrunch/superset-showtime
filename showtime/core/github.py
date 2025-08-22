"""
🎪 GitHub API interface for circus tent label management

Handles all GitHub operations including PR fetching, label management,
and circus tent emoji state synchronization.
"""

import os
from dataclasses import dataclass
from typing import Dict, List, Optional

import httpx


@dataclass
class GitHubError(Exception):
    """GitHub API error"""

    message: str
    status_code: Optional[int] = None


class GitHubInterface:
    """GitHub API client for circus tent label operations"""

    def __init__(self, token: str = None, org: str = None, repo: str = None):
        self.token = token or self._detect_token()
        self.org = org or os.getenv("GITHUB_ORG", "apache")
        self.repo = repo or os.getenv("GITHUB_REPO", "superset")
        self.base_url = "https://api.github.com"

        if not self.token:
            raise GitHubError("GitHub token required. Set GITHUB_TOKEN environment variable.")

    def _detect_token(self) -> Optional[str]:
        """Detect GitHub token from environment or gh CLI"""
        # 1. Environment variable (GHA style)
        token = os.getenv("GITHUB_TOKEN")
        if token:
            return token

        # 2. GitHub CLI (local development)
        try:
            import subprocess

            result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
            if result.returncode == 0:
                return result.stdout.strip()
        except FileNotFoundError:
            pass  # gh CLI not installed

        return None

    @property
    def headers(self) -> Dict[str, str]:
        """HTTP headers for GitHub API requests"""
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def get_labels(self, pr_number: int) -> List[str]:
        """Get all labels for a PR"""
        url = f"{self.base_url}/repos/{self.org}/{self.repo}/issues/{pr_number}/labels"

        with httpx.Client() as client:
            response = client.get(url, headers=self.headers)
            response.raise_for_status()

            labels_data = response.json()
            return [label["name"] for label in labels_data]

    def add_label(self, pr_number: int, label: str) -> None:
        """Add a label to a PR"""
        url = f"{self.base_url}/repos/{self.org}/{self.repo}/issues/{pr_number}/labels"

        with httpx.Client() as client:
            response = client.post(url, headers=self.headers, json={"labels": [label]})
            response.raise_for_status()

    def remove_label(self, pr_number: int, label: str) -> None:
        """Remove a label from a PR"""
        # URL encode the label name for special characters like emojis
        import urllib.parse

        encoded_label = urllib.parse.quote(label, safe="")
        url = f"{self.base_url}/repos/{self.org}/{self.repo}/issues/{pr_number}/labels/{encoded_label}"

        with httpx.Client() as client:
            response = client.delete(url, headers=self.headers)
            # 404 is OK - label might not exist
            if response.status_code not in (200, 204, 404):
                response.raise_for_status()

    def set_labels(self, pr_number: int, labels: List[str]) -> None:
        """Replace all labels on a PR"""
        url = f"{self.base_url}/repos/{self.org}/{self.repo}/issues/{pr_number}/labels"

        with httpx.Client() as client:
            response = client.put(url, headers=self.headers, json={"labels": labels})
            response.raise_for_status()

    def get_latest_commit_sha(self, pr_number: int) -> str:
        """Get the latest commit SHA for a PR"""
        url = f"{self.base_url}/repos/{self.org}/{self.repo}/pulls/{pr_number}"

        with httpx.Client() as client:
            response = client.get(url, headers=self.headers)
            response.raise_for_status()

            pr_data = response.json()
            return pr_data["head"]["sha"]

    def get_circus_labels(self, pr_number: int) -> List[str]:
        """Get only circus tent emoji labels for a PR"""
        all_labels = self.get_labels(pr_number)
        return [label for label in all_labels if label.startswith("🎪 ")]

    def remove_circus_labels(self, pr_number: int) -> None:
        """Remove all circus tent labels from a PR"""
        circus_labels = self.get_circus_labels(pr_number)
        for label in circus_labels:
            self.remove_label(pr_number, label)

    def find_prs_with_shows(self) -> List[int]:
        """Find all PRs that have circus tent labels"""
        # Search for issues with circus tent labels
        url = f"{self.base_url}/search/issues"
        params = {"q": f'repo:{self.org}/{self.repo} is:pr is:open label:"🎪 🚦"', "per_page": 100}

        with httpx.Client() as client:
            response = client.get(url, headers=self.headers, params=params)
            response.raise_for_status()

            issues = response.json()["items"]
            return [issue["number"] for issue in issues]

    def validate_connection(self) -> bool:
        """Test GitHub API connection"""
        try:
            url = f"{self.base_url}/repos/{self.org}/{self.repo}"
            with httpx.Client() as client:
                response = client.get(url, headers=self.headers)
                response.raise_for_status()
                return True
        except Exception:
            return False
