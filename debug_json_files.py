import os
import json
import sys

def debug_json_files():
    print("🔍 DEBUGGING JSON FILES")
    print("=" * 50)
    
    # Check current directory
    print(f"Current directory: {os.getcwd()}")
    
    # Check data directory
    data_dir = "data"
    print(f"\n📁 Checking data directory: {data_dir}")
    
    if os.path.exists(data_dir):
        print(f"✅ Data directory exists")
        print(f"   Permissions: {oct(os.stat(data_dir).st_mode)[-3:]}")
        print(f"   Contents: {os.listdir(data_dir)}")
    else:
        print(f"❌ Data directory doesn't exist")
        print("   Creating data directory...")
        try:
            os.makedirs(data_dir, exist_ok=True)
            print(f"   Created: {data_dir}")
        except Exception as e:
            print(f"   Failed to create: {e}")
    
    # Check JSON files
    json_files = {
        "unvalidated.json": os.path.join(data_dir, "unvalidated.json"),
        "validated.json": os.path.join(data_dir, "validated.json")
    }
    
    for filename, filepath in json_files.items():
        print(f"\n📄 Checking {filename}:")
        print(f"   Path: {filepath}")
        
        if os.path.exists(filepath):
            print(f"   ✅ File exists")
            print(f"   Size: {os.path.getsize(filepath)} bytes")
            print(f"   Permissions: {oct(os.stat(filepath).st_mode)[-3:]}")
            
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                print(f"   Content type: {type(data)}")
                print(f"   Item count: {len(data)}")
                
                if data:
                    print(f"   Sample (first 3 items):")
                    for i, item in enumerate(data[:3]):
                        if isinstance(item, dict):
                            word = item.get('word', 'N/A')
                            lang = item.get('language', 'N/A')
                            status = item.get('status', 'N/A')
                            print(f"     {i+1}. '{word}' ({lang}) - {status}")
                        else:
                            print(f"     {i+1}. {item}")
                else:
                    print(f"   Content: Empty list")
                    
            except json.JSONDecodeError as e:
                print(f"   ❌ Invalid JSON: {e}")
                # Show file content
                with open(filepath, 'r') as f:
                    content = f.read()
                    print(f"   Raw content (first 200 chars): {content[:200]}")
            except Exception as e:
                print(f"   ❌ Error reading: {e}")
        else:
            print(f"   ❌ File doesn't exist")
            
            # Try to create it
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump([], f, ensure_ascii=False, indent=2)
                print(f"   ✅ Created empty file")
            except Exception as e:
                print(f"   ❌ Failed to create: {e}")
    
    # Test writing to JSON
    print(f"\n✍️ Testing write to JSON...")
    test_file = os.path.join(data_dir, "test_write.json")
    try:
        test_data = [{"test": "data", "timestamp": "now"}]
        with open(test_file, 'w', encoding='utf-8') as f:
            json.dump(test_data, f, ensure_ascii=False, indent=2)
        print(f"   ✅ Successfully wrote to {test_file}")
        os.remove(test_file)
        print(f"   ✅ Cleaned up test file")
    except Exception as e:
        print(f"   ❌ Write test failed: {e}")
    
    print("\n" + "=" * 50)
    print("✅ Debug complete")

if __name__ == "__main__":
    debug_json_files()