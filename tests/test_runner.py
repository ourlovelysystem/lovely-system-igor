import json
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4


sys.path.insert(0, str(Path(__file__).parents[1] / "src" / "worker"))
import runner  # noqa: E402


credential_spec = importlib.util.spec_from_file_location(
    "github_app_credential",
    Path(__file__).parents[1] / "scripts" / "github-app-credential.py",
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
            "limitations": [],
        }
        with self.assertRaisesRegex(ValueError, "must have succeeded"):
            runner.Worker._validate_finish(finish, commands)

    def test_template_grants_unbounded_aws_administrator_access(self):
        template = (Path(__file__).parents[1] / "template.yaml").read_text()
        self.assertEqual(2, template.count("arn:aws:iam::aws:policy/AdministratorAccess"))
        self.assertNotIn("arn:aws:iam::aws:policy/PowerUserAccess", template)
        self.assertNotIn("Effect: Deny", template)
        self.assertIn("WORKLOAD_ROLE_ARN", template)
        self.assertIn("CONVERSATIONS_TABLE", template)

    def test_template_supports_github_app_credentials(self):
        template = (Path(__file__).parents[1] / "template.yaml").read_text()
        self.assertIn("GitHubAppSecretName", template)
        self.assertIn("GITHUB_APP_SECRET_NAME", template)
        self.assertIn("github-app-credential.py configure", template)

    def test_github_app_jwt_has_expected_claims(self):
        original_run = github_app_credential.subprocess.run
        github_app_credential.subprocess.run = Mock(
            return_value=Mock(stdout=b"signature")
        )
        try:
            token = github_app_credential._github_jwt("12345", "private-key", now=1_000)
        finally:
            github_app_credential.subprocess.run = original_run
        header, payload, signature = token.split(".")
        decode = lambda value: json.loads(
            __import__("base64").urlsafe_b64decode(value + "=" * (-len(value) % 4))
        )
        self.assertEqual({"alg": "RS256", "typ": "JWT"}, decode(header))
        self.assertEqual({"iat": 940, "exp": 1540, "iss": "12345"}, decode(payload))
        self.assertTrue(signature)

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


if __name__ == "__main__":
    unittest.main()
