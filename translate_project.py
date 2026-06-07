import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from deep_translator import GoogleTranslator

exclude_dirs = {'venv', '.venv', 'node_modules', '.git', '__pycache__', 'static', 'dist', '.vscode'}
# regex to find chunks of Chinese characters and Chinese punctuation
regex = re.compile(r'[\u4e00-\u9fa5\u3000-\u303f\uff00-\uffef]+')

def translate_chunk(chunk):
    for i in range(3):
        try:
            res = GoogleTranslator(source='zh-CN', target='en').translate(chunk)
            if res:
                return chunk, res
            time.sleep(1)
        except Exception:
            time.sleep(1)
    return chunk, chunk

files_to_process = []
for root, dirs, files in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in exclude_dirs]
    for file in files:
        if file.endswith(('.py', '.bat', '.ps1', '.ts', '.tsx', '.json', '.yml', '.env', '.md')):
            if file in ['translate_project.py', 'README.md', 'README_en.md', 'README_vi.md']:
                continue
            path = os.path.join(root, file)
            files_to_process.append(path)

print(f"Found {len(files_to_process)} files to check.")

for path in files_to_process:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        if not regex.search(content):
            continue
            
        chunks = list(set(regex.findall(content)))
        if not chunks:
            continue
            
        print(f"Translating {path} ({len(chunks)} chunks)...")
        
        translations = {}
        with ThreadPoolExecutor(max_workers=20) as executor:
            future_to_chunk = {executor.submit(translate_chunk, chunk): chunk for chunk in chunks}
            for future in as_completed(future_to_chunk):
                original, translated = future.result()
                translations[original] = translated

        # Sort by length descending so that shorter chunks don't overwrite parts of longer chunks
        chunks = sorted(chunks, key=len, reverse=True)
        for chunk in chunks:
            translated = translations.get(chunk, chunk)
            if translated and translated != chunk:
                content = content.replace(chunk, translated)
                
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
            
    except Exception as e:
        print(f"Error processing {path}: {e}")

print("Done.")
