import json
import importlib.util
import unittest
from pathlib import Path


dashboard_path = Path(__file__).parents[1] / "src" / "dashboard" / "app.py"
spec = importlib.util.spec_from_file_location("igor_dashboard", dashboard_path)
assert spec and spec.loader
dashboard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dashboard)


class DashboardTests(unittest.TestCase):
    def test_page_contains_runtime_configuration(self):
        result = dashboard.render_dashboard(
            api_url="https://api.example.test/",
            client_id="client-123",
            region="us-east-1",
        )
        self.assertEqual(200, result["statusCode"])
        self.assertIn("text/html", result["headers"]["content-type"])
        self.assertIn(
            'window.IGOR_CONFIG={"apiUrl":"https://api.example.test","clientId":"client-123","region":"us-east-1"}',
            result["body"],
        )
        self.assertIn("https://api.example.test", result["headers"]["content-security-policy"])
        self.assertIn("jobStates", result["body"])
        self.assertIn("await selectConversation(currentConversationId)", result["body"])
        self.assertIn("/part-url", result["body"])
        self.assertIn("uploadFile(file)", result["body"])
        self.assertIn("data-job-progress", result["body"])
        self.assertIn("https://*.amazonaws.com", result["headers"]["content-security-policy"])

    def test_non_root_path_is_not_found(self):
        result = dashboard.handler({"rawPath": "/missing"}, None)
        self.assertEqual(404, result["statusCode"])
        self.assertEqual({"error": "not found"}, json.loads(result["body"]))


if __name__ == "__main__":
    unittest.main()
