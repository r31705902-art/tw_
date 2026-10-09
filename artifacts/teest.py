import asyncio
import atexit
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
from rich.console import Console
from rich.markdown import Markdown

from colorama import Fore, Style, init
import websockets
console = Console()

init(autoreset=True)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INI_PATH = os.path.join(SCRIPT_DIR, "s.ini")
KEYS_TXT_PATH = os.path.join(SCRIPT_DIR, "keys.txt")
USAGE_JSON_PATH = os.path.join(SCRIPT_DIR, "usage.json")
SESSIONS_DIR = os.path.join(SCRIPT_DIR, "sessions")

os.makedirs(SESSIONS_DIR, exist_ok=True)

# ===== МЕНЕДЖЕР API КЛЮЧЕЙ И ОТСЛЕЖИВАНИЕ ЛИМИТОВ (USAGE) =====

MODEL_LIMITS = {
    "gemini-3.6-flash": {"RPM": 5, "RPD": 20},
    "gemini-3.1-flash-live-preview": {"RPM": 1000000000000000, "RPD": 1000000000000000}
}

# ===== ИСПРАВЛЕННЫЙ МЕНЕДЖЕР API КЛЮЧЕЙ С МГНОВЕННЫМ СОХРАНЕНИЕМ И СЧЕТОМ КАЖДОГО ТУРНА =====

class KeyManager:
    """Управляет списком API ключей, учитывает каждый ход Live API и мгновенно сохраняет на диск."""
    def __init__(self):
        self.lock = threading.Lock()
        self.keys = self._load_keys_from_txt()
        self.usage_data = self._load_usage_file()
        self._sync_keys()

    def _load_keys_from_txt(self) -> list:
        if not os.path.exists(KEYS_TXT_PATH):
            with open(KEYS_TXT_PATH, "w", encoding="utf-8") as f:
                f.write("# Вставьте ваши API ключи Gemini по одному на строку\n")
            print(Fore.YELLOW + f"[KeyManager] Файл {KEYS_TXT_PATH} создан. Добавьте в него API ключи.")
            return []

        with open(KEYS_TXT_PATH, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        
        if not lines:
            env_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            if env_key:
                lines.append(env_key)
        return lines

    def _load_usage_file(self) -> dict:
        if os.path.exists(USAGE_JSON_PATH):
            try:
                with open(USAGE_JSON_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(Fore.RED + f"[KeyManager Error]: Ошибка чтения usage.json: {e}")
        return {}

    def _sync_keys(self):
        now = time.time()
        for k in self.keys:
            if k not in self.usage_data:
                self.usage_data[k] = {}
            for model in ["gemini-3.6-flash", "gemini-3.1-flash-live-preview"]:
                if model not in self.usage_data[k]:
                    self.usage_data[k][model] = {
                        "rpm": 0,
                        "rpd": 0,
                        "rpm_reset": now,
                        "rpd_reset": now,
                        "cooldown": 0
                    }

    def save_to_disk(self):
        """Мгновенно сохраняет метрики на диск."""
        try:
            with open(USAGE_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(self.usage_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(Fore.RED + f"[KeyManager Error]: Ошибка сохранения usage.json: {e}")

    def get_best_key(self, model_name: str) -> str:
        with self.lock:
            now = time.time()
            limits = MODEL_LIMITS.get(model_name, {"RPM": 5, "RPD": 20})

            if not self.keys:
                raise ValueError("Список API ключей пуст! Заполните keys.txt")

            for key in self.keys:
                m_info = self.usage_data[key][model_name]

                # Сброс минутной квоты (RPM)
                if now - m_info.get("rpm_reset", 0) >= 60:
                    m_info["rpm"] = 0
                    m_info["rpm_reset"] = now

                # Сброс дневной квоты (RPD)
                if now - m_info.get("rpd_reset", 0) >= 86400:
                    m_info["rpd"] = 0
                    m_info["rpd_reset"] = now

                # Проверка КД
                if now < m_info.get("cooldown", 0):
                    continue

                if m_info["rpm"] < limits["RPM"] and m_info["rpd"] < limits["RPD"]:
                    return key

            best_key = min(self.keys, key=lambda k: self.usage_data[k][model_name].get("cooldown", 0))
            return best_key

    def record_usage(self, key: str, model_name: str, count: int = 1):
        """Записывает использование и сразу сохраняет файл на диск."""
        with self.lock:
            if key in self.usage_data and model_name in self.usage_data[key]:
                m_info = self.usage_data[key][model_name]
                m_info["rpm"] += count
                m_info["rpd"] += count
                self.save_to_disk() # Мгновенная запись на диск!

    def mark_cooldown(self, key: str, model_name: str, seconds: int = 60):
        with self.lock:
            if key in self.usage_data and model_name in self.usage_data[key]:
                self.usage_data[key][model_name]["cooldown"] = time.time() + seconds
                self.save_to_disk()
                print(Fore.YELLOW + f"[KeyManager] Ключ {key[:8]}... отправлен на КД на {seconds}с для {model_name}")
                
key_mgr = KeyManager()
atexit.register(key_mgr.save_to_disk)

MODEL_LIVE = "gemini-3.1-flash-live-preview"
MODEL_FLASH = "gemini-3.6-flash"


# ===== ЛОГИРОВАНИЕ И РАБОТА С СЕССИЯМИ (С СОХРАНЕНИЕМ CWD И SANITIZATION) =====

def sanitize_utf8_text(text: str) -> str:
    """Очищает текст от битых суррогатов UTF-8 и управляющих символов (Полный фикс ошибки WebSocket 1007)."""
    if not text:
        return ""
    if not isinstance(text, str):
        text = str(text)
    
    # 1. Жесткая очистка от непарных UTF-16/UTF-8 суррогатов (главная причина WS 1007)
    clean_bytes = text.encode('utf-8', 'ignore')
    text = clean_bytes.decode('utf-8', 'ignore')
    
    # 2. Удаление управляющих символов (кроме перевода строки \n, \r и табуляции \t)
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ufffd]', '', text)

def log_session_event(session_name: str, event_type: str, content: dict or str):
    if not session_name:
        return
    session_file = os.path.join(SESSIONS_DIR, f"{session_name}.json")
    try:
        data = {"created": str(datetime.now()), "name": session_name, "cwd": cmd_engine.cwd, "history": []}
        if os.path.exists(session_file):
            try:
                with open(session_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                pass

        data["updated"] = str(datetime.now())
        data["cwd"] = cmd_engine.cwd  # Запоминаем папку проекта!
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


def load_session_history(session_name: str) -> tuple[dict, str]:
    session_file = os.path.join(SESSIONS_DIR, f"{session_name}.json")
    if not os.path.exists(session_file):
        return None, f"Сессия '{session_name}' не найдена."
    try:
        with open(session_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Автоматически восстанавливаем папку проекта при загрузке сессии!
        saved_cwd = data.get("cwd")
        if saved_cwd and os.path.exists(saved_cwd):
            cmd_engine.cwd = saved_cwd
            print(Fore.GREEN + f"[+] Восстановлена рабочая папка проекта: {saved_cwd}")

        formatted_history = []
        for item in data.get("history", []):
            htype = item.get("type")
            content = item.get("content")
            if htype == "user_input":
                formatted_history.append(f"User: {content}")
            elif htype == "model_response":
                formatted_history.append(f"HEEM: {content}")
            elif htype == "tool_call" and isinstance(content, dict):
                formatted_history.append(f"Tool {content.get('name')}: {sanitize_utf8_text(str(content.get('result')))[:200]}")

        history_text = "\n".join(formatted_history[-30:])
        return data, history_text
    except Exception as e:
        return None, f"Ошибка чтения сессии: {e}"
    
def tool_set_session_name(current_session: dict, new_name: str) -> str:
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
            # os.replace перезаписывает файл в Windows без ошибки WinError 183
            os.replace(old_file, new_file)
            return f"Сессия переименована с '{old_name}' на '{clean_name}'."
        else:
            log_session_event(clean_name, "session_renamed", f"Сессия названа {clean_name}")
            return f"Установлено имя сессии: '{clean_name}'."
    except Exception as e:
        return f"Ошибка переименования сессии: {e}"

# ===== CMD ДВИЖОК =====

is_waiting_user_question = False

class CMDSession:
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

    def execute(self, cmd: str, workdir: str = None, timeout: int = 120, input_data: str = None) -> str:
        with self.lock:
            if workdir and os.path.exists(workdir):
                self.cwd = os.path.abspath(workdir)

            cwd_sentinel = f"__CWD_MARKER_{uuid.uuid4().hex[:6]}__"
            full_cmd = f'@chcp 65001 >nul & {cmd}\n@echo {cwd_sentinel} & cd'

            print(Fore.CYAN + f"\n[CMD Executing]: {Style.BRIGHT}{cmd}")
            if input_data:
                print(Fore.YELLOW + f"[CMD Stdin Input]:\n{input_data.strip()}")
            t0 = time.time()

            try:
                proc = subprocess.Popen(
                    ["cmd.exe", "/Q", "/S", "/C", full_cmd],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    cwd=self.cwd
                )

                if input_data:
                    if not input_data.endswith("\n"):
                        input_data += "\n"
                    stdin_bytes = input_data.encode("utf-8")
                else:
                    stdin_bytes = b"\n"

                stdout_bytes, _ = proc.communicate(input=stdin_bytes, timeout=timeout)
                elapsed = (time.time() - t0) * 1000

            except subprocess.TimeoutExpired:
                proc.kill()
                stdout_bytes, _ = proc.communicate()
                elapsed = (time.time() - t0) * 1000
                raw_text = sanitize_utf8_text(self._decode_bytes(stdout_bytes))

                prompt_indicators = ["(y/n)", "[y/n]", "y/n", "[y/N]", "choice", "выберите", "пароль", "password", "enter", "press any key", ">"]
                tail = raw_text.strip().lower()[-200:] if raw_text else ""
                
                is_prompt = any(ind in tail for ind in prompt_indicators)

                if is_prompt:
                    msg = (
                        f"{raw_text}\n\n"
                        f"[ТРЕБУЕТСЯ ВВОД ПОЛЬЗОВАТЕЛЯ / ВЫБОР]: Программа застряла в ожидании ввода! "
                        f"Лог программы: '{raw_text[-300:]}'. "
                        f"Вызовите `exec_command` с параметром `input_data` (например: 'y\\n' или '1\\n') "
                        f"или спросите пользователя через `request_user_input`."
                    )
                    print(Fore.MAGENTA + "\n[CMD Interactive Prompt Detected]: Обнаружен запрос на ввод!")
                    return sanitize_utf8_text(msg)

                print(Fore.RED + f"[Timeout Error]: Команда превысила таймаут {timeout}s")
                return raw_text + f"\n[ERROR: Процесс остановлен по таймауту {timeout} сек.]"

            except Exception as e:
                err = f"[CMD System Error]: {e}"
                print(Fore.RED + err)
                return err

            raw_output = sanitize_utf8_text(self._decode_bytes(stdout_bytes)).strip()

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

import queue

def truncate_large_output(text: str, max_chars: int = 10000) -> str:
    if not text:
        return ""
    if len(text) > max_chars:
        return text[:max_chars] + f"\n... [Вывод урезан, т.к превысил {max_chars} символов]"
    return text

# ===== МЕНЕДЖЕР ФОНОВЫХ ПРОЦЕССОВ =====

class BackgroundProcessManager:
    def __init__(self):
        self.jobs = {}
        self.lock = threading.Lock()
        self.counter = 1

    def start_job(self, cmd: str, workdir: str = None) -> str:
        job_id = f"job_{self.counter}"
        self.counter += 1

        cwd = workdir if (workdir and os.path.exists(workdir)) else cmd_engine.cwd
        full_cmd = f'@chcp 65001 >nul & {cmd}'

        print(Fore.CYAN + f"\n[BG Job Started]: {job_id} -> {cmd}")

        proc = subprocess.Popen(
            ["cmd.exe", "/Q", "/S", "/C", full_cmd],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=cwd
        )

        log_queue = queue.Queue()

        def reader_thread(process, q):
            while True:
                line_bytes = process.stdout.readline()
                if not line_bytes and process.poll() is not None:
                    break
                if line_bytes:
                    line_str = cmd_engine._decode_bytes(line_bytes)
                    clean = sanitize_utf8_text(line_str)
                    q.put(clean)
                    sys.stdout.write(Fore.LIGHTBLACK_EX + f"[{job_id}] " + Fore.WHITE + clean)
                    sys.stdout.flush()

        t = threading.Thread(target=reader_thread, args=(proc, log_queue), daemon=True)
        t.start()

        with self.lock:
            self.jobs[job_id] = {
                "proc": proc,
                "queue": log_queue,
                "cmd": cmd,
                "thread": t,
                "all_logs": [] # Полный архив логов (хранится в памяти на всякий случай)
            }

        return f"Запущен фоновый процесс {job_id} для команды: '{cmd}'. Используйте `get_bg_logs('{job_id}')` для проверки вывода."
    
    async def wait_for_job(self, job_id: str, timeout: int = 30) -> str:
        """Ждет появления НОВЫХ логов или завершения процесса, не блокируя WebSocket."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            with self.lock:
                if job_id not in self.jobs:
                    return f"Ошибка: Процесс '{job_id}' не найден."
                job = self.jobs[job_id]

            # Если в очереди ПОЯВИЛИСЬ НОВЫЕ логи или процесс завершился — сразу отдаем результат
            if not job["queue"].empty() or job["proc"].poll() is not None:
                return self.get_logs(job_id)

            await asyncio.sleep(1) # Неблокирующая пауза 1 сек

        return self.get_logs(job_id)
    
    def get_logs(self, job_id: str, max_lines: int = 50) -> str:
        """Возвращает СТРОГО ТОЛЬКО НОВЫЕ строки, поступившие с момента последней проверки."""
        with self.lock:
            if job_id not in self.jobs:
                return f"Ошибка: Процесс '{job_id}' не найден."
            job = self.jobs[job_id]

        new_lines = []
        q = job["queue"]

        # Извлекаем все СВЕЖИЕ строки из очереди (они удаляются из очереди и больше не повторятся!)
        while not q.empty():
            try:
                line = q.get_nowait()
                job["all_logs"].append(line)
                new_lines.append(line)
            except queue.Empty:
                break

        is_running = job["proc"].poll() is None
        status_str = "РАБОТАЕТ" if is_running else f"ЗАВЕРШЕН (код {job['proc'].returncode})"

        # Если новых логов нет
        if not new_lines:
            return f"--- [Статус {job_id}: {status_str}] ---\n(Новых логов с момента последней проверки нет)"

        # Схлопываем повторяющиеся ошибки/строки (Дедупликация)
        deduped_lines = []
        prev_line = None
        dup_count = 0

        for line in new_lines:
            if line == prev_line:
                dup_count += 1
            else:
                if dup_count > 1:
                    deduped_lines.append(f"   [повторялось ещё {dup_count - 1} раз...]\n")
                deduped_lines.append(line)
                prev_line = line
                dup_count = 1

        if dup_count > 1:
            deduped_lines.append(f"   [повторялось ещё{dup_count - 1} раз...]\n")

        # Ограничиваем количество новых строк
        if len(deduped_lines) > max_lines:
            dropped = len(deduped_lines) - max_lines
            deduped_lines = deduped_lines[-max_lines:]
            output = f"... Пропущено {dropped} более старых НОВЫХ строк] ...\n" + "".join(deduped_lines)
        else:
            output = "".join(deduped_lines)

        return truncate_large_output(f"--- [Статус {job_id}: {status_str}] ---\n{output}", max_chars=10000)

    def send_input(self, job_id: str, input_text: str) -> str:
        with self.lock:
            if job_id not in self.jobs:
                return f"Ошибка: Процесс '{job_id}' не найден."
            job = self.jobs[job_id]

        if job["proc"].poll() is not None:
            return f"Процесс '{job_id}' уже завершен."

        try:
            if not input_text.endswith("\n"):
                input_text += "\n"
            job["proc"].stdin.write(input_text.encode("utf-8"))
            job["proc"].stdin.flush()
            return f"Ввод '{input_text.strip()}' успешно отправлен в {job_id}."
        except Exception as e:
            return f"Ошибка отправки ввода: {e}"

    def stop_job(self, job_id: str) -> str:
        with self.lock:
            if job_id not in self.jobs:
                return f"Ошибка: Процесс '{job_id}' не найден."
            job = self.jobs[job_id]

        if job["proc"].poll() is not None:
            return f"Процесс '{job_id}' уже завершен."

        try:
            job["proc"].kill()
            return f"Процесс '{job_id}' принудительно остановлен (killed)."
        except Exception as e:
            return f"Ошибка остановки процесса: {e}"

    def list_jobs(self) -> str:
        with self.lock:
            if not self.jobs:
                return "Нет запущенных фоновых процессов."
            res = []
            for jid, j in self.jobs.items():
                running = j["proc"].poll() is None
                status = "РАБОТАЕТ" if running else f"ЗАВЕРШЕН ({j['proc'].returncode})"
                res.append(f"{jid}: [{status}] {j['cmd']}")
            return "\n".join(res)
        
bg_mgr = BackgroundProcessManager()

# ===== УТИЛИТЫ И ИНСТРУМЕНТЫ РАБОТЫ С КОДОМ, ВЕБОМ И ФАЙЛАМИ =====

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
        clean_path = path.strip('"\'' )
        if not clean_path or not os.path.exists(clean_path):
            return f"Ошибка: Файл '{clean_path}' не существует."

        with open(clean_path, "r", encoding="utf-8", errors="replace") as f:
            file_text = f.read()
            lines = file_text.splitlines(keepends=True)

        total_lines = len(lines)
        if total_lines == 0:
            return f"Ошибка: Файл '{clean_path}' пуст."

        actual_start = None
        actual_end = None

        # 1. Поиск по шаблонам (start_pattern / end_pattern)
        if start_pattern:
            matches = [i + 1 for i, l in enumerate(lines) if start_pattern in l]
            if len(matches) == 1:
                actual_start = matches[0]
            elif len(matches) > 1:
                matched_details = "\n".join([f"  Строка {m}: {lines[m-1].strip()}" for m in matches[:5]])
                return f"Ошибка: Найдено несколько ({len(matches)}) совпадений для 'start_pattern':\n{matched_details}\nУкажите 'start_line' или более точный 'start_pattern'."
            else:
                if start_pattern in file_text:
                    start_char_idx = file_text.find(start_pattern)
                    actual_start = file_text[:start_char_idx].count('\n') + 1

        if actual_start is None and start_line and start_line > 0:
            actual_start = start_line

        if actual_start is None:
            return (
                f"Ошибка: Не указана начальная строка (start_line) и шаблон (start_pattern) не найден.\n"
                f"Всего строк в файле: {total_lines}. Воспользуйтесь 'read_file_advanced' для просмотра номеров строк."
            )

        if end_pattern:
            matches = [i + 1 for i, l in enumerate(lines) if end_pattern in l]
            if matches:
                actual_end = max([m for m in matches if m >= actual_start], default=actual_start)
        if actual_end is None and end_line and end_line > 0:
            actual_end = end_line
        if actual_end is None:
            actual_end = actual_start

        actual_start = max(1, min(actual_start, total_lines))
        actual_end = max(1, min(actual_end, total_lines))

        if actual_start > actual_end:
            return f"Ошибка: Начальная строка ({actual_start}) больше конечной ({actual_end})."

        replacement_lines = [l + "\n" for l in new_content.splitlines()]
        if not new_content.endswith("\n") and replacement_lines:
            replacement_lines[-1] = replacement_lines[-1].rstrip("\n") + "\n"

        lines[actual_start - 1 : actual_end] = replacement_lines

        with open(clean_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        return f"Успешно заменен блок со строки {actual_start} по {actual_end} в файле {os.path.basename(clean_path)}."

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
                if any(ignored in root for ignored in [".git", "__pycache__", "node_modules", "venv", "sessions"]):
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
    """Сжимает изображение и возвращает Base64 строки."""
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
        # Очищаем кавычки
        clean_path = path.strip('"\'' )
        if not os.path.exists(clean_path):
            return f"Ошибка: Файл '{clean_path}' не существует."

        mime_type, _ = mimetypes.guess_type(clean_path)
        if not mime_type:
            mime_type = "application/octet-stream"

        if mime_type.startswith("image/") or clean_path.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp')):
            b64 = compress_image_to_b64(clean_path)
            return json.dumps({
                "file_name": os.path.basename(clean_path),
                "mime_type": "image/jpeg",
                "data_b64": b64,
                "note": "Изображение подготовлена и передается в визуальный поток."
            }, ensure_ascii=False)
        else:
            with open(clean_path, "rb") as f:
                chunk = f.read(2048)
                is_binary = b"\x00" in chunk

            if is_binary:
                with open(clean_path, "rb") as f:
                    raw = f.read(100000)
                b64 = base64.b64encode(raw).decode("utf-8")
                return json.dumps({
                    "file_name": os.path.basename(clean_path),
                    "mime_type": mime_type,
                    "data_uri": f"data:{mime_type};base64,{b64}"
                }, ensure_ascii=False)
            else:
                with open(clean_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read(20000)
                return f"Файл {clean_path} (Текст):\n" + content

    except Exception as e:
        return f"Ошибка инспектирования файла: {str(e)}"


async def tool_request_user_input(question: str) -> str:
    global is_waiting_user_question
    is_waiting_user_question = True
    try:
        print(Fore.MAGENTA + Style.BRIGHT + f"\n[ПАУЗА / ВОПРОС ОТ HEEM]: {question}")
        loop = asyncio.get_event_loop()
        user_reply = await loop.run_in_executor(None, input, Fore.GREEN + "Ваш ответ > " + Style.RESET_ALL)
        return user_reply
    finally:
        is_waiting_user_question = False


# ===== ИНТЕГРАЦИЯ GEMINI 3.6 FLASH (СУБ-ЧАТ / КОНСУЛЬТАЦИЯ) =====

SYSTEM_INSTRUCTION_36_FLASH = """
Ты — Старший AI-Архитектор и Главный Кодер уровня Staff Engineer.
Твой клиент — автономный AI-разработчик HEEM агент, работающий прямо на ПК пользователя.

ТВОЯ ЗАДАЧА:
1. Когда HEEM запрашивает помощь (из-за ошибки, неясной инструкции или сложной задачи по программированию/архитектуре) — дай ему ТОЧНЫЙ, ИСЧЕРПЫВАЮЩИЙ и сразу ПРИМЕНИМЫЙ ответ.
2. Всегда пиши ПОЛНЫЙ, рабочий код без сокращений ("// остальной код без изменений" — ЗАПРЕЩЕНО).
3. Структурируй ответ:
   - Причина проблемы / Архитектурное решение
   - Пошаговые инструкции для HEEM агента
   - Полный исправленный или новый код.
"""

def tool_consult_gemini_36_flash(current_session: dict, prompt: str, code_context: str = "") -> str:
    """Выполняет REST-запрос к Gemini 3.6 Flash с сохранением под-чата и ротацией ключей."""
    session_name = current_session.get("name", "default_session")
    subchat_file = os.path.join(SESSIONS_DIR, f"{session_name}_flash36.json")
    print(Fore.MAGENTA + f"\n[GEMINI 3.6 FLASH CONSULTATION]: Запрос от HEEM...")

    history = []
    if os.path.exists(subchat_file):
        try:
            with open(subchat_file, "r", encoding="utf-8") as f:
                sub_data = json.load(f)
                history = sub_data.get("history", [])
        except Exception:
            history = []

    full_input_text = prompt
    if code_context:
        full_input_text += f"\n\n--- КОНТЕКСТ КОДА / ОШИБКИ ---\n{code_context}"

    history.append({"role": "user", "parts": [{"text": full_input_text}]})

    payload = {
        "systemInstruction": {
            "parts": [{"text": SYSTEM_INSTRUCTION_36_FLASH}]
        },
        "contents": history,
        "generationConfig": {
            "temperature": 0.2,
            "thinkingConfig": {
                "thinkingLevel": "MEDIUM"
            }
        }
    }

    max_retries = len(key_mgr.keys) or 1
    for attempt in range(max_retries):
        api_key = key_mgr.get_best_key(MODEL_FLASH)
        key_mgr.record_usage(api_key, MODEL_FLASH)

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_FLASH}:generateContent?key={api_key}"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )

        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                
                candidates = res_data.get("candidates", [])
                if not candidates:
                    return "Gemini 3.6 Flash вернул пустой ответ."

                model_text = ""
                for p in candidates[0].get("content", {}).get("parts", []):
                    if "text" in p:
                        model_text += p["text"]

                history.append({"role": "model", "parts": [{"text": model_text}]})
                with open(subchat_file, "w", encoding="utf-8") as f:
                    json.dump({"updated": str(datetime.now()), "history": history}, f, ensure_ascii=False, indent=2)

                print(Fore.MAGENTA + f"[GEMINI 3.6 FLASH ОТВЕТИЛ]: {len(model_text)} символов.")
                return model_text

        except urllib.error.HTTPError as e:
            if e.code == 429:
                print(Fore.YELLOW + f"[429 Quota Error]: Gemini 3.6 Flash ключ {api_key[:8]}... исчерпан. Повтор с новым ключом.")
                key_mgr.mark_cooldown(api_key, MODEL_FLASH, seconds=120)
                continue
            else:
                err_msg = e.read().decode("utf-8", errors="ignore")
                return f"HTTP Ошибка {e.code} при обращении к Gemini 3.6 Flash: {err_msg}"
        except Exception as e:
            return f"Ошибка соединения с Gemini 3.6 Flash: {e}"

    return "Ошибка: Все доступные API-ключи для Gemini 3.6 Flash на КД или исчерпаны."


# ===== ОБРАБОТЧИК ВЫЗОВОВ ФУНКЦИЙ =====

async def execute_tool(func_name: str, args: dict, current_session: dict = None) -> str:
    if func_name == "set_session_name" and current_session:
        return tool_set_session_name(current_session, args.get("name", ""))
    elif func_name == "consult_gemini_36_flash":
        return tool_consult_gemini_36_flash(current_session, args.get("prompt", ""), args.get("code_context", ""))
    elif func_name == "exec_command":
        return cmd_engine.execute(
            cmd=args.get("cmd", ""),
            workdir=args.get("workdir"),
            timeout=args.get("timeout", 120),
            input_data=args.get("input_data")
        )
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
        
    elif func_name == "start_bg_command":
        return bg_mgr.start_job(args.get("cmd", ""), args.get("workdir"))
    elif func_name == "get_bg_logs":
        return bg_mgr.get_logs(args.get("job_id", ""))
    elif func_name == "send_bg_input":
        return bg_mgr.send_input(args.get("job_id", ""), args.get("input_text", ""))
    elif func_name == "stop_bg_command":
        return bg_mgr.stop_job(args.get("job_id", ""))
    elif func_name == "list_bg_commands":
        return bg_mgr.list_jobs()
    elif func_name == "wait_for_bg_job":
        return await bg_mgr.wait_for_job(args.get("job_id", ""), args.get("timeout", 30))
    
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


# ===== СИСТЕМНЫЙ ПРОМПТ ДЛЯ HEEM =====

# ===== ОБНОВЛЕННЫЙ СИСТЕМНЫЙ ПРОМПТ ДЛЯ HEEM =====

SYSTEM_INSTRUCTION = """
You are HEEM, a Principal AI Software Engineer operating directly on the user's computer.

CRITICAL OPERATIONAL RULES:
1. ALWAYS EXPLAIN BEFORE ACTING:
   - BEFORE calling any tool (like write_file, replace_block, exec_command), you MUST output a brief text sentence explaining to the user WHAT you are about to do and WHERE. Never call tools silently without context.

2. PATH & DIRECTORY VERIFICATION:
   - ALWAYS verify the target path before modifying files. If working with Minecraft shaderpacks, remember that shaders are located in 'C:\\Users\\Rb\\AppData\\Roaming\\.minecraft\\shaderpacks\\...' unless specified otherwise.
   - Do NOT assume relative paths ('.') are correct if the project is located in another folder.

3. SESSION MANAGEMENT:
   - On your very first response in a turn/task, you MUST call `set_session_name` with a descriptive, concise `snake_case` name.

4. CODE QUALITY & PRECISE EDITING:
   - NO STUBS OR TRUNCATION: Never write placeholder code or stub comments. Always write fully functional, complete blocks of code.
   - READ BEFORE EDITING: Always use `read_file_advanced` or `search_code_with_lines` to inspect line numbers before calling `replace_block`.
   - EDITS: Provide exact `start_line` and `end_line` parameters in `replace_block`. If replacing an entire file or a large section, prefer `write_file`.

6. TOOL MASTERY & SSH / INTERACTIVE CONSOLE:
   - `exec_command`:
     * INTERACTIVE & SSH COMMANDS: NEVER pass remote commands inside arguments when connecting to tmate or interactive SSH (e.g. DO NOT run `ssh user@host "command"`, as servers like tmate return 'Invalid command').
     * FOR SSH / TMATE: Call `exec_command` with SSH parameters, and pass all shell commands into `input_data` line by line, ending with `exit\n`.
       Example SSH call via `exec_command`:
         cmd: "ssh root@gate-1.outplane.app -p 48722"
         input_data: "cat /sys/fs/cgroup/cpu.max 2>/dev/null || cat /sys/fs/cgroup/cpu/cpu.shares\ncat /sys/fs/cgroup/memory.max 2>/dev/null || cat /sys/fs/cgroup/memory/memory.limit_in_bytes\nexit\n"
     * If a command gets stuck waiting for prompt (`[y/n]`), provide input via `input_data` or ask user via `request_user_input`.
   - `consult_gemini_36_flash`: Use if stuck on compilation errors or complex bugs.
5. FOR INTERACTIVE OR LONG-RUNNING COMMANDS (SSH, downloads, apt, servers):
Use start_bg_command instead of exec_command. This returns a job_id. You can then inspect logs using get_bg_logs, send user inputs/commands mid-execution via send_bg_input, or terminate stuck tasks using stop_bg_command.
"""

def get_session_suggestions() -> list[str]:
    if not os.path.exists(SESSIONS_DIR):
        return []
    files = os.listdir(SESSIONS_DIR)
    return [f[:-5] for f in files if f.endswith(".json") and not f.endswith("_flash36.json")]


# ===== WEBSOCKET ОБРАБОТКА =====

async def handle_tool_call(websocket, tool_call, current_session: dict):
    function_responses = []

    for fc in tool_call.get("functionCalls", []):
        func_name = fc.get("name")
        func_id = fc.get("id")
        args = fc.get("args", {})

        print(f"\n[HEEM ВЫЗВАЛ ИНСТРУМЕНТ]: {func_name}({args})")

        # 1. Выполняем инструмент
        res = await execute_tool(func_name, args, current_session)

        # 2. Очищаем ответ от битых байт
        clean_res = sanitize_utf8_text(str(res))

        # 3. Если вызван просмотр картинки — отправляем кадр
        if func_name == "view_image_or_file":
            path = args.get("path", "").strip('"\'' )
            mime_type, _ = mimetypes.guess_type(path)
            
            if (mime_type and mime_type.startswith("image/")) or path.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp')):
                if os.path.exists(path):
                    b64 = compress_image_to_b64(path)
                    image_msg = {
                        "clientContent": {
                            "turns": [{
                                "role": "user",
                                "parts": [
                                    {"inlineData": {"mimeType": "image/jpeg", "data": b64}},
                                    {"text": f"Вот файл изображения '{os.path.basename(path)}'. Внимательно проанализируй его."}
                                ]
                            }],
                            "turnComplete": True
                        }
                    }
                    await websocket.send(json.dumps(image_msg, ensure_ascii=False))

        log_session_event(
            current_session.get("name"),
            "tool_call",
            {"name": func_name, "args": args, "result": clean_res}
        )

        print(f"[РЕЗУЛЬТАТ ИНСТРУМЕНТА]:\n{(clean_res[:300] + '...') if len(clean_res) > 300 else clean_res}\n")

        function_responses.append({
            "name": func_name,
            "id": func_id,
            "response": {"result": clean_res}
        })

    if current_session.get("live_key"):
        key_mgr.record_usage(current_session["live_key"], MODEL_LIVE, count=len(function_responses))

    tool_response_msg = {
        "toolResponse": {
            "functionResponses": function_responses
        }
    }
    # Используем ensure_ascii=False с очищенным UTF-8
    await websocket.send(json.dumps(tool_response_msg, ensure_ascii=False))

# Флаг, указывающий, что модель генерирует ответ или выполняет инструменты
is_model_generating = False

async def receive_loop(websocket, current_session: dict):
    global is_model_generating
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
                    is_model_generating = True
                    current_turn_text.append(text_to_print)
                    if is_first_chunk:
                        print(Fore.GREEN + "\nHEEM: ", end="", flush=True)
                        is_first_chunk = False
                    print(Fore.GREEN + text_to_print, end="", flush=True)

                if server_content.get("turnComplete"):
                    print("\n" + Fore.YELLOW + "--------------------------------------------------", flush=True)
                    full_text = "".join(current_turn_text)
                    if full_text.strip():
                        log_session_event(current_session.get("name"), "model_response", full_text)
                    current_turn_text = []
                    is_first_chunk = True
                    is_model_generating = False
                    # Завершаем цикл, чтобы автоматически закрыть WebSocket соединение после ответа
                    return

            if "toolCall" in response:
                is_model_generating = True
                if not is_first_chunk:
                    print()
                is_first_chunk = True
                await handle_tool_call(websocket, response["toolCall"], current_session)
                is_model_generating = False

    except websockets.exceptions.ConnectionClosed as e:
        print(Fore.YELLOW + f"\n[WebSocket Disconnect]: {e.reason}")
    except Exception as e:
        print(Fore.RED + f"\n[WebSocket Error]: {e}")
    finally:
        is_model_generating = False

TOOLS_DECLARATIONS = [
    {
        "name": "start_bg_command",
        "description": "Запускает консольную команду в ФОНОВОМ ИНТЕРАКТИВНОМ режиме. Возвращает job_id. Используйте для долгих задач, SSH или процессов с вводом.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "cmd": {"type": "STRING"},
                "workdir": {"type": "STRING"}
            },
            "required": ["cmd"]
        }
    },
    {
        "name": "get_bg_logs",
        "description": "Возвращает свежие логи из запущенного фонового процесса по job_id.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"job_id": {"type": "STRING"}},
            "required": ["job_id"]
        }
    },
    {
        "name": "send_bg_input",
        "description": "Отправляет текст/ввод (stdin) в РАБОТАЮЩИЙ фоновый процесс (например, ответ 'y', пароль или следующую команду).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "job_id": {"type": "STRING"},
                "input_text": {"type": "STRING"}
            },
            "required": ["job_id", "input_text"]
        }
    },
    {
        "name": "stop_bg_command",
        "description": "Принудительно останавливает/убивает фоновый процесс по job_id.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"job_id": {"type": "STRING"}},
            "required": ["job_id"]
        }
    },
    {
        "name": "list_bg_commands",
        "description": "Возвращает список всех фоновых процессов и их статусы.",
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "wait_for_bg_job",
        "description": "Умное ожидание завершения или новых логов фонового процесса. Пауза происходит на стороне Python (по умолчанию 30 сек). Используйте ЭТО вместо частых вызовов get_bg_logs! ( К примеру во время установки больших или небольших библиотек или при прочих длинных процессов ( 10-20+ секунд ) )",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "job_id": {"type": "STRING"},
                "timeout": {"type": "INTEGER", "description": "Время ожидания в секундах (например, 30)"}
            },
            "required": ["job_id"]
        }
    },
    {
        "name": "set_session_name",
        "description": "Устанавливает имя сессии (snake_case). Вызывается в начале.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"name": {"type": "STRING"}},
            "required": ["name"]
        }
    },
    {
        "name": "consult_gemini_36_flash",
        "description": "Запрашивает консультацию у модели Gemini 3.6 Flash.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "prompt": {"type": "STRING"},
                "code_context": {"type": "STRING"}
            },
            "required": ["prompt"]
        }
    },
    {
        "name": "exec_command",
        "description": "Выполняет консольную команду Windows (cmd).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "cmd": {"type": "STRING"},
                "workdir": {"type": "STRING"},
                "timeout": {"type": "INTEGER"},
                "input_data": {"type": "STRING"}
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
        "description": "Заменяет блок кода в файле.",
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
        "description": "Ищет фрагмент в коде.",
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
            "properties": {"code": {"type": "STRING"}},
            "required": ["code"]
        }
    },
    {
        "name": "check_python_syntax",
        "description": "Проверяет файл Python на синтаксические ошибки.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"path": {"type": "STRING"}},
            "required": ["path"]
        }
    },
    {
        "name": "get_file_info",
        "description": "Возвращает метаданные файла.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"path": {"type": "STRING"}},
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
            "properties": {"path": {"type": "STRING"}}
        }
    },
    {
        "name": "run_tests",
        "description": "Запускает тесты проекта.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"test_command": {"type": "STRING"}}
        }
    },
    {
        "name": "get_git_status",
        "description": "Возвращает git status проекта.",
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "web_search",
        "description": "Выполняет поиск в сети.",
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
        "description": "Загружает и читает веб-страницу по URL.",
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
        "description": "Просматривает и передает картинку в визуальный поток.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"path": {"type": "STRING"}},
            "required": ["path"]
        }
    },
    {
        "name": "request_user_input",
        "description": "Задает уточняющий вопрос пользователю.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"question": {"type": "STRING"}},
            "required": ["question"]
        }
    }
]


async def send_turn_and_receive(current_session: dict, user_prompt: str):
    """Подключается к WS, передает контекст сессии + новый запрос, принимает ответ и закрывает сокет."""
    clean_prompt = sanitize_utf8_text(user_prompt)
    
    # 1. Записываем запрос пользователя в сессию
    log_session_event(current_session["name"], "user_input", clean_prompt)

    live_key = key_mgr.get_best_key(MODEL_LIVE)
    current_session["live_key"] = live_key
    key_mgr.record_usage(live_key, MODEL_LIVE)
    
    ws_url = f"wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key={live_key}"

    # 2. Подгружаем историю текущей сессии для восстановления контекста
    _, history_text = load_session_history(current_session["name"])

    if history_text:
        full_input_prompt = (
            f"[СИСТЕМНЫЙ КОНТЕКСТ СЕССИИ '{current_session['name']}']:\n{history_text}\n\n"
            f"[НОВЫЙ ЗАПРОС ПОЛЬЗОВАТЕЛЯ]: {clean_prompt}"
        )
    else:
        full_input_prompt = clean_prompt

    try:
        async with websockets.connect(ws_url, ping_interval=20, ping_timeout=10) as websocket:
            setup_message = {
                "setup": {
                    "model": f"models/{MODEL_LIVE}",
                    "generationConfig": {
                        "responseModalities": ["AUDIO"],
                        "temperature": 0.2,
                        "thinkingConfig": {"thinkingLevel": "MEDIUM"}
                    },
                    "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
                    "tools": [{"functionDeclarations": TOOLS_DECLARATIONS}]
                }
            }
            # Отправляем setup
            await websocket.send(json.dumps(setup_message, ensure_ascii=False))

            # Отправляем сообщение пользователя
            msg = {"realtimeInput": {"text": full_input_prompt}}
            await websocket.send(json.dumps(msg, ensure_ascii=False))

            # Принимаем весь ответ модельки
            await receive_loop(websocket, current_session)

    except websockets.exceptions.InvalidStatusCode as e:
        if e.status_code == 429:
            print(Fore.YELLOW + f"\n[429 Quota Exceeded] Ключ {live_key[:8]}... на КД. Повторите запрос.")
            key_mgr.mark_cooldown(live_key, MODEL_LIVE, seconds=120)
        else:
            print(Fore.RED + f"\nОшибка WebSocket HTTP {e.status_code}: {e}")
    except Exception as e:
        print(Fore.RED + f"\nСбой подключения: {e}")


async def main():
    print(Fore.GREEN + Style.BRIGHT + "==========================================================")
    print(Fore.GREEN + Style.BRIGHT + "   HEEM Agent (Live API + Gemini 3.6 Flash Advisor)       ")
    print(Fore.GREEN + Style.BRIGHT + "==========================================================\n")
    
    current_session = {"name": f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"}

    existing_sessions = get_session_suggestions()
    if existing_sessions:
        print(Fore.YELLOW + f"Доступные сессии ({len(existing_sessions)} шт.): " + Fore.WHITE + ", ".join(existing_sessions[:5]) + ("..." if len(existing_sessions) > 5 else ""))
        print(Fore.YELLOW + "Используйте '/s имя_сессии' или '/ls' для выбора сессии.\n")

    loop = asyncio.get_event_loop()

    def get_input_str(prompt_msg: str) -> str:
        try:
            return input(prompt_msg).strip()
        except (EOFError, KeyboardInterrupt):
            return "/exit"

    # Шаг 1: Выбор сессии или ввод первой задачи
    while True:
        prompt_input = await loop.run_in_executor(None, get_input_str, Fore.YELLOW + "/ Введите задачу > " + Style.RESET_ALL)

        if prompt_input == "/exit":
            return

        if not prompt_input:
            print(Fore.RED + "Ввод не может быть пустым.")
            continue

        if prompt_input == "/ls":
            sessions = get_session_suggestions()
            print(Fore.YELLOW + "\n--- СОХРАНЕННЫЕ СЕССИИ ---")
            print(Fore.YELLOW + ("\n".join([f"  • {s}" for s in sessions]) if sessions else "  (Список сессий пуст)"))
            print(Fore.YELLOW + "---------------------------\n")
            continue

        elif prompt_input.startswith("/s "):
            session_name = prompt_input[3:].strip()
            data, history_text = load_session_history(session_name)
            if data:
                current_session["name"] = session_name
                print(Fore.GREEN + f"\n[+] Загружена сессия: '{session_name}'")
                print(Fore.YELLOW + "--- ПОСЛЕДНЯЯ ИСТОРИЯ ---")
                print(Fore.WHITE + (history_text if history_text else "(История пуста)"))
                print(Fore.YELLOW + "-------------------------\n")
            else:
                current_session["name"] = session_name
                log_session_event(session_name, "session_created", f"Создана сессия {session_name}")
                print(Fore.GREEN + f"\n[+] Создана новая сессия: '{session_name}'\n")

            sub_task = await loop.run_in_executor(None, get_input_str, Fore.YELLOW + f"Введите задачу для '{session_name}' (или Enter чтобы продолжить) > " + Style.RESET_ALL)
            if sub_task:
                await send_turn_and_receive(current_session, sub_task)
            break

        elif prompt_input == "/new":
            current_session["name"] = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            print(Fore.GREEN + f"\n[+] Начата новая сессия: '{current_session['name']}'\n")
            continue

        else:
            # Выполняем первую задачу
            await send_turn_and_receive(current_session, prompt_input)
            break

    # Шаг 2: Цикл дополнительных сообщений
    while True:
        user_msg = await loop.run_in_executor(None, get_input_str, Fore.CYAN + "Доп. сообщение > " + Style.RESET_ALL)

        if user_msg == "/exit":
            print(Fore.YELLOW + "Завершение работы.")
            break

        if not user_msg:
            continue

        if user_msg == "/ls":
            sessions = get_session_suggestions()
            print(Fore.YELLOW + "\n--- СОХРАНЕННЫЕ СЕССИИ ---")
            print(Fore.YELLOW + ("\n".join([f"  • {s}" for s in sessions]) if sessions else "  (Список сессий пуст)"))
            print(Fore.YELLOW + "---------------------------\n")
            continue

        if user_msg.startswith("/s "):
            session_name = user_msg[3:].strip()
            data, history_text = load_session_history(session_name)
            if data:
                current_session["name"] = session_name
                print(Fore.GREEN + f"\n[+] Переключено на сессию: '{session_name}'\n")
            else:
                current_session["name"] = session_name
                log_session_event(session_name, "session_created", f"Создана сессия {session_name}")
                print(Fore.GREEN + f"\n[+] Создана новая сессия: '{session_name}'\n")
            continue

        # Отправляем сообщение, открываем WebSocket, получаем ответ и закрываем сокет
        await send_turn_and_receive(current_session, user_msg)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(Fore.YELLOW + "\nЗавершение работы HEEM агента.")