# transcriber.py - Updated with unvalidated word saving
import os, queue, json, sqlite3, time, threading, wave
import sounddevice as sd
import vosk
import logging
import offline_manager
from datetime import datetime

# Setup logging
logger = logging.getLogger(__name__)

# Paths to models
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")

MODEL_PATHS = {
    "en": os.path.join(MODELS_DIR, "vosk-model-small-en-us-0.15"), 
    "es": os.path.join(MODELS_DIR, "vosk-model-small-es-0.42"),
    "hi": os.path.join(MODELS_DIR, "vosk-model-small-hi-0.22")
}

recognizers = {}
for lang, path in MODEL_PATHS.items():
    if not os.path.exists(path):
        raise FileNotFoundError(f"Download model for {lang} from: https://alphacephei.com/vosk/models")
    model = vosk.Model(path)
    recognizers[lang] = vosk.KaldiRecognizer(model, 16000)


DB_FILE = "transcriptions.db"
AUDIO_DIR = "audio_clips"
os.makedirs(AUDIO_DIR, exist_ok=True)

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

q = queue.Queue()

def init_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transcripts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            language TEXT,
            text TEXT,
            audio_file TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS translations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_word TEXT NOT NULL,
            detected_language TEXT NOT NULL,
        
            -- Translations
            translation_en TEXT,
            translation_es TEXT,
            translation_hi TEXT,
        
            -- Meanings (in different languages)
            meaning_en TEXT,
            meaning_es TEXT,
            meaning_hi TEXT,
        
            -- Part of speech
            part_of_speech TEXT,
        
            -- Context and metadata
            context TEXT,
            source TEXT DEFAULT 'transcription',
            is_validated INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            validated_at TIMESTAMP,
            is_offline INTEGER DEFAULT 0,
        
            -- Additional metadata
            example_sentence TEXT,
            synonyms TEXT,  -- JSON array of synonyms
            frequency_score REAL DEFAULT 0.0
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            user_input TEXT NOT NULL,
            input_language TEXT NOT NULL,
            response_en TEXT,
            response_es TEXT,
            response_hi TEXT,
            translation_source TEXT DEFAULT 'unknown',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    return conn

conn = init_db()

def init_json_files():
    """Initialize JSON files for offline storage"""
    json_files = {
        "unvalidated": os.path.join(DATA_DIR, "unvalidated.json"),
        "validated": os.path.join(DATA_DIR, "validated.json")
    }
    
    for name, path in json_files.items():
        if not os.path.exists(path):
            with open(path, 'w', encoding='utf-8') as f:
                json.dump([], f, ensure_ascii=False, indent=2)
            logger.info(f"Created {name}.json")
    
    return json_files

json_files = init_json_files()

def save_to_json_with_meaning(file_type, word_data, meanings=None):
    enriched_data = {
        **word_data,
        'meanings': meanings or {},
        'timestamp':datetime.now().isoformat(),
        'enriched':True
    }

    return save_to_json(file_type=file_type, data=enriched_data)

def save_to_json(file_type, data):
    """Save data to JSON file"""
    try:
        filepath = json_files.get(file_type)
        if not filepath:
            logger.error(f"Unknown file type: {file_type}")
            return False
        
        # Read existing data
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
        else:
            existing_data = []
        
        # Add new data
        if isinstance(data, list):
            existing_data.extend(data)
        else:
            existing_data.append(data)
        
        # Save back
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(existing_data, f, ensure_ascii=False, indent=2)
        
        logger.debug(f"Saved to {file_type}.json: {data.get('word', 'data') if isinstance(data, dict) else 'list'}")
        return True
        
    except Exception as e:
        logger.error(f"Error saving to JSON {file_type}: {e}")
        return False

def save_transcript(text, lang, audio_path=None):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO transcripts (timestamp, language, text, audio_file) VALUES (?, ?, ?, ?)",
        (ts, lang, text, audio_path)
    )
    conn.commit()
    
    # Also extract and save words to JSON
    saved_count = extract_and_save_words(text, lang, audio_path)
    
    if saved_count > 0:
        logger.info(f"📝 Saved {saved_count} words to JSON from: '{text}'")
    
    return saved_count

def extract_and_save_words(text, lang, audio_path=None):
    """Extract words from transcript and save to unvalidated JSON"""
    # Split into words and clean them
    words = text.split()
    saved_count = 0
    
    common_words = {
        'en': {'the', 'be', 'to', 'of', 'and', 'a', 'in', 'that', 'have', 'i', 'it', 'for', 'not', 'on', 'with', 'as', 'you', 'do', 'at'},
        'es': {'el', 'la', 'de', 'que', 'y', 'a', 'en', 'un', 'ser', 'se', 'no', 'haber', 'por', 'con', 'su', 'para', 'como', 'estar'},
        'hi': {'और', 'है', 'से', 'का', 'एक', 'में', 'की', 'को', 'यह', 'वह', 'न', 'कर', 'ने', 'पर', 'भी', 'तो', 'हो', 'था', 'ही'}
    }
    
    # Check online status once
    online_status = is_online()
    
    for word in words:
        word_clean = word.strip('.,!?;:"\'()[]{}').lower()
        
        # Only save meaningful words
        if len(word_clean) > 2 and word_clean.isalpha():
            # Check if word is common
            is_common = False
            for lang_code, common_set in common_words.items():
                if word_clean in common_set:
                    is_common = True
                    break
            
            if not is_common:
                # Save to unvalidated JSON - ALWAYS save when offline, optional when online
                if not online_status:  # Only save when offline
                    unvalidated_entry = {
                        "word": word_clean,
                        "language": lang,
                        "context": text,
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "audio_reference": audio_path,
                        "source": "transcription",
                        "status": "pending",
                        "is_offline": True
                    }
                    
                    if save_to_json("unvalidated", unvalidated_entry):
                        saved_count += 1
                        print(f"💾 Saved offline word to JSON: '{word_clean}' ({lang})")
                else:
                    # When online, we could still save for learning purposes
                    # But for now, just log it
                    print(f"📝 Online word (not saved): '{word_clean}'")
    
    if saved_count > 0:
        print(f"📝 Saved {saved_count} words from transcription to unvalidated.json")
    
    return saved_count


# In transcriber.py, update the save_unvalidated_word function:
def save_unvalidated_word(word, lang, context="", audio_path=""):
    """Save a word to the unvalidated table WITHOUT audio reference"""
    try:
        cursor = conn.cursor()
        
        # Check if word already exists in translations table
        cursor.execute('''
            SELECT id FROM translations 
            WHERE original_word = ? AND detected_language = ?
        ''', (word, lang))
        
        existing = cursor.fetchone()
        
        if not existing:
            # Save to translations table WITHOUT audio_file_reference
            cursor.execute('''
                INSERT INTO translations 
                (original_word, detected_language, context, source, is_validated)
                VALUES (?, ?, ?, 'transcription', 0)
            ''', (word, lang, context))
            conn.commit()
            print(f"💾 Saved unvalidated word: '{word}' ({lang})")
        else:
            print(f"📝 Word '{word}' already exists in translations table")
            
    except Exception as e:
        print(f"Error saving unvalidated word: {e}")

def extract_potential_new_words(text, lang):
    """Extract potential new words from text"""
    # Simple implementation - you can enhance this
    words = text.split()
    new_words = []
    
    for word in words:
        word = word.strip('.,!?;:"\'()[]{}').lower()
        if len(word) > 2:  # Only consider words longer than 2 characters
            # Check if word contains only letters
            if word.isalpha():
                new_words.append(word)
    
    return new_words

def save_audio_chunk(raw_data, lang):
    ts = time.strftime("%Y%m%d_%H%M%S")
    filename = f"{lang}_{ts}.wav"
    filepath = os.path.join(AUDIO_DIR, filename)
    with wave.open(filepath, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(raw_data)
    return filepath

def audio_callback(indata, frames, time, status):
    if status:
        print("Audio status:", status, flush=True)
    q.put(bytes(indata))

def is_online():
    """Check if internet connection is available"""
    try:
        import socket
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        return True
    except OSError:
        return False

def transcribe_loop():
    with sd.RawInputStream(samplerate=16000, blocksize=8000,
                           dtype="int16", channels=1,
                           callback=audio_callback):
        print("🎤 Listening... (checking EN, ES, HI)")
        while True:
            data = q.get()
            for lang, rec in recognizers.items():
                if rec.AcceptWaveform(data):
                    result = json.loads(rec.Result())
                    text = result.get("text", "").strip()
                    if text:
                        audio_path = save_audio_chunk(data, lang)
                        print(f"[{lang.upper()}] {text}  🎵 saved {audio_path}")
                        
                        # Save transcript to database
                        save_transcript(text, lang, audio_path)
                        
                        # Extract and save words to JSON - ADD THIS
                        saved_count = extract_and_save_words(text, lang, audio_path)
                        if saved_count > 0:
                            print(f"   💾 Saved {saved_count} words to unvalidated.json")
                        
                        # Old logic for backward compatibility
                        if not is_online():
                            potential_words = extract_potential_new_words(text, lang)
                            for word in potential_words:
                                save_unvalidated_word(word, lang, text, audio_path)

def detect_language_from_audio(audio_data):
    results = {}
    for lang, recognizer in recognizers.items():
        if recognizer.AcceptWaveform(audio_data):
            result = json.loads(recognizer.Result())
            text = result.get("text", "").strip()
            confidence = result.get("confidence", 0)
            if text:
                results[lang] = {
                    "confidence": confidence,
                    "text": text
                }
    if results:
        best_lang = max(results.items(), key=lambda x: x[1]["confidence"])
        return best_lang[0], best_lang[1]["text"]
    return None, ""

def get_json_stats():
    """Get statistics about JSON files"""
    stats = {
        "unvalidated": 0,
        "validated": 0
    }
    
    for file_type, filepath in json_files.items():
        try:
            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                stats[file_type] = len(data)
        except:
            pass
    
    return stats

def transcribe_with_language(audio_data, language='en'):
    if language in recognizers:
        recognizer = recognizers[language]
        if recognizer.AcceptWaveform(audio_data):
            result = json.loads(recognizer.Result())
            return result.get("text", "")
    return ""

def start_transcriber():
    t = threading.Thread(target=transcribe_loop, daemon=True)
    t.start()