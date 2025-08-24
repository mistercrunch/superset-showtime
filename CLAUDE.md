# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Superset Showtime is a Python CLI tool for managing Apache Superset ephemeral environments using **circus tent emoji labels** as a state management system on GitHub PRs. The system implements **ACID-style atomic transactions** using GitHub labels as a distributed coordination mechanism, with **compare-and-swap** patterns to prevent race conditions.

## Development Commands

### Essential Commands
```bash
# Development setup
uv pip install -e ".[dev]"     # Install with dev dependencies
make pre-commit                 # Setup pre-commit hooks
make test                       # Run tests
make lint                       # Run ruff + mypy

# Testing circus tent functionality
python -m showtime --help               # Shows complete workflow tutorial
python -m showtime labels               # Complete label reference
python -m showtime list                 # List all environments (requires GITHUB_TOKEN)
python -m showtime test-lifecycle 1234  # Full workflow simulation

# Test new unified sync command
export GITHUB_TOKEN=xxx
showtime sync 34809 --check-only                    # Analyze what's needed
showtime sync 34809 --dry-run-aws --dry-run-docker # Test full flow safely
showtime set-state building 34809                   # Manual state transitions
```

### Testing Single Components
```bash
pytest tests/unit/test_circus.py                    # Test label parsing
pytest tests/unit/test_circus.py::test_show_properties -v   # Single test
python -c "from showtime.core.circus import Show; show = Show(pr_number=1234, sha='abc123f', status='running'); print(show.to_circus_labels())"   # Quick circus label test
```

## Architecture Overview

### Core State Management Pattern
The system uses **GitHub labels as a distributed ACID-style database**:
- **Trigger labels** (`🎪 ⚡ showtime-trigger-start`) - Commands added by users, atomically processed and removed
- **State labels** (`🎪 abc123f 🚦 building`) - Per-SHA status managed with atomic compare-and-swap operations
- **No external database** - All state reconstructed from GitHub labels
- **Race condition prevention** - Atomic claim prevents double-processing of triggers

### Enhanced State Lifecycle
**Complete state progression**: `building → built → deploying → running/failed`
- **building**: Docker image construction in progress
- **built**: Docker build complete, ready for AWS deployment
- **deploying**: AWS ECS deployment in progress
- **running**: Environment live and accessible
- **failed**: Build or deployment failed

### Key Classes and Responsibilities

#### `Show` (showtime/core/circus.py:16)
Represents a single ephemeral environment with per-SHA state:
- **Properties**: `aws_service_name`, `aws_image_tag` for deterministic AWS naming
- **Methods**: `to_circus_labels()` creates per-SHA format labels
- **Parsing**: `from_circus_labels()` reconstructs from GitHub labels

#### `PullRequest` (showtime/core/circus.py:121)
Container parsing all shows from a PR's labels:
- **Properties**: `current_show`, `building_show`, `circus_labels`
- **State reconstruction**: Parses all environments from labels
- **Factory method**: `from_id()` loads real GitHub data

#### `GitHubInterface` (showtime/core/github.py:23)
GitHub API operations with emoji label support:
- **Authentication**: Auto-detects `GITHUB_TOKEN` or `gh auth token`
- **Label operations**: Handles emoji encoding for GitHub API
- **Discovery**: `find_prs_with_shows()` searches for circus tent labels

#### `AWSInterface` (showtime/core/aws.py:35)
Replicates current GitHub Actions AWS logic:
- **Naming**: Uses same deterministic patterns as current GHA
- **Operations**: `create_environment()`, `delete_environment()` mirror existing workflows
- **Network config**: Same subnets/security groups as production

### Label Format Design

#### Per-SHA State Labels
```bash
🎪 🚦 {sha} {status}        # 🎪 🚦 abc123f running
🎪 🌐 {sha} {ip-dashes}     # 🎪 🌐 abc123f 52-1-2-3
🎪 📅 {sha} {timestamp}     # 🎪 📅 abc123f 2024-01-15T14-30
🎪 ⌛ {sha} {ttl}           # 🎪 ⌛ abc123f 24h
🎪 🤡 {sha} {username}      # 🎪 🤡 abc123f maxime
🎪 ⚙️ {sha} {config}        # 🎪 ⚙️ abc123f alerts,debug
```

#### Pointer Labels (No Value)
```bash
🎪 🎯 {sha}                 # Active environment pointer
🎪 🏗️ {sha}                 # Building environment pointer
```

### GitHub Actions Integration

#### Current Integration Points
- **`.github/workflows/circus.yml`** - Main workflow replacing `ephemeral-env.yml`
- **`.github/workflows/circus-cleanup.yml`** - Scheduled cleanup replacing manual processes
- **Security model**: `pull_request_target` + PyPI install (no PR code execution)

#### CLI Commands Called by GHA
- `showtime sync {pr-number} --check-only` - Analyze state and determine build_needed
- `showtime sync {pr-number} --sha {sha}` - Execute atomic claim + build + deploy
- `showtime set-state {state} {pr-number}` - Manual state transitions
- `showtime cleanup --older-than 48h` - Scheduled cleanup

## Important Implementation Details

### Authentication Pattern
```python
# Priority order for credentials:
github = GitHubInterface()  # Auto-detects GITHUB_TOKEN or gh CLI
# No config files - environment variables only
```

### Dry-Run Testing Strategy
The CLI has comprehensive dry-run support for safe testing:
```bash
--dry-run-aws        # Skip AWS operations, use mock data
--dry-run-github     # Skip GitHub operations, show what would happen
--dry-run-docker     # Skip Docker build, use mock success
--aws-sleep N        # Sleep N seconds to simulate AWS timing
```

### AWS Resource Naming & Docker Integration
**Direct Docker build** (no supersetbot dependency):
- **Docker Image**: `apache/superset:pr-{pr_number}-{sha}-ci` (single tag, built directly)
- **ECS Service**: `pr-{pr_number}-{sha}` (e.g., `pr-1234-abc123f`)
- **Network**: Same subnets/security groups as current production setup

**Docker Build Command**:
```bash
docker buildx build --push --load --platform linux/amd64 --target ci \
  --build-arg INCLUDE_CHROMIUM=false --build-arg LOAD_EXAMPLES_DUCKDB=true \
  -t apache/superset:pr-{pr}-{sha}-ci .
```

### State Recovery Pattern
Since the CLI is stateless, it always reconstructs state from GitHub labels:
```python
pr = PullRequest.from_id(pr_number, github)  # Reads all labels
show = pr.current_show                       # Finds active environment
# All state comes from parsing circus tent emoji labels
```

## Critical Development Notes

### ACID-Style Atomic Transactions
GitHub label operations implement compare-and-swap pattern for race condition prevention:
```python
# Atomic claim pattern in _atomic_claim_environment():
# 1. CHECK: Validate current state allows new work
# 2. COMPARE: Ensure triggers exist and state is valid
# 3. SWAP: Remove triggers + Set building state atomically
# 4. COMMIT: Environment successfully claimed

# Example atomic transaction:
if not _validate_non_active_state(pr):
    return False  # Another job already active
github.remove_label(pr_number, trigger_label)  # Remove trigger
github.remove_circus_labels(pr_number)         # Clear stale state
for label in building_show.to_circus_labels():
    github.add_label(pr_number, label)         # Set building state
```

### Per-SHA Format Required
All new state labels must include SHA for multi-environment support:
```python
# Correct: Per-SHA format
f"🎪 🚦 {sha} running"      # Status per environment
f"🎪 🌐 {sha} {ip}"         # IP per environment

# Incorrect: Global format (legacy)
"🎪 🚦 running"             # Which environment??
```

### Testing Against Real PRs
The CLI can safely test against real Superset PRs:
```bash
# Test label management without AWS costs
showtime start 34809 --dry-run-aws
# Removes test labels when done
showtime stop 34809 --force
```

## Current Implementation Status

### ✅ Current Architecture (Production Ready)
- **ACID-style transactions**: Atomic compare-and-swap prevents race conditions
- **Direct Docker integration**: No supersetbot dependency, single tag builds
- **Streamlined GitHub Actions**: 3-step workflow (check → setup → sync)
- **Enhanced state machine**: building→built→deploying→running/failed lifecycle
- **Unified sync command**: Handles atomic claim + build + deploy in one command
- **Smart conditionals**: Skip Docker setup when build_needed=false
- **Race condition safe**: Multiple jobs can't double-process triggers

### 🎯 Label System (Streamlined)
- **Trigger labels**: `🎪 ⚡ showtime-trigger-start` (namespaced, searchable)
- **State labels**: `🎪 abc123f 🚦 running` (color-coded status)
- **Freeze support**: `🎪 🧊 showtime-freeze` (prevents auto-sync)
- **Automatic creation**: Labels get proper colors/descriptions automatically

### 📦 Key Commands for Development
```bash
# Core sync command (replaces handle-trigger, handle-sync):
showtime sync PR_NUMBER --check-only        # Returns build_needed + target_sha
showtime sync PR_NUMBER --sha SHA           # Atomic claim + build + deploy

# Manual state management:
showtime set-state building PR_NUMBER       # Set specific state
showtime set-state failed PR_NUMBER --error-msg "Build failed"

# Development testing:
showtime sync PR_NUMBER --dry-run-aws --dry-run-docker --dry-run-github
```
