import os
import sys
import subprocess
import json
import time
import re
import urllib.request
import urllib.error
import shutil
import tempfile
import threading
import uuid
from datetime import datetime
from colorama import init, Fore, Style
from playwright.sync_api import sync_playwright

init(autoreset=True)

SESSION_FILE = ".agent_session.json"
CDP_PORT = 9222
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"

# ===== NON-BLOCKING PERSISTENT CMD ENGINE =====

class CMDSession:
    """
    Executes commands via Windows CMD with strict CP65001 UTF-8 forced encoding 
    and multi-encoding fallback (UTF-8 / CP866 / CP1251) for pristine Cyrillic output.
    """
    def __init__(self):
        self.cwd = os.getcwd()
        self.lock = threading.Lock()

    def _decode_bytes(self, data: bytes) -> str:
        if not data:
            return ""
        # Try UTF-8 first, then Russian Windows encodings
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
            # Force CP65001 (UTF-8) code page in Windows CMD before running command
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
                
                # Pass '\n' to stdin to unlock interactive commands (e.g. `date`)
                stdout_bytes, _ = proc.communicate(input=b"\n", timeout=timeout)
                elapsed = (time.time() - t0) * 1000

            except subprocess.TimeoutExpired:
                proc.kill()
                stdout_bytes, _ = proc.communicate()
                elapsed = (time.time() - t0) * 1000
                print(Fore.RED + f"[Timeout Error]: Command killed after {timeout}s")
                raw_text = self._decode_bytes(stdout_bytes)
                return raw_text + f"\n[ERROR: Process timed out after {timeout} seconds and was terminated.]"
            except Exception as e:
                err = f"[CMD System Error]: {e}"
                print(Fore.RED + err)
                return err

            raw_output = self._decode_bytes(stdout_bytes).strip()
            
            # Clean residual invalid Unicode/replacement chars that break Gemini API
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
                print(Fore.WHITE + "--- RAW OUTPUT START ---")
                print(Fore.WHITE + (main_output[:1200] + ("\n... [truncated in CLI]" if len(main_output) > 1200 else "")))
                print(Fore.WHITE + "--- RAW OUTPUT END ---")
            else:
                print(Fore.YELLOW + "(No console output produced)")

            return main_output if main_output else f"(Command finished with Exit Code {proc.returncode} and no console output)"

cmd_engine = CMDSession()

# ===== SAFE CSS-BASED DOM OPTIMIZER =====
# Instead of deleting elements from Angular DOM (which causes 403 permission denied),
# we collapse/hide heavy code pre tags and old thoughts via CSS rules.

OPTIMIZER_SCRIPT = """
(() => {
    if (window.__AIS_OPTIMIZER_INJECTED__) return;
    window.__AIS_OPTIMIZER_INJECTED__ = true;

    if (!document.getElementById('ais-native-optimizer-theme')) {
        const style = document.createElement('style');
        style.id = 'ais-native-optimizer-theme';
        style.textContent = `
            .ais-processed-chunk ms-code-block pre,
            .ais-processed-chunk .mat-expansion-panel-body {
                display: none !important;
            }
            .ais-processed-chunk .title-text::after {
                content: " (Completed)";
                font-size: 11px;
                opacity: 0.7;
            }
        `;
        document.head.appendChild(style);
    }

    window.nukeHeavyDOM = function() {
        try {
            document.querySelectorAll('input[data-processed="true"]').forEach(input => {
                let chunk = input.closest('ms-function-call-chunk') || input.closest('ms-code-block');
                if (chunk) {
                    chunk.classList.add('ais-processed-chunk');
                }
            });
        } catch (e) {
            console.error('[AI Studio Optimizer Error]:', e);
        }
    };

    setInterval(window.nukeHeavyDOM, 2500);
})();
"""

# ===== FILE VALIDATION & FORMAT HANDLING =====
DIRECTLY_SUPPORTED_EXTS = {
    ".txt", ".md", ".pdf", ".py", ".cs", ".js", ".ts", ".jsx", ".tsx",
    ".json", ".html", ".css", ".cpp", ".c", ".h", ".hpp", ".java", ".go",
    ".rs", ".rb", ".php", ".sh", ".bat", ".ps1", ".sql", ".xml",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp",
    ".mp3", ".wav", ".ogg", ".mp4", ".webm"
}

def is_binary_file(filepath: str) -> bool:
    try:
        with open(filepath, "rb") as f:
            chunk = f.read(8192)
            return b"\x00" in chunk
    except Exception:
        return True

def prepare_file_for_upload(filepath: str) -> tuple[str, bool]:
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    _, ext = os.path.splitext(filepath)
    ext_lower = ext.lower()

    if ext_lower in DIRECTLY_SUPPORTED_EXTS:
        return filepath, False

    if not is_binary_file(filepath):
        temp_dir = tempfile.gettempdir()
        filename = os.path.basename(filepath)
        temp_path = os.path.join(temp_dir, f"{filename}.txt")
        shutil.copyfile(filepath, temp_path)
        return temp_path, True

    return filepath, False

# ===== SESSION TRACKING =====

def load_session() -> dict:
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"processed_calls": [], "attached_files": []}

def save_session(data: dict):
    try:
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(Fore.RED + f"[Session Storage Error]: {e}")

def mark_call_processed(call_signature: str):
    sess = load_session()
    if call_signature not in sess["processed_calls"]:
        sess["processed_calls"].append(call_signature)
        save_session(sess)

def is_call_processed(call_signature: str) -> bool:
    sess = load_session()
    return call_signature in sess["processed_calls"]

# ===== LOCAL ENGINE TOOLS =====

def tool_read_file(path: str, start_line: int = None, end_line: int = None) -> str:
    print(Fore.CYAN + f"\n[Tool Read File]: {path}")
    t0 = time.time()
    try:
        if not path or not os.path.exists(path):
            return f"Error: File '{path}' does not exist."
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        
        start = (start_line - 1) if start_line and start_line > 0 else 0
        end = end_line if end_line and end_line <= len(lines) else len(lines)
        selected_content = "".join(lines[start:end])
        elapsed = (time.time() - t0) * 1000
        
        print(Fore.GREEN + f"[Success]: Read lines {start+1}-{end} of {len(lines)} in {elapsed:.2f}ms")
        return selected_content
    except Exception as e:
        return f"Error reading file: {str(e)}"

def tool_write_file(path: str, content: str) -> str:
    print(Fore.CYAN + f"\n[Tool Write File]: {path}")
    try:
        if not path:
            return "Error: Path is empty."
        full_path = os.path.abspath(path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        msg = f"Successfully wrote {len(content)} characters to {full_path}"
        print(Fore.GREEN + f"[Success]: {msg}")
        return msg
    except Exception as e:
        return f"Error writing file: {str(e)}"

def tool_apply_patch(path: str, patch: str) -> str:
    print(Fore.CYAN + f"\n[Tool Apply Patch]: {path}")
    try:
        if not path:
            return "Error: Path is empty."
        with open(path, "w", encoding="utf-8") as f:
            f.write(patch)
        msg = f"Patch successfully applied to {path}"
        print(Fore.GREEN + f"[Success]: {msg}")
        return msg
    except Exception as e:
        return f"Error applying patch: {str(e)}"

def tool_list_directory(path: str = ".") -> str:
    print(Fore.CYAN + f"\n[Tool List Dir]: {path}")
    try:
        target = path if path else "."
        items = os.listdir(target)
        print(Fore.YELLOW + f"[Directory Items]: {len(items)} entries found")
        return "\n".join(items)
    except Exception as e:
        return f"Error listing directory: {str(e)}"

def tool_search_codebase(query: str, path: str = ".") -> str:
    cmd = f"rg --line-number \"{query}\" {path}"
    return cmd_engine.execute(cmd)

def tool_request_user_input(question: str) -> str:
    print(Fore.MAGENTA + f"\n[User Clarification Required]: {question}")
    return input(Fore.GREEN + "Answer in CLI > ")

def tool_run_tests(test_command: str = None) -> str:
    cmd = test_command if test_command else "dotnet test"
    return cmd_engine.execute(cmd)

def tool_get_git_status() -> str:
    return cmd_engine.execute("git status")

def execute_standard_tool(name: str, args: dict) -> str:
    if name == "exec_command":
        return cmd_engine.execute(args.get("cmd", ""), args.get("workdir"))
    elif name == "read_file":
        return tool_read_file(args.get("path", ""), args.get("start_line"), args.get("end_line"))
    elif name == "write_file":
        return tool_write_file(args.get("path", ""), args.get("content", ""))
    elif name == "apply_patch":
        return tool_apply_patch(args.get("path", ""), args.get("patch", ""))
    elif name == "list_directory":
        return tool_list_directory(args.get("path", "."))
    elif name == "search_codebase":
        return tool_search_codebase(args.get("query", ""), args.get("path", "."))
    elif name == "request_user_input":
        return tool_request_user_input(args.get("question", ""))
    elif name == "run_tests":
        return tool_run_tests(args.get("test_command"))
    elif name == "get_git_status":
        return tool_get_git_status()
    return f"Unknown tool call: {name}"

# ===== ATTACHMENT & PROMPT BOX UPLOADER =====

import base64
import mimetypes

def attach_and_send_via_main_prompt(page, file_paths: list[str], custom_note: str = "") -> bool:
    try:
        files_data = []
        file_metas = []

        for fp in file_paths:
            if not os.path.exists(fp):
                print(Fore.RED + f"[Attachment Error]: File not found: {fp}")
                continue
            
            mime_type, _ = mimetypes.guess_type(fp)
            if not mime_type:
                mime_type = "application/octet-stream"
            
            with open(fp, "rb") as f:
                b64_content = base64.b64encode(f.read()).decode("utf-8")

            filename = os.path.basename(fp)
            size_kb = os.path.getsize(fp) / 1024.0
            file_metas.append(f"• Name: {filename} | Size: {size_kb:.1f} KB | Path: {fp}")

            files_data.append({
                "name": filename,
                "type": mime_type,
                "base64": b64_content
            })

        if not files_data:
            return False

        print(Fore.CYAN + f"[Emulating Fast Single Clipboard Paste for {len(files_data)} File(s)...]")

        page.evaluate("""async (data) => {
            const dt = new DataTransfer();
            for (const item of data.files) {
                const res = await fetch(`data:${item.type};base64,${item.base64}`);
                const blob = await res.blob();
                const file = new File([blob], item.name, { type: item.type });
                dt.items.add(file);
            }

            const target = document.querySelector("textarea[placeholder*='prompt']") || document.body;
            
            const pasteEvent = new ClipboardEvent('paste', {
                bubbles: true,
                cancelable: true,
                clipboardData: dt
            });
            target.dispatchEvent(pasteEvent);
        }""", {"files": files_data})

        time.sleep(0.5)

        meta_text = "Attached requested workspace file(s):\n" + "\n".join(file_metas)
        if custom_note:
            meta_text += f"\nNote: {custom_note}"

        textarea = page.locator("textarea[placeholder*='prompt']").first
        if textarea.count() and textarea.is_visible():
            textarea.focus()
            textarea.fill(meta_text)
            textarea.evaluate("""el => {
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }""")
            time.sleep(0.5)

            run_btn = page.locator("ms-run-button button[type='submit']").first
            if run_btn.count() and run_btn.is_enabled():
                run_btn.click(force=True)
                print(Fore.GREEN + Style.BRIGHT + "[Success]: Attached file & Clicked Run!")
            else:
                textarea.press("Control+Enter")
                print(Fore.GREEN + Style.BRIGHT + "[Success]: Submitted via Ctrl+Enter!")

        return True
    except Exception as e:
        print(Fore.RED + f"[Attachment Pipeline Exception]: {e}")
        return False
    
# ===== FAST CDP TARGET DISCOVERY =====

def get_ai_studio_target_ws() -> str:
    try:
        req = urllib.request.urlopen(f"{CDP_URL}/json", timeout=2)
        targets = json.loads(req.read().decode("utf-8"))
        for target in targets:
            if target.get("type") == "page" and "aistudio.google.com" in target.get("url", ""):
                return target.get("webSocketDebuggerUrl")
    except Exception:
        pass
    return None

# ===== GUARANTEED AI STUDIO FORM SUBMISSION =====

def send_function_response(page, input_elem, json_response: str) -> bool:
    """
    Sets value directly via JS and calls form.requestSubmit(), avoiding 
    accidental clicks on header buttons (e.g. Download) or Enter keys.
    """
    try:
        # 1. Снимаем disabled и фокусируем инпут
        input_elem.evaluate("""el => {
            el.removeAttribute('disabled');
            el.scrollIntoView({ block: 'center', inline: 'center' });
        }""")
        time.sleep(0.2)

        # 2. Записываем значение и обновляем Angular
        input_elem.evaluate("""(input, responseVal) => {
            input.value = responseVal;
            input.dispatchEvent(new Event('input', { bubbles: true, cancelable: true }));
            input.dispatchEvent(new Event('change', { bubbles: true, cancelable: true }));
            input.dispatchEvent(new Event('blur', { bubbles: true }));
        }""", json_response)
        
        time.sleep(0.3)

        # 3. Чистый сабмит формы напрямую без поиска кнопок и без Enter
        input_elem.evaluate("""el => {
            const form = el.closest('form');
            if (form) {
                if (form.requestSubmit) {
                    form.requestSubmit();
                } else {
                    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
                }
            }
        }""")
        print(Fore.GREEN + "[Success]: Submitted cleanly via form.requestSubmit()!")
        return True

    except Exception as e:
        print(Fore.RED + f"[Submission Error]: {e}")
        return False

# ===== MAIN PROCESSOR =====

VALID_TOOLS = {
    "exec_command", "read_file", "write_file", "apply_patch", 
    "list_directory", "search_codebase", "view_image", "attach_files",
    "request_user_input", "run_tests", "get_git_status"
}

def extract_json_args(text: str) -> dict:
    if not text:
        return {}
    
    first_brace = text.find('{')
    last_brace = text.rfind('}')
    
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidate = text[first_brace:last_brace + 1]
        try:
            return json.loads(candidate)
        except Exception:
            pass

    matches = re.findall(r'\{[\s\S]*?\}', text)
    for m in reversed(matches):
        try:
            res = json.loads(m)
            if isinstance(res, dict) and res:
                return res
        except Exception:
            continue
    return {}

def wait_for_model_idle(page, timeout=15):
    """Ждет, пока модель закончит генерацию и интерфейс станет свободным."""
    time.sleep(0.6)  # Даем времени AI Studio переключить статус на генерацию
    t0 = time.time()
    while time.time() - t0 < timeout:
        is_generating = page.evaluate("""() => {
            const stopBtn = document.querySelector("ms-run-button button .stoppable-spinner, ms-run-button button[aria-label*='Stop']");
            return !!stopBtn;
        }""")
        if not is_generating:
            break
        time.sleep(0.3)
    time.sleep(1.0)

def process_function_calls(page):
    inputs = page.locator("input[placeholder='Enter function response'], input[aria-label='Enter a function response']").all()
    
    for input_elem in inputs:
        try:
            # Пропускаем, если блок уже ранее был закрыт
            if input_elem.evaluate("el => el.getAttribute('data-processed') === 'true'"):
                continue

            container = input_elem.locator("xpath=ancestor::ms-function-call-chunk[1]")
            if not container.count():
                container = input_elem.locator("xpath=ancestor::ms-code-block[1]")
            
            text_content = container.inner_text() if container.count() else ""
            
            fn_name = None
            for tool in VALID_TOOLS:
                if re.search(rf'\b{tool}\b', text_content):
                    fn_name = tool
                    break
            
            if not fn_name:
                continue

            args = extract_json_args(text_content)
            call_id = f"{fn_name}_{hash(json.dumps(args, sort_keys=True))}"
            
            # Если запрос уже был обработан в прошлых циклах — помечаем и пропускаем
            if is_call_processed(call_id):
                input_elem.evaluate("el => el.setAttribute('data-processed', 'true')")
                continue

            now_str = datetime.now().strftime("%H:%M:%S")
            print(Fore.BLUE + Style.BRIGHT + f"\n[{now_str}] [Function Call Detected]: {fn_name}")
            if args:
                print(Fore.CYAN + f"   Args: {json.dumps(args, ensure_ascii=False)[:180]}")

            # =========================================================
            # ШАГ 1: ВЫПОЛНЕНИЕ ИНСТРУМЕНТА И ПОДГОТОВКА JSON (ИНПУТ ОТКРЫТ)
            # =========================================================
            if fn_name in ("view_image", "attach_files"):
                paths = []
                if "path" in args:
                    paths.append(args["path"])
                if "paths" in args and isinstance(args["paths"], list):
                    paths.extend(args["paths"])
                
                note = args.get("note", "")
                files_payload = []

                for fp in paths:
                    if not os.path.exists(fp):
                        files_payload.append({"path": fp, "error": "File not found"})
                        continue
                    
                    mime_type, _ = mimetypes.guess_type(fp)
                    if not mime_type:
                        mime_type = "application/octet-stream"
                    
                    if is_binary_file(fp) or mime_type.startswith("image/"):
                        with open(fp, "rb") as f:
                            b64_content = base64.b64encode(f.read()).decode("utf-8")
                        files_payload.append({
                            "path": fp,
                            "filename": os.path.basename(fp),
                            "mime_type": mime_type,
                            "data_uri": f"data:{mime_type};base64,{b64_content}"
                        })
                    else:
                        try:
                            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                                content = f.read(50000)
                            files_payload.append({
                                "path": fp,
                                "filename": os.path.basename(fp),
                                "content": content
                            })
                        except Exception as e:
                            files_payload.append({"path": fp, "error": str(e)})

                json_result = json.dumps({
                    "status": "success",
                    "note": note,
                    "attached_files": files_payload
                }, ensure_ascii=False)
            else:
                raw_res = execute_standard_tool(fn_name, args)
                if isinstance(raw_res, str):
                    raw_res = raw_res.replace('\r\n', '\n').replace('\r', '\n')

                json_result = json.dumps({"result": raw_res}, ensure_ascii=False)

            # =========================================================
            # ШАГ 2: ВВОД ОТВЕТА В ПОЛЕ И НАЖАТИЕ SEND (ОТПРАВКА)
            # =========================================================
            response_sent = send_function_response(page, input_elem, json_result)

            # =========================================================
            # ШАГ 3: ТОЛЬКО ПОСЛЕ ОТПРАВКИ ЗАКРЫВАЕМ БЛОК И ЗАПИСЫВАЕМ СЕССИЮ
            # =========================================================
            if response_sent:
                mark_call_processed(call_id)
                input_elem.evaluate("el => el.setAttribute('data-processed', 'true')")
                print(Fore.GREEN + f"[{now_str}] [Success: Input Filled -> Form Submitted -> Chunk Closed cleanly!]")

            time.sleep(2.0)
            break

        except Exception as e:
            print(Fore.RED + f"[Process Error]: {e}")
            
    # ===== ENTRY POINT =====

def main():
    print(Fore.GREEN + Style.BRIGHT + "==========================================================")
    print(Fore.GREEN + Style.BRIGHT + "   Codex-Gemini Chrome Bridge (AI Studio Optimized)       ")
    print(Fore.GREEN + Style.BRIGHT + f"   Targeting Chrome Debug Port {CDP_PORT}...                 ")
    print(Fore.GREEN + Style.BRIGHT + "==========================================================\n")

    ws_url = get_ai_studio_target_ws()
    if not ws_url:
        print(Fore.YELLOW + f"[Search]: Scanning Chrome instances on port {CDP_PORT}...")

    with sync_playwright() as p:
        try:
            t0 = time.time()
            browser = p.chromium.connect_over_cdp(CDP_URL)
            context = browser.contexts[0]
            
            ai_studio_page = None
            for page in context.pages:
                if "aistudio.google.com" in page.url:
                    ai_studio_page = page
                    break
            
            if not ai_studio_page:
                print(Fore.RED + "[Error]: Target 'aistudio.google.com' tab not found in Chrome!")
                sys.exit(1)

            elapsed = (time.time() - t0) * 1000
            print(Fore.GREEN + f"[Connected in {elapsed:.1f}ms]: {ai_studio_page.title()}")
            
            print(Fore.MAGENTA + "[Injecting Safe CSS DOM Optimizer...]")
            ai_studio_page.evaluate(OPTIMIZER_SCRIPT)
            
            # ФИКС: Помечаем всю имеющуюся историю как обработанную, чтобы не триггериться на старые вызовы
            ai_studio_page.evaluate("""() => {
                document.querySelectorAll("input[placeholder='Enter function response'], input[aria-label='Enter a function response']").forEach(el => {
                    el.setAttribute('data-processed', 'true');
                });
            }""")
            
            print(Fore.MAGENTA + "[Bridge Ready]: Listening for NEW AI Studio Function Calls...\n")

            while True:
                time.sleep(1.2)
                process_function_calls(ai_studio_page)

        except KeyboardInterrupt:
            print(Fore.YELLOW + "\n[Bridge Terminated by User]")
        except Exception as e:
            print(Fore.RED + f"\n[CDP Connection Error]: {e}")
            
if __name__ == "__main__":
    main()