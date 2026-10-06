import unittest

from app.services.language_service import (
    detect_language_profile,
    language_contract,
    response_matches_language,
)


class LanguageServiceTests(unittest.TestCase):
    def test_gujarati_script_detection(self):
        profile = detect_language_profile("તમારી કંપની શું કામ કરે છે અને તમારી મુખ્ય સેવાઓ કઈ છે?")
        self.assertEqual(profile["code"], "gu")
        self.assertEqual(profile["style"], "native")
        self.assertEqual(profile["locale"], "gu-IN")

    def test_hindi_script_detection(self):
        profile = detect_language_profile("आपकी कंपनी कौन-कौन सी सेवाएँ प्रदान करती है?")
        self.assertEqual(profile["code"], "hi")
        self.assertEqual(profile["style"], "native")

    def test_gujlish_detection(self):
        profile = detect_language_profile("tame shu service aapo cho ane tamari company shu kare chhe")
        self.assertEqual(profile["code"], "gu")
        self.assertEqual(profile["style"], "latin")

    def test_hinglish_detection(self):
        profile = detect_language_profile("aap kya service dete hain mujhe batao")
        self.assertEqual(profile["code"], "hi")
        self.assertEqual(profile["style"], "latin")

    def test_reply_guard_enforces_english(self):
        profile = detect_language_profile("તમારી કંપની શું કામ કરે છે?")
        self.assertTrue(response_matches_language("We provide AI and web development services.", profile))
        self.assertTrue(response_matches_language("Hello! We provide web development, mobile apps, CRM development and AI automation services for businesses.", profile))
        self.assertFalse(response_matches_language("અમે AI અને વેબ ડેવલપમેન્ટ જેવી ટેક્નોલોજી સેવાઓ પ્રદાન કરીએ છીએ.", profile))
        self.assertFalse(response_matches_language("हम वेब और मोबाइल ऐप डेवलपमेंट सेवाएं प्रदान करते हैं।", profile))

    def test_contract_enforces_english_only(self):
        profile = detect_language_profile("તમારી મુખ્ય સેવાઓ કઈ છે?")
        contract = language_contract(profile)
        self.assertIn("English", contract)
        self.assertIn("Gujarati", contract)
        self.assertIn("strictly and exclusively in clear, professional English", contract)


if __name__ == "__main__":
    unittest.main()
