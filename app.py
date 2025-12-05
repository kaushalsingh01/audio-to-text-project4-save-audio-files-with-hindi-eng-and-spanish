from flask import Flask, render_template, jsonify, Response, send_from_directory, request
import threading
from flask_cors import CORS
import time
import logging
import sqlite3
import csv
import io
import os
import transcriber
from unvalidated_manager import UnvalidatedWordManager
from translation_service import GoogletransTranslationService

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

translation_service = GoogletransTranslationService()
unvalidated_manager = UnvalidatedWordManager("transcriptions.db")

# Start background transcriber
transcriber.start_transcriber()

DB_FILE = "transcriptions.db"
AUDIO_DIR = "audio_clips"
os.makedirs(AUDIO_DIR, exist_ok=True)

# Conversation history in memory 
conversation_history = {}

# Initialize database with new tables
def init_extended_db():
    """Initialize the database with new tables for translations and conversations"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Create translations table if not exists
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS translations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_word TEXT NOT NULL,
            detected_language TEXT NOT NULL,
            translation_en TEXT,
            translation_es TEXT,
            translation_hi TEXT,
            context TEXT,
            source TEXT DEFAULT 'transcription',
            is_validated INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            validated_at TIMESTAMP,
            audio_file_reference TEXT
        )
    ''')
    
    # Create conversations table if not exists
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            user_input TEXT NOT NULL,
            input_language TEXT NOT NULL,
            response_en TEXT,
            response_es TEXT,
            response_hi TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create index for faster queries
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_unvalidated 
        ON translations(is_validated, created_at)
    ''')
    
    conn.commit()
    conn.close()
    logger.info("Extended database initialized")

# Initialize the database
init_extended_db()

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
    return send_from_directory(AUDIO_DIR, filename)

# NEW ENDPOINTS FOR CHAT AND TRANSLATION

@app.route('/api/chat/text', methods=['POST'])
def chat_text():
    """Chat endpoint for text input"""
    data = request.json
    message = data.get('message', '')
    session_id = data.get('session_id', 'default')
    
    if not message:
        return jsonify({"error": "No message provided"}), 400
    
    try:
        # Detect language
        detected_lang = translation_service.detect_language(message)
        
        # Get translations for user input
        user_translations = translation_service.translate_to_all(message)
        
        # Generate bot response
        bot_response = generate_bot_response(message, detected_lang)
        bot_translations = translation_service.translate_to_all(bot_response)
        
        # Save conversation to database
        save_conversation(session_id, message, detected_lang, 
                         bot_translations.get('en'), 
                         bot_translations.get('es'), 
                         bot_translations.get('hi'))
        
        # Add to in-memory history
        if session_id not in conversation_history:
            conversation_history[session_id] = []
        
        conversation_history[session_id].append({
            "timestamp": time.time(),
            "user_input": user_translations,
            "bot_response": bot_translations
        })
        
        return jsonify({
            "user_input": {
                "text": message,
                "language": detected_lang,
                "translations": {
                    lang: user_translations.get(lang, message)
                    for lang in ['en', 'es', 'hi']
                    if lang != detected_lang
                }
            },
            "bot_response": {
                "text": bot_response,
                "translations": {
                    'en': bot_translations.get('en', bot_response),
                    'es': bot_translations.get('es', bot_response),
                    'hi': bot_translations.get('hi', bot_response)
                }
            }
        })
    except Exception as e:
        logger.error(f"Chat error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/chat/audio', methods=['POST'])
def chat_audio():
    """Chat endpoint for audio input"""
    if 'audio' not in request.files:
        return jsonify({"error": "No audio file provided"}), 400
    
    audio_file = request.files['audio']
    session_id = request.form.get('session_id', 'default')
    
    # Save and process audio
    temp_path = f"temp_chat_{session_id}_{int(time.time())}.wav"
    audio_file.save(temp_path)
    
    try:
        # Read audio data
        import wave
        with wave.open(temp_path, 'rb') as wf:
            audio_data = wf.readframes(wf.getnframes())
        
        # Detect language and transcribe
        detected_lang, text = transcriber.detect_language_from_audio(audio_data)
        
        if not text:
            return jsonify({"error": "Could not transcribe audio"}), 400
        
        # Process as chat message
        user_translations = translation_service.translate_to_all(text)
        
        # Generate bot response
        bot_response = generate_bot_response(text, detected_lang)
        bot_translations = translation_service.translate_to_all(bot_response)
        
        # Save conversation to database
        save_conversation(session_id, text, detected_lang,
                         bot_translations.get('en'),
                         bot_translations.get('es'),
                         bot_translations.get('hi'))
        
        # Add to in-memory history
        if session_id not in conversation_history:
            conversation_history[session_id] = []
        
        conversation_history[session_id].append({
            "timestamp": time.time(),
            "user_input": user_translations,
            "bot_response": bot_translations
        })
        
        return jsonify({
            "user_input": {
                "text": text,
                "language": detected_lang,
                "translations": {
                    lang: user_translations.get(lang, text)
                    for lang in ['en', 'es', 'hi']
                    if lang != detected_lang
                }
            },
            "bot_response": {
                "text": bot_response,
                "translations": {
                    'en': bot_translations.get('en', bot_response),
                    'es': bot_translations.get('es', bot_response),
                    'hi': bot_translations.get('hi', bot_response)
                }
            }
        })
    except Exception as e:
        logger.error(f"Audio chat error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        # Clean up
        if os.path.exists(temp_path):
            os.remove(temp_path)

@app.route('/api/translate', methods=['POST'])
def translate():
    """Direct translation endpoint"""
    data = request.json
    text = data.get('text', '')
    target_lang = data.get('target_lang', 'en')
    
    if not text:
        return jsonify({"error": "No text provided"}), 400
    
    try:
        translated = translation_service.translate_text(text, target_lang)
        
        # Also get all translations for display
        all_translations = translation_service.translate_to_all(text)
        
        return jsonify({
            "original": text,
            "translated": translated,
            "target_language": target_lang,
            "all_translations": all_translations
        })
    except Exception as e:
        logger.error(f"Translation error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/sync', methods=['POST'])
def sync_unvalidated():
    """Sync unvalidated words"""
    try:
        # Check if online
        if not check_internet_connection():
            return jsonify({"error": "No internet connection"}), 503
        
        processed = unvalidated_manager.process_pending(translation_service)
        
        return jsonify({
            "status": "success",
            "processed_count": len(processed),
            "processed_words": processed
        })
    except Exception as e:
        logger.error(f"Sync error: {e}")
        return jsonify({"error": str(e)}), 500

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

@app.route('/api/translations', methods=['GET'])
def get_translations():
    """Get all validated translations"""
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
        ''', (language, validated))
    else:
        cursor.execute('''
            SELECT * FROM translations 
            WHERE is_validated = ?
            ORDER BY created_at DESC
            LIMIT 100
        ''', (validated,))
    
    translations = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return jsonify({"translations": translations, "count": len(translations)})

@app.route('/api/status', methods=['GET'])
def get_status():
    """Get system status"""
    # Check internet connection
    is_online = check_internet_connection()
    
    # Get statistics
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Count transcripts
    cursor.execute("SELECT COUNT(*) FROM transcripts")
    transcript_count = cursor.fetchone()[0]
    
    # Count unvalidated words
    cursor.execute("SELECT COUNT(*) FROM translations WHERE is_validated = 0")
    unvalidated_count = cursor.fetchone()[0]
    
    conn.close()
    
    return jsonify({
        "online": is_online,
        "transcript_count": transcript_count,
        "unvalidated_words": unvalidated_count,
        "timestamp": time.time()
    })

def save_conversation(session_id, user_input, input_lang, resp_en, resp_es, resp_hi):
    """Save conversation to database"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO conversations 
        (session_id, user_input, input_language, response_en, response_es, response_hi)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (session_id, user_input, input_lang, resp_en, resp_es, resp_hi))
    
    conn.commit()
    conn.close()

def generate_bot_response(user_message, user_lang):
    """Generate exactly the format you requested"""
    
    translations = translation_service.translate_to_all(user_message)
    
    return f"""
🇺🇸 You Said: '{translations.get('en', user_message)}'
🇪🇸 Translation in Spanish: '{translations.get('es', '')}'
🇮🇳 Translation in Hindi: '{translations.get('hi', '')}'"""

def check_internet_connection():
    """Check if internet connection is available"""
    try:
        import socket
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        return True
    except OSError:
        return False

# Background sync service
class BackgroundSyncService:
    def __init__(self, unvalidated_manager, translation_service, interval=60):
        self.manager = unvalidated_manager
        self.translation_service = translation_service
        self.interval = interval  # seconds
        self.running = False
        self.thread = None
    
    def start(self):
        """Start background sync thread"""
        self.running = True
        self.thread = threading.Thread(target=self._sync_loop, daemon=True)
        self.thread.start()
        logger.info("Background sync service started")
    
    def stop(self):
        """Stop background sync"""
        self.running = False
        if self.thread:
            self.thread.join()
    
    def _sync_loop(self):
        """Main sync loop"""
        while self.running:
            try:
                # Check internet connection
                if check_internet_connection():
                    # Process unvalidated words
                    try:
                        processed = self.manager.process_pending(self.translation_service)
                        if processed:
                            logger.info(f"Background sync processed {len(processed)} words")
                    except Exception as e:
                        logger.error(f"Error in background sync: {e}")
            except Exception as e:
                logger.error(f"Background sync error: {e}")
            
            time.sleep(self.interval)

# Initialize and start background sync
sync_service = BackgroundSyncService(unvalidated_manager, translation_service, interval=300)  # 5 minutes
sync_service.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)