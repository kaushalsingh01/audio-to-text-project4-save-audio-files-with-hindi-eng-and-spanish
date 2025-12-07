# monitor_transcriber.py
import time
import json
import os
from datetime import datetime

def monitor_transcriber():
    """Monitor transcriber JSON file activity"""
    print("👁️ Monitoring Transcriber JSON Activity")
    print("=" * 60)
    print("Press Ctrl+C to stop\n")
    
    data_dir = "data"
    unvalidated_file = os.path.join(data_dir, "unvalidated.json")
    
    if not os.path.exists(unvalidated_file):
        print("❌ unvalidated.json doesn't exist!")
        return
    
    last_size = 0
    last_mod_time = 0
    entry_count = 0
    
    try:
        while True:
            # Check file stats
            current_size = os.path.getsize(unvalidated_file)
            current_mod_time = os.path.getmtime(unvalidated_file)
            
            if current_mod_time != last_mod_time:
                # File has changed
                with open(unvalidated_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                new_entries = len(data) - entry_count
                
                if new_entries > 0:
                    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 📥 NEW WORDS ADDED: {new_entries}")
                    print("   Latest words:")
                    for entry in data[-new_entries:]:
                        word = entry.get('word', 'N/A')
                        lang = entry.get('language', 'N/A')
                        source = entry.get('source', 'N/A')
                        print(f"     • '{word}' ({lang}) - {source}")
                
                entry_count = len(data)
                last_mod_time = current_mod_time
                last_size = current_size
            
            # Show status
            print(f"\r📊 Monitoring: {entry_count} words in JSON | Size: {current_size} bytes | Waiting...", end="", flush=True)
            
            time.sleep(2)  # Check every 2 seconds
            
    except KeyboardInterrupt:
        print("\n\n🛑 Monitoring stopped")
        print(f"📈 Final count: {entry_count} words in unvalidated.json")
        
        if entry_count > 0:
            print("\n📋 All words in unvalidated.json:")
            with open(unvalidated_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            for i, entry in enumerate(data):
                word = entry.get('word', 'N/A')
                lang = entry.get('language', 'N/A')
                source = entry.get('source', 'N/A')
                print(f"  {i+1:3d}. '{word}' ({lang}) - {source}")

if __name__ == "__main__":
    monitor_transcriber()