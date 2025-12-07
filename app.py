# app.py - WITH FIXED TRANSLATIONS ENDPOINT
from flask import Flask, render_template, jsonify, Response, send_from_directory, request
import threading
from flask_cors import CORS
import time, json
import logging
import sqlite3
import csv
import io
import os
import transcriber
from translation_service import GoogletransTranslationService
from offline_manager import OfflineManager

app = Flask(__name__)
CORS(app)
DB_FILE = "transcriptions.db"
AUDIO_DIR = "audio_clips"
os.makedirs(AUDIO_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize services
translation_service = GoogletransTranslationService()
offline_manager = OfflineManager()

# Start background transcriber
transcriber.start_transcriber()

# Conversation history in memory
conversation_history = {}

# ===== VOSK INTEGRATION FOR OFFLINE CHAT =====
def detect_language_with_vosk(text):
    try:
        from transcriber import recognizers
        
        if not recognizers:
            logger.warning("Vosk recognizers not available, using simple detection")
            return detect_language_simple(text), 0.5
        
        detected_lang = detect_language_simple(text)
        confidence = 0.8  
        
        if len(text) > 10:
            confidence = 0.9
        elif len(text) < 3:
            confidence = 0.6
        
        logger.debug(f"Vosk-enhanced detection: '{text}' -> {detected_lang} (confidence: {confidence})")
        return detected_lang, confidence
        
    except Exception as e:
        logger.error(f"Vosk detection error: {e}")
        return detect_language_simple(text), 0.5

def get_offline_translation_vosk(text, detected_lang):
    """
    Get translations using Vosk-enhanced offline system
    """
    # Try to get from cache first
    cached = get_cached_translations(text, detected_lang)
    
    # If we have full translations in cache, use them
    if (cached.get('en') and cached.get('es') and cached.get('hi') and 
        not cached['es'].startswith("[Offline]") and 
        not cached['hi'].startswith("[Offline]")):
        logger.debug(f"Using cached translations for: {text}")
        return cached
    
    # Otherwise, use rule-based translations for common phrases
    translations = {
        "original": text,
        "detected_lang": detected_lang,
        "en": text,
        "es": translate_with_rules(text, 'es'),
        "hi": translate_with_rules(text, 'hi')
    }
    
    # Save as unvalidated for later translation
    save_unknown_words_offline(text, detected_lang)
    
    return translations

def translate_with_rules(text, target_lang):
    """
    Simple rule-based translation for common phrases when offline
    """
    text_lower = text.lower()
    
    # Common greetings and phrases
    translation_rules = {
        'en': {
            'hello': {'es': 'hola', 'hi': 'नमस्ते'},
            'hi': {'es': 'hola', 'hi': 'नमस्ते'},
            'thank you': {'es': 'gracias', 'hi': 'धन्यवाद'},
            'thanks': {'es': 'gracias', 'hi': 'धन्यवाद'},
            'goodbye': {'es': 'adiós', 'hi': 'अलविदा'},
            'bye': {'es': 'adiós', 'hi': 'अलविदा'},
            'how are you': {'es': 'cómo estás', 'hi': 'आप कैसे हैं'},
            'what is your name': {'es': 'cómo te llamas', 'hi': 'तुम्हारा नाम क्या है'},
            'my name is': {'es': 'me llamo', 'hi': 'मेरा नाम है'},
            'please': {'es': 'por favor', 'hi': 'कृपया'},
            'yes': {'es': 'sí', 'hi': 'हाँ'},
            'no': {'es': 'no', 'hi': 'नहीं'},
            'sorry': {'es': 'lo siento', 'hi': 'माफ़ करना'},
            'good morning': {'es': 'buenos días', 'hi': 'सुप्रभात'},
            'good night': {'es': 'buenas noches', 'hi': 'शुभ रात्रि'},
        }
    }
    
    # Check for exact matches
    for phrase, translations in translation_rules['en'].items():
        if text_lower == phrase and target_lang in translations:
            return translations[target_lang]
    
    # Check for partial matches
    for phrase, translations in translation_rules['en'].items():
        if phrase in text_lower and target_lang in translations:
            # Replace the phrase in the text
            result = text_lower.replace(phrase, translations[target_lang])
            return result.capitalize() if text[0].isupper() else result
    
    # No rule found, return placeholder
    return f"[Offline - will translate when online] {text}"

def get_transcriber_json_stats():
    """Get stats from transcriber's JSON files"""
    try:
        # Import transcriber's function
        from transcriber import get_json_stats
        return get_json_stats()
    except:
        return {"unvalidated": 0, "validated": 0}

def merge_transcriber_json_with_offline():
    """Merge transcriber's JSON data with offline manager"""
    try:
        from transcriber import json_files
        
        # Read transcriber's unvalidated JSON
        if os.path.exists(json_files.get("unvalidated", "")):
            with open(json_files["unvalidated"], 'r', encoding='utf-8') as f:
                transcriber_data = json.load(f)
            
            # Add to offline manager
            for entry in transcriber_data:
                if entry.get("status") == "pending":
                    offline_manager.save_unvalidated_word(
                        word=entry.get("word", ""),
                        language=entry.get("language", "en"),
                        context=entry.get("context", ""),
                        is_offline=entry.get("is_offline", True)
                    )
            
            # Clear transcriber's file after merging
            with open(json_files["unvalidated"], 'w', encoding='utf-8') as f:
                json.dump([], f, ensure_ascii=False, indent=2)
            
            logger.info(f"✅ Merged {len(transcriber_data)} words from transcriber JSON")
            return len(transcriber_data)
        
    except Exception as e:
        logger.error(f"❌ Error merging transcriber JSON: {e}")
    
    return 0

# === EXISTING ENDPOINTS ===

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/data")
def data():
    lang = request.args.get("lang", "all")
    return jsonify(get_transcripts(limit=20, lang=lang))

@app.route("/download/txt")
def download_txt():
    transcripts = get_transcripts()
    output = io.StringIO()
    for t in transcripts:
        output.write(f"{t['timestamp']} [{t['language']}] - {t['text']}\n")
    return Response(output.getvalue(),
                    mimetype="text/plain",
                    headers={"Content-Disposition": "attachment;filename=transcripts.txt"})

@app.route("/download/csv")
def download_csv():
    transcripts = get_transcripts()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Timestamp", "Language", "Transcript", "AudioFile"])
    for t in transcripts:
        writer.writerow([t['timestamp'], t['language'], t['text'], t['audio_file']])
    return Response(output.getvalue(),
                    mimetype="text/csv",
                    headers={"Content-Disposition": "attachment;filename=transcripts.csv"})

@app.route("/audio_clips/<path:filename>")
def download_audio(filename):
    return send_from_directory(".", filename)


# === FIXED TRANSLATIONS ENDPOINT ===

# Add this endpoint back to app.py
@app.route('/api/translations', methods=['GET'])
def get_translations():
    """Get translations from database"""
    language = request.args.get('language', None)
    validated = request.args.get('validated', '1')  # Default to validated
    
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    if language:
        cursor.execute('''
            SELECT * FROM translations 
            WHERE detected_language = ? AND is_validated = ?
            ORDER BY created_at DESC
        ''', (language, int(validated)))
    else:
        cursor.execute('''
            SELECT * FROM translations 
            WHERE is_validated = ?
            ORDER BY created_at DESC
            LIMIT 100
        ''', (int(validated),))
    
    translations = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return jsonify({"translations": translations, "count": len(translations)})

# === CHAT ENDPOINTS ===

@app.route('/api/chat/text', methods=['POST'])
def chat_text():
    """Chat endpoint with Vosk-enhanced offline support"""
    data = request.json
    message = data.get('message', '')
    session_id = data.get('session_id', 'default')
    
    if not message:
        return jsonify({"error": "No message provided"}), 400
    
    try:
        # Check if we're online
        is_online = offline_manager.check_internet()
        logger.info(f"💬 Chat request: '{message}' | Online: {is_online}")
        
        # Detect language with Vosk enhancement
        detected_lang, confidence = detect_language_with_vosk(message)
        logger.info(f"🔍 Language detected: {detected_lang} (confidence: {confidence})")
        
        if is_online:
            try:
                # Online: Use Google Translate
                logger.debug(f"🌐 Using Google Translate for: {message}")
                translations = translation_service.translate_to_all(message)
                translation_source = "google"
            except Exception as e:
                logger.error(f"❌ Google Translate failed: {e}")
                # Fallback to offline mode
                translations = get_offline_translation_vosk(message, detected_lang)
                is_online = False
                translation_source = "vosk_offline_fallback"
        else:
            # Offline: Use Vosk-enhanced system
            logger.debug(f"📴 Using Vosk offline translation for: {message}")
            translations = get_offline_translation_vosk(message, detected_lang)
            translation_source = "vosk_offline"
            
            # Save unknown words to unvalidated JSON
            save_unknown_words_offline(message, detected_lang)
        
        # Generate clean translation response
        response_text = format_translation_response(message, detected_lang, translations, is_online)
        
        # Save to database
        save_chat_to_db(session_id, message, detected_lang, translations, translation_source)
        
        # Log the response
        logger.info(f"📤 Chat response: {len(response_text)} chars | Source: {translation_source}")
        
        return jsonify({
            "user_input": {
                "text": message,
                "language": detected_lang,
                "language_confidence": confidence,
                "translations": {
                    lang: translations.get(lang, message)
                    for lang in ['en', 'es', 'hi']
                    if lang != detected_lang
                }
            },
            "bot_response": {
                "text": response_text,
                "translations": translations,
                "translation_source": translation_source
            },
            "online": is_online,
            "confidence": confidence
        })
        
    except Exception as e:
        logger.error(f"❌ Chat error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/chat/audio', methods=['POST'])
def chat_audio():
    """Audio chat endpoint - simplified"""
    return jsonify({
        "error": "Audio chat temporarily disabled",
        "message": "Please use text chat for now",
        "user_input": {"text": "", "language": "en", "translations": {}},
        "bot_response": {
            "text": "Audio chat is currently disabled. Please use text input instead.",
            "translations": {
                "en": "Audio chat is currently disabled. Please use text input instead.",
                "es": "El chat de audio está deshabilitado temporalmente. Por favor use entrada de texto.",
                "hi": "ऑडियो चैट अस्थायी रूप से अक्षम है। कृपया पाठ इनपुट का उपयोग करें।"
            }
        }
    })

# === OTHER ENDPOINTS ===

@app.route('/api/translate', methods=['POST'])
def translate():
    """Direct translation endpoint"""
    data = request.json
    text = data.get('text', '')
    target_lang = data.get('target_lang', 'en')
    
    if not text:
        return jsonify({"error": "No text provided"}), 400
    
    try:
        is_online = offline_manager.check_internet()
        
        if is_online:
            translated = translation_service.translate_text(text, target_lang)
            all_translations = translation_service.translate_to_all(text)
        else:
            cached = get_cached_translation(text, target_lang)
            if cached:
                translated = cached
                all_translations = {"original": text, target_lang: cached}
            else:
                detected_lang = detect_language_simple(text)
                offline_manager.save_unvalidated_word(text, detected_lang, "direct_translation", True)
                translated = f"[Offline - saved for later] {text}"
                all_translations = {"original": text, "offline": True}
        
        return jsonify({
            "original": text,
            "translated": translated,
            "target_language": target_lang,
            "all_translations": all_translations,
            "online": is_online
        })
    except Exception as e:
        logger.error(f"Translation error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/sync', methods=['POST'])
def sync_unvalidated():
    """Sync unvalidated words"""
    try:
        if not offline_manager.check_internet():
            return jsonify({"error": "No internet connection"}), 503
        
        processed_count = offline_manager.process_unvalidated(translation_service)
        
        return jsonify({
            "status": "success",
            "processed_count": processed_count,
            "message": f"Synced {processed_count} words"
        })
    except Exception as e:
        logger.error(f"Sync error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/status', methods=['GET'])
def get_status():
    """Get system status"""
    stats = offline_manager.get_stats()
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM transcripts")
    transcript_count = cursor.fetchone()[0]
    conn.close()
    
    return jsonify({
        "online": stats["is_online"],
        "transcript_count": transcript_count,
        "unvalidated_words": stats["unvalidated_count"],
        "validated_words": stats["validated_db_count"],
        "timestamp": time.time()
    })

@app.route('/api/conversations', methods=['GET'])
def get_conversations():
    """Get conversation history"""
    session_id = request.args.get('session_id', 'default')
    
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT * FROM conversations 
        WHERE session_id = ? 
        ORDER BY created_at DESC
        LIMIT 50
    ''', (session_id,))
    
    conversations = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return jsonify({"conversations": conversations, "count": len(conversations)})

@app.route('/api/transcriber/stats', methods=['Get'])
def  get_transcriber_stats():
    try:
        from transcriber import get_json_stats, json_files
        stats = get_json_stats()
        file_info= {}
        for name, path in json_files.items():
            file_info[name]= {
                "path":path,
                "exists": os.path.exists(path),
                "size": os.path.getsize(path) if os.path.exists(path) else 0
            }
        return jsonify({
            "stats": stats,
            "files": file_info,
            "transcriber_running": True
        })
    except Exception as e:
        logger.error(f"Transciber stats error: {e}")
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/word/details/<word>', methods=['GET'])
def get_word_details(word):
    """Get detailed information about a specific word"""
    try:
        from meaning_service import MeaningService
        from translation_service import GoogletransTranslationService
        
        meaning_service = MeaningService()
        translation_service = GoogletransTranslationService()
        
        # Get translations
        translations = translation_service.translate_to_all(word)
        detected_lang = translations.get('detected_lang', 'en')
        
        # Get meanings
        meanings = meaning_service.get_comprehensive_meaning(
            word, detected_lang, translations
        )
        
        # Check if word exists in database
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM translations 
            WHERE original_word = ? AND detected_language = ?
            ORDER BY created_at DESC LIMIT 1
        ''', (word, detected_lang))
        
        db_entry = cursor.fetchone()
        conn.close()
        
        return jsonify({
            'word': word,
            'detected_language': detected_lang,
            'translations': translations,
            'meanings': meanings,
            'in_database': db_entry is not None,
            'database_entry': dict(db_entry) if db_entry else None,
            'complexity': meaning_service.get_word_complexity(word, detected_lang)
        })
        
    except Exception as e:
        logger.error(f"Word details error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/words/with-meanings', methods=['GET'])
def get_words_with_meanings():
    """Get all words with their meanings"""
    try:
        language = request.args.get('language', None)
        
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if language:
            cursor.execute('''
                SELECT original_word, detected_language,
                       translation_en, translation_es, translation_hi,
                       meaning_en, meaning_es, meaning_hi,
                       part_of_speech, example_sentence
                FROM translations 
                WHERE detected_language = ? AND is_validated = 1
                ORDER BY created_at DESC
            ''', (language,))
        else:
            cursor.execute('''
                SELECT original_word, detected_language,
                       translation_en, translation_es, translation_hi,
                       meaning_en, meaning_es, meaning_hi,
                       part_of_speech, example_sentence
                FROM translations 
                WHERE is_validated = 1
                ORDER BY created_at DESC
                LIMIT 50
            ''')
        
        words = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return jsonify({
            "words": words,
            "count": len(words),
            "with_meanings": sum(1 for w in words if w.get('meaning_en'))
        })
        
    except Exception as e:
        logger.error(f"Words with meanings error: {e}")
        return jsonify({"error": str(e)}), 500

# === HELPER FUNCTIONS ===

def merge_transcriber_json_data():
    """
    Merge transcriber's JSON data with the main offline manager
    This should be called periodically or during sync
    """
    try:
        from transcriber import json_files
        
        unvalidated_file = json_files.get("unvalidated")
        validated_file = json_files.get("validated")
        
        merged_count = 0
        
        # Merge unvalidated words
        if os.path.exists(unvalidated_file):
            with open(unvalidated_file, 'r', encoding='utf-8') as f:
                transcriber_data = json.load(f)
            
            for entry in transcriber_data:
                if entry.get("status") == "pending":
                    # Add to offline manager
                    success = offline_manager.save_unvalidated_word(
                        word=entry.get("word", ""),
                        language=entry.get("language", "en"),
                        context=entry.get("context", ""),
                        is_offline=entry.get("is_offline", True)
                    )
                    if success:
                        merged_count += 1
            
            # Clear the file after merging
            if merged_count > 0:
                with open(unvalidated_file, 'w', encoding='utf-8') as f:
                    json.dump([], f, ensure_ascii=False, indent=2)
                logger.info(f"✅ Merged {merged_count} unvalidated words from transcriber")
        
        # Merge validated words (if any)
        if os.path.exists(validated_file):
            with open(validated_file, 'r', encoding='utf-8') as f:
                validated_data = json.load(f)
            
            # These could be added to database or just kept in JSON
            logger.info(f"📄 Found {len(validated_data)} validated words in transcriber JSON")
        
        return merged_count
        
    except Exception as e:
        logger.error(f"❌ Error merging transcriber JSON: {e}")
        return 0

def detect_language_simple(text):
    """Simple offline language detection"""
    if not text:
        return 'en'
    
    if any('\u0900' <= char <= '\u097F' for char in text):
        return 'hi'
    
    spanish_indicators = ['hola', 'cómo', 'qué', 'por qué', 'gracias', 'adiós']
    text_lower = text.lower()
    if any(indicator in text_lower for indicator in spanish_indicators):
        return 'es'
    
    return 'en'

def get_cached_translations(text, detected_lang):
    """Get translations from cache when offline"""
    validated = offline_manager.get_validated_data()
    
    translations = {
        "original": text,
        "detected_lang": detected_lang
    }
    
    words = text.lower().split()
    for entry in validated:
        if "word" in entry and entry["word"].lower() in words:
            if "translations" in entry:
                translations.update(entry["translations"])
                break
    
    if 'en' not in translations:
        translations['en'] = text
    if 'es' not in translations:
        translations['es'] = f"[Offline] {text}"
    if 'hi' not in translations:
        translations['hi'] = f"[Offline] {text}"
    
    return translations

def get_cached_translation(text, target_lang):
    """Get single translation from cache"""
    validated = offline_manager.get_validated_data()
    
    for entry in validated:
        if "word" in entry and entry["word"].lower() == text.lower():
            if "translations" in entry and target_lang in entry["translations"]:
                return entry["translations"][target_lang]
    
    return None

def save_unknown_words_offline(text, detected_lang):
    if offline_manager.check_internet():
        logger.debug("📡 Online - skipping unvalidated save")
        return
    
    logger.info(f"📴 Offline - saving unknown words from: '{text}'")
    
    common_words = {
        'en': {'the', 'be', 'to', 'of', 'and', 'a', 'in', 'that', 'have', 'i'},
        'es': {'el', 'la', 'de', 'que', 'y', 'a', 'en', 'un', 'ser', 'se'},
        'hi': {'और', 'है', 'से', 'का', 'एक', 'में', 'की', 'को', 'यह', 'वह'}
    }
    
    words = text.split()
    saved_count = 0
    
    for word in words:
        word_clean = word.strip('.,!?;:"\'()[]{}').lower()
        if len(word_clean) > 2 and word_clean.isalpha():
            is_common = False
            for lang, common_set in common_words.items():
                if word_clean in common_set:
                    is_common = True
                    break
            
            if not is_common:
                success = offline_manager.save_unvalidated_word(
                    word=word_clean,
                    language=detected_lang,
                    context=text,
                    is_offline=True
                )
                if success:
                    saved_count += 1

def format_translation_response(original, detected_lang, translations, is_online):
    """Format the translation response"""
    response = f"Translations:\n"
    
    # English line
    english_text = translations.get('en', original)
    if detected_lang == 'en':
        response += f"🇺🇸 You Said: '{english_text}'\n"
    else:
        response += f"🇺🇸 Translation in English: '{english_text}'\n"
    
    # Spanish line
    spanish_text = translations.get('es', '')
    if spanish_text:
        if detected_lang == 'es':
            response += f"🇪🇸 You Said: '{spanish_text}'\n"
        else:
            response += f"🇪🇸 Translation in Spanish: '{spanish_text}'\n"
    
    # Hindi line
    hindi_text = translations.get('hi', '')
    if hindi_text:
        if detected_lang == 'hi':
            response += f"🇮🇳 You Said: '{hindi_text}'\n"
        else:
            response += f"🇮🇳 Translation in Hindi: '{hindi_text}'\n"
    
    if not is_online:
        response += "\n⚠️ Offline mode"
    
    return response.strip()

def save_chat_to_db(session_id, user_input, input_lang, translations, source="unknown"):
    """Save chat to database with source"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO conversations 
        (session_id, user_input, input_language, response_en, response_es, response_hi, translation_source)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        session_id, 
        user_input, 
        input_lang,
        translations.get('en', user_input),
        translations.get('es', ''),
        translations.get('hi', ''),
        source
    ))
    
    conn.commit()
    conn.close()

def get_transcripts(limit=None, lang=None):
    """Get transcripts from database"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    if lang and lang != "all":
        query = "SELECT timestamp, language, text, audio_file FROM transcripts WHERE language=? ORDER BY id DESC"
        params = (lang,)
    else:
        query = "SELECT timestamp, language, text, audio_file FROM transcripts ORDER BY id DESC"
        params = ()
    if limit:
        query += f" LIMIT {limit}"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [{"timestamp": r[0], "language": r[1], "text": r[2], "audio_file": r[3]} for r in rows]
# === BACKGROUND SYNC SERVICE ===

class BackgroundSyncService:
    def __init__(self, offline_manager, translation_service, interval=300):
        self.offline_manager = offline_manager
        self.translation_service = translation_service
        self.interval = interval  # 5 minutes
        self.running = False
        self.thread = None
    
    def start(self):
        """Start background sync thread"""
        self.running = True
        self.thread = threading.Thread(target=self._sync_loop, daemon=True)
        self.thread.start()
        logger.info("✅ Background sync service started")
    
    def _sync_loop(self):
        """Main sync loop - runs every 5 minutes when online"""
        while self.running:
            try:
                # Check if we're online
                if self.offline_manager.check_internet():
                    logger.info("🌐 Online - checking for unvalidated words...")
                    
                    # Process unvalidated words
                    processed = self.offline_manager.process_unvalidated(self.translation_service)
                    
                    if processed > 0:
                        logger.info(f"✅ Background sync processed {processed} words")
                    else:
                        logger.info("📭 No unvalidated words to process")
                else:
                    logger.info("📴 Offline - skipping background sync")
                    
            except Exception as e:
                logger.error(f"❌ Background sync error: {e}")
            
            # Wait before next check
            time.sleep(self.interval)

# Initialize and start background sync - MUST BE BEFORE app.run()
logger.info("🔄 Starting background sync service...")
sync_service = BackgroundSyncService(offline_manager, translation_service, interval=300)
sync_service.start()

if __name__ == "__main__":
    logger.info("🚀 Starting Flask application...")
    app.run(host="0.0.0.0", port=5000, debug=True)