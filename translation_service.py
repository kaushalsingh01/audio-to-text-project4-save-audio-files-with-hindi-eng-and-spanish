from googletrans import Translator
import logging
from functools import lru_cache
import time

class GoogletransTranslationService:
    def __init__(self, max_retries=3, delay=1):
        self.translator = Translator()
        self.max_retries = max_retries
        self.delay = delay
        self.logger = logging.getLogger(__name__)
    
    def detect_language(self, text):
        if not text or not text.strip():
            return 'unknown'
        
        for attempt in range(self.max_retries):
            try:
                detection = self.translator.detect(text)
                lang_code = detection.lang if len(detection.lang) == 2 else detection.lang[:2]
                return lang_code
            except Exception as e:
                self.logger.warning(f"Language detection attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.delay)
        
        return self._simple_language_detection(text)
    
    def _simple_language_detection(self, text):
        if any('\u0900' <= char <= '\u097F' for char in text):
            return 'hi'
        spanish_indicators = ['él', 'ella', 'usted', 'por qué', 'qué', 'cómo']
        if any(indicator in text.lower() for indicator in spanish_indicators):
            return 'es'
        return 'en'
    
    @lru_cache(maxsize=1000)
    def translate_text(self, text, target_lang='en', source_lang='auto'):
        if not text or not text.strip():
            return text
        
        for attempt in range(self.max_retries):
            try:
                translation = self.translator.translate(
                    text, 
                    dest=target_lang, 
                    src=source_lang
                )
                return translation.text
            except Exception as e:
                self.logger.warning(f"Translation attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.delay * (attempt + 1))

        self.logger.error(f"Failed to translate after {self.max_retries} attempts: {text}")
        return text
    
    def translate_to_all(self, text):

        if not text:
            return {
                "original": "",
                "detected_lang": "unknown",
                "en": "",
                "es": "",
                "hi": ""
            }
        
        detected_lang = self.detect_language(text)
        
        translations = {
            "original": text,
            "detected_lang": detected_lang
        }
        
        for lang_code in ['en', 'es', 'hi']:
            if lang_code != detected_lang:
                translations[lang_code] = self.translate_text(
                    text, target_lang=lang_code, source_lang=detected_lang
                )
            else:
                translations[lang_code] = text
        
        return translations
    
    def batch_translate(self, texts, target_lang='en'):
        if not texts:
            return []
        
        for attempt in range(self.max_retries):
            try:
                translations = self.translator.translate(
                    texts, 
                    dest=target_lang
                )
                return [t.text for t in translations]
            except Exception as e:
                self.logger.warning(f"Batch translation attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.delay)
        
        # Fallback: translate individually
        return [self.translate_text(text, target_lang) for text in texts]