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
        self.codebuild.batch_get_builds.return_value = {"builds": []}

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
        stored = self.table.put_item.call_args.kwargs["Item"]
        self.assertEqual("Waiting for an execution worker.", stored["current_activity"])
        self.assertEqual("queued", stored["work_events"][0]["type"])
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

    def test_submit_links_job_to_conversation(self):
        result = self.call(
            "POST",
            "/jobs",
            {"idea": "List EC2 instances", "conversation_id": "conversation-123"},
        )
        self.assertEqual(202, result["statusCode"])
        item = self.table.put_item.call_args.kwargs["Item"]
        self.assertEqual("conversation-123", item["conversation_id"])

    def test_submit_carries_private_s3_attachments_to_worker(self):
        attachment = {
            "attachment_id": "file-1",
            "filename": "inventory.csv",
            "content_type": "text/csv",
            "size": 1234,
            "s3_uri": "s3://igor/attachments/operator/conversation/file-1/inventory.csv",
            "s3_key": "attachments/operator/conversation/file-1/inventory.csv",
        }
        result = self.call("POST", "/jobs", {"idea": "Inspect it", "attachments": [attachment]})
        self.assertEqual(202, result["statusCode"])
        item = self.table.put_item.call_args.kwargs["Item"]
        self.assertEqual([attachment], item["attachments"])
        self.assertEqual("Waiting for an execution worker.", item["progress_message"])

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

    def test_stale_running_job_is_not_reported_as_active_after_failed_build(self):
        self.table.scan.return_value = {"Items": [{
            "job_id": "stale", "status": "RUNNING", "stage": "verify",
            "build_id": "igor-worker:stale", "created_at": "2026-09-04T00:00:00+00:00",
        }]}
        self.codebuild.batch_get_builds.return_value = {"builds": [{
            "id": "igor-worker:stale", "buildStatus": "FAILED",
            "buildComplete": True, "currentPhase": "COMPLETED",
        }]}

        job = json.loads(self.call("GET", "/jobs")["body"])["jobs"][0]

        self.assertEqual("INCOMPLETE", job["status"])
        self.assertEqual("RUNNING", job["stored_status"])
        self.assertFalse(job["execution_active"])
        self.assertEqual("FAILED", job["execution_state"])
        self.assertEqual("terminalization", job["stage"])
        self.assertTrue(job["reconciliation_persisted"])
        update = self.table.update_item.call_args.kwargs
        self.assertEqual({"job_id": "stale"}, update["Key"])
        self.assertIn("build_id = :build_id", update["ConditionExpression"])
        self.assertEqual("INCOMPLETE", update["ExpressionAttributeValues"][":incomplete"])
        self.assertFalse(update["ExpressionAttributeValues"][":inactive"])

    def test_stale_running_job_is_incomplete_even_when_build_succeeded(self):
        self.table.get_item.return_value = {"Item": {
            "job_id": "stale", "status": "RUNNING", "build_id": "igor-worker:stale",
        }}
        self.codebuild.batch_get_builds.return_value = {"builds": [{
            "id": "igor-worker:stale", "buildStatus": "SUCCEEDED",
            "buildComplete": True, "currentPhase": "COMPLETED",
        }]}

        job = json.loads(self.call("GET", "/jobs/stale")["body"])

        self.assertEqual("INCOMPLETE", job["status"])
        self.assertFalse(job["execution_active"])
        self.assertEqual("SUCCEEDED", job["execution_state"])
        self.table.update_item.assert_called_once()

    def test_in_progress_build_is_authoritatively_active(self):
        self.table.scan.return_value = {"Items": [{
            "job_id": "live", "status": "RUNNING", "build_id": "igor-worker:live",
            "created_at": "2026-09-04T00:00:00+00:00",
        }]}
        self.codebuild.batch_get_builds.return_value = {"builds": [{
            "id": "igor-worker:live", "buildStatus": "IN_PROGRESS",
            "buildComplete": False, "currentPhase": "BUILD",
        }]}

        job = json.loads(self.call("GET", "/jobs")["body"])["jobs"][0]

        self.assertEqual("RUNNING", job["status"])
        self.assertTrue(job["execution_active"])
        self.assertEqual("BUILD", job["execution_phase"])
        self.table.update_item.assert_not_called()

    def test_unavailable_liveness_check_never_claims_active(self):
        self.table.scan.return_value = {"Items": [{
            "job_id": "unknown", "status": "RUNNING", "build_id": "igor-worker:unknown",
            "created_at": "2026-09-04T00:00:00+00:00",
        }]}
        self.codebuild.batch_get_builds.side_effect = RuntimeError("unavailable")

        job = json.loads(self.call("GET", "/jobs")["body"])["jobs"][0]

        self.assertFalse(job["execution_active"])
        self.assertEqual("UNVERIFIED", job["execution_state"])


if __name__ == "__main__":
    unittest.main()
