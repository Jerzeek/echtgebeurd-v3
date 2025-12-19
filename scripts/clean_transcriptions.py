import os

transcription_dir = 'docs/assets/transcriptions'
target_phrase = "Welkom bij aflevering"
remove_prefix = "Welkom bij "

print(f"Scanning {transcription_dir}...")

files_processed = 0
files_changed = 0

for filename in os.listdir(transcription_dir):
    if not filename.endswith('.txt'):
        continue
    
    filepath = os.path.join(transcription_dir, filename)
    files_processed += 1
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if target_phrase in content:
            # Find the start index of the target phrase
            start_index = content.find(target_phrase)
            
            # Slice the content from that index
            new_content = content[start_index:]
            
            # Remove the "Welkom bij " part from the start
            if new_content.startswith(remove_prefix):
                new_content = new_content[len(remove_prefix):]
            
            # Write back if content changed (it should, unless the file already started perfectly)
            if new_content != content:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                print(f"Cleaned: {filename}")
                files_changed += 1
            else:
                 print(f"Skipped (already clean?): {filename}")

    except Exception as e:
        print(f"Error processing {filename}: {e}")

print(f"\nDone. Processed {files_processed} files. Updated {files_changed} files.")
