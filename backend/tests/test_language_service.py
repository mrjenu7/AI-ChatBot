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

    def test_gujarati_reply_guard_rejects_english(self):
        profile = detect_language_profile("તમારી કંપની શું કામ કરે છે?")
        self.assertFalse(response_matches_language("We provide AI and web development services.", profile))
        self.assertFalse(response_matches_language("નમસ્તે. We provide web development, mobile apps, CRM development and AI automation services for businesses.", profile))
        self.assertTrue(response_matches_language("અમે AI અને વેબ ડેવલપમેન્ટ જેવી ટેક્નોલોજી સેવાઓ પ્રદાન કરીએ છીએ.", profile))

    def test_contract_is_explicit(self):
        profile = detect_language_profile("તમારી મુખ્ય સેવાઓ કઈ છે?")
        contract = language_contract(profile)
        self.assertIn("Gujarati", contract)
        self.assertIn("Gujarati script", contract)


if __name__ == "__main__":
    unittest.main()
