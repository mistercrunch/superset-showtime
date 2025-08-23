# 🎪 Superset Showtime

**Modern ephemeral environment management for Apache Superset using circus tent emoji labels**

[![PyPI version](https://badge.fury.io/py/superset-showtime.svg)](https://badge.fury.io/py/superset-showtime)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

## 🎯 What is Showtime?

Superset Showtime replaces the complex GitHub Actions scripts for ephemeral environments with a simple, powerful CLI tool that uses **circus tent emoji labels** for state management.

### The Problem We Solve

**Current Superset ephemeral environment issues:**
- 🚨 **Stale environments** - New commits don't update existing environments
- 💸 **Resource waste** - Multiple environments per PR, no automatic cleanup
- 🔧 **Hard to maintain** - Complex GitHub Actions logic scattered across workflows
- 👀 **Poor visibility** - Hard to see what environments exist and their status

### The Showtime Solution

**🎪 GitHub labels become a visual state machine:**
```bash
# User adds trigger label in GitHub UI:
🎪 trigger-start

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

## 🚀 Quick Start for Superset Contributors

### 1. As a Contributor (Using GitHub Labels)

**Create an ephemeral environment:**
1. Go to your PR in GitHub
2. Add label: `🎪 trigger-start`
3. Watch the magic happen - labels will update automatically
4. When you see `🎪 🚦 {sha} running`, your environment is ready!
5. Get URL from `🎪 🌐 {sha} {ip}` → `http://{ip}:8080`

**Configure your environment:**
```bash
# Add these labels to enable Superset feature flags:
🎪 conf-enable-ALERTS              # Enable alerts feature
🎪 conf-enable-DASHBOARD_RBAC      # Enable dashboard RBAC
🎪 conf-disable-SSH_TUNNELING      # Disable SSH tunneling
```

**Clean up when done:**
```bash
# Add this label:
🎪 trigger-stop
# All circus labels disappear, AWS resources cleaned up
```

### 2. As a Maintainer (Using CLI)

**Install the CLI:**
```bash
pip install superset-showtime
export GITHUB_TOKEN=your_token
```

**Monitor all environments:**
```bash
showtime list                    # See all active environments
showtime status 1234            # Check specific PR environment
showtime labels                 # Learn the complete label system
```

**Test and debug:**
```bash
showtime start 1234 --dry-run-aws      # Test environment creation
showtime test-lifecycle 1234           # Full workflow simulation
```

## 🎪 Complete Label Reference

### 🎯 Trigger Labels (Add These to Your PR)

| Label | Action | Result |
|-------|---------|---------|
| `🎪 ⚡ showtime-trigger-start` | Create environment | Builds and deploys ephemeral environment with blue-green deployment |
| `🎪 🛑 showtime-trigger-stop` | Destroy environment | Cleans up AWS resources and removes all labels |
| `🎪 🔄 showtime-trigger-sync` | Update to latest commit | Zero-downtime rolling update |
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

## 🔧 Altering Feature Flags or Configuration

**Recommendation**: Modify feature flags directly in your PR code instead of using labels.

**Why this approach is better**:
✅ **Creates new SHA**: Testable, traceable, reviewable  
✅ **Infinitely extensible**: Any configuration change possible  
✅ **Code-based**: Changes are explicit and permanent  
✅ **Git history**: Configuration changes are tracked  

**Example workflow**:
1. Modify `superset_config.py` with feature flag changes
2. Push commit → Creates new SHA (e.g., `def456a`)  
3. Add `🎪 ⚡ showtime-trigger-start` → Deploys with new config
4. Test environment reflects your exact code changes

This keeps complexity in code where it belongs, not in label management!

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
   🎪 abc123f 🌐 52-1-2-3      ← Visit http://52.1.2.3:8080
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

### How GitHub Actions Work

The new system replaces complex GHA scripts with simple ones:

```yaml
# .github/workflows/circus.yml (replaces current ephemeral-env.yml)
on:
  pull_request_target:
    types: [labeled, unlabeled, synchronize]

jobs:
  circus-handler:
    if: contains(github.event.label.name, '🎪')
    steps:
      - name: Install Showtime from PyPI
        run: pip install superset-showtime

      - name: Process circus triggers
        run: python -m showtime handle-trigger ${{ github.event.pull_request.number }}
```

**Security benefits:**
- **Always runs trusted code** (from PyPI, not PR code)
- **Simple workflow logic** (just install CLI and run)
- **Same permission model** as current system

## 🛠️ Installation & Setup

### For Contributors (GitHub Labels Only)
No installation needed! Just use the GitHub label system.

### For Maintainers (CLI Access)

**Install CLI:**
```bash
pip install superset-showtime
export GITHUB_TOKEN=your_personal_access_token
```

**Test CLI:**
```bash
showtime list                    # See all active environments
showtime status 1234            # Check specific environment
showtime labels                 # Learn complete label system
```

### For Repository Setup (One-Time)

**1. Install GitHub workflows:**
Copy `.github/workflows/circus.yml` and `.github/workflows/circus-cleanup.yml` to your Superset repo.

**2. Add repository secrets:**
- `AWS_ACCESS_KEY_ID` (already exists)
- `AWS_SECRET_ACCESS_KEY` (already exists)
- `GITHUB_TOKEN` (already exists)

**3. Replace old workflows:**
Remove or disable the current `ephemeral-env.yml` and `ephemeral-env-pr-close.yml`.

## 📊 CLI Commands Reference

### Core Commands
```bash
showtime start 1234                    # Create environment (latest SHA)
showtime start 1234 --sha abc123f     # Create environment (specific SHA)
showtime start 1234 --force           # Force re-deployment
showtime stop 1234                    # Delete environment
showtime status 1234                  # Show environment status
showtime list                         # List all environments with clickable links
showtime sync 1234                    # Intelligent sync to desired state
showtime cleanup --respect-ttl        # Clean up based on individual TTL labels
```

### Testing & Development
```bash
showtime start 1234 --dry-run-aws          # Mock AWS, real GitHub labels
showtime test-lifecycle 1234 --real-github # Full workflow simulation
showtime handle-trigger 1234 --dry-run-aws # Simulate GitHub Actions
```

### Advanced Operations
```bash
showtime cleanup --older-than 48h          # Clean up old environments
showtime list --status running --user maxime  # Filter environments
```

## 🎪 Benefits for Superset

### For Contributors
- **🎯 Simple workflow** - Just add/remove GitHub labels
- **👀 Visual feedback** - See environment status in PR labels
- **⚡ Automatic updates** - New commits update environments automatically
- **🔧 Live configuration** - Enable/disable feature flags without rebuilding

### For Maintainers
- **📊 Complete visibility** - `showtime list` shows all environments
- **🧹 Easy cleanup** - Automatic expired environment cleanup
- **🔍 Better debugging** - Clear state in labels, comprehensive CLI
- **💰 Cost savings** - No duplicate environments, proper cleanup

### For Operations
- **📝 Simpler workflows** - Replace complex GHA scripts with simple CLI calls
- **🔒 Same security model** - No new permissions needed
- **🎯 Deterministic** - Predictable AWS resource naming
- **🚨 Monitoring ready** - 48h maximum lifetime, scheduled cleanup

## 🏗️ Architecture

### State Management
All state lives in **GitHub labels** - no external databases needed:
- **Trigger labels** (`🎪 trigger-*`) - Commands that get processed and removed
- **State labels** (`🎪 🚦 *`) - Current environment status, managed by CLI

### AWS Resources
Deterministic naming enables reliable cleanup:
- **ECS Service:** `pr-{pr_number}-{sha}` (e.g., `pr-1234-abc123f`)
- **ECR Image:** `pr-{pr_number}-{sha}-ci` (e.g., `pr-1234-abc123f-ci`)

### Rolling Updates
Zero-downtime updates by running multiple environments:
1. Keep old environment serving traffic
2. Build new environment in parallel
3. Switch traffic when new environment is healthy
4. Clean up old environment

## 🤝 Contributing

### Testing Your Changes

**Test with real PRs safely:**
```bash
# Test label management without AWS costs:
showtime start YOUR_PR_NUMBER --dry-run-aws --aws-sleep 10

# Test full lifecycle:
showtime test-lifecycle YOUR_PR_NUMBER --real-github
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
