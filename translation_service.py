# translation_service.py
from googletrans import Translator
import logging

class TranslationService:
    def __init__(self):
        self.translator = Translator()
        self.logger = logging.getLogger(__name__)
        self.is_online = True  # Will be checked dynamically
    
    def check_online(self):
        try:
            import socket
            socket.create_connection(("8.8.8.8", 53), timeout=3)
            return True
        except:
            return False
    
    def translate_to_all(self, text):
        self.is_online = self.check_online()
        
        if not self.is_online:
            raise ConnectionError("No internet connection")
        
        try:
            # Detect language
            detection = self.translator.detect(text)
            detected_lang = detection.lang[:2] if len(detection.lang) > 2 else detection.lang
            
            translations = {
                "original": text,
                "detected_lang": detected_lang
            }
            
            # Translate to other languages
            for target_lang in ['en', 'es', 'hi']:
                if target_lang != detected_lang:
                    try:
                        translation = self.translator.translate(
                            text, dest=target_lang, src=detected_lang
                        )
                        translations[target_lang] = translation.text
                    except Exception as e:
                        self.logger.error(f"Translation error for {target_lang}: {e}")
                        translations[target_lang] = ""
                else:
                    translations[target_lang] = text
            
            return translations
            
        except Exception as e:
            self.logger.error(f"Translation failed: {e}")
            raise