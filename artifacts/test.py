import asyncio
import base64
import configparser
import json
import mimetypes
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime

from colorama import Fore, Style, init
import websockets

init(autoreset=True)

# ===== РАБОТА С ФАЙЛОМ КОНФИГУРАЦИИ s.ini И КЛЮЧОМ API =====

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INI_PATH = os.path.join(SCRIPT_DIR, "s.ini")
SESSIONS_DIR = os.path.join(SCRIPT_DIR, "sessions")

os.makedirs(SESSIONS_DIR, exist_ok=True)

def load_or_request_api_key() -> str:
    config = configparser.ConfigParser()
    api_key = None

    if os.path.exists(INI_PATH):
        config.read(INI_PATH, encoding="utf-8")
        if "SETTINGS" in config and "GEMINI_API_KEY" in config["SETTINGS"]:
            api_key = config["SETTINGS"]["GEMINI_API_KEY"].strip()

    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    if not api_key:
        print(Fore.YELLOW + "\n[!] Файл s.ini не найден или не содержит GEMINI_API_KEY.")
        api_key = input(Fore.CYAN + "Введите ваш GEMINI API Key > " + Style.RESET_ALL).strip()
        
        while not api_key:
            print(Fore.RED + "Ключ API не может быть пустым!")
            api_key = input(Fore.CYAN + "Введите ваш GEMINI API Key > " + Style.RESET_ALL).strip()

        if not config.has_section("SETTINGS"):
            config.add_section("SETTINGS")
        config.set("SETTINGS", "GEMINI_API_KEY", api_key)

        try:
            with open(INI_PATH, "w", encoding="utf-8") as f:
                config.write(f)
            print(Fore.GREEN + f"[+] API Key успешно сохранен в {INI_PATH}\n")
        except Exception as e:
            print(Fore.RED + f"Ошибка сохранения s.ini: {e}")

    return api_key

API_KEY = load_or_request_api_key()
MODEL_NAME = "gemini-3.1-flash-live-preview"
WS_URL = f"wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key={API_KEY}"


# ===== ЛОГИРОВАНИЕ, ЗАГРУЗКА И АВТОСОХРАНЕНИЕ СЕССИЙ =====

def log_session_event(session_name: str, event_type: str, content: dict or str):
    """Автоматически сохраняет все события и диалоги в sessions/<session_name>.json"""
    if not session_name:
        return
    session_file = os.path.join(SESSIONS_DIR, f"{session_name}.json")
    try:
        data = {"created": str(datetime.now()), "name": session_name, "history": []}
        if os.path.exists(session_file):
            try:
                with open(session_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                pass

        data["updated"] = str(datetime.now())
        if "history" not in data or not isinstance(data["history"], list):
            data["history"] = []

        data["history"].append({
            "timestamp": str(datetime.now()),
            "type": event_type,
            "content": content
        })

        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(Fore.RED + f"[Session Save Error]: {e}")


def tool_set_session_name(current_session: dict, new_name: str) -> str:
    """Устанавливает осмысленное имя сессии и переименовывает json файл."""
    print(Fore.CYAN + f"\n[Tool Set Session Name]: {new_name}")
    try:
        clean_name = re.sub(r'[^a-zA-Z0-9_\-]', '', new_name.strip().replace(' ', '_')).lower()
        if not clean_name:
            clean_name = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        old_name = current_session.get("name")
        old_file = os.path.join(SESSIONS_DIR, f"{old_name}.json")
        new_file = os.path.join(SESSIONS_DIR, f"{clean_name}.json")

        current_session["name"] = clean_name

        if os.path.exists(old_file) and old_file != new_file:
            os.rename(old_file, new_file)
            return f"Сессия переименована с '{old_name}' на '{clean_name}'."
        else:
            log_session_event(clean_name, "session_renamed", f"Сессия названа {clean_name}")
            return f"Установлено имя сессии: '{clean_name}'."
    except Exception as e:
        return f"Ошибка переименования сессии: {e}"


def load_session_history(session_name: str) -> tuple[dict, str]:
    """Загружает историю сообщений сессии для отправки в модель."""
    session_file = os.path.join(SESSIONS_DIR, f"{session_name}.json")
    if not os.path.exists(session_file):
        return None, f"Сессия '{session_name}' не найдена."
    try:
        with open(session_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        formatted_history = []
        for item in data.get("history", []):
            htype = item.get("type")
            content = item.get("content")
            if htype == "user_input":
                formatted_history.append(f"User: {content}")
            elif htype == "model_response":
                formatted_history.append(f"Gemini: {content}")
            elif htype == "tool_call" and isinstance(content, dict):
                formatted_history.append(f"Tool {content.get('name')}: {str(content.get('result'))[:200]}")

        history_text = "\n".join(formatted_history[-25:])
        return data, history_text
    except Exception as e:
        return None, f"Ошибка чтения сессии: {e}"


# ===== CMD ДВИЖОК =====

is_waiting_user_question = False

class CMDSession:
    """Выполняет команды в Windows CMD с поддержкой UTF-8 / CP65001."""
    def __init__(self):
        self.cwd = os.getcwd()
        self.lock = threading.Lock()

    def _decode_bytes(self, data: bytes) -> str:
        if not data:
            return ""
        for enc in ["utf-8", "cp866", "cp1251", "latin-1"]:
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace")

    def execute(self, cmd: str, workdir: str = None, timeout: int = 40) -> str:
        with self.lock:
            if workdir and os.path.exists(workdir):
                self.cwd = os.path.abspath(workdir)

            cwd_sentinel = f"__CWD_MARKER_{uuid.uuid4().hex[:6]}__"
            full_cmd = f'@chcp 65001 >nul && {cmd}\n@echo {cwd_sentinel} & cd'

            print(Fore.CYAN + f"\n[CMD Executing]: {Style.BRIGHT}{cmd}")
            t0 = time.time()

            try:
                proc = subprocess.Popen(
                    ["cmd.exe", "/Q", "/C", full_cmd],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    cwd=self.cwd
                )
                stdout_bytes, _ = proc.communicate(input=b"\n", timeout=timeout)
                elapsed = (time.time() - t0) * 1000
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout_bytes, _ = proc.communicate()
                elapsed = (time.time() - t0) * 1000
                print(Fore.RED + f"[Timeout Error]: Команда превысила таймаут {timeout}s")
                raw_text = self._decode_bytes(stdout_bytes)
                return raw_text + f"\n[ERROR: Процесс остановлен по таймауту {timeout} сек.]"
            except Exception as e:
                err = f"[CMD System Error]: {e}"
                print(Fore.RED + err)
                return err

            raw_output = self._decode_bytes(stdout_bytes).strip()
            raw_output = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ufffd]', '', raw_output)

            if cwd_sentinel in raw_output:
                parts = raw_output.split(cwd_sentinel)
                main_output = parts[0].strip()
                new_cwd = parts[1].strip() if len(parts) > 1 else ""
                if new_cwd and os.path.exists(new_cwd):
                    self.cwd = new_cwd
            else:
                main_output = raw_output

            print(Fore.YELLOW + f"[Exit Code]: {proc.returncode} | [Time]: {elapsed:.2f}ms | [CWD]: {self.cwd}")
            
            if main_output:
                preview = main_output[:1000] + ("\n... [вывод обрезан]" if len(main_output) > 1000 else "")
                print(Fore.WHITE + "--- ВЫВОД КОМАНДЫ ---")
                print(Fore.WHITE + preview)
                print(Fore.WHITE + "---------------------")
            else:
                print(Fore.YELLOW + "(Команда выполнена без вывода)")

            return main_output if main_output else f"(Команда завершена с кодом {proc.returncode} без вывода)"

cmd_engine = CMDSession()


# ===== УТИЛИТЫ И ИНСТРУМЕНТЫ РАБОТЫ С КОДОМ И ФАЙЛАМИ =====

def _find_pattern_line(lines: list, pattern: str) -> tuple[int, str]:
    matches = [idx + 1 for idx, l in enumerate(lines) if pattern in l]
    if len(matches) == 0:
        return -1, f"Ошибка: Шаблон '{pattern}' не найден в файле."
    if len(matches) > 1:
        matched_details = "\n".join([f"  Строка {m}: {lines[m-1].strip()}" for m in matches[:10]])
        return -1, f"Ошибка: Найдено несколько ({len(matches)}) совпадений для шаблона '{pattern}':\n{matched_details}\nУточните шаблон или используйте точные номера строк."
    return matches[0], ""

def format_numbered_lines(lines: list, start_index_1based: int = 1) -> str:
    formatted = []
    for idx, line in enumerate(lines, start=start_index_1based):
        clean_line = line.rstrip("\r\n")
        formatted.append(f"{idx:5d} {clean_line}")
    return "\n".join(formatted)


def tool_read_file_advanced(path: str, start_line: int = None, end_line: int = None, 
                            start_pattern: str = None, end_pattern: str = None) -> str:
    print(Fore.CYAN + f"\n[Tool Read Advanced]: {path}")
    try:
        if not path or not os.path.exists(path):
            return f"Ошибка: Файл '{path}' не найден."

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        total_lines = len(lines)
        if total_lines == 0:
            return f"Файл '{path}' пуст."

        if start_pattern:
            s_idx, err = _find_pattern_line(lines, start_pattern)
            if err: return err
            actual_start = s_idx
        elif start_line and start_line > 0:
            actual_start = start_line
        else:
            actual_start = 1

        if end_pattern:
            e_idx, err = _find_pattern_line(lines, end_pattern)
            if err: return err
            actual_end = e_idx
        elif end_line and end_line > 0:
            actual_end = end_line
        else:
            actual_end = total_lines

        if actual_start > actual_end:
            return f"Ошибка: Начальная строка ({actual_start}) больше конечной ({actual_end})."

        actual_start = max(1, min(actual_start, total_lines))
        actual_end = max(1, min(actual_end, total_lines))

        selected = lines[actual_start - 1 : actual_end]
        return format_numbered_lines(selected, start_index_1based=actual_start)

    except Exception as e:
        return f"Ошибка чтения файла: {str(e)}"


def tool_replace_block(path: str, new_content: str, start_line: int = None, end_line: int = None,
                       start_pattern: str = None, end_pattern: str = None) -> str:
    print(Fore.CYAN + f"\n[Tool Replace Block]: {path}")
    try:
        if not path or not os.path.exists(path):
            return f"Ошибка: Файл '{path}' не существует."

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        total_lines = len(lines)

        if start_pattern:
            s_idx, err = _find_pattern_line(lines, start_pattern)
            if err: return err
            actual_start = s_idx
        elif start_line and start_line > 0:
            actual_start = start_line
        else:
            return "Ошибка: Не указана начальная строка (start_line) или шаблон (start_pattern)."

        if end_pattern:
            e_idx, err = _find_pattern_line(lines, end_pattern)
            if err: return err
            actual_end = e_idx
        elif end_line and end_line > 0:
            actual_end = end_line
        else:
            actual_end = actual_start

        if actual_start > actual_end:
            return f"Ошибка: Начальная строка ({actual_start}) больше конечной ({actual_end})."

        actual_start = max(1, min(actual_start, total_lines))
        actual_end = max(1, min(actual_end, total_lines))

        replacement_lines = [l + "\n" for l in new_content.splitlines()]
        if not new_content.endswith("\n") and len(replacement_lines) > 0:
            replacement_lines[-1] = replacement_lines[-1].rstrip("\n") + "\n"

        lines[actual_start - 1 : actual_end] = replacement_lines

        with open(path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        return f"Успешно заменен блок со строки {actual_start} по {actual_end} (всего {len(replacement_lines)} новых строк)."

    except Exception as e:
        return f"Ошибка замены блока: {str(e)}"


def tool_search_code_with_lines(path: str = ".", query: str = "", context: int = 1) -> str:
    print(Fore.CYAN + f"\n[Tool Search Code]: '{query}' in {path}")
    try:
        if os.path.isfile(path):
            files = [path]
        else:
            files = []
            for root, _, filenames in os.walk(path):
                if any(ignored in root for ignored in [".git", "__pycache__", "node_modules", "venv"]):
                    continue
                for fn in filenames:
                    files.append(os.path.join(root, fn))

        results = []
        for filepath in files[:100]:
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                
                matched_indices = [i for i, l in enumerate(lines) if query in l]
                if matched_indices:
                    results.append(f"\n--- Файл: {filepath} ---")
                    printed_lines = set()
                    for idx in matched_indices:
                        start = max(0, idx - context)
                        end = min(len(lines), idx + context + 1)
                        for i in range(start, end):
                            if i not in printed_lines:
                                printed_lines.add(i)
                                results.append(f"{i+1:5d} {lines[i].rstrip()}")
            except Exception:
                continue

        if not results:
            return f"Совпадений по запросу '{query}' не найдено."
        return "\n".join(results[:200])
    except Exception as e:
        return f"Ошибка поиска: {e}"


def tool_run_python_code(code: str) -> str:
    print(Fore.CYAN + f"\n[Tool Run Python Code]")
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tf:
            tf.write(code)
            temp_path = tf.name

        proc = subprocess.run(
            [sys.executable, temp_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30
        )
        
        try: os.remove(temp_path)
        except: pass

        output = (proc.stdout + proc.stderr).strip()
        print(Fore.WHITE + "--- ВЫВОД PYTHON ---")
        print(Fore.WHITE + (output if output else "(Код выполнен без вывода)"))
        print(Fore.WHITE + "---------------------")
        return output if output else "(Код выполнен успешно без вывода)"
    except subprocess.TimeoutExpired:
        return "[ERROR: Выполнение Python-кода превысило таймаут 30 сек.]"
    except Exception as e:
        return f"Ошибка выполнения Python: {e}"

def tool_check_python_syntax(path: str) -> str:
    print(Fore.CYAN + f"\n[Tool Syntax Check]: {path}")
    try:
        import ast
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            code = f.read()
        ast.parse(code)
        return f"Синтаксических ошибок в '{path}' не обнаружено."
    except SyntaxError as se:
        return f"Синтаксическая ошибка в '{path}': строка {se.lineno}, колонка {se.offset}: {se.msg}\n-> {se.text}"
    except Exception as e:
        return f"Ошибка проверки: {e}"


def tool_get_file_info(path: str) -> str:
    print(Fore.CYAN + f"\n[Tool File Info]: {path}")
    try:
        if not os.path.exists(path):
            return f"Файл '{path}' не существует."
        
        stat = os.stat(path)
        size_kb = stat.st_size / 1024
        mtime = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')

        line_count = 0
        if os.path.isfile(path):
            with open(path, "rb") as f:
                line_count = sum(1 for _ in f)

        return json.dumps({
            "path": os.path.abspath(path),
            "size_kb": round(size_kb, 2),
            "lines": line_count,
            "last_modified": mtime
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"Ошибка получения метаданных: {e}"


def tool_write_file(path: str, content: str) -> str:
    print(Fore.CYAN + f"\n[Tool Write File]: {path}")
    try:
        full_path = os.path.abspath(path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Успешно записано {len(content)} символов в {full_path}"
    except Exception as e:
        return f"Ошибка записи файла: {str(e)}"


def tool_list_directory(path: str = ".") -> str:
    print(Fore.CYAN + f"\n[Tool List Dir]: {path}")
    try:
        target = path if path else "."
        items = os.listdir(target)
        return "\n".join(items) if items else "(Папка пуста)"
    except Exception as e:
        return f"Ошибка чтения каталога: {str(e)}"


def tool_web_search(query: str, max_results: int = 5) -> str:
    print(Fore.CYAN + f"\n[Tool Web Search]: {query}")
    results = []

    try:
        encoded_query = urllib.parse.quote(query)
        url = f"https://www.google.com/search?q={encoded_query}&num={max_results+3}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
            }
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode('utf-8', errors='ignore')

        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')
            for h3 in soup.find_all('h3'):
                parent = h3.parent
                while parent and parent.name != 'a':
                    parent = parent.parent
                if parent and parent.name == 'a' and 'href' in parent.attrs:
                    href = parent['href']
                    if href.startswith('/url?q='):
                        href = href.split('/url?q=')[1].split('&')[0]
                    if href.startswith('http') and 'google.com' not in href:
                        title = h3.get_text()
                        container = parent.find_parent('div')
                        snippet = container.get_text() if container else ""
                        results.append({"title": title, "href": href, "body": snippet[:300]})
                        if len(results) >= max_results:
                            break
        except Exception:
            pass
    except Exception:
        pass

    if len(results) < max_results:
        try:
            from ddgs import DDGS
            time.sleep(0.5)
            with DDGS() as ddgs:
                ddg_res = list(ddgs.text(query, max_results=int(max_results)))
                for r in ddg_res:
                    if not any(existing['href'] == r.get('href') for existing in results):
                        results.append({"title": r.get('title'), "href": r.get('href'), "body": r.get('body')})
        except Exception:
            pass

    if not results:
        return f"Результатов по запросу '{query}' не найдено."

    formatted = []
    for i, r in enumerate(results[:max_results], 1):
        formatted.append(f"[{i}] {r.get('title')}\n    URL: {r.get('href')}\n    Snippet: {r.get('body')}\n")
    return f"Результаты поиска по '{query}':\n\n" + "\n".join(formatted)


def tool_fetch_web_page(url: str, mode: str = "text", max_length: int = 30000) -> str:
    print(Fore.CYAN + f"\n[Tool URL Context / Fetch Page]: {url}")
    try:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        req = urllib.request.Request(
            url, 
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req, timeout=12) as response:
            html_bytes = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            html_content = html_bytes.decode(charset, errors="replace")

        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content, 'html.parser')
            for tag in soup(["script", "style", "noscript", "svg", "nav"]):
                tag.extract()
            text = soup.get_text(separator='\n')
            lines = (line.strip() for line in text.splitlines())
            result = '\n'.join(chunk for chunk in lines if chunk)
        except ImportError:
            clean_text = re.sub(r'<(script|style|noscript)\b[^>]*>[\s\S]*?</\1>', '', html_content, flags=re.IGNORECASE)
            result = re.sub(r'<[^>]+>', ' ', clean_text)

        max_len = int(max_length) if max_length else 30000
        if len(result) > max_len:
            result = result[:max_len] + f"\n\n... [Содержимое усечено до {max_len} символов]"
        return result
    except Exception as e:
        return f"Ошибка скачивания страницы URL: {str(e)}"


def compress_image_to_b64(image_path: str, max_dim: int = 800, quality: int = 60) -> str:
    try:
        from PIL import Image
        import io
        with Image.open(image_path) as img:
            img.thumbnail((max_dim, max_dim))
            if img.mode != "RGB":
                img = img.convert("RGB")
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=quality)
            return base64.b64encode(buffer.getvalue()).decode("utf-8")
    except ImportError:
        pass

    ps_script = f"""
    Add-Type -AssemblyName System.Drawing
    $src = [System.Drawing.Image]::FromFile('{image_path}')
    $ratio = [Math]::Min({max_dim} / $src.Width, {max_dim} / $src.Height)
    if ($ratio -gt 1) {{ $ratio = 1 }}
    $newW = [int]($src.Width * $ratio)
    $newH = [int]($src.Height * $ratio)
    $bmp = New-Object System.Drawing.Bitmap($newW, $newH)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.DrawImage($src, 0, 0, $newW, $newH)
    $ms = New-Object System.IO.MemoryStream
    $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Jpeg)
    $bytes = $ms.ToArray()
    $g.Dispose(); $bmp.Dispose(); $src.Dispose(); $ms.Dispose()
    [Convert]::ToBase64String($bytes)
    """
    try:
        res = subprocess.run(
            ["powershell", "-Command", ps_script],
            capture_output=True, text=True, timeout=10
        )
        b64_str = res.stdout.strip()
        if b64_str and len(b64_str) > 100:
            return b64_str
    except Exception:
        pass

    with open(image_path, "rb") as f:
        raw = f.read(150000)
        return base64.b64encode(raw).decode("utf-8")


def tool_view_image_or_file(path: str) -> str:
    print(Fore.CYAN + f"\n[Tool View File/Image]: {path}")
    try:
        if not os.path.exists(path):
            return f"Ошибка: Файл '{path}' не существует."

        mime_type, _ = mimetypes.guess_type(path)
        if not mime_type:
            mime_type = "application/octet-stream"

        if mime_type.startswith("image/"):
            b64 = compress_image_to_b64(path)
            return json.dumps({
                "file_name": os.path.basename(path),
                "mime_type": "image/jpeg",
                "data_uri": f"data:image/jpeg;base64,{b64}",
                "note": "Изображение оптимизировано и доступно."
            }, ensure_ascii=False)
        else:
            with open(path, "rb") as f:
                chunk = f.read(2048)
                is_binary = b"\x00" in chunk

            if is_binary:
                with open(path, "rb") as f:
                    raw = f.read(100000)
                b64 = base64.b64encode(raw).decode("utf-8")
                return json.dumps({
                    "file_name": os.path.basename(path),
                    "mime_type": mime_type,
                    "data_uri": f"data:{mime_type};base64,{b64}"
                }, ensure_ascii=False)
            else:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read(20000)
                return f"Файл {path} (Текст):\n" + content

    except Exception as e:
        return f"Ошибка инспектирования файла: {str(e)}"


async def tool_request_user_input(question: str) -> str:
    global is_waiting_user_question
    is_waiting_user_question = True
    try:
        print(Fore.MAGENTA + Style.BRIGHT + f"\n[ПАУЗА / ВОПРОС ОТ GEMINI]: {question}")
        loop = asyncio.get_event_loop()
        user_reply = await loop.run_in_executor(None, input, Fore.GREEN + "Ваш ответ > " + Style.RESET_ALL)
        return user_reply
    finally:
        is_waiting_user_question = False

# ===== ОБРАБОТЧИК ВЫЗОВОВ ФУНКЦИЙ =====

async def execute_tool(func_name: str, args: dict, current_session: dict = None) -> str:
    if func_name == "set_session_name" and current_session:
        return tool_set_session_name(current_session, args.get("name", ""))
    elif func_name == "exec_command":
        return cmd_engine.execute(args.get("cmd", ""), args.get("workdir"))
    elif func_name == "read_file_advanced":
        return tool_read_file_advanced(
            args.get("path", ""), args.get("start_line"), args.get("end_line"),
            args.get("start_pattern"), args.get("end_pattern")
        )
    elif func_name == "replace_block":
        return tool_replace_block(
            args.get("path", ""), args.get("new_content", ""),
            args.get("start_line"), args.get("end_line"),
            args.get("start_pattern"), args.get("end_pattern")
        )
    elif func_name == "search_code_with_lines":
        return tool_search_code_with_lines(args.get("path", "."), args.get("query", ""), args.get("context", 1))
    elif func_name == "run_python_code":
        return tool_run_python_code(args.get("code", ""))
    elif func_name == "check_python_syntax":
        return tool_check_python_syntax(args.get("path", ""))
    elif func_name == "get_file_info":
        return tool_get_file_info(args.get("path", ""))
    elif func_name == "write_file":
        return tool_write_file(args.get("path", ""), args.get("content", ""))
    elif func_name == "list_directory":
        return tool_list_directory(args.get("path", "."))
    elif func_name == "run_tests":
        cmd = args.get("test_command") or "dotnet test"
        return cmd_engine.execute(cmd)
    elif func_name == "get_git_status":
        return cmd_engine.execute("git status")
    elif func_name == "web_search":
        return tool_web_search(args.get("query", ""), args.get("max_results", 5))
    elif func_name == "fetch_web_page":
        return tool_fetch_web_page(args.get("url", ""), args.get("mode", "text"))
    elif func_name == "view_image_or_file":
        return tool_view_image_or_file(args.get("path", ""))
    elif func_name == "request_user_input":
        return await tool_request_user_input(args.get("question", ""))
    
    return f"Неизвестный инструмент: {func_name}"


# ===== СИСТЕМНЫЙ ПРОМПТ С УКАЗАНИЕМ ВЫЗОВА ИНСТРУМЕНТА СЕССИИ =====

SYSTEM_INSTRUCTION = """
Ты — профессиональный автономный AI-разработчик и системный архитектор высшего уровня, работающий напрямую на ПК пользователя.

ОБЯЗАТЕЛЬНОЕ ПРАВИЛО ИМЕНОВАНИЯ СЕССИИ:
1. В самом первом ответе при получении задачи ты ОБЯЗАН первейшим делом вызвать инструмент `set_session_name` с понятным названием сессии на английском/латинице (в формате snake_case, например: `create_minecraft_shader` или `fix_database_bug`). НЕ пиши имя сессии просто текстом в чат, а ОБЯЗАТЕЛЬНО вызови инструмент `set_session_name`!

2. КРИТИЧЕСКИ ВАЖНОЕ ПРАВИЛО ПОЛНОТЫ ВЫПОЛНЕНИЯ ЗАДАЧ:
   - ЗАПРЕЩЕНО ПРЕЖДЕВРЕМЕННО ОСТАНАВЛИВАТЬСЯ ИЛИ ЗАВЕРШАТЬ ОТВЕТ, ЕСЛИ ЗАДАЧА НЕ ВЫПОЛНЕНА ДО КОНЦА!
   - Никогда не отчитывайся о промежуточном успехе со словами "я сделал половину, остальное сделай сам" или "попробуй проверить сам".
   - Если пользователь попросил написать шейдер/программу/проект — напиши ВСЕ необходимые файлы до единого!
   - Если какая-то команда, ссылка на скачивание или тулза упала/выдала 404 — НЕ СДАВАЙСЯ и НЕ СТОПАЙСЯ! Используй `web_search` для поиска альтернативных зеркал/ссылок или создай собственную проверку/скрипт на Python!
   - Завершай ход (отправляй финальный текстуальный вывод) ТОЛЬКО ТОГДА, когда ВСЕ файлы созданы, код проверен и задача выполнена на 100%.

3. ВЫСОКАЯ ТОЧНОСТЬ РЕДАКТИРОВАНИЯ И ПРОВЕРКА КОДА:
   - При чтении кода всегда используй `read_file_advanced` или `search_code_with_lines` (с нумерацией строк).
   - При изменении файлов используй `replace_block` с точными номерами строк или уникальными шаблонами.
   - Обязательно проверяй созданный код на синтаксические и логические ошибки.

4. ЗАПРОС У ПОЛЬЗОВАТЕЛЯ (`request_user_input`):
   - Вызывай `request_user_input` ТОЛЬКО в случае если перепробовал 3+ разных способов/ссылок/подходов и зашел в абсолютный тупик, либо перед необратимыми деструктивными действиями.
"""


def get_session_suggestions() -> list[str]:
    if not os.path.exists(SESSIONS_DIR):
        return []
    files = os.listdir(SESSIONS_DIR)
    names = []
    for f in files:
        if f.endswith(".json"):
            names.append(f[:-5])
        else:
            names.append(f)
    return names

def read_input_with_ghost_autocomplete(prompt_str: str) -> str:
    try:
        user_text = input(prompt_str)
        return user_text
    except (KeyboardInterrupt, EOFError):
        return ""

# ===== ОБРАБОТКА WEBSOCKET СООБЩЕНИЙ =====

async def handle_tool_call(websocket, tool_call, current_session: dict):
    function_responses = []

    for fc in tool_call.get("functionCalls", []):
        func_name = fc.get("name")
        func_id = fc.get("id")
        args = fc.get("args", {})

        print(f"\n[GEMINI ВЫЗВАЛ]: {func_name}({args})")

        if func_name == "view_image_or_file":
            path = args.get("path", "")
            mime_type, _ = mimetypes.guess_type(path)
            
            if mime_type and mime_type.startswith("image/") and os.path.exists(path):
                b64 = compress_image_to_b64(path)
                media_msg = {
                    "realtimeInput": {
                        "video": {
                            "mimeType": "image/jpeg",
                            "data": b64
                        }
                    }
                }
                await websocket.send(json.dumps(media_msg))
                res = f"Изображение '{os.path.basename(path)}' передано в визуальный поток. Опиши полученный кадр."
            else:
                res = await execute_tool(func_name, args, current_session)
        else:
            res = await execute_tool(func_name, args, current_session)

        log_session_event(
            current_session.get("name"),
            "tool_call",
            {"name": func_name, "args": args, "result": str(res)}
        )

        print(f"[РЕЗУЛЬТАТ ИНСТРУМЕНТА]:\n{(str(res)[:300] + '...') if len(str(res)) > 300 else res}\n")

        function_responses.append({
            "name": func_name,
            "id": func_id,
            "response": {"result": res}
        })

    tool_response_msg = {
        "toolResponse": {
            "functionResponses": function_responses
        }
    }
    await websocket.send(json.dumps(tool_response_msg))


async def receive_loop(websocket, current_session: dict):
    is_first_chunk = True
    current_turn_text = []
    try:
        async for message in websocket:
            response = json.loads(message)

            if "serverContent" in response:
                server_content = response["serverContent"]

                text_to_print = ""
                if "outputTranscription" in server_content and "text" in server_content["outputTranscription"]:
                    text_to_print += server_content["outputTranscription"]["text"]

                if "modelTurn" in server_content and "parts" in server_content["modelTurn"]:
                    for part in server_content["modelTurn"]["parts"]:
                        if "text" in part:
                            text_to_print += part["text"]

                if text_to_print:
                    current_turn_text.append(text_to_print)
                    if is_first_chunk:
                        print(Fore.GREEN + "\nGemini: ", end="", flush=True)
                        is_first_chunk = False
                    print(Fore.GREEN + text_to_print, end="", flush=True)

                if server_content.get("turnComplete"):
                    print("\n" + Fore.YELLOW + "--------------------------------------------------")
                    print(Fore.YELLOW + "[Gemini завершил ответ]")
                    print(Fore.YELLOW + "--------------------------------------------------")
                    full_text = "".join(current_turn_text)
                    if full_text.strip():
                        log_session_event(current_session.get("name"), "model_response", full_text)
                    current_turn_text = []
                    is_first_chunk = True

            if "toolCall" in response:
                if not is_first_chunk:
                    print()
                is_first_chunk = True
                await handle_tool_call(websocket, response["toolCall"], current_session)

    except websockets.exceptions.ConnectionClosedOK:
        print(Fore.YELLOW + "\nСоединение закрыто.")
    except Exception as e:
        print(Fore.RED + f"\nОшибка в цикле приема данных: {e}")

async def user_interactive_loop(websocket, current_session: dict):
    global is_waiting_user_question
    loop = asyncio.get_event_loop()
    paused = False
    pause_reason = ""

    while True:
        try:
            if is_waiting_user_question:
                await asyncio.sleep(0.5)
                continue

            prompt = await loop.run_in_executor(
                None, read_input_with_ghost_autocomplete, Fore.CYAN + "Доп. сообщение > " + Style.RESET_ALL
            )
            prompt_str = prompt.strip()

            if not prompt_str:
                continue

            if prompt_str.startswith("/pause"):
                paused = True
                pause_reason = prompt_str[6:].strip() or "Причина не указана"
                print(Fore.YELLOW + f"\n[ПАУЗА]: Работа приостановлена. Причина: {pause_reason}\n")
                continue

            elif prompt_str == "/unpause":
                paused = False
                pause_reason = ""
                print(Fore.GREEN + "\n[СНЯТИЕ ПАУЗЫ]: Прием и отправка возобновлены.\n")
                continue

            if paused:
                print(Fore.RED + f"\n[Ассистент на паузе]: {pause_reason}. Введите /unpause для возобновления.\n")
                continue

            if prompt_str.startswith("/pls "):
                msg_text = prompt_str[5:].strip()
                print(Fore.MAGENTA + f"\n[ПРИОРИТЕТНЫЙ СБРОС И ОТПРАВКА]: {msg_text}\n")
                log_session_event(current_session.get("name"), "user_input", f"[ПРИОРИТЕТ] {msg_text}")
                msg = {"realtimeInput": {"text": f"[ПРИОРИТЕТНЫЙ ЗАПРОС / ПЕРЕБИВАНИЕ]: {msg_text}"}}
                await websocket.send(json.dumps(msg))
                continue

            if prompt_str == "/ls":
                sessions = get_session_suggestions()
                print(Fore.YELLOW + "\n--- Доступные сессии ---")
                if sessions:
                    for s in sessions:
                        print(Fore.YELLOW + f" - {s}")
                else:
                    print(Fore.YELLOW + "(Папка sessions/ пуста)")
                print(Fore.YELLOW + "------------------------\n")
                continue

            elif prompt_str.startswith("/s "):
                session_name = prompt_str[3:].strip()
                data, history_text = load_session_history(session_name)
                if data:
                    current_session["name"] = session_name
                    print(Fore.GREEN + f"\n[+] Успешно переключено на сессию: '{session_name}'")
                    print(Fore.YELLOW + "--- ПОСЛЕДНЯЯ ИСТОРИЯ СЕССИИ ---")
                    print(Fore.WHITE + (history_text if history_text else "(История пуста)"))
                    print(Fore.YELLOW + "--------------------------------\n")

                    context_msg = {
                        "realtimeInput": {
                            "text": f"[СИСТЕМНОЕ СООБЩЕНИЕ: Переключение на сессию '{session_name}']. Вот история предыдущего диалога этой сессии:\n\n{history_text}\n\nПродолжай работу с пользователем с этого момента."
                        }
                    }
                    await websocket.send(json.dumps(context_msg))
                else:
                    current_session["name"] = session_name
                    log_session_event(session_name, "session_created", f"Создана сессия {session_name}")
                    print(Fore.GREEN + f"\n[+] Создана новая сессия: '{session_name}'\n")
                continue

            elif prompt_str == "/new":
                current_session["name"] = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                log_session_event(current_session["name"], "session_created", "Новая сессия")
                print(Fore.GREEN + f"\n[+] Начата новая сессия: '{current_session['name']}'\n")
                continue

            print(Fore.CYAN + f"[User]: {prompt_str}\n")
            log_session_event(current_session.get("name"), "user_input", prompt_str)

            msg = {
                "realtimeInput": {
                    "text": prompt_str
                }
            }
            await websocket.send(json.dumps(msg))

        except Exception as e:
            print(Fore.RED + f"Ошибка ввода: {e}")
            break

# ===== ГЛАВНАЯ ТОЧКА ВХОДА =====

async def main():
    print(Fore.GREEN + Style.BRIGHT + "==========================================================")
    print(Fore.GREEN + Style.BRIGHT + "   Gemini Live API Agent (gemini-3.1-flash-live-preview)  ")
    print(Fore.GREEN + Style.BRIGHT + "==========================================================\n")

    current_session = {"name": f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"}

    initial_task = input(Fore.YELLOW + "Введите начальную задачу для Gemini Agent > " + Style.RESET_ALL)
    if not initial_task.strip():
        print(Fore.RED + "Задача не может быть пустой.")
        return

    log_session_event(current_session["name"], "user_input", initial_task)

    print(Fore.CYAN + f"\nПодключение к Gemini Live API ({MODEL_NAME})...")

    try:
        async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=10) as websocket:
            print(Fore.GREEN + "WebSocket Подключен!")

            setup_message = {
                "setup": {
                    "model": f"models/{MODEL_NAME}",
                    "generationConfig": {
                        "responseModalities": ["AUDIO"],
                        "temperature": 0.2,
                        "topP": 0.95,
                        "thinkingConfig": {
                            "thinkingLevel": "MEDIUM"
                        }
                    },
                    "systemInstruction": {
                        "parts": [{"text": SYSTEM_INSTRUCTION}]
                    },
                    "tools": [{
                        "functionDeclarations": [
                            {
                                "name": "set_session_name",
                                "description": "Устанавливает понятное системное имя сессии (snake_case). Вызывается в самом начале работы.",
                                "parameters": {
                                    "type": "OBJECT",
                                    "properties": {
                                        "name": {"type": "STRING", "description": "Понятное имя латиницей (например: minecraft_shader_bheem)"}
                                    },
                                    "required": ["name"]
                                }
                            },
                            {
                                "name": "exec_command",
                                "description": "Выполняет консольную команду Windows (cmd).",
                                "parameters": {
                                    "type": "OBJECT",
                                    "properties": {
                                        "cmd": {"type": "STRING", "description": "Команда CMD"},
                                        "workdir": {"type": "STRING", "description": "Рабочая директория"}
                                    },
                                    "required": ["cmd"]
                                }
                            },
                            {
                                "name": "read_file_advanced",
                                "description": "Читает строки файла по номерам или по шаблонам-якорям.",
                                "parameters": {
                                    "type": "OBJECT",
                                    "properties": {
                                        "path": {"type": "STRING"},
                                        "start_line": {"type": "INTEGER"},
                                        "end_line": {"type": "INTEGER"},
                                        "start_pattern": {"type": "STRING"},
                                        "end_pattern": {"type": "STRING"}
                                    },
                                    "required": ["path"]
                                }
                            },
                            {
                                "name": "replace_block",
                                "description": "Заменяет блок кода в файле на новое содержимое.",
                                "parameters": {
                                    "type": "OBJECT",
                                    "properties": {
                                        "path": {"type": "STRING"},
                                        "new_content": {"type": "STRING"},
                                        "start_line": {"type": "INTEGER"},
                                        "end_line": {"type": "INTEGER"},
                                        "start_pattern": {"type": "STRING"},
                                        "end_pattern": {"type": "STRING"}
                                    },
                                    "required": ["path", "new_content"]
                                }
                            },
                            {
                                "name": "search_code_with_lines",
                                "description": "Ищет фрагмент в коде и отдает найденное с нумерацией строк.",
                                "parameters": {
                                    "type": "OBJECT",
                                    "properties": {
                                        "path": {"type": "STRING"},
                                        "query": {"type": "STRING"},
                                        "context": {"type": "INTEGER"}
                                    },
                                    "required": ["query"]
                                }
                            },
                            {
                                "name": "run_python_code",
                                "description": "Исполняет чистый Python код.",
                                "parameters": {
                                    "type": "OBJECT",
                                    "properties": {
                                        "code": {"type": "STRING"}
                                    },
                                    "required": ["code"]
                                }
                            },
                            {
                                "name": "check_python_syntax",
                                "description": "Проверяет файл Python на синтаксические ошибки без запуска.",
                                "parameters": {
                                    "type": "OBJECT",
                                    "properties": {
                                        "path": {"type": "STRING"}
                                    },
                                    "required": ["path"]
                                }
                            },
                            {
                                "name": "get_file_info",
                                "description": "Возвращает метаданные файла.",
                                "parameters": {
                                    "type": "OBJECT",
                                    "properties": {
                                        "path": {"type": "STRING"}
                                    },
                                    "required": ["path"]
                                }
                            },
                            {
                                "name": "write_file",
                                "description": "Создает или полностью перезаписывает файл.",
                                "parameters": {
                                    "type": "OBJECT",
                                    "properties": {
                                        "path": {"type": "STRING"},
                                        "content": {"type": "STRING"}
                                    },
                                    "required": ["path", "content"]
                                }
                            },
                            {
                                "name": "list_directory",
                                "description": "Возвращает список файлов в директории.",
                                "parameters": {
                                    "type": "OBJECT",
                                    "properties": {
                                        "path": {"type": "STRING"}
                                    }
                                }
                            },
                            {
                                "name": "run_tests",
                                "description": "Запускает тесты проекта.",
                                "parameters": {
                                    "type": "OBJECT",
                                    "properties": {
                                        "test_command": {"type": "STRING"}
                                    }
                                }
                            },
                            {
                                "name": "get_git_status",
                                "description": "Возвращает git status проекта.",
                                "parameters": {"type": "OBJECT", "properties": {}}
                            },
                            {
                                "name": "web_search",
                                "description": "Выполняет поиск в сети (Google / DuckDuckGo) для получения информации.",
                                "parameters": {
                                    "type": "OBJECT",
                                    "properties": {
                                        "query": {"type": "STRING"},
                                        "max_results": {"type": "INTEGER"}
                                    },
                                    "required": ["query"]
                                }
                            },
                            {
                                "name": "fetch_web_page",
                                "description": "Загружает и читает веб-страницу по указанному URL (URL Context).",
                                "parameters": {
                                    "type": "OBJECT",
                                    "properties": {
                                        "url": {"type": "STRING"},
                                        "mode": {"type": "STRING"}
                                    },
                                    "required": ["url"]
                                }
                            },
                            {
                                "name": "view_image_or_file",
                                "description": "Инспектирует картинку или бинарный файл.",
                                "parameters": {
                                    "type": "OBJECT",
                                    "properties": {
                                        "path": {"type": "STRING"}
                                    },
                                    "required": ["path"]
                                }
                            },
                            {
                                "name": "request_user_input",
                                "description": "Задает уточнающий вопрос пользователю.",
                                "parameters": {
                                    "type": "OBJECT",
                                    "properties": {
                                        "question": {"type": "STRING"}
                                    },
                                    "required": ["question"]
                                }
                            }
                        ]
                    }]
                }
            }

            await websocket.send(json.dumps(setup_message))
            print(Fore.GREEN + "Конфигурация и инструменты переданы. Кэш контекста активен.\n")

            receive_task = asyncio.create_task(receive_loop(websocket, current_session))
            input_task = asyncio.create_task(user_interactive_loop(websocket, current_session))

            print(Fore.CYAN + f"[ВЫ]: {initial_task}\n")
            initial_msg = {
                "realtimeInput": {
                    "text": initial_task
                }
            }
            await websocket.send(json.dumps(initial_msg))

            await asyncio.gather(receive_task, input_task)

    except Exception as e:
        print(Fore.RED + f"\nОшибка соединения WebSocket: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(Fore.YELLOW + "\nЗавершение работы ассистента.")