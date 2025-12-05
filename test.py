from translation_service import GoogletransTranslationService

def test_translation():
    translator = GoogletransTranslationService()
    
    # Test texts in different languages
    test_texts = [
        ("how are you doing?", "English test")
        # ("Hola, ¿cómo estás?", "Spanish test"),
        # ("नमस्ते, आप कैसे हैं?", "Hindi test")
    ]
    
    for text, description in test_texts:
        print(f"\n{description}:")
        print(f"Original: {text}")
        
        # Detect language
        lang = translator.detect_language(text)
        print(f"Detected language: {lang}")
        
        # Translate to all languages
        translations = translator.translate_to_all(text)
        print(f"English: {translations.get('en')}")
        print(f"Spanish: {translations.get('es')}")
        print(f"Hindi: {translations.get('hi')}")

if __name__ == "__main__":
    test_translation()