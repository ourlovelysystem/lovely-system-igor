import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock


sys.path.insert(0, str(Path(__file__).parents[1] / "src" / "worker"))
import runner  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
