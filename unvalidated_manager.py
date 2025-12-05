import sqlite3
import  logging
from datetime import datetime
from translation_service import GoogletransTranslationService

class UnvalidatedWordManager:
    def __init__(self, db_path="transcriptions.db", batch_size=10):
        self.db_path = db_path
        self.batch_size = batch_size
        self.translation_service = GoogletransTranslationService()
        self.logger = logging.getLogger(__name__)
        self.__init_db()

    def __init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
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
                audio_file_reference TEXT,
                confidence_score REAL DEFAULT 1.0
            )
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_unvalidated 
            ON translations(is_validated, created_at)
        ''')
        
        conn.commit()
        conn.close()
    
    def process_unvalidate_batch(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('''
            SELECT id, original_word, detected_language 
            FROM translations 
            WHERE is_validated = 0 
            ORDER BY created_at 
            LIMIT ?
        ''', (self.batch_size,))

        words = [dict(row) for row in cursor.fetchall()]

        if not words:
            conn.close()
            return 0
        
        texts = [word['original_word'] for word in words]

        try:
            for i, word in enumerate(words):
                if not word['detected_language'] or word['detected_language'] == 'unknown':
                    detected_lang = self.translation_service.detect_language(word['original_word'])
                    words[i]['detected_language'] = detected_lang

            for word in words:
                translations = self.translation_service.translate_to_all(
                    word['original_word']
                )
                cursor.execute('''
                    UPDATE translations 
                    SET translation_en = ?, 
                        translation_es = ?, 
                        translation_hi = ?,
                        detected_language = ?,
                        is_validated = 1,
                        validated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (
                    translations.get('en'),
                    translations.get('es'),
                    translations.get('hi'),
                    translations.get('detected_lang'),
                    word['id']
                ))
                conn.commit()
                self.logger.info(f"Processed {len(words)} unvalidated words")
        except Exception as e:
            conn.rollback()
            self.logger.error(f"Error processing batch: {e}")
            raise
        finally:
            conn.close()
        
        return len(words)
    
    
    def process_pending(self, translation_service):
        """Process all pending words using translation service"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get pending words
        cursor.execute('''
            SELECT id, original_word, detected_language 
            FROM translations 
            WHERE is_validated = 0
            ORDER BY created_at
        ''')
        
        pending_words = cursor.fetchall()
        processed = []
        
        for word_id, original_word, detected_lang in pending_words:
            try:
                # Get translations
                translations = translation_service.translate_to_all(original_word)
                
                # Update database
                cursor.execute('''
                    UPDATE translations 
                    SET translation_en = ?, 
                        translation_es = ?, 
                        translation_hi = ?,
                        detected_language = ?,
                        is_validated = 1,
                        validated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (
                    translations.get('en'),
                    translations.get('es'),
                    translations.get('hi'),
                    translations.get('detected_lang'),
                    word_id
                ))
                
                processed.append({
                    'id': word_id,
                    'word': original_word,
                    'translations': translations
                })
                
            except Exception as e:
                print(f"Error processing word {original_word}: {e}")
                # Mark as error
                cursor.execute('''
                    UPDATE translations 
                    SET is_validated = -1
                    WHERE id = ?
                ''', (word_id,))
        
        conn.commit()
        conn.close()
        
        return processed