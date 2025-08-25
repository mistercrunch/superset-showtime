# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Superset Showtime is a CLI tool for managing Apache Superset ephemeral environments using "circus tent emoji labels" as a visual state management system on GitHub PRs. The tool integrates with GitHub Actions to provide automated environment provisioning on AWS ECS/ECR.

## Development Commands

**Package Management:**
```bash
# Install for development (preferred)
uv pip install -e ".[dev]"

# Traditional pip installation
pip install -e ".[dev]"
```

**Code Quality:**
```bash
make lint           # Run ruff and mypy checks
make format         # Auto-format with ruff
make pre-commit     # Install pre-commit hooks
make pre-commit-run # Run all pre-commit hooks
```

**Testing:**
```bash
make test          # Run pytest
make test-cov      # Run tests with coverage report
pytest tests/unit/test_circus.py  # Run specific test file
```

**Build and Distribution:**
```bash
make build         # Build package with uv
make publish       # Publish to PyPI (use with caution)
make clean         # Clean build artifacts
```

**Quick Testing:**
```bash
make circus        # Test circus emoji parsing logic
```

## Core Architecture

### Main Components

**CLI Layer (`showtime/cli.py`):**
- Typer-based CLI with rich output formatting
- Commands: `sync`, `start`, `stop`, `status`, `list`, `labels`, `cleanup`
- Primary entry point for GitHub Actions and manual usage

**Core Business Logic (`showtime/core/`):**

1. **PullRequest (`pull_request.py`)** - Main orchestrator
   - Manages PR-level state and atomic transactions
   - Handles trigger processing and environment lifecycle
   - Coordinates between GitHub labels and AWS resources
   - Implements sync logic for automatic deployments

2. **Show (`show.py`)** - Individual environment representation
   - Represents a single ephemeral environment
   - Manages Docker builds and AWS deployments
   - Handles state transitions (building → running → failed)

3. **GitHubInterface (`github.py`)** - GitHub API client
   - Label management and PR data fetching
   - Circus tent emoji label parsing and creation
   - Token detection from environment or gh CLI

4. **AWSInterface (`aws.py`)** - AWS operations
   - ECS service deployment and management
   - ECR image management
   - Network configuration and service discovery

### State Management Pattern

The system uses GitHub labels as a distributed state machine:

**Trigger Labels (User Actions):**
- `🎪 ⚡ showtime-trigger-start` - Create environment
- `🎪 🛑 showtime-trigger-stop` - Destroy environment
- `🎪 🧊 showtime-freeze` - Prevent auto-sync

**State Labels (System Managed):**
- `🎪 {sha} 🚦 {status}` - Environment status
- `🎪 🎯 {sha}` - Active environment pointer
- `🎪 🏗️ {sha}` - Building environment pointer
- `🎪 {sha} 🌐 {ip}` - Environment URL
- `🎪 {sha} 📅 {timestamp}` - Creation timestamp

### Atomic Transaction Model

The `PullRequest.sync()` method implements an atomic claim pattern:
1. **Claim**: Atomically remove trigger labels and set building state
2. **Build**: Docker build with deterministic tags (`pr-{number}-{sha}-ci`)
3. **Deploy**: AWS ECS service deployment with blue-green updates
4. **Validate**: Health checks and state synchronization

## Testing Approach

**Unit Tests:** Focus on circus label parsing and business logic
**Integration Tests:** Test with `--dry-run-aws --dry-run-docker` flags
**Manual Testing:** Use CLI commands with dry-run modes

## Key Design Principles

1. **Deterministic Naming:** All AWS resources use `pr-{number}-{sha}` pattern
2. **Idempotent Operations:** Safe to retry any operation
3. **Visual State Management:** GitHub labels provide immediate status visibility
4. **Zero-Downtime Updates:** Blue-green deployments with automatic traffic switching
5. **Fail-Safe Defaults:** Conservative cleanup and error handling

## Environment Variables

**Required:**
- `GITHUB_TOKEN` - GitHub API access
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` - AWS credentials

**Optional:**
- `AWS_REGION` - Default: us-west-2
- `ECS_CLUSTER` - Default: superset-ci
- `ECR_REPOSITORY` - Default: superset-ci
- `GITHUB_ORG` - Default: apache
- `GITHUB_REPO` - Default: superset

## GitHub Actions Integration

The tool is designed to be called from GitHub Actions workflows:
```yaml
- name: Install Superset Showtime
  run: pip install superset-showtime

- name: Sync PR state
  run: showtime sync ${{ github.event.number }}
```

Primary workflow file: `workflows-reference/showtime-trigger.yml`

## Common Development Patterns

**Testing without AWS costs:**
```bash
showtime sync 1234 --dry-run-aws --dry-run-docker
```

**Debugging specific PR:**
```bash
showtime status 1234 --verbose
showtime list --status running
```

**Manual environment management:**
```bash
showtime start 1234 --sha abc123f
showtime stop 1234 --force
```
