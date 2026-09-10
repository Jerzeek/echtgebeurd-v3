import os

transcription_dir = 'assets/transcriptions'
threshold = 100  # Adjust this number to define "short"

print(f"Scanning {transcription_dir} for episodes with fewer than {threshold} words...")

short_files = []

if os.path.exists(transcription_dir):
    for filename in sorted(os.listdir(transcription_dir)):
        if filename.endswith('.txt'):
            filepath = os.path.join(transcription_dir, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                    words = content.split()
                    word_count = len(words)
                    
                    if word_count < threshold:
                        short_files.append((filename, word_count))
            except Exception as e:
                print(f"Error reading {filename}: {e}")

    if short_files:
        print(f"\nFound {len(short_files)} short episodes:")
        print(f"{ 'Word Count':<12} | {'Filename'}")
        print("-" * 60)
        for name, count in short_files:
            print(f"{count:<12} | {name}")
    else:
        print("No short episodes found.")
else:
    print(f"Directory not found: {transcription_dir}")
