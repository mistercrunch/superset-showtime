"""
🚩 Tests for reconciling feature flags against a running environment.

Removed flags must be cleared, unrelated env vars kept, and an unchanged
flag set must not restart the container.
"""

from typing import Any, Dict, List
from unittest.mock import MagicMock

from showtime.core.aws import AWSInterface
from showtime.core.feature_flags import reconcile_env_vars


def _env(**pairs: str) -> List[Dict[str, str]]:
    return [{"name": k, "value": v} for k, v in pairs.items()]


def _as_dict(env: List[Dict[str, str]]) -> Dict[str, str]:
    return {e["name"]: e["value"] for e in env}


class TestReconcileEnvVars:
    """The reconcile decision itself - pure input/output, no AWS involved"""

    def test_removes_flag_no_longer_requested(self) -> None:
        result = reconcile_env_vars(
            _env(
                SUPERSET_FEATURE_EMBEDDED_SUPERSET="True", SUPERSET_FEATURE_DRILL_TO_DETAIL="True"
            ),
            {"SUPERSET_FEATURE_EMBEDDED_SUPERSET": True},
        )

        assert result is not None
        assert _as_dict(result) == {"SUPERSET_FEATURE_EMBEDDED_SUPERSET": "True"}

    def test_removes_all_flags_when_none_requested(self) -> None:
        result = reconcile_env_vars(
            _env(SUPERSET_PORT="8080", SUPERSET_FEATURE_EMBEDDED_SUPERSET="True"), {}
        )

        assert result is not None
        assert _as_dict(result) == {"SUPERSET_PORT": "8080"}

    def test_preserves_unrelated_env_vars(self) -> None:
        result = reconcile_env_vars(
            _env(SUPERSET_PORT="8080", SUPERSET_SECRET_KEY="shh"),
            {"SUPERSET_FEATURE_THUMBNAILS": True},
        )

        assert result is not None
        assert _as_dict(result) == {
            "SUPERSET_PORT": "8080",
            "SUPERSET_SECRET_KEY": "shh",
            "SUPERSET_FEATURE_THUMBNAILS": "True",
        }

    def test_disables_flag_set_to_false(self) -> None:
        result = reconcile_env_vars(
            _env(SUPERSET_FEATURE_DRILL_TO_DETAIL="True"),
            {"SUPERSET_FEATURE_DRILL_TO_DETAIL": False},
        )

        assert result is not None
        assert _as_dict(result) == {"SUPERSET_FEATURE_DRILL_TO_DETAIL": "False"}

    def test_identical_flags_need_no_change(self) -> None:
        result = reconcile_env_vars(
            _env(SUPERSET_PORT="8080", SUPERSET_FEATURE_EMBEDDED_SUPERSET="True"),
            {"SUPERSET_FEATURE_EMBEDDED_SUPERSET": True},
        )

        assert result is None

    def test_no_flags_deployed_and_none_requested_needs_no_change(self) -> None:
        assert reconcile_env_vars(_env(SUPERSET_PORT="8080"), {}) is None

    def test_flag_order_is_not_a_change(self) -> None:
        result = reconcile_env_vars(
            _env(SUPERSET_FEATURE_THUMBNAILS="True", SUPERSET_FEATURE_ALERT_REPORTS="True"),
            {"SUPERSET_FEATURE_ALERT_REPORTS": True, "SUPERSET_FEATURE_THUMBNAILS": True},
        )

        assert result is None

    def test_empty_container_env_gains_requested_flags(self) -> None:
        result = reconcile_env_vars([], {"SUPERSET_FEATURE_THUMBNAILS": True})

        assert result is not None
        assert _as_dict(result) == {"SUPERSET_FEATURE_THUMBNAILS": "True"}


def _ecs_client(env: List[Dict[str, str]]) -> MagicMock:
    """ECS client double serving a task definition with the given env vars."""
    client = MagicMock()
    client.describe_services.return_value = {
        "services": [{"taskDefinition": "arn:aws:ecs:::task-definition/pr-1-abc123f:1"}]
    }
    client.describe_task_definition.return_value = {
        "taskDefinition": {
            "family": "pr-1-abc123f",
            "containerDefinitions": [{"name": "superset", "environment": env}],
            "requiresCompatibilities": ["FARGATE"],
            "networkMode": "awsvpc",
            "cpu": "2048",
            "memory": "4096",
            "executionRoleArn": "arn:aws:iam::123:role/exec",
            "taskRoleArn": "arn:aws:iam::123:role/task",
        }
    }
    client.register_task_definition.return_value = {
        "taskDefinition": {"taskDefinitionArn": "arn:aws:ecs:::task-definition/pr-1-abc123f:2"}
    }
    return client


def _aws(client: MagicMock) -> AWSInterface:
    return AWSInterface(ecs_client=client, ecr_client=MagicMock(), ec2_client=MagicMock())


class TestUpdateFeatureFlagsDrivesECS:
    """The AWS glue: does a needed change reach ECS, and is a no-op truly silent?

    These use a client double because "we did not restart the container" is only
    observable as an absent API call.
    """

    def test_change_registers_new_task_definition_and_updates_service(self) -> None:
        client = _ecs_client(_env(SUPERSET_FEATURE_DRILL_TO_DETAIL="True"))

        result = _aws(client).update_feature_flags("pr-1-abc123f-service", {})

        assert result.success is True
        assert result.changed is True
        registered = client.register_task_definition.call_args.kwargs
        assert registered["containerDefinitions"][0]["environment"] == []
        client.update_service.assert_called_once()

    def test_no_change_leaves_the_environment_alone(self) -> None:
        client = _ecs_client(_env(SUPERSET_FEATURE_EMBEDDED_SUPERSET="True"))

        result = _aws(client).update_feature_flags(
            "pr-1-abc123f-service", {"SUPERSET_FEATURE_EMBEDDED_SUPERSET": True}
        )

        assert result.changed is False
        client.register_task_definition.assert_not_called()
        client.update_service.assert_not_called()

    def test_missing_service_reports_failure(self) -> None:
        client = MagicMock()
        client.describe_services.return_value = {"services": []}

        result = _aws(client).update_feature_flags("pr-1-abc123f-service", {})

        assert result.success is False
        assert result.error is not None

    def test_aws_exception_reports_failure(self) -> None:
        client = MagicMock()
        client.describe_services.side_effect = Exception("boom")

        result = _aws(client).update_feature_flags("pr-1-abc123f-service", {})

        assert result.success is False
        assert "boom" in str(result.error)


RUNNING_ENV_LABELS = [
    "🎪 abc123f 🚦 running",
    "🎪 🎯 abc123f",
    "🎪 abc123f 📅 2024-01-15T14-30",
]


class TestSyncReconcilesRunningEnvironment:
    """sync() must reconcile a running env, driven by real label parsing"""

    def _sync(self, labels: List[str], deployed_env: List[Dict[str, str]]) -> Any:
        """Run sync() against a running env with the given deployed env vars."""
        from unittest.mock import patch

        from showtime.core.pull_request import PullRequest

        client = _ecs_client(deployed_env)
        pr = PullRequest(1234, labels)

        with patch.object(pr, "_determine_action", return_value="no_action"):
            with patch.object(pr, "refresh_labels"):
                with patch("showtime.core.show.get_interfaces", return_value=(None, _aws(client))):
                    result = pr.sync(
                        "abc123f", dry_run_aws=False, dry_run_github=True, dry_run_docker=True
                    )

        return result, client

    def test_removing_the_last_flag_label_clears_it_from_the_container(self) -> None:
        result, client = self._sync(
            RUNNING_ENV_LABELS, _env(SUPERSET_FEATURE_EMBEDDED_SUPERSET="True")
        )

        registered = client.register_task_definition.call_args.kwargs
        assert registered["containerDefinitions"][0]["environment"] == []
        assert result.success is True
        assert result.action_taken == "update_feature_flags"

    def test_flag_label_reaches_the_container_as_an_env_var(self) -> None:
        result, client = self._sync(
            [*RUNNING_ENV_LABELS, "🎪 🚩 EMBEDDED_SUPERSET=true", "🎪 🚩 THUMBNAILS=false"], []
        )

        registered = client.register_task_definition.call_args.kwargs
        assert _as_dict(registered["containerDefinitions"][0]["environment"]) == {
            "SUPERSET_FEATURE_EMBEDDED_SUPERSET": "True",
            "SUPERSET_FEATURE_THUMBNAILS": "False",
        }
        assert result.action_taken == "update_feature_flags"

    def test_already_applied_flag_does_not_restart_the_container(self) -> None:
        result, client = self._sync(
            [*RUNNING_ENV_LABELS, "🎪 🚩 EMBEDDED_SUPERSET=true"],
            _env(SUPERSET_FEATURE_EMBEDDED_SUPERSET="True"),
        )

        client.register_task_definition.assert_not_called()
        client.update_service.assert_not_called()
        assert result.success is True
        assert result.action_taken == "no_action"

    def test_reconcile_failure_is_reported(self) -> None:
        from unittest.mock import patch

        from showtime.core.pull_request import PullRequest

        client = MagicMock()
        client.describe_services.side_effect = Exception("nope")
        pr = PullRequest(1234, [*RUNNING_ENV_LABELS, "🎪 🚩 EMBEDDED_SUPERSET=true"])

        with patch.object(pr, "_determine_action", return_value="no_action"):
            with patch.object(pr, "refresh_labels"):
                with patch("showtime.core.show.get_interfaces", return_value=(None, _aws(client))):
                    result = pr.sync(
                        "abc123f", dry_run_aws=False, dry_run_github=True, dry_run_docker=True
                    )

        assert result.success is False
        assert result.action_taken == "update_feature_flags"
        assert "nope" in str(result.error)


class TestAnalyzeSchedulesReconcile:
    """analyze() must ask for a sync so removals get a chance to apply"""

    def test_sync_needed_for_running_env_without_flags(self) -> None:
        from unittest.mock import Mock, patch

        from showtime.core.pull_request import PullRequest
        from showtime.core.sync_state import ActionNeeded

        with patch("showtime.core.pull_request.get_github") as mock_get_github:
            mock_github = Mock()
            mock_get_github.return_value = mock_github
            mock_github.get_labels.return_value = RUNNING_ENV_LABELS

            pr = PullRequest(1234, RUNNING_ENV_LABELS)
            result = pr.analyze("abc123f", "open")

        assert result.action_needed == ActionNeeded.NO_ACTION
        assert result.build_needed is False
        # Needed so a removed flag label can be reconciled away
        assert result.sync_needed is True

    def test_sync_not_needed_without_running_env(self) -> None:
        from unittest.mock import Mock, patch

        from showtime.core.pull_request import PullRequest

        labels = ["🎪 abc123f 🚦 building", "🎪 🏗️ abc123f"]

        with patch("showtime.core.pull_request.get_github") as mock_get_github:
            mock_github = Mock()
            mock_get_github.return_value = mock_github
            mock_github.get_labels.return_value = labels

            pr = PullRequest(1234, labels)
            result = pr.analyze("abc123f", "open")

        assert result.sync_needed is False
