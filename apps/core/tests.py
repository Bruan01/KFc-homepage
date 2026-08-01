from django.test import TestCase


class HealthViewTests(TestCase):
    def test_health_returns_json(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertIn("time", response.json())

    def test_health_rejects_post(self):
        response = self.client.post("/api/health")
        self.assertEqual(response.status_code, 405)
