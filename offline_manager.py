import json
import os
import sys
from datetime import datetime
import sqlite3
import logging
from meaning_service import MeaningService

logger = logging.getLogger(__name__)

class OfflineManager:
    def __init__(self, db_path="transcriptions.db", json_path="data/"):
        self.db_path = db_path
        self.json_path = json_path
        self.meaning_service = MeaningService()
        
        # Ensure JSON directory exists
        try:
            os.makedirs(self.json_path, exist_ok=True)
            logger.info(f"✅ JSON directory: {self.json_path}")
        except Exception as e:
            logger.error(f"❌ Failed to create JSON directory: {e}")
            # Fallback to current directory
            self.json_path = "."
        
        # JSON files
        self.unvalidated_file = os.path.join(self.json_path, "unvalidated.json")
        self.validated_file = os.path.join(self.json_path, "validated.json")
        
        logger.info(f"📄 Unvalidated file: {self.unvalidated_file}")
        logger.info(f"📄 Validated file: {self.validated_file}")
        
        # Initialize files and database
        self._init_json_files()
        self._init_db()
        
        # Log initial stats
        stats = self.get_stats()
        logger.info(f"📊 Initial stats: {stats}")
    
    def _init_json_files(self):
        """Initialize JSON files with proper error handling"""
        for file_path, file_name in [
            (self.unvalidated_file, "unvalidated.json"),
            (self.validated_file, "validated.json")
        ]:
            try:
                if not os.path.exists(file_path):
                    with open(file_path, 'w', encoding='utf-8') as f:
                        json.dump([], f, ensure_ascii=False, indent=2)
                    logger.info(f"✅ Created {file_name}")
                else:
                    # Verify file is valid JSON
                    with open(file_path, 'r', encoding='utf-8') as f:
                        json.load(f)
                    logger.info(f"✅ {file_name} is valid")
            except json.JSONDecodeError:
                logger.warning(f"⚠️ {file_name} is invalid, recreating...")
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump([], f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"❌ Failed to initialize {file_name}: {e}")
    
    def _init_db(self):
        """Initialize database tables"""
        try:
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
                    is_offline INTEGER DEFAULT 0
                )
            ''')
            
            conn.commit()
            conn.close()
            logger.info("✅ Database initialized")
        except Exception as e:
            logger.error(f"❌ Database initialization failed: {e}")
    
    def save_unvalidated_word(self, word, language, context="", is_offline=True):
        """Save word to unvalidated JSON file"""
        try:
            # Read existing data
            data = self._read_json_file(self.unvalidated_file)
            
            # Check if word already exists (avoid duplicates)
            word_exists = any(
                entry.get("word") == word and 
                entry.get("language") == language and
                entry.get("status") == "pending"
                for entry in data
            )
            
            if word_exists:
                logger.debug(f"📝 Word '{word}' already in unvalidated")
                return True
            
            # Add new entry
            entry = {
                "word": word,
                "language": language,
                "context": context,
                "timestamp": datetime.now().isoformat(),
                "is_offline": is_offline,
                "status": "pending"
            }
            
            data.append(entry)
            
            # Save back to file
            self._write_json_file(self.unvalidated_file, data)
            
            logger.info(f"💾 Saved to unvalidated.json: '{word}' ({language})")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error saving unvalidated word '{word}': {e}")
            return False
    
    def get_unvalidated_words(self):
        """Get all unvalidated words from JSON file"""
        try:
            data = self._read_json_file(self.unvalidated_file)
            # Return only pending words
            return [entry for entry in data if entry.get("status") == "pending"]
        except Exception as e:
            logger.error(f"❌ Error reading unvalidated words: {e}")
            return []
    
    def process_unvalidated(self, translation_service):
        """
        Process unvalidated words when online
        Returns number of processed words
        """
        try:
            # Read unvalidated words
            unvalidated = self.get_unvalidated_words()
            if not unvalidated:
                logger.info("📭 No unvalidated words to process")
                return 0
            
            logger.info(f"🔄 Processing {len(unvalidated)} unvalidated words...")
            
            processed = []
            remaining = []
            errors = []
            
            for entry in unvalidated:
                word = entry.get("word", "")
                language = entry.get("language", "")
                
                if not word:
                    errors.append("Empty word")
                    continue
                
                try:
                    # Translate using Google API
                    logger.debug(f"🔤 Translating: '{word}'")
                    translations = translation_service.translate_to_all(word)
                    
                    # Save to database
                    self._save_to_database(
                        word=word,
                        language=language,
                        translations=translations,
                        context=entry.get("context", ""),
                        is_offline=entry.get("is_offline", True)
                    )
                    
                    # Mark as processed
                    processed_entry = {
                        **entry,
                        "translations": translations,
                        "validated_at": datetime.now().isoformat(),
                        "status": "validated"
                    }
                    processed.append(processed_entry)
                    
                    logger.info(f"✅ Validated: '{word}' → {translations.get('en', 'N/A')}")
                    
                except Exception as e:
                    logger.error(f"❌ Failed to translate '{word}': {e}")
                    errors.append(f"{word}: {str(e)}")
                    remaining.append(entry)  # Keep for retry
            
            # Update files
            if processed:
                self._update_validated_file(processed)
            
            # Keep only unprocessed words
            self._write_json_file(self.unvalidated_file, remaining)
            
            # Log summary
            logger.info(f"📊 Processed: {len(processed)}, Failed: {len(errors)}, Remaining: {len(remaining)}")
            
            if errors:
                logger.warning(f"⚠️ Errors: {errors[:3]}")  # Show first 3 errors
            
            return len(processed)
            
        except Exception as e:
            logger.error(f"❌ Error processing unvalidated words: {e}")
            return 0
        
    def _has_valid_translations(self, translations):
        if not translations or not isinstance(translations, dict):
            return False
        
        required_languages = ['en', 'es', 'hi']
        for lang in required_languages:
            text = translations.get(lang, "")
            if not text or str(text).strip() == "":
                logger.debug(f"⚠️ Missing {lang} translation")
                return False
            error_indicators = [
                "[offline]",
                "[translation failed]",
                "translation failed",
                "failed to translate",
                "error",
                "none"
            ]
            
            text_lower = str(text).lower()
            if any(indicator in text_lower for indicator in error_indicators):
                logger.debug(f"⚠️ {lang} translation has error marker: {text}")
                return False
        return True
    
    def _save_to_database(self, word, language, translations, meanings=None, context="", is_offline=True):
        """Save validated translation to the database with safe field mapping."""
        try:
            if not self._has_valid_translations(translations):
                logger.warning(f"Skipping database save for '{word}' - invalid translations")
                return False

            # Ensure meanings are available
            if not meanings:
                meanings = self.meaning_service.get_comprehensive_meaning(
                    word, language, translations
                )

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            source = "offline" if is_offline else "chat"
            synonyms_json = json.dumps(meanings.get("synonyms", []))
            pos = meanings.get("part_of_speech", {}).get("en", "")
            example_sentence = meanings.get("example_sentence", "")
            complexity_score = self.meaning_service.get_word_complexity(word, language)

            # --- Check if entry exists ---
            cursor.execute('''
                SELECT id FROM translations 
                WHERE original_word = ? AND detected_language = ?
            ''', (word, language))

            existing = cursor.fetchone()

            if existing:
                cursor.execute(''' 
                    UPDATE translations 
                    SET translation_en = ?, 
                        translation_es = ?, 
                        translation_hi = ?,
                        meaning_en = ?,
                        meaning_es = ?, 
                        meaning_hi = ?,
                        part_of_speech = ?,
                        context = ?,
                        source = ?,
                        is_validated = 1,
                        validated_at = CURRENT_TIMESTAMP,
                        example_sentence = ?,
                        synonyms = ?,
                        frequency_score = ?,
                        is_offline = ?
                    WHERE id = ? 
                ''', (
                    translations.get("en"),
                    translations.get("es"),
                    translations.get("hi"),

                    meanings.get("meanings", {}).get("en", ""),
                    meanings.get("meanings", {}).get("es", ""),
                    meanings.get("meanings", {}).get("hi", ""),

                    pos,
                    context,
                    source,

                    example_sentence,
                    synonyms_json,
                    complexity_score,
                    1 if is_offline else 0,

                    existing[0]
                ))

                logger.debug(f"📝 Updated existing translation for '{word}'")

            else:
                cursor.execute('''
                    INSERT INTO translations 
                    (original_word, detected_language,
                    translation_en, translation_es, translation_hi,
                    meaning_en, meaning_es, meaning_hi,
                    part_of_speech,
                    context, source, is_validated, is_offline,
                    example_sentence, synonyms, frequency_score,
                    validated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ''', (
                    word, language,

                    translations.get("en"),
                    translations.get("es"),
                    translations.get("hi"),

                    meanings.get("meanings", {}).get("en", ""),
                    meanings.get("meanings", {}).get("es", ""),
                    meanings.get("meanings", {}).get("hi", ""),

                    pos,
                    context,
                    source,
                    1 if is_offline else 0,

                    example_sentence,
                    synonyms_json,
                    complexity_score
                ))

                logger.debug(f"💾 Saved new translation for '{word}' to database")

            conn.commit()
            conn.close()
            return True

        except Exception as e:
            logger.error(f"❌ Database save error for '{word}': {e}")
            return False

    
    def _update_validated_file(self, new_validated):
        """Update validated JSON file"""
        try:
            # Read existing validated data
            existing = self._read_json_file(self.validated_file)
            
            # Add new validated entries
            existing.extend(new_validated)
            
            # Save back
            self._write_json_file(self.validated_file, existing)
            
            logger.info(f"💾 Added {len(new_validated)} entries to validated.json")
            
        except Exception as e:
            logger.error(f"❌ Error updating validated file: {e}")
    
    def get_validated_data(self):
        """Get validated data for frontend"""
        try:
            return self._read_json_file(self.validated_file)
        except Exception as e:
            logger.error(f"❌ Error reading validated data: {e}")
            return []
    
    def check_internet(self):
        """Check if internet is available"""
        try:
            import socket
            socket.create_connection(("8.8.8.8", 53), timeout=3)
            return True
        except OSError:
            return False
    
    def get_stats(self):
        """Get statistics about unvalidated/validated words"""
        try:
            unvalidated = self.get_unvalidated_words()
            validated = self.get_validated_data()
            
            # Get database count
            db_count = 0
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM translations WHERE is_validated = 1")
                db_count = cursor.fetchone()[0]
                conn.close()
            except:
                pass
            
            return {
                "unvalidated_count": len(unvalidated),
                "validated_json_count": len(validated),
                "validated_db_count": db_count,
                "is_online": self.check_internet(),
                "json_files_exist": {
                    "unvalidated": os.path.exists(self.unvalidated_file),
                    "validated": os.path.exists(self.validated_file)
                }
            }
        except Exception as e:
            logger.error(f"❌ Error getting stats: {e}")
            return {"error": str(e)}
    
    # Helper methods for JSON file operations
    def _read_json_file(self, filepath):
        """Read JSON file with error handling"""
        try:
            if not os.path.exists(filepath):
                return []
            
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if not isinstance(data, list):
                logger.warning(f"⚠️ {filepath} is not a list, resetting")
                return []
            
            return data
            
        except json.JSONDecodeError:
            logger.error(f"❌ Invalid JSON in {filepath}, resetting")
            return []
        except Exception as e:
            logger.error(f"❌ Error reading {filepath}: {e}")
            return []
    
    def _write_json_file(self, filepath, data):
        """Write JSON file with error handling"""
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"❌ Error writing {filepath}: {e}")
            return False
    
    def clear_json_files(self):
        """Clear JSON files (for testing)"""
        try:
            for filepath in [self.unvalidated_file, self.validated_file]:
                if os.path.exists(filepath):
                    with open(filepath, 'w', encoding='utf-8') as f:
                        json.dump([], f, ensure_ascii=False, indent=2)
            logger.info("🧹 Cleared JSON files")
            return True
        except Exception as e:
            logger.error(f"❌ Error clearing JSON files: {e}")
            return False