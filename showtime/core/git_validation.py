"""
🎪 Git SHA Validation for Superset Showtime

Validates that the current Git repository contains required commit SHA to prevent
usage with outdated releases.
"""

from typing import TYPE_CHECKING, Optional, Tuple

if TYPE_CHECKING:
    from git import InvalidGitRepositoryError, Repo
else:
    try:
        from git import InvalidGitRepositoryError, Repo
    except ImportError:
        # Fallback if GitPython is not available
        Repo = None
        InvalidGitRepositoryError = Exception


# Hard-coded required SHA - update this when needed
# https://github.com/apache/superset/commit/47414e18d4c2980d0cc4718b3e704845f7dfd356
REQUIRED_SHA = "47414e18d4c2980d0cc4718b3e704845f7dfd356"


class GitValidationError(Exception):
    """Raised when Git validation fails"""

    pass


def is_git_repository(path: str = ".") -> bool:
    """
    Check if the current directory (or specified path) is a Git repository.

    Args:
        path: Path to check (default: current directory)

    Returns:
        True if it's a Git repository, False otherwise
    """
    try:
        from git import InvalidGitRepositoryError, Repo
    except ImportError:
        # GitPython not available, assume not a git repo
        return False

    try:
        Repo(path)
        return True
    except (InvalidGitRepositoryError, Exception):
        return False


def validate_required_sha(required_sha: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    """
    Validate that the required SHA exists in the current Git repository.
    Uses GitHub API for reliable validation in shallow clone environments.

    Args:
        required_sha: SHA to validate (default: REQUIRED_SHA constant)

    Returns:
        Tuple of (is_valid, error_message)
        - (True, None) if validation passes
        - (False, error_message) if validation fails
    """
    sha_to_check = required_sha or REQUIRED_SHA
    if not sha_to_check:
        return True, None  # No requirement set

    # Try GitHub API validation first (works in shallow clones)
    try:
        return _validate_sha_via_github_api(sha_to_check)
    except Exception as e:
        print(f"⚠️ GitHub API validation failed: {e}")
        # Fall through to Git validation

    # Fallback to Git validation for non-GitHub origins
    try:
        from git import Repo
    except ImportError:
        print("⚠️ GitPython not available, skipping SHA validation")
        return True, None

    try:
        repo = Repo(".")
        is_valid, error = _validate_sha_in_log(repo, sha_to_check)
        if is_valid:
            return True, None
        else:
            print(f"⚠️ Git validation failed: {error}")
            return True, None  # Allow operation to continue

    except Exception as e:
        print(f"⚠️ Git validation error: {e}")
        return True, None


def _validate_sha_via_github_api(required_sha: str) -> Tuple[bool, Optional[str]]:
    """Validate SHA using GitHub API - works reliably in shallow clones"""
    try:
        import httpx
        from git import Repo

        from .github import GitHubInterface

        # Get current SHA from Git
        repo = Repo(".")
        current_sha = repo.head.commit.hexsha

        # Use existing GitHubInterface (handles all the setup/token detection)
        github = GitHubInterface()

        # 1. Check if required SHA exists
        commit_url = f"{github.base_url}/repos/{github.org}/{github.repo}/commits/{required_sha}"

        with httpx.Client() as client:
            response = client.get(commit_url, headers=github.headers)
            if response.status_code == 404:
                return False, f"Required SHA {required_sha[:7]} not found in repository"
            response.raise_for_status()

        # 2. Compare SHAs to verify ancestry
        compare_url = f"{github.base_url}/repos/{github.org}/{github.repo}/compare/{required_sha}...{current_sha}"

        with httpx.Client() as client:
            response = client.get(compare_url, headers=github.headers)
            if response.status_code == 404:
                return (
                    False,
                    f"Current branch does not include required SHA {required_sha[:7]}. Please rebase onto main.",
                )
            response.raise_for_status()

            data = response.json()
            status = data.get("status")

            # If status is 'ahead' or 'identical', required SHA is ancestor (good)
            # If status is 'behind', current is behind required (bad)
            if status in ["ahead", "identical"]:
                print(
                    f"✅ Validated that required SHA {required_sha[:7]} is included in current branch"
                )
                return True, None
            else:
                return (
                    False,
                    f"Current branch does not include required SHA {required_sha[:7]}. Please rebase onto main.",
                )

    except Exception as e:
        # Re-raise to be caught by the caller for proper fallback handling
        raise Exception(f"GitHub API validation error: {e}") from e


def _validate_sha_in_log(repo: "Repo", sha_to_check: str) -> Tuple[bool, Optional[str]]:
    """Helper function to validate SHA exists in git log output."""
    try:
        log_output = repo.git.log("--oneline", "--all")
        if sha_to_check in log_output or sha_to_check[:7] in log_output:
            return True, None
        else:
            return False, (
                f"Required commit {sha_to_check} not found in Git history. "
                f"Please update to a branch that includes this commit."
            )
    except Exception as e:
        return False, f"Git log search failed: {e}"


def get_validation_error_message(required_sha: Optional[str] = None) -> str:
    """
    Get a user-friendly error message for SHA validation failure.

    Args:
        required_sha: SHA that was required (default: REQUIRED_SHA)

    Returns:
        Formatted error message with resolution steps
    """
    sha_to_check = required_sha or REQUIRED_SHA

    return f"""
🎪 [bold red]Git SHA Validation Failed[/bold red]

This branch requires commit {sha_to_check} to be present in your Git history.

[bold yellow]Why this commit is required:[/bold yellow]
Showtime depends on Docker build infrastructure (LOAD_EXAMPLES_DUCKDB) and DuckDB
examples support that was introduced in this commit. Without it, Docker builds will fail.

[bold yellow]To resolve this:[/bold yellow]
1. Ensure you're on the correct branch (usually main)
2. Pull the latest changes: [cyan]git pull origin main[/cyan]
3. Verify the commit exists: [cyan]git log --oneline | grep {sha_to_check[:7]}[/cyan]
4. If needed, switch to main branch: [cyan]git checkout main[/cyan]

[dim]This prevents Docker build failures on PRs missing required infrastructure.[/dim]
""".strip()


def should_skip_validation() -> bool:
    """
    Determine if Git validation should be skipped.

    Currently skips validation when not in a Git repository,
    allowing --check-only to work in non-Git environments.

    Returns:
        True if validation should be skipped
    """
    return not is_git_repository()
