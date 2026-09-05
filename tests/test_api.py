import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).parents[1] / "src" / "api"))
import app  # noqa: E402


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.table = Mock()
        self.codebuild = Mock()
        self.codebuild.start_build.return_value = {"build": {"id": "igor-worker:123"}}

    def call(self, method, path, body=None):
        event = {
            "requestContext": {"http": {"method": method}},
            "rawPath": path,
            "body": json.dumps(body or {}),
        }
        with patch.object(app, "now_iso", return_value="2026-09-04T00:00:00+00:00"):
            return app.handle(
                event,
                table=self.table,
                codebuild=self.codebuild,
                project_name="igor-worker",
                default_model_id="model-default",
            )

    def test_submit_persists_before_starting_worker(self):
        result = self.call("POST", "/jobs", {"idea": "Build a greeting API"})
        self.assertEqual(202, result["statusCode"])
        item = self.table.put_item.call_args.kwargs["Item"]
        self.assertEqual("QUEUED", item["status"])
        self.assertEqual("general_aws", item["task_type"])
        self.assertEqual("Build a greeting API", item["objective"])
        self.assertEqual("model-default", item["model_id"])
        self.codebuild.start_build.assert_called_once()
        self.assertIn("job_id", json.loads(result["body"]))

    def test_submit_rejects_empty_idea(self):
        result = self.call("POST", "/jobs", {"idea": "  "})
        self.assertEqual(400, result["statusCode"])
        self.table.put_item.assert_not_called()

    def test_get_returns_durable_job(self):
        self.table.get_item.return_value = {"Item": {"job_id": "abc", "status": "WORKING"}}
        result = self.call("GET", "/jobs/abc")
        self.assertEqual(200, result["statusCode"])
        self.assertEqual("WORKING", json.loads(result["body"])["status"])

    def test_list_returns_newest_jobs_first(self):
        self.table.scan.return_value = {
            "Items": [
                {"job_id": "old", "created_at": "2026-09-03T00:00:00+00:00"},
                {"job_id": "new", "created_at": "2026-09-04T00:00:00+00:00"},
            ]
        }
        result = self.call("GET", "/jobs")
        self.assertEqual(200, result["statusCode"])
        jobs = json.loads(result["body"])["jobs"]
        self.assertEqual(["new", "old"], [job["job_id"] for job in jobs])

    def test_list_follows_scan_pages(self):
        self.table.scan.side_effect = [
            {
                "Items": [{"job_id": "one", "created_at": "2026-09-03T00:00:00+00:00"}],
                "LastEvaluatedKey": {"job_id": "one"},
            },
            {"Items": [{"job_id": "two", "created_at": "2026-09-04T00:00:00+00:00"}]},
        ]
        result = self.call("GET", "/jobs")
        self.assertEqual(200, result["statusCode"])
        jobs = json.loads(result["body"])["jobs"]
        self.assertEqual(["two", "one"], [job["job_id"] for job in jobs])


if __name__ == "__main__":
    unittest.main()
