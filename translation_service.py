from googletrans import Translator
import logging
from functools import lru_cache
import time
from meaning_service import MeaningService
from typing import Dict, List, Union

class GoogletransTranslationService:
    def __init__(self, max_retries=3, delay=1):
        self.translator = Translator()
        self.max_retries = max_retries
        self.delay = delay
        self.logger = logging.getLogger(__name__)
        self.meaning_service = MeaningService()

    def detect_language(self, text: str) -> str:
        if not text or not text.strip():
            return "unknown"

        for attempt in range(self.max_retries):
            try:
                detection = self.translator.detect(text)
                lang_code = detection.lang[:2]
                return lang_code
            except Exception as e:
                self.logger.warning(
                    f"Language detection attempt {attempt + 1} failed: {e}"
                )
                time.sleep(self.delay)

        # fallback
        return self._simple_language_detection(text)

    def _simple_language_detection(self, text: str) -> str:
        if any("\u0900" <= char <= "\u097F" for char in text):
            return "hi"

        spanish_indicators = ["él", "ella", "usted", "por qué", "qué", "cómo"]
        if any(ind in text.lower() for ind in spanish_indicators):
            return "es"

        return "en"

    @staticmethod
    @lru_cache(maxsize=1000)
    def _cached_translate(text: str, target_lang: str, source_lang: str) -> str:
        translator = Translator()
        result = translator.translate(text, dest=target_lang, src=source_lang)
        return result.text

    def translate_text(self, text: str, target_lang="en", source_lang="auto") -> str:
        if not text or not text.strip():
            return text

        for attempt in range(self.max_retries):
            try:
                return self._cached_translate(text, target_lang, source_lang)
            except Exception as e:
                self.logger.warning(
                    f"Translation attempt {attempt + 1} failed: {e}"
                )
                time.sleep(self.delay * (attempt + 1))

        self.logger.error(f"Failed to translate after retries: {text}")
        return text

    def translate_to_all(self, text: str) -> Dict:
        if not text:
            return {
                "original": "",
                "detected_lang": "unknown",
                "en": "",
                "es": "",
                "hi": "",
            }

        # 1-letter/character words → assume same language
        if len(text.strip()) < 2:
            detected = self.detect_language(text)
            return {
                "original": text,
                "detected_lang": detected,
                "en": text if detected == "en" else "",
                "es": text if detected == "es" else "",
                "hi": text if detected == "hi" else "",
            }

        detected_lang = self.detect_language(text)

        translations = {"original": text, "detected_lang": detected_lang}

        for lang_code in ["en", "es", "hi"]:
            if lang_code == detected_lang:
                translations[lang_code] = text
                continue

            try:
                translated = self.translate_text(
                    text, target_lang=lang_code, source_lang=detected_lang
                )
                # Accept identical translations (many are legitimate)
                translations[lang_code] = translated or ""
            except Exception as e:
                self.logger.warning(f"Translation to {lang_code} failed: {e}")
                translations[lang_code] = ""

        return translations

    def batch_translate(self, texts: List[str], target_lang="en") -> List[str]:
        if not texts:
            return []

        for attempt in range(self.max_retries):
            try:
                results = self.translator.translate(texts, dest=target_lang)

                # googletrans returns a single object if only one item
                if isinstance(results, list):
                    return [r.text for r in results]
                return [results.text]

            except Exception as e:
                self.logger.warning(
                    f"Batch translation attempt {attempt + 1} failed: {e}"
                )
                time.sleep(self.delay)

        # fallback: translate individually
        return [self.translate_text(t, target_lang) for t in texts]
    
    def translate_with_meaning(self, text: str) -> Dict:
        translations = self.translate_to_all(text)
        detected_lang = translations.get("detected_lang", "en")

        try:
            meanings = self.meaning_service.get_comprehensive_meaning(
                text, detected_lang, translations
            )
            complexity = self.meaning_service.get_word_complexity(
                text, detected_lang
            )
        except Exception as e:
            self.logger.error(f"MeaningService error: {e}")
            meanings = {}
            complexity = None

        return {
            "translations": translations,
            "meanings": meanings,
            "word_complexity": complexity,
            "detected_language": detected_lang,
        }

    def process_word_with_details(self, word: str, context: str = "") -> Dict:
        result = self.translate_with_meaning(word)
        result["metadata"] = {
            "timestamp": time.time(),
            "context": context,
            "word_length": len(word),
            "is_compound": " " in word or "-" in word,
            "has_special_chars": any(not char.isalnum() for char in word),
        }
        return result
