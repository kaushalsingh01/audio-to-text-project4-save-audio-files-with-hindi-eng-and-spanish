# transcriber.py - Updated with unvalidated word saving
import os, queue, json, sqlite3, time, threading, wave
import sounddevice as sd
import vosk

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

q = queue.Queue()

def init_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cursor = conn.cursor()
    
    # Create transcripts table if not exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transcripts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            language TEXT,
            text TEXT,
            audio_file TEXT
        )
    """)
    
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
    
    conn.commit()
    return conn

conn = init_db()

def save_transcript(text, lang, audio_path=None):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO transcripts (timestamp, language, text, audio_file) VALUES (?, ?, ?, ?)",
        (ts, lang, text, audio_path)
    )
    conn.commit()

def save_unvalidated_word(word, lang, context="", audio_path=""):
    """Save a word to the unvalidated table"""
    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO translations 
            (original_word, detected_language, context, source, is_validated, audio_file_reference)
            VALUES (?, ?, ?, 'transcription', 0, ?)
        ''', (word, lang, context, audio_path))
        conn.commit()
        print(f"💾 Saved unvalidated word: '{word}' ({lang})")
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
                        save_transcript(text, lang, audio_path)
                        
                        # Check for new/unvalidated words
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