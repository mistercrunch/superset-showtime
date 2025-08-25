# 🎪 Superset Showtime

**Modern ephemeral environment management for Apache Superset using circus tent emoji labels**

[![PyPI version](https://badge.fury.io/py/superset-showtime.svg)](https://badge.fury.io/py/superset-showtime)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

## 🎯 What is Showtime?

Superset Showtime is a CLI tool designed primarily for **GitHub Actions** to manage Apache Superset ephemeral environments. It uses **circus tent emoji labels** as a visual state management system and depends on Superset's existing build infrastructure.

## 🚀 Quick Start for Superset Contributors

**Create an ephemeral environment:**
1. Go to your PR in GitHub
2. Add label: `🎪 ⚡ showtime-trigger-start`
3. Watch the magic happen - labels will update automatically
4. When you see `🎪 🚦 {sha} running`, your environment is ready!
5. Get URL from `🎪 🌐 {sha} {ip}` → `http://{ip}:8080`
6. **Every new commit automatically deploys a fresh environment** (zero-downtime)

**To test a specific commit without auto-updates:**
- Add label: `🎪 🧊 showtime-freeze` (prevents auto-sync on new commits)

**Clean up when done:**
```bash
# Add this label:
🎪 🛑 showtime-trigger-stop
# All circus labels disappear, AWS resources cleaned up
```

## 🎪 How It Works

**🎪 GitHub labels become a visual state machine:**
```bash
# User adds trigger label in GitHub UI:
🎪 ⚡ showtime-trigger-start

# System responds with state labels:
🎪 abc123f 🚦 building      # Environment abc123f is building
🎪 🎯 abc123f               # abc123f is the active environment
🎪 abc123f 📅 2024-01-15T14-30  # Created timestamp
🎪 abc123f ⌛ 24h           # Time-to-live policy
🎪 abc123f 🤡 maxime        # Requested by maxime (clown emoji!)

# When ready:
🎪 abc123f 🚦 running       # Environment is now running
🎪 abc123f 🌐 52-1-2-3      # Available at http://52.1.2.3:8080
```

### 🔄 Showtime Workflow

```mermaid
flowchart TD
    A[User adds 🎪 ⚡ trigger-start] --> B[GitHub Actions: sync]
    B --> C{Current state?}

    C -->|No environment| D[🔒 Claim: Remove trigger + Set building]
    C -->|Running + new SHA| E[🔒 Claim: Remove trigger + Set building]
    C -->|Already building| F[❌ Exit: Another job active]
    C -->|No triggers| G[❌ Exit: Nothing to do]

    D --> H[📋 State: building]
    E --> H
    H --> I[🐳 Docker build]
    I -->|Success| J[📋 State: built]
    I -->|Fail| K[📋 State: failed]

    J --> L[📋 State: deploying]
    L --> M[☁️ AWS Deploy]
    M -->|Success| N[📋 State: running]
    M -->|Fail| O[📋 State: failed]

    N --> P[🎪 Environment ready!]

    Q[User adds 🎪 🛑 trigger-stop] --> R[🧹 Cleanup AWS + Remove labels]
```


**Install CLI for debugging:**
```bash
pip install superset-showtime
export GITHUB_TOKEN=your_token
```

**Monitor and debug:**
```bash
showtime list                    # See all active environments
showtime status 1234            # Debug specific environment
showtime labels                 # Complete label reference
```

**Testing/development:**
```bash
showtime sync 1234 --dry-run-aws --dry-run-docker  # Test without costs
showtime cleanup --dry-run --older-than 1h         # Test cleanup logic
```

> **Architecture**: This CLI implements ACID-style atomic transactions with direct Docker integration. It handles complete environment lifecycle from Docker build to AWS deployment with race condition prevention.

## 🎪 Complete Label Reference

### 🎯 Trigger Labels (Add These to Your PR)

| Label | Action | Result |
|-------|---------|---------|
| `🎪 ⚡ showtime-trigger-start` | Create environment | Builds and deploys ephemeral environment with blue-green deployment |
| `🎪 🛑 showtime-trigger-stop` | Destroy environment | Cleans up AWS resources and removes all labels |
| `🎪 🧊 showtime-freeze` | Freeze environment | Prevents auto-sync on new commits (for testing specific SHAs) |

### 📊 State Labels (Automatically Managed)

| Label Pattern | Meaning | Example |
|---------------|---------|---------|
| `🎪 {sha} 🚦 {status}` | Environment status | `🎪 abc123f 🚦 running` |
| `🎪 🎯 {sha}` | Active environment pointer | `🎪 🎯 abc123f` |
| `🎪 🏗️ {sha}` | Building environment pointer | `🎪 🏗️ def456a` |
| `🎪 {sha} 📅 {timestamp}` | Creation time | `🎪 abc123f 📅 2024-01-15T14-30` |
| `🎪 {sha} 🌐 {ip:port}` | Environment URL | `🎪 abc123f 🌐 52.1.2.3:8080` |
| `🎪 {sha} ⌛ {ttl}` | Time-to-live policy | `🎪 abc123f ⌛ 24h` |
| `🎪 {sha} 🤡 {username}` | Who requested | `🎪 abc123f 🤡 maxime` |

## 🔧 Testing Configuration Changes

**Approach**: Modify configuration directly in your PR code, then trigger environment.

**Workflow**:
1. Modify `superset_config.py` with your changes
2. Push commit → Creates new SHA (e.g., `def456a`)
3. Add `🎪 ⚡ showtime-trigger-start` → Deploys with your config
4. Test environment reflects your exact code changes

This approach creates traceable, reviewable changes that are part of your git history.

## 🔄 Complete Workflows

### Creating Your First Environment

1. **Add trigger label** in GitHub UI: `🎪 ⚡ showtime-trigger-start`
2. **Watch state labels appear:**
   ```
   🎪 abc123f 🚦 building      ← Environment is building
   🎪 🎯 abc123f               ← This is the active environment
   🎪 abc123f 📅 2024-01-15T14-30  ← Started building at this time
   ```
3. **Wait for completion:**
   ```
   🎪 abc123f 🚦 running       ← Now ready!
   🎪 abc123f 🌐 52.1.2.3:8080  ← Visit http://52.1.2.3:8080
   ```

### Testing Specific Commits

1. **Add freeze label:** `🎪 🧊 showtime-freeze`
2. **Result:** Environment won't auto-update on new commits
3. **Use case:** Test specific SHA while continuing development
4. **Override:** Add `🎪 ⚡ showtime-trigger-start` to force update despite freeze

### Rolling Updates (Automatic!)

When you push new commits, Showtime automatically:
1. **Detects new commit** via GitHub webhook
2. **Builds new environment** alongside old one
3. **Switches traffic** when new environment is ready
4. **Cleans up old environment**

You'll see:
```bash
# During update:
🎪 abc123f 🚦 running       # Old environment still serving
🎪 def456a 🚦 building      # New environment building
🎪 🎯 abc123f               # Traffic still on old
🎪 🏗️ def456a               # New one being prepared

# After update:
🎪 def456a 🚦 running       # New environment live
🎪 🎯 def456a               # Traffic switched
🎪 def456a 🌐 52-4-5-6      # New IP address
# All abc123f labels removed automatically
```

## 🔒 Security & Permissions

### Who Can Use This?

- **✅ Superset maintainers** (with write access) can add trigger labels
- **❌ External contributors** cannot trigger environments (no write access to add labels)
- **🔒 Secure by design** - only trusted users can create expensive AWS resources

### GitHub Actions Integration

**🎯 Live Workflow**: [showtime-trigger.yml](https://github.com/apache/superset/actions/workflows/showtime-trigger.yml)

**How it works:**
- Triggers on PR label changes, commits, and closures
- Installs `superset-showtime` from PyPI (trusted code, not PR code)
- Runs `showtime sync` to handle trigger processing and deployments
- Supports manual testing via `workflow_dispatch` with specific SHA override

**Commands used:**
```bash
showtime sync PR_NUMBER --check-only    # Determine build_needed + target_sha
showtime sync PR_NUMBER --sha SHA       # Execute atomic claim + build + deploy
```

## 🛠️ CLI Usage

The CLI is primarily used by GitHub Actions, but available for debugging and advanced users:

```bash
pip install superset-showtime
export GITHUB_TOKEN=your_token

# Core commands:
showtime sync PR_NUMBER              # Sync to desired state (main command)
showtime start PR_NUMBER             # Create new environment
showtime stop PR_NUMBER              # Delete environment
showtime status PR_NUMBER            # Show current state
showtime list                        # List all environments
showtime cleanup --older-than 48h    # Clean up expired environments
```



## 🤝 Contributing

### Testing Your Changes

**Test with real PRs safely:**
```bash
# Test full workflow without costs:
showtime sync YOUR_PR_NUMBER --dry-run-aws --dry-run-docker

# Test cleanup logic:
showtime cleanup --dry-run --older-than 24h
```

### Development Setup

```bash
git clone https://github.com/mistercrunch/superset-showtime
cd superset-showtime

# Using uv (recommended):
uv pip install -e ".[dev]"
make pre-commit
make test

# Traditional pip:
pip install -e ".[dev]"
pre-commit install
pytest
```

## 📄 License

Apache License 2.0 - same as Apache Superset.

---

**🎪 "Ladies and gentlemen, welcome to Superset Showtime - where ephemeral environments are always under the big top!"** 🎪🤡✨
