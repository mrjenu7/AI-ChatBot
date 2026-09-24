"""Offline regressions: python -m unittest discover -s tests -v"""
import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'backend'))
# The test doesn't need external credentials or the real OpenAI SDK.
config = types.ModuleType('app.core.config')
config.settings = types.SimpleNamespace(has_openai_api_key=False, llm_model='test')
sys.modules['app.core.config'] = config
from app.services.company_guard import classify_scope, is_other_vision_brand, refusal


class GuardTests(unittest.TestCase):
    def test_similar_names_rejected(self):
        for query in ['Tell me about Wepro Vision', 'Weprovision services',
                      'We4vision', 'we-pro-vision', 'Wepro Vision and We3vision']:
            with self.subTest(query=query):
                self.assertTrue(is_other_vision_brand(query))
                self.assertEqual(asyncio.run(classify_scope(query)), 'OUT_OF_SCOPE')

    def test_official_name_not_rejected(self):
        for query in ['We3vision', 'We3 Vision', 'we-3-vision']:
            with self.subTest(query=query):
                self.assertFalse(is_other_vision_brand(query))

    def test_greeting(self):
        self.assertEqual(asyncio.run(classify_scope('Hello!')), 'GREETING')

    def test_unknown_fails_closed(self):
        self.assertEqual(asyncio.run(classify_scope('What are your services?')), 'AMBIGUOUS')

    def test_refusal_languages(self):
        self.assertIn('We3vision', refusal({'code': 'en'}))
        self.assertIn('We3vision', refusal({'code': 'gu', 'style': 'native'}))
        self.assertIn('We3vision', refusal({'code': 'hi', 'style': 'native'}))

    def test_llm_classification(self):
        class Completion:
            choices = [types.SimpleNamespace(message=types.SimpleNamespace(content='IN_SCOPE'))]
        class Completions:
            async def create(self, **kwargs):
                self_call = kwargs['messages'][-1]['content']
                self_outer = self_call
                return Completion()
        client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=Completions()))
        fake_llm = types.ModuleType('app.services.llm_service')
        fake_llm._get_client = lambda: client
        with patch.object(config.settings, 'has_openai_api_key', True), patch.dict(sys.modules, {'app.services.llm_service': fake_llm}):
            self.assertEqual(asyncio.run(classify_scope('Can you build my website?')), 'IN_SCOPE')


if __name__ == '__main__':
    unittest.main()
