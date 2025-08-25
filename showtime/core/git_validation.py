"""
🎪 Git SHA Validation for Superset Showtime

Validates that the current Git repository contains required commit SHA to prevent
usage with outdated releases.
"""

from typing import Optional, Tuple

try:
    from git import InvalidGitRepositoryError, Repo
except ImportError:
    # Fallback if GitPython is not available
    Repo = None
    InvalidGitRepositoryError = Exception


# Hard-coded required SHA - update this when needed
REQUIRED_SHA = "277f03c2075a74fbafb55531054fb5083debe5cc"  # Placeholder SHA for testing


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
    if Repo is None:
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

    Args:
        required_sha: SHA to validate (default: REQUIRED_SHA constant)

    Returns:
        Tuple of (is_valid, error_message)
        - (True, None) if validation passes
        - (False, error_message) if validation fails
    """
    if Repo is None:
        return False, "GitPython not available for SHA validation"

    sha_to_check = required_sha or REQUIRED_SHA
    if not sha_to_check:
        return True, None  # No requirement set

    try:
        repo = Repo(".")

        # Search for SHA in git log (has to work in shallow clones where merge_base fails)
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

    except InvalidGitRepositoryError:
        return False, "Current directory is not a Git repository"
    except Exception as e:
        return False, f"Git validation error: {e}"


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

[bold yellow]To resolve this:[/bold yellow]
1. Ensure you're on the correct branch (usually main)
2. Pull the latest changes: [cyan]git pull origin main[/cyan]
3. Verify the commit exists: [cyan]git log --oneline | grep {sha_to_check[:7]}[/cyan]
4. If needed, switch to main branch: [cyan]git checkout main[/cyan]

[dim]This check prevents Showtime from running on outdated releases.[/dim]
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
