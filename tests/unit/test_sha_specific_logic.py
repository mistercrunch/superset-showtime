"""
TDD tests for SHA-specific build logic

Tests the correct behavior when multiple environments exist per PR.
The system should make decisions based on the target SHA's state, 
not the overall PR state.
"""

from showtime.core.pull_request import PullRequest


def test_target_sha_does_not_exist_should_build():
    """When target SHA doesn't exist, should create environment"""
    # PR with existing environments for different SHAs
    pr = PullRequest(1234, [
        "🎪 abc123f 🚦 running",    # Different SHA running
        "🎪 🎯 abc123f",           # Active pointer to different SHA
        "🎪 def456a 🚦 failed",    # Different SHA failed
        "🎪 xyz789b 🚦 building",  # Different SHA building
    ])
    
    # Target a completely new SHA
    action = pr._determine_action("new567c")
    
    # Should create environment for new SHA
    assert action == "create_environment"


def test_target_sha_failed_should_rebuild():
    """When target SHA is in failed state, should rebuild"""
    pr = PullRequest(1234, [
        "🎪 abc123f 🚦 running",   # Other SHA running
        "🎪 🎯 abc123f",          # Active pointer
        "🎪 def456a 🚦 failed",   # Target SHA failed
        "🎪 🎯 def456a",          # Target has pointer (failed but pointed to)
    ])
    
    # Target the failed SHA
    action = pr._determine_action("def456a")
    
    # Should rebuild failed environment
    assert action == "create_environment"


def test_target_sha_building_should_wait():
    """When target SHA is already building, should not start another build"""
    pr = PullRequest(1234, [
        "🎪 abc123f 🚦 running",    # Other SHA running
        "🎪 🎯 abc123f",           # Active pointer
        "🎪 def456a 🚦 building",  # Target SHA building
        "🎪 🏗️ def456a",          # Building pointer
    ])
    
    # Target the building SHA
    action = pr._determine_action("def456a")
    
    # Should not start duplicate build
    assert action == "no_action"


def test_target_sha_running_should_not_rebuild():
    """When target SHA is already running, should not rebuild"""
    pr = PullRequest(1234, [
        "🎪 abc123f 🚦 running",   # Target SHA running
        "🎪 🎯 abc123f",          # Active pointer
        "🎪 def456a 🚦 building", # Other SHA building
    ])
    
    # Target the running SHA (same as current)
    action = pr._determine_action("abc123f")
    
    # Should not rebuild running environment
    assert action == "no_action"


def test_target_sha_running_with_trigger_should_rebuild():
    """When target SHA is running but has start trigger, should rebuild"""
    pr = PullRequest(1234, [
        "🎪 ⚡ showtime-trigger-start",  # Explicit start trigger
        "🎪 abc123f 🚦 running",        # Target SHA running
        "🎪 🎯 abc123f",               # Active pointer
    ])
    
    # Target the running SHA with explicit trigger
    action = pr._determine_action("abc123f")
    
    # Should rebuild due to explicit trigger (force rebuild)
    assert action == "create_environment"


def test_atomic_claim_sha_specific_validation():
    """Atomic claim should validate based on target SHA state, not any environment"""
    pr = PullRequest(1234, [
        "🎪 abc123f 🚦 running",   # Other SHA running
        "🎪 🎯 abc123f",          # Active pointer
        "🎪 def456a 🚦 building", # Other SHA building
    ])
    
    # Should allow claim for new SHA even though other SHAs are active
    can_claim_new = pr._atomic_claim("new567c", "create_environment", dry_run=True)
    assert can_claim_new is True
    
    # Should block claim for SHA that's already building
    can_claim_building = pr._atomic_claim("def456a", "create_environment", dry_run=True) 
    assert can_claim_building is False
    
    # Should allow claim for running SHA with rolling update
    can_claim_rolling = pr._atomic_claim("abc123f", "rolling_update", dry_run=True)
    assert can_claim_rolling is True


def test_multiple_environments_pointer_management():
    """Test proper pointer management with multiple environments"""
    # Scenario: Multiple environments exist, need to identify which is which
    pr = PullRequest(1234, [
        "🎪 abc123f 🚦 running",   # Old active
        "🎪 🎯 abc123f",          # Active pointer (should be only one)
        "🎪 def456a 🚦 running",   # Orphaned (no pointer)
        "🎪 xyz789b 🚦 failed",   # Failed (no pointer)
    ])
    
    # Should have 3 total shows
    assert len(pr.shows) == 3
    
    # Should have 1 active show (with pointer)
    assert pr.current_show is not None
    assert pr.current_show.sha == "abc123f"
    
    # Should have no building show
    assert pr.building_show is None
    
    # Other shows should be findable but not pointed to
    def456a_show = pr.get_show_by_sha("def456a")
    assert def456a_show is not None
    assert def456a_show.status == "running"
    
    xyz789b_show = pr.get_show_by_sha("xyz789b") 
    assert xyz789b_show is not None
    assert xyz789b_show.status == "failed"


def test_rolling_update_should_clean_old_pointers():
    """Rolling update should remove old active pointer and add new one"""
    # This test defines the expected behavior for pointer management
    # Implementation should ensure only 1 active pointer exists at a time
    pass  # Implementation test - will write after fixing the logic