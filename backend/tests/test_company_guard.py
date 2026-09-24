"""Offline regression tests: python -m unittest backend/tests/test_company_guard.py"""
import unittest
from unittest.mock import AsyncMock, patch

from app.services.company_guard import classify_scope, is_other_vision_brand


class CompanyGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_company_and_service_queries(self):
        for prompt in (
            "Tell me about We3vision", "What services does We3 Vision offer?",
            "what services do you offer", "Can you develop my website?",
            "Do you provide AI chatbot development?", "What is your pricing?",
        ):
            with self.subTest(prompt=prompt):
                self.assertEqual(await classify_scope(prompt), "IN_SCOPE")

    async def test_similar_and_other_companies(self):
        for prompt in ("Tell me about Wepro Vision", "Weprovision services",
                       "What does We4vision do?", "Tell me about Google",
                       "Compare We3vision vs Microsoft"):
            with self.subTest(prompt=prompt):
                self.assertEqual(await classify_scope(prompt), "OUT_OF_SCOPE")

    async def test_greetings_and_general_topic(self):
        self.assertEqual(await classify_scope("Hello"), "GREETING")
        self.assertEqual(await classify_scope("What is today's weather?"), "OUT_OF_SCOPE")

    async def test_followup_uses_history(self):
        history = [
            {"role": "user", "content": "What does We3vision offer?"},
            {"role": "assistant", "content": "We3vision offers software development."},
        ]
        self.assertEqual(await classify_scope("Tell me more", history), "IN_SCOPE")

    async def test_no_key_does_not_cause_repeated_clarification(self):
        with patch("app.services.company_guard.settings") as settings:
            settings.has_openai_api_key = False
            self.assertEqual(await classify_scope("What are your services?"), "IN_SCOPE")
            self.assertEqual(await classify_scope("Tell me about Microsoft"), "OUT_OF_SCOPE")
            self.assertEqual(await classify_scope("Explain nuclear fusion"), "OUT_OF_SCOPE")

    async def test_provider_exception_does_not_reclassify_clear_in_scope(self):
        # A clear company request is accepted before any provider call.
        with patch("app.services.company_guard.settings") as settings:
            settings.has_openai_api_key = False
            self.assertEqual(await classify_scope("Tell me about We3vision"), "IN_SCOPE")

    def test_brand_matching(self):
        self.assertFalse(is_other_vision_brand("We3vision"))
        self.assertFalse(is_other_vision_brand("We3 Vision"))
        self.assertTrue(is_other_vision_brand("Wepro Vision"))


if __name__ == "__main__":
    unittest.main()
