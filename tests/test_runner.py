import importlib.util
import io
import json
import subprocess
import tempfile
import zipfile
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4


sys.path.insert(0, str(Path(__file__).parents[1] / "src" / "worker"))
import runner  # noqa: E402


credential_spec = importlib.util.spec_from_file_location(
    "github_app_credential",
    Path(__file__).parents[1] / "scripts" / "github-credential.py",
)
github_app_credential = importlib.util.module_from_spec(credential_spec)
assert credential_spec.loader is not None
credential_spec.loader.exec_module(github_app_credential)


VALID_SOURCE = '''import json

def handler(event, context):
    return {
        "statusCode": 200,
        "headers": {"content-type": "application/json"},
        "body": json.dumps({"hello": "world"}),
    }
'''


class RunnerTests(unittest.TestCase):
    def test_parse_exact_envelope(self):
        envelope = runner.parse_model_envelope(
            json.dumps({"description": "Greeting", "app_py": VALID_SOURCE})
        )
        self.assertEqual("Greeting", envelope["description"])

    def test_parse_rejects_extra_claims(self):
        with self.assertRaisesRegex(ValueError, "exactly"):
            runner.parse_model_envelope(
                json.dumps(
                    {"description": "Greeting", "app_py": VALID_SOURCE, "working": True}
                )
            )

    def test_validate_accepts_small_handler(self):
        result = runner.validate_source(VALID_SOURCE)
        self.assertTrue(result["passed"])
        self.assertEqual(64, len(result["source_sha256"]))

    def test_validate_rejects_aws_access(self):
        with self.assertRaisesRegex(ValueError, "import not permitted"):
            runner.validate_source("import boto3\ndef handler(event, context): return {}")

    def test_validate_rejects_dynamic_execution(self):
        with self.assertRaisesRegex(ValueError, "call not permitted"):
            runner.validate_source("def handler(event, context): return eval(event['body'])")

    def test_template_uses_minimal_execution_role(self):
        template = json.loads(
            runner.workload_template(
                code_bucket="bucket", code_key="source.zip", execution_role_arn="role-arn"
            )
        )
        function = template["Resources"]["Function"]["Properties"]
        self.assertEqual("role-arn", function["Role"])
        self.assertNotIn("Environment", function)

    def test_model_request_omits_unsupported_temperature(self):
        bedrock = Mock()
        bedrock.converse.return_value = {
            "output": {
                "message": {
                    "content": [
                        {
                            "text": json.dumps(
                                {"description": "Greeting", "app_py": VALID_SOURCE}
                            )
                        }
                    ]
                }
            }
        }
        runner.model_request(bedrock, model_id="terra", idea="Build a greeting")
        inference_config = bedrock.converse.call_args.kwargs["inferenceConfig"]
        self.assertEqual({"maxTokens": 5000}, inference_config)
        self.assertNotIn("temperature", inference_config)

    def test_working_finish_requires_post_change_verification(self):
        commands = [
            {"command_id": "cmd-001", "category": "change", "exit_code": 0},
            {"command_id": "cmd-002", "category": "verify", "exit_code": 0},
        ]
        finish = {
            "status": "WORKING",
            "summary": "Live service verified.",
            "changes_made": True,
            "evidence_command_ids": ["cmd-002"],
            "resources": ["example-resource"],
            "public_endpoints": ["https://example.com"],
            "published_revisions": [],
            "deployment_claims": [],
            "limitations": [],
        }
        self.assertEqual(finish, runner.Worker._validate_finish(finish, commands))

    def test_working_finish_rejects_pre_change_evidence(self):
        commands = [
            {"command_id": "cmd-001", "category": "verify", "exit_code": 0},
            {"command_id": "cmd-002", "category": "change", "exit_code": 0},
        ]
        finish = {
            "status": "WORKING",
            "summary": "Unsupported claim.",
            "changes_made": True,
            "evidence_command_ids": ["cmd-001"],
            "resources": [],
            "public_endpoints": [],
            "published_revisions": [],
            "deployment_claims": [],
            "limitations": [],
        }
        with self.assertRaisesRegex(ValueError, "after the last change"):
            runner.Worker._validate_finish(finish, commands)

    def test_working_finish_rejects_failed_evidence_command(self):
        commands = [{"command_id": "cmd-001", "category": "verify", "exit_code": 1}]
        finish = {
            "status": "WORKING",
            "summary": "False success.",
            "changes_made": False,
            "evidence_command_ids": ["cmd-001"],
            "resources": [],
            "public_endpoints": [],
            "published_revisions": [],
            "deployment_claims": [],
            "limitations": [],
        }
        with self.assertRaisesRegex(ValueError, "must have succeeded"):
            runner.Worker._validate_finish(finish, commands)

    def test_working_rejects_failed_final_change_even_after_successful_verification(self):
        commands = [
            {"command_id": "cmd-001", "command": "git commit -am update", "purpose": "Commit", "category": "change", "exit_code": 0},
            {"command_id": "cmd-002", "command": "git push origin HEAD:main", "purpose": "Push to main", "category": "change", "exit_code": 128},
            {"command_id": "cmd-003", "command": "python3 -m unittest", "purpose": "Run tests", "category": "verify", "exit_code": 0},
        ]
        finish = {
            "status": "WORKING", "summary": "Locally committed but push failed.",
            "changes_made": True, "evidence_command_ids": ["cmd-003"],
            "resources": [], "public_endpoints": [], "published_revisions": [],
            "deployment_claims": [],
            "limitations": ["push failed"],
        }
        with self.assertRaisesRegex(ValueError, "final change command failed"):
            runner.Worker._validate_finish(finish, commands, "Commit and push to main")

    def test_working_requires_published_revision_when_objective_requires_push(self):
        commands = [
            {"command_id": "cmd-001", "command": "git commit -am update", "purpose": "Commit", "category": "change", "exit_code": 0},
            {"command_id": "cmd-002", "command": "python3 -m unittest", "purpose": "Run tests", "category": "verify", "exit_code": 0},
        ]
        finish = {
            "status": "WORKING", "summary": "Done.", "changes_made": True,
            "evidence_command_ids": ["cmd-002"], "resources": [],
            "public_endpoints": [], "published_revisions": [], "deployment_claims": [], "limitations": [],
        }
        with self.assertRaisesRegex(ValueError, "published revisions"):
            runner.Worker._validate_finish(finish, commands, "Push the change to main")

    def test_working_rejects_failed_git_dash_c_push_even_after_later_change(self):
        commands = [
            {"command_id": "cmd-001", "command": "git commit -am update", "purpose": "Commit", "category": "change", "exit_code": 0},
            {"command_id": "cmd-002", "command": "git -C /tmp/igor push origin HEAD:main", "purpose": "Push", "category": "change", "exit_code": 128},
            {"command_id": "cmd-003", "command": "touch /tmp/report", "purpose": "Write report", "category": "change", "exit_code": 0},
            {"command_id": "cmd-004", "command": "python3 -m unittest", "purpose": "Verify", "category": "verify", "exit_code": 0},
        ]
        finish = {
            "status": "WORKING", "summary": "Changes published.",
            "changes_made": True, "evidence_command_ids": ["cmd-004"],
            "resources": ["commit"], "public_endpoints": [],
            "published_revisions": [], "deployment_claims": [], "limitations": [],
        }
        with self.assertRaisesRegex(ValueError, "final publication"):
            runner.Worker._validate_finish(finish, commands, "Implement changes")

    def test_published_revision_is_checked_against_remote_branch(self):
        completed = Mock(returncode=0, stdout="a" * 40 + "\trefs/heads/main\n", stderr="")
        revision = {
            "repository": "https://github.com/ourlovelysystem/lovely-system-igor.git",
            "branch": "main",
            "commit": "a" * 40,
        }
        with patch.object(runner.subprocess, "run", return_value=completed) as run:
            result = runner.Worker.verify_published_revision(revision)
        self.assertTrue(result["passed"])
        self.assertEqual("independent_git_remote_ref", result["check"])
        self.assertEqual("git", run.call_args.args[0][0])

    def test_working_rejects_non_full_published_commit_before_remote_check(self):
        commands = [
            {"command_id": "cmd-001", "command": "git commit -am update", "purpose": "Commit", "category": "change", "exit_code": 0},
            {"command_id": "cmd-002", "command": "git push origin main", "purpose": "Push", "category": "change", "exit_code": 0},
            {"command_id": "cmd-003", "command": "git ls-remote origin refs/heads/main", "purpose": "Verify remote", "category": "verify", "exit_code": 0},
        ]
        finish = {
            "status": "WORKING", "summary": "Published.", "changes_made": True,
            "evidence_command_ids": ["cmd-003"], "resources": [], "public_endpoints": [],
            "published_revisions": [{"repository": "https://github.com/ourlovelysystem/lovely-system-igor.git", "branch": "main", "commit": "abc123"}],
            "deployment_claims": [], "limitations": [],
        }
        with self.assertRaisesRegex(ValueError, "full 40-character SHA"):
            runner.Worker._validate_finish(finish, commands, "Push the change to main")

    def test_published_revision_rejects_remote_branch_mismatch(self):
        completed = Mock(returncode=0, stdout="b" * 40 + "\trefs/heads/main\n", stderr="")
        revision = {
            "repository": "https://github.com/ourlovelysystem/lovely-system-igor.git",
            "branch": "main",
            "commit": "a" * 40,
        }
        with patch.object(runner.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(RuntimeError, "points to"):
                runner.Worker.verify_published_revision(revision)

    def test_successful_aws_deploy_requires_independent_deployment_claim(self):
        commands = [
            {"command_id": "cmd-001", "command": "sam deploy", "purpose": "Deploy stack", "category": "change", "exit_code": 0},
            {"command_id": "cmd-002", "command": "aws cloudformation describe-stacks", "purpose": "Verify stack", "category": "verify", "exit_code": 0},
        ]
        finish = {
            "status": "WORKING", "summary": "Stack deployed.", "changes_made": True,
            "evidence_command_ids": ["cmd-002"], "resources": ["stack"],
            "public_endpoints": [], "published_revisions": [], "deployment_claims": [], "limitations": [],
        }
        with self.assertRaisesRegex(ValueError, "deployment claims"):
            runner.Worker._validate_finish(finish, commands, "Deploy the stack to AWS")

    def test_template_grants_unbounded_aws_administrator_access(self):
        template = (Path(__file__).parents[1] / "template.yaml").read_text()
        self.assertEqual(2, template.count("arn:aws:iam::aws:policy/AdministratorAccess"))
        self.assertNotIn("arn:aws:iam::aws:policy/PowerUserAccess", template)
        self.assertNotIn("Effect: Deny", template)
        self.assertIn("WORKLOAD_ROLE_ARN", template)
        self.assertIn("CONVERSATIONS_TABLE", template)

    def test_template_supports_github_token(self):
        template = (Path(__file__).parents[1] / "template.yaml").read_text()
        self.assertIn("GitHubTokenSecretName", template)
        self.assertIn("GITHUB_TOKEN_SECRET_NAME", template)
        self.assertIn("github-credential.py configure", template)

    def test_template_supports_private_large_attachments(self):
        template = (Path(__file__).parents[1] / "template.yaml").read_text()
        self.assertIn("AbortIncompleteMultipartUpload", template)
        self.assertIn("POST /conversations/{conversation_id}/attachments", template)
        self.assertIn(
            "POST /conversations/{conversation_id}/attachments/{attachment_id}/part-urls",
            template,
        )
        self.assertIn(
            "DELETE /conversations/{conversation_id}/attachments/{attachment_id}",
            template,
        )
        self.assertIn("- DELETE", template)
        self.assertIn("ATTACHMENTS_BUCKET", template)
        self.assertIn("${EvidenceBucket.Arn}/attachments/*", template)

    def test_github_token_secret_must_be_nonempty(self):
        self.assertEqual(
            "github-token",
            github_app_credential._token_from_response({"SecretString": " github-token "}),
        )
        with self.assertRaisesRegex(RuntimeError, "empty"):
            github_app_credential._token_from_response({"SecretString": ""})

    def test_general_agent_executes_changes_and_records_evidence(self):
        table = Mock()
        conversations_table = Mock()
        s3 = Mock()
        bedrock = Mock()
        bedrock.converse.side_effect = [
            {
                "output": {
                    "message": {
                        "content": [
                            {
                                "toolUse": {
                                    "toolUseId": "tool-change",
                                    "name": "run_command",
                                    "input": {
                                        "command": "touch service",
                                        "purpose": "Create the service",
                                        "category": "change",
                                    },
                                }
                            }
                        ]
                    }
                }
            },
            {
                "output": {
                    "message": {
                        "content": [
                            {
                                "toolUse": {
                                    "toolUseId": "tool-verify",
                                    "name": "run_command",
                                    "input": {
                                        "command": "test -f service",
                                        "purpose": "Verify the service",
                                        "category": "verify",
                                    },
                                }
                            }
                        ]
                    }
                }
            },
            {
                "output": {
                    "message": {
                        "content": [
                            {
                                "toolUse": {
                                    "toolUseId": "tool-finish",
                                    "name": "finish_task",
                                    "input": {
                                        "status": "WORKING",
                                        "summary": "Service created and verified.",
                                        "changes_made": True,
                                        "evidence_command_ids": ["cmd-002"],
                                        "resources": ["service"],
                                        "public_endpoints": [],
                                        "published_revisions": [],
                                        "deployment_claims": [],
                                        "limitations": [],
                                    },
                                }
                            }
                        ]
                    }
                }
            },
        ]
        command_runner = Mock(
            return_value={"exit_code": 0, "stdout": "ok", "stderr": "", "duration_seconds": 0.1}
        )
        worker = runner.Worker(
            table=table,
            bedrock=bedrock,
            s3=s3,
            cloudformation=Mock(),
            evidence_bucket="evidence",
            execution_role_arn="legacy-role",
            cloudformation_role_arn="legacy-cfn-role",
            workload_role_arn="workload-role",
            workload_instance_profile="workload-profile",
            command_runner=command_runner,
            conversations_table=conversations_table,
        )
        job_id = uuid4().hex
        item = {
            "job_id": job_id,
            "task_type": "general_aws",
            "objective": "Create and verify a service",
            "idea": "Create and verify a service",
            "model_id": "terra",
            "conversation_id": "conversation-123",
        }
        evidence = {"job_id": job_id, "checks": []}

        result = worker.run_general(job_id, item, evidence)

        self.assertEqual("WORKING", result["status"])
        self.assertEqual(2, len(result["commands"]))
        self.assertEqual(3, bedrock.converse.call_count)
        self.assertEqual(2, s3.put_object.call_count)
        completion = conversations_table.put_item.call_args.kwargs["Item"]
        self.assertEqual("conversation-123", completion["conversation_id"])
        self.assertEqual("WORKING", completion["terminal_status"])
        self.assertIn("Service created and verified.", completion["content_json"])
        progress_updates = [
            call.kwargs["ExpressionAttributeValues"]
            for call in table.update_item.call_args_list
            if "ExpressionAttributeValues" in call.kwargs
        ]
        self.assertTrue(
            any(
                "progress_message" in str(values) or "Planning the next action" in str(values)
                for values in progress_updates
            )
        )

    def test_attachment_manifest_preserves_large_s3_object_location(self):
        manifest = runner.Worker.attachment_manifest(
            {
                "attachments": [
                    {
                        "filename": "huge.pdf",
                        "content_type": "application/pdf",
                        "size": 8 * 1024**3,
                        "s3_uri": "s3://igor/attachments/operator/chat/file/huge.pdf",
                    }
                ]
            }
        )
        self.assertIn("huge.pdf", manifest)
        self.assertIn("s3://igor/attachments/operator/chat/file/huge.pdf", manifest)
        self.assertIn("range requests", manifest)


if __name__ == "__main__":
    unittest.main()

class LiveWorkEventTests(unittest.TestCase):
    def test_event_text_redacts_credentials_and_command_activity_is_classified(self):
        text = runner.safe_event_text("publish token=ghp_abcdefghijklmnopqrstuvwxyz123456")
        self.assertNotIn("ghp_", text)
        self.assertIn("[REDACTED]", text)
        self.assertEqual("verification", runner.command_activity("python -m unittest", "verify"))
        self.assertEqual("publication", runner.command_activity("git push origin main", "change"))
        self.assertEqual("deployment", runner.command_activity("sam deploy", "change"))
        self.assertEqual("change", runner.command_activity("cat scripts/deploy.sh", "change"))
        self.assertEqual("change", runner.command_activity("printf 'git push' >> ENHANCEMENTS.md", "change"))
        self.assertEqual("publication", runner.command_activity("cd repo && git push origin main", "change"))
        self.assertEqual("deployment", runner.command_activity("./scripts/deploy.sh", "change"))

    def test_record_event_persists_safe_completed_event_with_exit_status(self):
        table = Mock()
        worker = runner.Worker(
            table=table, bedrock=Mock(), s3=Mock(), cloudformation=Mock(), evidence_bucket="bucket",
            execution_role_arn="role", cloudformation_role_arn="role",
        )
        worker.record_event("job-1", "command_completed", "Completed verification: token=secret", command_id="cmd-001", exit_code=0)
        values = table.update_item.call_args.kwargs["ExpressionAttributeValues"]
        event = values[":event"][-1]
        self.assertEqual("command_completed", event["type"])
        self.assertEqual(0, event["exit_code"])
        self.assertNotIn("secret", event["message"])

class DeliveryEvidenceRegressionTests(unittest.TestCase):
    REVISION = "a" * 40
    REPOSITORY = "https://github.com/ourlovelysystem/lovely-system-igor.git"

    def finish(self, **overrides):
        value = {
            "status": "WORKING", "summary": "Published and deployed.", "changes_made": True,
            "evidence_command_ids": ["cmd-003"], "resources": [], "public_endpoints": [],
            "published_revisions": [{"repository": self.REPOSITORY, "branch": "main", "commit": self.REVISION}],
            "deployment_claims": [{"stack": "igor-job-123456789012-live", "region": "us-east-1",
                "repository": self.REPOSITORY, "branch": "main", "source_revision": self.REVISION}],
            "limitations": [],
        }
        value.update(overrides)
        return value

    def commands(self, deploy_exit=0):
        return [
            {"command_id": "cmd-001", "command": "git push origin main", "purpose": "Publish", "category": "change", "exit_code": 0},
            {"command_id": "cmd-002", "command": "sam deploy", "purpose": "Deploy", "category": "change", "exit_code": deploy_exit},
            {"command_id": "cmd-003", "command": "aws cloudformation describe-stacks", "purpose": "Verify", "category": "verify", "exit_code": 0},
        ]

    def test_deployment_claim_without_readback_is_rejected_by_finish_validation(self):
        with self.assertRaisesRegex(ValueError, "deployment claims"):
            runner.Worker._validate_finish(
                self.finish(deployment_claims=[]), self.commands(), "Deploy the published revision"
            )

    def test_failed_deployment_cannot_produce_working(self):
        with self.assertRaisesRegex(ValueError, "final change command failed"):
            runner.Worker._validate_finish(self.finish(), self.commands(deploy_exit=1), "Deploy the published revision")

    def test_cloudformation_readback_requires_matching_source_revision(self):
        cloudformation = Mock()
        cloudformation.describe_stacks.return_value = {"Stacks": [{"Parameters": [
            {"ParameterKey": "SourceRevision", "ParameterValue": "b" * 40}
        ]}]}
        worker = runner.Worker(table=Mock(), bedrock=Mock(), s3=Mock(), cloudformation=cloudformation,
            evidence_bucket="bucket", execution_role_arn="role", cloudformation_role_arn="role")
        with self.assertRaisesRegex(RuntimeError, "SourceRevision"):
            worker.verify_deployment_claim(self.finish()["deployment_claims"][0], self.finish()["published_revisions"])

    def test_cloudformation_readback_is_persistable_structured_evidence(self):
        cloudformation = Mock()
        cloudformation.describe_stacks.return_value = {"Stacks": [{"Parameters": [
            {"ParameterKey": "SourceRevision", "ParameterValue": self.REVISION}
        ]}]}
        worker = runner.Worker(table=Mock(), bedrock=Mock(), s3=Mock(), cloudformation=cloudformation,
            evidence_bucket="bucket", execution_role_arn="role", cloudformation_role_arn="role")
        check = worker.verify_deployment_claim(self.finish()["deployment_claims"][0], self.finish()["published_revisions"])
        self.assertTrue(check["passed"])
        self.assertEqual(self.REVISION, check["deployed_source_revision"])

    def test_terminal_message_includes_full_published_and_deployed_revisions(self):
        conversations = Mock()
        worker = runner.Worker(table=Mock(), bedrock=Mock(), s3=Mock(), cloudformation=Mock(), evidence_bucket="bucket",
            execution_role_arn="role", cloudformation_role_arn="role", conversations_table=conversations)
        worker.publish_completion(item={"conversation_id": "conversation"}, job_id="job", status="WORKING",
            summary="Done", evidence_uri="s3://bucket/evidence.json", finished_at="2026-01-01T00:00:00+00:00",
            published_revisions=self.finish()["published_revisions"], deployment_claims=self.finish()["deployment_claims"])
        text = conversations.put_item.call_args.kwargs["Item"]["content_json"]
        self.assertIn(self.REVISION, text)
        self.assertIn("igor-job-123456789012-live", text)


class AtomicEventRegressionTests(unittest.TestCase):
    def test_concurrent_event_writers_use_atomic_list_append_without_read_replace(self):
        table = Mock()
        worker = runner.Worker(table=table, bedrock=Mock(), s3=Mock(), cloudformation=Mock(), evidence_bucket="bucket",
            execution_role_arn="role", cloudformation_role_arn="role")
        worker.record_event("job", "command_started", "first")
        worker.record_event("job", "command_completed", "second", exit_code=0)
        table.get_item.assert_not_called()
        calls = table.update_item.call_args_list
        self.assertEqual(2, len(calls))
        self.assertTrue(all("list_append(if_not_exists(work_events, :empty), :event)" in call.kwargs["UpdateExpression"] for call in calls))
        self.assertEqual("first", calls[0].kwargs["ExpressionAttributeValues"][":event"][0]["message"])
        self.assertEqual("second", calls[1].kwargs["ExpressionAttributeValues"][":event"][0]["message"])


class GitRecoveryAcceptanceTests(unittest.TestCase):
    """Disposable-job acceptance: a local commit survives a failed/no push exactly."""

    def _git(self, cwd, *args):
        completed = subprocess.run(["git", "-C", str(cwd), *args], text=True, capture_output=True)
        self.assertEqual(0, completed.returncode, completed.stderr)
        return completed.stdout.strip()

    def test_unpushed_commit_is_restored_exactly_without_secrets_or_unrelated_objects(self):
        class MemoryS3:
            def __init__(self): self.objects = {}
            def put_object(self, **kwargs): self.objects[(kwargs["Bucket"], kwargs["Key"])] = kwargs["Body"]
            def get_object(self, **kwargs): return {"Body": io.BytesIO(self.objects[(kwargs["Bucket"], kwargs["Key"])])}

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            origin, seed, first, second = root / "origin.git", root / "seed", root / "first", root / "second"
            subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
            subprocess.run(["git", "init", str(seed)], check=True, capture_output=True)
            self._git(seed, "config", "user.email", "test@example.invalid")
            self._git(seed, "config", "user.name", "Test")
            (seed / ".gitignore").write_text("ignored-secret.txt\n")
            (seed / "tracked.txt").write_text("base\n")
            self._git(seed, "add", ".")
            self._git(seed, "commit", "-m", "base")
            self._git(seed, "branch", "-M", "main")
            self._git(seed, "remote", "add", "origin", str(origin))
            self._git(seed, "push", "-u", "origin", "main")
            subprocess.run(["git", "clone", str(origin), str(first / "repository")], check=True, capture_output=True)
            repository = first / "repository"
            self._git(repository, "config", "user.email", "test@example.invalid")
            self._git(repository, "config", "user.name", "Test")
            self._git(repository, "checkout", "main")
            (repository / "tracked.txt").write_text("recovered exact content\n")
            (repository / "binary.dat").write_bytes(b"\x00binary\xff\n")
            (repository / "ignored-secret.txt").write_text("DO-NOT-ARCHIVE")
            (repository / ".env").write_text("TOKEN=DO-NOT-ARCHIVE")
            self._git(repository, "add", "tracked.txt", "binary.dat")
            self._git(repository, "commit", "-m", "commit that cannot push")
            expected_revision = self._git(repository, "rev-parse", "HEAD")
            expected_history = self._git(repository, "rev-list", "--reverse", "HEAD")

            s3 = MemoryS3()
            worker = runner.Worker(table=Mock(), bedrock=Mock(), s3=s3, cloudformation=Mock(),
                evidence_bucket="evidence", execution_role_arn="role", cloudformation_role_arn="role")
            workspace_uri = worker.put_workspace("firstjob", str(first))
            manifest = worker.put_recovery_artifacts("firstjob", str(first), workspace_uri)
            self.assertEqual("not_pushed", manifest["push_status"])
            self.assertEqual(expected_revision, manifest["resulting_revision"])
            self.assertEqual(str(origin), manifest["repository_url"])
            workspace_names = zipfile.ZipFile(io.BytesIO(s3.objects[("evidence", "jobs/firstjob/workspace.zip")])).namelist()
            self.assertNotIn("repository/ignored-secret.txt", workspace_names)
            self.assertNotIn("repository/.env", workspace_names)
            self.assertFalse(any(".git/" in name for name in workspace_names))
            artifact_bytes = b"".join(s3.objects.values())
            self.assertNotIn(b"DO-NOT-ARCHIVE", artifact_bytes)
            bundle_heads = subprocess.run(["git", "bundle", "list-heads", "-"], input=s3.objects[("evidence", "jobs/firstjob/recovery/history.bundle")], capture_output=True).stdout.decode()
            self.assertIn(expected_revision, bundle_heads)

            source = {"job_id": "firstjob", "recovery_manifest_uri": manifest["manifest_uri"]}
            worker.table.get_item.return_value = {"Item": source}
            restored = worker.restore_recovery("firstjob", str(second))
            recovered = second / "repository"
            self.assertEqual(expected_revision, restored["restored_revision"])
            self.assertEqual(expected_revision, self._git(recovered, "rev-parse", "HEAD"))
            self.assertEqual(expected_history, self._git(recovered, "rev-list", "--reverse", "HEAD"))
            self.assertEqual(b"\x00binary\xff\n", (recovered / "binary.dat").read_bytes())
            self.assertFalse((recovered / "ignored-secret.txt").exists())
            self.assertFalse((recovered / ".env").exists())
            # The second job can publish the recovered object without rebuilding a replacement commit.
            self._git(recovered, "push", "origin", "main")
            remote = self._git(recovered, "ls-remote", "origin", "refs/heads/main").split()[0]
            self.assertEqual(expected_revision, remote)


    def test_pushed_head_at_upstream_uses_remote_commit_without_empty_bundle(self):
        class MemoryS3:
            def __init__(self): self.objects = {}
            def put_object(self, **kwargs): self.objects[(kwargs["Bucket"], kwargs["Key"])] = kwargs["Body"]
            def get_object(self, **kwargs): return {"Body": io.BytesIO(self.objects[(kwargs["Bucket"], kwargs["Key"])])}

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            origin, seed, first, second = root / "origin.git", root / "seed", root / "first", root / "second"
            subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
            subprocess.run(["git", "init", str(seed)], check=True, capture_output=True)
            self._git(seed, "config", "user.email", "test@example.invalid")
            self._git(seed, "config", "user.name", "Test")
            (seed / "tracked.txt").write_text("base\n")
            self._git(seed, "add", ".")
            self._git(seed, "commit", "-m", "base")
            self._git(seed, "branch", "-M", "main")
            self._git(seed, "remote", "add", "origin", str(origin))
            self._git(seed, "push", "-u", "origin", "main")
            subprocess.run(["git", "clone", str(origin), str(first / "repository")], check=True, capture_output=True)
            repository = first / "repository"
            self._git(repository, "config", "user.email", "test@example.invalid")
            self._git(repository, "config", "user.name", "Test")
            self._git(repository, "checkout", "main")
            (repository / "tracked.txt").write_text("pushed\n")
            self._git(repository, "commit", "-am", "pushed result")
            self._git(repository, "push", "origin", "main")
            expected_revision = self._git(repository, "rev-parse", "HEAD")

            s3 = MemoryS3()
            worker = runner.Worker(table=Mock(), bedrock=Mock(), s3=s3, cloudformation=Mock(),
                evidence_bucket="evidence", execution_role_arn="role", cloudformation_role_arn="role")
            workspace_uri = worker.put_workspace("pushedjob", str(first))
            manifest = worker.put_recovery_artifacts("pushedjob", str(first), workspace_uri)
            self.assertEqual("pushed", manifest["push_status"])
            self.assertEqual("remote_commit", manifest["recovery_source"])
            self.assertNotIn("bundle_uri", manifest)
            self.assertNotIn(("evidence", "jobs/pushedjob/recovery/history.bundle"), s3.objects)

            worker.table.get_item.return_value = {"Item": {"job_id": "pushedjob", "recovery_manifest_uri": manifest["manifest_uri"]}}
            restored = worker.restore_recovery("pushedjob", str(second))
            self.assertEqual(expected_revision, restored["restored_revision"])
            self.assertEqual(expected_revision, self._git(second / "repository", "rev-parse", "HEAD"))

    def test_pushed_commit_restores_safe_uncommitted_workspace_files_without_bundle(self):
        class MemoryS3:
            def __init__(self): self.objects = {}
            def put_object(self, **kwargs): self.objects[(kwargs["Bucket"], kwargs["Key"])] = kwargs["Body"]
            def get_object(self, **kwargs): return {"Body": io.BytesIO(self.objects[(kwargs["Bucket"], kwargs["Key"])])}

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            origin, seed, first, second = root / "origin.git", root / "seed", root / "first", root / "second"
            subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
            subprocess.run(["git", "init", str(seed)], check=True, capture_output=True)
            self._git(seed, "config", "user.email", "test@example.invalid")
            self._git(seed, "config", "user.name", "Test")
            (seed / ".gitignore").write_text("ignored.txt\n")
            (seed / "tracked.txt").write_text("base\n")
            self._git(seed, "add", ".")
            self._git(seed, "commit", "-m", "base")
            self._git(seed, "branch", "-M", "main")
            self._git(seed, "remote", "add", "origin", str(origin))
            self._git(seed, "push", "-u", "origin", "main")
            subprocess.run(["git", "clone", str(origin), str(first / "repository")], check=True, capture_output=True)
            repository = first / "repository"
            self._git(repository, "config", "user.email", "test@example.invalid")
            self._git(repository, "config", "user.name", "Test")
            self._git(repository, "checkout", "main")
            (repository / "tracked.txt").write_text("pushed\n")
            self._git(repository, "commit", "-am", "pushed result")
            self._git(repository, "push", "origin", "main")
            expected_revision = self._git(repository, "rev-parse", "HEAD")
            (repository / "safe-notes.txt").write_text("preserve this uncommitted file\n")
            (repository / "ignored.txt").write_text("do not archive\n")
            (repository / ".env").write_text("TOKEN=do-not-archive\n")

            s3 = MemoryS3()
            worker = runner.Worker(table=Mock(), bedrock=Mock(), s3=s3, cloudformation=Mock(),
                evidence_bucket="evidence", execution_role_arn="role", cloudformation_role_arn="role")
            workspace_uri = worker.put_workspace("safejob", str(first))
            manifest = worker.put_recovery_artifacts("safejob", str(first), workspace_uri)
            self.assertNotIn("bundle_uri", manifest)
            worker.table.get_item.return_value = {"Item": {"job_id": "safejob", "recovery_manifest_uri": manifest["manifest_uri"]}}
            restored = worker.restore_recovery("safejob", str(second))
            recovered = second / "repository"
            self.assertEqual(expected_revision, restored["restored_revision"])
            self.assertEqual("preserve this uncommitted file\n", (recovered / "safe-notes.txt").read_text())
            self.assertFalse((recovered / "ignored.txt").exists())
            self.assertFalse((recovered / ".env").exists())
