"""
🎪 Superset Showtime - Smart ephemeral environment management

Circus tent emoji state tracking for Apache Superset ephemeral environments.
"""

__version__ = "0.2.5"
__author__ = "Maxime Beauchemin"
__email__ = "maximebeauchemin@gmail.com"

from .core.circus import PullRequest, Show
from .core.github import GitHubInterface

__all__ = [
    "__version__",
    "Show",
    "PullRequest",
    "GitHubInterface",
]
