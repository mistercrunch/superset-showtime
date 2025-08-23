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

## 📊 For Maintainers (CLI Operations)

> **Note**: CLI is mainly for debugging or developing Showtime itself. Primary interface is GitHub labels above.

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
showtime start 1234 --dry-run-aws      # Test without AWS costs
showtime test-lifecycle 1234           # Full workflow simulation
```

> **Dependency**: This CLI coordinates with Superset's existing GitHub Actions build infrastructure. It orchestrates environments but relies on Superset's build workflows for container creation.

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

Showtime is designed to be called by Superset's GitHub Actions workflows:

```yaml
# .github/workflows/showtime.yml - Integrates with Superset's existing build workflows
on:
  pull_request_target:
    types: [labeled, unlabeled, synchronize]

jobs:
  showtime-handler:
    if: contains(github.event.label.name, '🎪')
    steps:
      - name: Install Showtime from PyPI
        run: pip install superset-showtime

      - name: Process circus triggers
        run: python -m showtime handle-trigger ${{ github.event.pull_request.number }}
```

**Integration approach:**
- **Coordinates with Superset builds** - Uses existing container build workflows
- **Runs trusted code** (from PyPI, not PR code)
- **Simple orchestration logic** (install CLI and run commands)
- **Leverages existing infrastructure** - Same AWS resources and permissions

## 🛠️ Installation & Setup

### For Contributors (GitHub Labels Only)
No installation needed! Just use GitHub labels to trigger environments.

### For Maintainers (Manual CLI Operations)

**Install CLI for debugging/testing:**
```bash
pip install superset-showtime
export GITHUB_TOKEN=your_personal_access_token
```

**Manual operations:**
```bash
showtime list                    # Monitor all active environments
showtime status 1234            # Debug specific environment
showtime labels                 # Reference complete label system
```

### For Repository Integration (GitHub Actions)

**1. Install GitHub workflows:**
Copy `workflows-reference/showtime-trigger.yml` and `workflows-reference/showtime-cleanup.yml` to Superset's `.github/workflows/`.

**2. Configure secrets (already exist in Superset):**
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `GITHUB_TOKEN`

**3. Dependencies:**
Showtime coordinates with Superset's existing build infrastructure - no additional setup needed.

## 📊 CLI Reference (For Development/Debugging)

> **Primary Interface**: Use GitHub labels in PR interface. CLI is mainly for maintainers debugging or developing Showtime itself.

### Debugging Commands
```bash
showtime list                         # Monitor all environments
showtime status 1234                  # Debug specific environment
showtime labels                       # Complete label reference
showtime test-lifecycle 1234          # Full workflow simulation
```

### Manual Operations (Advanced)
```bash
showtime start 1234                    # Manually create environment
showtime start 1234 --sha abc123f     # Create environment (specific SHA)
showtime stop 1234                    # Manually delete environment
showtime sync 1234                    # Force sync to desired state
showtime cleanup --respect-ttl        # Manual cleanup
```

### GitHub Actions Commands
```bash
showtime handle-trigger 1234          # Process trigger labels (called by GHA)
showtime cleanup --older-than 48h     # Scheduled cleanup (called by GHA)
```

## 🎪 Benefits for Superset

### For Contributors
- **🎯 Simple workflow** - Just add/remove GitHub labels
- **👀 Visual feedback** - See environment status in PR labels
- **⚡ Automatic updates** - New commits update environments automatically
- **🔧 Configuration testing** - Test config changes through code commits

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
