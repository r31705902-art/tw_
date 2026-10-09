import os

ROOT_DIR = os.getcwd()
OUTPUT_FILE = "all.txt"
SCRIPT_FILE = os.path.basename(__file__)

# Замена для специфических длинных файлов
REPLACE_FILE = "FastNoiseLite.cs"
REPLACEMENT_TEXT = "// [Содержимое FastNoiseLite.cs пропущено]"

# --- Игнорируемые папки и файлы ---
IGNORE_DIRS = {"bin", "debug", "obj", ".git", ".vs", ".idea", ".vscode"}
IGNORE_FILES = {"Earthbound.AssemblyInfo.cs", OUTPUT_FILE, SCRIPT_FILE}


def is_binary_file(filepath):
    """Проверяет, является ли файл бинарным, чтобы не замусоривать итоговый текст."""
    try:
        with open(filepath, "rb") as f:
            chunk = f.read(1024)
            return b"\0" in chunk
    except Exception:
        return True


def is_allowed_file(filename):
    if filename in IGNORE_FILES:
        return False
    return True


with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
    for root, dirs, files in os.walk(ROOT_DIR):
        # Игнорируем системные и билд-папки
        dirs[:] = [d for d in dirs if d.lower() not in IGNORE_DIRS]

        for file in files:
            if not is_allowed_file(file):
                continue

            full_path = os.path.join(root, file)

            # Пропускаем бинарные файлы (картинки, dll, exe и т.п.)
            if is_binary_file(full_path):
                continue

            rel_path = os.path.relpath(full_path, ROOT_DIR)

            out.write(f'START OF FILE "{file}"\n')
            out.write(f"{rel_path}\n")
            out.write('"\n')

            if file == REPLACE_FILE:
                out.write(REPLACEMENT_TEXT + "\n")
            else:
                try:
                    with open(
                        full_path, "r", encoding="utf-8", errors="ignore"
                    ) as f:
                        out.write(f.read())
                except Exception:
                    out.write("[ERROR: не удалось прочитать файл]\n")

            out.write('\n"\n\n')

print(
    f"[OK] {OUTPUT_FILE} создан — обработаны текстовые файлы всех расширений (бинарные пропущены)."
)