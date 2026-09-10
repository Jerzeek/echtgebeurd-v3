import os

# Updated path to the assets folder as requested
transcription_dir = 'assets/transcriptions'
threshold = 100

print(f"Scanning {transcription_dir} for episodes with fewer than {threshold} words to DELETE...")

if os.path.exists(transcription_dir):
    deleted_count = 0
    for filename in sorted(os.listdir(transcription_dir)):
        if filename.endswith('.txt'):
            filepath = os.path.join(transcription_dir, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                    words = content.split()
                    word_count = len(words)
                
                if word_count < threshold:
                    print(f"Deleting {filename} ({word_count} words)...")
                    os.remove(filepath)
                    deleted_count += 1
            except Exception as e:
                print(f"Error processing {filename}: {e}")

    if deleted_count == 0:
        print("No short episodes found to delete.")
    else:
        print(f"\nSuccessfully deleted {deleted_count} files.")
else:
    print(f"Directory not found: {transcription_dir}")

