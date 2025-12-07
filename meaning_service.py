import requests
import json
import logging
from typing import Dict, Optional, List
from googletrans import Translator
import time

logger = logging.getLogger(__name__)
class MeaningService:
    def __init__(self, max_retries=3, delay=1):
        self.transaltor = Translator()
        self.max_retries = max_retries
        self.delay = delay

        #Free APIs
        self.dictionary_apis = {
            'en': 'https://api.dictionaryapi.dev/api/v2/entries/en/',
            'es': None, # Spanish dictionary not available
            'hi': None  # Hindi dictionary not available
        }

        self.offline_dictionary = self._load_offline_dictionary()
    
    def _load_offline_dictionary(self):
        """Basic offline dictionary for common words"""
        return {
            'en': {
                'hello': {'meaning': 'A greeting', 'pos': 'interjection', 'synonyms': ['hi', 'hey']},
                'thank': {'meaning': 'Express gratitude', 'pos': 'verb', 'synonyms': ['appreciate']},
                'water': {'meaning': 'Clear liquid essential for life', 'pos': 'noun', 'synonyms': ['H2O', 'aqua']},
                'eat': {'meaning': 'Put food into the mouth and chew', 'pos': 'verb', 'synonyms': ['consume', 'devour']},
                'book': {'meaning': 'A set of written or printed pages', 'pos': 'noun', 'synonyms': ['volume', 'tome']},
            },
            'es': {
                'hola': {'meaning': 'Un saludo', 'pos': 'interjección', 'synonyms': ['buenos días']},
                'gracias': {'meaning': 'Expresar gratitud', 'pos': 'interjección', 'synonyms': ['agradecimiento']},
                'agua': {'meaning': 'Líquido transparente esencial para la vida', 'pos': 'sustantivo', 'synonyms': ['H2O']},
            },
            'hi': {
                'नमस्ते': {'meaning': 'एक अभिवादन', 'pos': 'संज्ञा', 'synonyms': ['प्रणाम']},
                'धन्यवाद': {'meaning': 'कृतज्ञता व्यक्त करना', 'pos': 'संज्ञा', 'synonyms': ['शुक्रिया']},
                'पानी': {'meaning': 'जीवन के लिए आवश्यक स्पष्ट तरल', 'pos': 'संज्ञा', 'synonyms': ['जल']},
            }
        }
    
    def get_meaning_online(self, word:str, language: str='en') -> Optional[Dict]:
        if language not in self.dictionary_apis or not self.dictionary_apis[language]:
            return None
        
        url = f"{self.dictionary_apis[language]}{word}"

        for attempt in range(self.max_retries):
            try:
                response = requests.get(url, timeout=5)

                if response.status_code == 200:
                    data = response.json()

                    if isinstance(data, list) and len(data) > 0:
                        entry = data[0]
                        meanings = []
                        if 'meanings' in entry:
                            for meaning in entry['meanings']:
                                if 'definitions' in meaning and meaning['definitions']:
                                    definitions = meaning['definitions']
                                    for definition in definitions[:2]:
                                        meaning.append({
                                            'definition': definition.get('definition', ''),
                                            'partOfSpeech': meaning.get('partOfSpeech', ''),
                                            'example': definition.get('example', '')
                                        })
                        
                        phonetics = None
                        if 'phonetics' in entry and entry['phonetics']:
                            phonetics = entry['phonetics'][0].get('text', '')
                        
                        return {
                            'word': word,
                            'language':language,
                            'meanings':meanings[:3],
                            'phonetics': phonetics,
                            'source': 'dictionary_api'
                        }
            except requests.exceptions.RequestException as e:
                logger.warning(f"Dictionary API attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.delay)
                
            except Exception as e:
                logger.error(f"Error parsing dictionary response: {e}")
        return None
    
    def get_meaning_offline(self, word: str, language: str = 'en') -> Optional[Dict]:
        word_lower = word.lower()
        if language in self.offline_dictionary and word_lower in self.offline_dictionary[language]:
            meaning_data = self.offline_dictionary[language][word_lower]
            return {
                'word': word,
                'language': language,
                'meanings': [{
                    'definition': meaning_data['meaning'],
                    'partOfSpeech': meaning_data['pos'],
                    'example': ''
                }],
                'synonyms': meaning_data.get('synonyms', []),
                'source': 'offline_dictionary'
            }
        
        return None
    
    def generate_meaning_from_translation(self, word: str, translation: str, source_lang: str, target_lang: str) -> Dict: 
        meaning_templates = {
            'en': f"The English word '{word}' means '{translation}' in {target_lang.upper()}.",
            'es': f"La palabra española '{word}' significa '{translation}' en {target_lang.upper()}.",
            'hi': f"हिंदी शब्द '{word}' का अर्थ '{translation}' है {target_lang.upper()} में।"
        }
        return {
            'word': word,
            'language': source_lang,
            'meanings': [{
                'definition': meaning_templates.get(source_lang, f"'{word}' means '{translation}'"),
                'partOfSpeech': 'unknown',
                'example': ''
            }],
            'source': 'generated_from_translation'
        }
    
    def get_comprehensive_meaning(self, word: str, source_lang: str, translations: Dict = None) -> Dict:
        result = {
            'word': word,
            'source_language': source_lang,
            'meanings': {},
            'synonyms': {},
            'part_of_speech': {},
            'source': {}
        }
        if translations and 'en' in translations:
            english_meaning = self.get_meaning_online(word if source_lang == 'en' else translations.get('en', ''), 'en')
            if english_meaning:
                result['meanings']['en'] = english_meaning['meanings'][0]['definition'] if english_meaning['meanings'] else ''
                result['part_of_speech']['en'] = english_meaning['meanings'][0]['partOfSpeech'] if english_meaning['meanings'] else ''
                result['source']['en'] = english_meaning['source']

                if 'synonyms' in english_meaning:
                    result['synonyms']['en'] = english_meaning['synonyms']

            else:
                # Fallback to offline
                offline_meaning = self.get_meaning_offline(word if source_lang == 'en' else translations.get('en', ''), 'en')
                if offline_meaning:
                    result['meanings']['en'] = offline_meaning['meanings'][0]['definition']
                    result['part_of_speech']['en'] = offline_meaning['meanings'][0]['partOfSpeech']
                    result['source']['en'] = offline_meaning['source']
                    
                    if 'synonyms' in offline_meaning:
                        result['synonyms']['en'] = offline_meaning['synonyms']
                else:
                    # Generate from translation
                    if translations and 'en' in translations:
                        generated = self.generate_meaning_from_translation(
                            translations.get('en', word), 
                            translations.get('en', word),
                            'en', source_lang
                        )
                        result['meanings']['en'] = generated['meanings'][0]['definition']
                        result['part_of_speech']['en'] = generated['meanings'][0]['partOfSpeech']
                        result['source']['en'] = generated['source']
            # Generate meanings for other languages from English meaning
        if 'en' in result['meanings']:
            english_meaning_text = result['meanings']['en']
            
            # Translate the English meaning to other languages
            for lang in ['es', 'hi']:
                if lang != source_lang:
                    try:
                        translated_meaning = self.translator.translate(
                            english_meaning_text, 
                            dest=lang, 
                            src='en'
                        ).text
                        
                        result['meanings'][lang] = translated_meaning
                        result['source'][lang] = 'translated_from_en'
                    except:
                        # If translation fails, use English meaning
                        result['meanings'][lang] = english_meaning_text
                        result['source'][lang] = 'fallback_en'
        
        # Add example sentence
        result['example_sentence'] = self._generate_example_sentence(word, source_lang, translations)
        
        return result
    
    def _generate_example_sentence(self, word: str, source_lang: str, translations: Dict) -> str:
        """Generate an example sentence using the word"""
        examples = {
            'en': {
                'hello': "Hello, how are you today?",
                'thank': "I want to thank you for your help.",
                'water': "Please bring me a glass of water.",
                'eat': "I like to eat healthy food.",
                'book': "I'm reading an interesting book."
            },
            'es': {
                'hola': "Hola, ¿cómo estás hoy?",
                'gracias': "Quiero darte las gracias por tu ayuda.",
                'agua': "Por favor, tráeme un vaso de agua."
            },
            'hi': {
                'नमस्ते': "नमस्ते, आप आज कैसे हैं?",
                'धन्यवाद': "मैं आपकी मदद के लिए धन्यवाद देना चाहता हूं।",
                'पानी': "कृपया मुझे एक गिलास पानी लाएं।"
            }
        }
        
        word_lower = word.lower()
        
        if source_lang in examples and word_lower in examples[source_lang]:
            return examples[source_lang][word_lower]
        
        # Generate a simple example
        if source_lang == 'en':
            return f"I use the word '{word}' in my daily conversations."
        elif source_lang == 'es':
            return f"Uso la palabra '{word}' en mis conversaciones diarias."
        elif source_lang == 'hi':
            return f"मैं अपनी दैनिक बातचीत में '{word}' शब्द का प्रयोग करता हूं।"
        
        return f"Example sentence with '{word}'"
    
    def get_word_complexity(self, word: str, language: str = 'en') -> float:
        """Calculate word complexity score (0-1, where 1 is most complex)"""
        # Simple complexity calculation
        factors = {
            'length': min(len(word) / 20, 1.0),  # Longer words are more complex
            'has_hyphen': 0.3 if '-' in word else 0,
            'has_apostrophe': 0.2 if "'" in word else 0,
            'has_digits': 0.5 if any(char.isdigit() for char in word) else 0,
            'uppercase_count': sum(1 for char in word if char.isupper()) / len(word) if word else 0
        }
        
        complexity = sum(factors.values()) / len(factors)
        return min(complexity, 1.0)