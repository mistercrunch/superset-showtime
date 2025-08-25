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
    Tries to fetch the SHA from origin if validation fails in a shallow clone.

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

        # First attempt: Search for SHA in git log (has to work in shallow clones where merge_base fails)
        is_valid, error = _validate_sha_in_log(repo, sha_to_check)
        if is_valid:
            return True, None

        # If validation failed, check if we're in a shallow clone and try fetching
        try:
            is_shallow = repo.git.rev_parse("--is-shallow-repository") == "true"
            if is_shallow:
                try:
                    print(f"🌊 Shallow clone detected, attempting to fetch {sha_to_check[:7]}...")
                    repo.git.fetch("origin", sha_to_check)

                    # Retry validation after fetch
                    is_valid_after_fetch, error_after_fetch = _validate_sha_in_log(
                        repo, sha_to_check
                    )
                    if is_valid_after_fetch:
                        print(f"✅ Successfully fetched and validated {sha_to_check[:7]}")
                        return True, None
                    else:
                        return False, error_after_fetch

                except Exception as fetch_error:
                    return False, (
                        f"Required commit {sha_to_check} not found in shallow clone. "
                        f"Failed to fetch from origin: {fetch_error}"
                    )
            else:
                return False, error

        except Exception:
            # If shallow check fails, return original error
            return False, error

    except InvalidGitRepositoryError:
        return False, "Current directory is not a Git repository"
    except Exception as e:
        return False, f"Git validation error: {e}"


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
