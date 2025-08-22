"""
🎪 AWS interface for circus tent environment management

Replicates the AWS logic from current GitHub Actions workflows.
"""

import os
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import boto3


@dataclass
class AWSError(Exception):
    """AWS operation error"""

    message: str
    operation: str
    resource: Optional[str] = None


@dataclass
class EnvironmentResult:
    """Result of AWS environment operation"""

    success: bool
    ip: Optional[str] = None
    service_name: Optional[str] = None
    error: Optional[str] = None


class AWSInterface:
    """AWS ECS/ECR client replicating current GHA logic"""

    def __init__(self, region: str = None, cluster: str = None, repository: str = None):
        self.region = region or os.getenv("AWS_REGION", "us-west-2")
        self.cluster = cluster or os.getenv("ECS_CLUSTER", "superset-ci")
        self.repository = repository or os.getenv("ECR_REPOSITORY", "superset-ci")

        # AWS clients
        self.ecs_client = boto3.client("ecs", region_name=self.region)
        self.ecr_client = boto3.client("ecr", region_name=self.region)
        self.ec2_client = boto3.client("ec2", region_name=self.region)

        # Network configuration (from current GHA)
        self.subnets = ["subnet-0e15a5034b4121710", "subnet-0e8efef4a72224974"]
        self.security_group = "sg-092ff3a6ae0574d91"

    def create_environment(
        self, pr_number: int, sha: str, github_user: str = "unknown"
    ) -> EnvironmentResult:
        """
        Create ephemeral environment - replicates GHA logic

        Steps:
        1. Build Docker image with supersetbot
        2. Push to ECR with PR+SHA tag
        3. Create ECS service
        4. Wait for deployment
        5. Get public IP
        """
        service_name = f"pr-{pr_number}-{sha[:7]}"
        image_tag = f"pr-{pr_number}-{sha[:7]}-ci"

        try:
            # Step 1: Build Docker image (replicate supersetbot logic)
            success = self._build_docker_image(sha, image_tag)
            if not success:
                return EnvironmentResult(success=False, error="Docker build failed")

            # Step 2: Push to ECR
            success = self._push_to_ecr(image_tag)
            if not success:
                return EnvironmentResult(success=False, error="ECR push failed")

            # Step 3: Check if service already exists
            if self._service_exists(service_name):
                return EnvironmentResult(
                    success=False, error=f"Service {service_name} already exists"
                )

            # Step 4: Create ECS service
            success = self._create_ecs_service(service_name, image_tag, pr_number, github_user)
            if not success:
                return EnvironmentResult(success=False, error="ECS service creation failed")

            # Step 5: Wait for deployment and get IP
            ip = self._wait_for_deployment_and_get_ip(service_name)
            if not ip:
                return EnvironmentResult(success=False, error="Failed to get environment IP")

            return EnvironmentResult(success=True, ip=ip, service_name=service_name)

        except Exception as e:
            return EnvironmentResult(success=False, error=str(e))

    def delete_environment(self, service_name: str, pr_number: int) -> bool:
        """
        Delete ephemeral environment - replicates cleanup GHA logic

        Steps:
        1. Check if ECS service exists and is active
        2. Delete ECS service with --force
        3. Delete ECR image tag
        """
        try:
            # Step 1: Check if service exists and is active
            if not self._service_exists(service_name):
                return True  # Already deleted

            # Step 2: Delete ECS service (force delete)
            self.ecs_client.delete_service(cluster=self.cluster, service=service_name, force=True)

            # Step 3: Delete ECR image tag
            # Extract SHA from service name: pr-1234-abc123f → abc123f
            sha = service_name.split("-")[-1]
            image_tag = f"pr-{pr_number}-{sha}"

            try:
                self.ecr_client.batch_delete_image(
                    repositoryName=self.repository, imageIds=[{"imageTag": image_tag}]
                )
            except self.ecr_client.exceptions.ImageNotFoundException:
                pass  # Image already deleted

            return True

        except Exception as e:
            raise AWSError(message=str(e), operation="delete_environment", resource=service_name)

    def get_environment_ip(self, service_name: str) -> Optional[str]:
        """
        Get public IP for environment - replicates GHA IP discovery logic

        Steps:
        1. List tasks for service
        2. Describe task to get network interface
        3. Get public IP from network interface
        """
        try:
            # Step 1: List tasks
            tasks_response = self.ecs_client.list_tasks(
                cluster=self.cluster, serviceName=service_name
            )

            if not tasks_response["taskArns"]:
                return None

            task_arn = tasks_response["taskArns"][0]

            # Step 2: Describe task to get network interface
            task_response = self.ecs_client.describe_tasks(cluster=self.cluster, tasks=[task_arn])

            if not task_response["tasks"]:
                return None

            task = task_response["tasks"][0]

            # Find network interface ID
            eni_id = None
            for attachment in task.get("attachments", []):
                for detail in attachment.get("details", []):
                    if detail["name"] == "networkInterfaceId":
                        eni_id = detail["value"]
                        break
                if eni_id:
                    break

            if not eni_id:
                return None

            # Step 3: Get public IP from network interface
            eni_response = self.ec2_client.describe_network_interfaces(NetworkInterfaceIds=[eni_id])

            if not eni_response["NetworkInterfaces"]:
                return None

            eni = eni_response["NetworkInterfaces"][0]
            return eni.get("Association", {}).get("PublicIp")

        except Exception:
            return None

    def get_environment_status(self, service_name: str) -> str:
        """Get environment status from AWS"""
        try:
            response = self.ecs_client.describe_services(
                cluster=self.cluster, services=[service_name]
            )

            if not response["services"]:
                return "not_found"

            service = response["services"][0]
            status = service["status"]

            if status == "ACTIVE":
                # Check if tasks are running
                running_count = service["runningCount"]
                desired_count = service["desiredCount"]

                if running_count == desired_count and running_count > 0:
                    return "running"
                else:
                    return "building"
            else:
                return "failed"

        except Exception:
            return "unknown"

    def _build_docker_image(self, sha: str, image_tag: str) -> bool:
        """Build Docker image using supersetbot (replicate GHA logic)"""
        try:
            # Replicate: supersetbot docker --push --load --preset ci --platform linux/amd64
            cmd = [
                "supersetbot",
                "docker",
                "--push",
                "--load",
                "--preset",
                "ci",
                "--platform",
                "linux/amd64",
                "--context-ref",
                sha,
                "--extra-flags",
                "--build-arg INCLUDE_CHROMIUM=false",
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.returncode == 0

        except FileNotFoundError:
            # supersetbot not available - this is expected in CLI usage
            return False
        except Exception:
            return False

    def _push_to_ecr(self, image_tag: str) -> bool:
        """Push image to ECR (replicate GHA logic)"""
        try:
            # Get ECR registry URL
            ecr_response = self.ecr_client.get_authorization_token()
            registry_url = ecr_response["authorizationData"][0]["proxyEndpoint"]
            registry_url = registry_url.replace("https://", "")

            # Tag and push image
            full_tag = f"{registry_url}/{self.repository}:{image_tag}"

            # Docker tag and push
            subprocess.run(["docker", "tag", f"apache/superset:{image_tag}", full_tag])
            result = subprocess.run(["docker", "push", full_tag], capture_output=True)

            return result.returncode == 0

        except Exception:
            return False

    def _service_exists(self, service_name: str) -> bool:
        """Check if ECS service exists and is active"""
        try:
            response = self.ecs_client.describe_services(
                cluster=self.cluster, services=[service_name]
            )

            for service in response["services"]:
                if service["status"] == "ACTIVE":
                    return True

            return False

        except Exception:
            return False

    def _create_ecs_service(
        self, service_name: str, image_tag: str, pr_number: int, github_user: str
    ) -> bool:
        """Create ECS service (replicate GHA logic)"""
        try:
            # Get ECR registry for full image URL
            ecr_response = self.ecr_client.get_authorization_token()
            registry_url = ecr_response["authorizationData"][0]["proxyEndpoint"]
            registry_url = registry_url.replace("https://", "")

            full_image_url = f"{registry_url}/{self.repository}:{image_tag}"

            # Create ECS service (replicate exact GHA parameters)
            self.ecs_client.create_service(
                cluster=self.cluster,
                serviceName=service_name,
                taskDefinition=self.cluster,  # Uses same name as cluster
                launchType="FARGATE",
                desiredCount=1,
                platformVersion="LATEST",
                networkConfiguration={
                    "awsvpcConfiguration": {
                        "subnets": self.subnets,
                        "securityGroups": [self.security_group],
                        "assignPublicIp": "ENABLED",
                    }
                },
                tags=[
                    {"key": "pr", "value": str(pr_number)},
                    {"key": "github_user", "value": github_user},
                    {"key": "circus_sha", "value": service_name.split("-")[-1]},
                    {"key": "circus_created", "value": str(int(time.time()))},
                ],
            )

            return True

        except Exception as e:
            print(f"ECS service creation failed: {e}")
            return False

    def _wait_for_deployment_and_get_ip(
        self, service_name: str, timeout_minutes: int = 10
    ) -> Optional[str]:
        """Wait for ECS deployment to complete and get IP"""
        try:
            # Wait for service stability (replicate GHA wait-for-service-stability)
            waiter = self.ecs_client.get_waiter("services_stable")
            waiter.wait(
                cluster=self.cluster,
                services=[service_name],
                WaiterConfig={"maxAttempts": timeout_minutes * 2},  # 30s intervals
            )

            # Get IP after deployment is stable
            return self.get_environment_ip(service_name)

        except Exception:
            return None

    def list_circus_environments(self) -> List[Dict[str, Any]]:
        """List all environments with circus tags"""
        try:
            # List all services in cluster
            services_response = self.ecs_client.list_services(cluster=self.cluster)

            circus_services = []
            for service_arn in services_response["serviceArns"]:
                service_name = service_arn.split("/")[-1]

                # Check if it's a circus service (pr-{number}-{sha} pattern)
                if service_name.startswith("pr-") and len(service_name.split("-")) >= 3:
                    # Get service details and tags
                    service_response = self.ecs_client.describe_services(
                        cluster=self.cluster, services=[service_name]
                    )

                    if service_response["services"]:
                        service = service_response["services"][0]
                        circus_services.append(
                            {
                                "service_name": service_name,
                                "status": service["status"],
                                "running_count": service["runningCount"],
                                "desired_count": service["desiredCount"],
                                "created_at": service["createdAt"],
                                "ip": self.get_environment_ip(service_name),
                            }
                        )

            return circus_services

        except Exception:
            return []

    def cleanup_orphaned_environments(self, max_age_hours: int = 48) -> List[str]:
        """Clean up environments older than max_age_hours"""
        import time

        try:
            orphaned = []
            circus_services = self.list_circus_environments()

            current_time = time.time()
            max_age_seconds = max_age_hours * 3600

            for service in circus_services:
                # Calculate age
                created_timestamp = service["created_at"].timestamp()
                age_seconds = current_time - created_timestamp

                if age_seconds > max_age_seconds:
                    service_name = service["service_name"]

                    # Extract PR number for cleanup
                    pr_number = int(service_name.split("-")[1])

                    # Delete the service
                    if self.delete_environment(service_name, pr_number):
                        orphaned.append(service_name)

            return orphaned

        except Exception as e:
            raise AWSError(message=str(e), operation="cleanup_orphaned_environments")

    def update_feature_flags(self, service_name: str, feature_flags: Dict[str, bool]) -> bool:
        """Update feature flags in running environment"""
        try:
            # Get current task definition
            service_response = self.ecs_client.describe_services(
                cluster=self.cluster, services=[service_name]
            )

            if not service_response["services"]:
                return False

            task_def_arn = service_response["services"][0]["taskDefinition"]

            # Get task definition details
            task_def_response = self.ecs_client.describe_task_definition(
                taskDefinition=task_def_arn
            )

            task_def = task_def_response["taskDefinition"]

            # Update environment variables
            container_def = task_def["containerDefinitions"][0]
            env_vars = container_def.get("environment", [])

            # Update feature flags
            for flag_name, enabled in feature_flags.items():
                # Remove existing flag
                env_vars = [e for e in env_vars if e["name"] != flag_name]
                # Add updated flag
                env_vars.append({"name": flag_name, "value": "True" if enabled else "False"})

            container_def["environment"] = env_vars

            # Register new task definition
            new_task_def = self.ecs_client.register_task_definition(
                family=task_def["family"],
                containerDefinitions=task_def["containerDefinitions"],
                requiresCompatibilities=task_def["requiresCompatibilities"],
                networkMode=task_def["networkMode"],
                cpu=task_def["cpu"],
                memory=task_def["memory"],
                executionRoleArn=task_def["executionRoleArn"],
                taskRoleArn=task_def.get("taskRoleArn"),
            )

            # Update service to use new task definition
            self.ecs_client.update_service(
                cluster=self.cluster,
                service=service_name,
                taskDefinition=new_task_def["taskDefinition"]["taskDefinitionArn"],
            )

            return True

        except Exception as e:
            print(f"Feature flag update failed: {e}")
            return False
