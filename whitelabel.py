import os
import re

TARGET_DIR = "/Users/vanson/marketior"

EXCLUDE_DIRS = {
    "node_modules",
    ".git",
    ".next",
    "dist",
    "build",
    "__pycache__",
    ".marketior", # We'll handle renaming this later
    "public/demo" # We don't want to replace inside cached demo outputs, although it's fine if we do
}

EXCLUDE_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".woff", ".woff2", ".ttf", ".eot",
    ".pyc", ".mp3", ".mp4", ".zip", ".tar", ".gz"
}

# The replacements ordered specifically to avoid sub-match issues
REPLACEMENTS = [
    # CamelCase
    (r"Marketior", "Marketior"),
    (r"Marketior", "Marketior"),
    
    # UPPER_CASE
    (r"MARKETIOR", "MARKETIOR"),
    (r"MARKETIOR", "MARKETIOR"),
    
    # lower_case and lower-case
    (r"marketior", "marketior"),
    (r"marketior", "marketior"),
    (r"marketior", "marketior"),
]

def process_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        # Skip binary files that somehow bypassed the extension check
        return False
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return False

    original_content = content
    
    for pattern, replacement in REPLACEMENTS:
        content = re.sub(pattern, replacement, content)

    if content != original_content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    return False

def main():
    modified_count = 0
    for root, dirs, files in os.walk(TARGET_DIR):
        # Filter excluded directories
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext in EXCLUDE_EXTS:
                continue
                
            filepath = os.path.join(root, file)
            if process_file(filepath):
                modified_count += 1
                
    print(f"Replacement complete! Modified {modified_count} files.")

if __name__ == "__main__":
    main()
