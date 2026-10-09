import os
import sys
import subprocess
import json
import time
import re
from datetime import datetime
from colorama import init, Fore, Style
from playwright.sync_api import sync_playwright

init(autoreset=True)

# ===== ЛОКАЛЬНЫЕ ФУНКЦИИ ИСПОЛНЕНИЯ НА ПК =====

def tool_exec_command(cmd: str, workdir: str = None) -> str:
    print(Fore.CYAN + f"\n[AI Executing Command]: {Style.BRIGHT}{cmd}")
    t0 = time.time()
    try:
        cwd = workdir if workdir and os.path.exists(workdir) else os.getcwd()
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd, timeout=120)
        output = (res.stdout + res.stderr).strip()
        elapsed = (time.time() - t0) * 1000
        
        lines = output.split("\n")
        print(Fore.YELLOW + f"[Exit Code]: {res.returncode} | [Execution Time]: {elapsed:.2f} ms | [CWD]: {cwd}")
        if len(lines) > 8:
            summary = "\n".join(lines[:4]) + f"\n... [{len(lines) - 6} lines omitted in CLI] ...\n" + "\n".join(lines[-2:])
            print(Fore.WHITE + summary)
        else:
            print(Fore.WHITE + (output if output else "(No output)"))
        return output if output else "(Command executed successfully with no output)"
    except Exception as e:
        err = f"Execution error: {str(e)}"
        print(Fore.RED + f"[Error]: {err}")
        return err

def tool_read_file(path: str, start_line: int = None, end_line: int = None) -> str:
    print(Fore.CYAN + f"\n[AI Reading File]: {path}")
    t0 = time.time()
    try:
        if not path:
            err = "Error: Path is empty."
            print(Fore.RED + f"[Error]: {err}")
            return err
        if not os.path.exists(path):
            err = f"Error: File '{path}' does not exist."
            print(Fore.RED + f"[Error]: {err}")
            return err
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        
        start = (start_line - 1) if start_line and start_line > 0 else 0
        end = end_line if end_line and end_line <= len(lines) else len(lines)
        selected_content = "".join(lines[start:end])
        elapsed = (time.time() - t0) * 1000
        
        print(Fore.GREEN + f"[File Read Success]: Read {end - start}/{len(lines)} lines ({len(selected_content)} chars) in {elapsed:.2f} ms")
        return selected_content
    except Exception as e:
        err = f"Error reading file: {str(e)}"
        print(Fore.RED + f"[Error]: {err}")
        return err

def tool_write_file(path: str, content: str) -> str:
    print(Fore.CYAN + f"\n[AI Writing File]: {path}")
    t0 = time.time()
    try:
        if not path:
            err = "Error writing file: Path parameter is empty."
            print(Fore.RED + f"[Error]: {err}")
            return err
            
        full_path = os.path.abspath(path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        elapsed = (time.time() - t0) * 1000
        msg = f"Successfully wrote {len(content)} chars to {full_path}"
        print(Fore.GREEN + f"[Write Success]: {msg} ({elapsed:.2f} ms)")
        return msg
    except Exception as e:
        err = f"Error writing file: {str(e)}"
        print(Fore.RED + f"[Error]: {err}")
        return err

def tool_apply_patch(path: str, patch: str) -> str:
    print(Fore.CYAN + f"\n[AI Applying Patch to File]: {path}")
    try:
        if not path:
            return "Error: Path parameter is empty."
        with open(path, "w", encoding="utf-8") as f:
            f.write(patch)
        msg = f"Patch applied to {path}"
        print(Fore.GREEN + f"[Success]: {msg}")
        return msg
    except Exception as e:
        return f"Error applying patch: {str(e)}"

def tool_list_directory(path: str = ".") -> str:
    print(Fore.CYAN + f"\n[AI Listing Directory]: {path}")
    try:
        target = path if path else "."
        items = os.listdir(target)
        result = "\n".join(items)
        print(Fore.YELLOW + f"[Items Found]: {len(items)} entries in '{target}'")
        return result
    except Exception as e:
        err = f"Error listing directory: {str(e)}"
        print(Fore.RED + f"[Error]: {err}")
        return err

def tool_search_codebase(query: str, path: str = ".") -> str:
    print(Fore.CYAN + f"\n[AI Search Codebase]: '{query}' in {path}")
    cmd = f"rg --line-number \"{query}\" {path}"
    return tool_exec_command(cmd)

def tool_view_image(path: str) -> str:
    print(Fore.CYAN + f"\n[AI Viewing Image]: {path}")
    if path and os.path.exists(path):
        size = os.path.getsize(path)
        print(Fore.GREEN + f"[Image Verified]: {path} | Size: {size} bytes ({size / 1024:.2f} KB)")
        return f"Image '{path}' exists on disk, size: {size} bytes."
    err = f"Image file '{path}' not found."
    print(Fore.RED + f"[Error]: {err}")
    return err

def tool_request_user_input(question: str) -> str:
    print(Fore.MAGENTA + f"\n[AI Question]: {question}")
    ans = input(Fore.GREEN + "Answer in CLI > ")
    return ans

def tool_run_tests(test_command: str = None) -> str:
    cmd = test_command if test_command else "pytest"
    print(Fore.CYAN + f"\n[AI Running Tests]: {cmd}")
    return tool_exec_command(cmd)

def tool_get_git_status() -> str:
    print(Fore.CYAN + "\n[AI Checking Git Status]")
    return tool_exec_command("git status")

# ===== УЛУЧШЕННЫЙ ПАРСЕР JSON-АРГУМЕНТОВ =====

def extract_json_args(text: str) -> dict:
    if not text:
        return {}
    
    # 1. Попробовать найти внешний JSON-объект от первой '{' до последней '}'
    first_brace = text.find('{')
    last_brace = text.rfind('}')
    
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidate = text[first_brace:last_brace + 1]
        try:
            return json.loads(candidate)
        except Exception:
            pass

    # 2. Подсчет баланса скобок для сложных структур
    brace_count = 0
    in_string = False
    escape = False
    start_idx = -1
    
    for idx, char in enumerate(text):
        if char == '"' and not escape:
            in_string = not in_string
        elif char == '\\' and in_string:
            escape = not escape
            continue
        elif not in_string:
            if char == '{':
                if brace_count == 0:
                    start_idx = idx
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0 and start_idx != -1:
                    block = text[start_idx:idx + 1]
                    try:
                        return json.loads(block)
                    except Exception:
                        pass
        escape = False

    # 3. Резервный поиск
    matches = re.findall(r'\{[\s\S]*?\}', text)
    for m in reversed(matches):
        try:
            res = json.loads(m)
            if isinstance(res, dict) and res:
                return res
        except Exception:
            continue
            
    return {}

# Маршрутизатор вызова инструмента (возвращает JSON-объект)
def execute_tool_call(name: str, args: dict) -> str:
    raw_res = ""
    if name == "exec_command":
        raw_res = tool_exec_command(args.get("cmd", ""), args.get("workdir"))
    elif name == "read_file":
        raw_res = tool_read_file(args.get("path", ""), args.get("start_line"), args.get("end_line"))
    elif name == "write_file":
        raw_res = tool_write_file(args.get("path", ""), args.get("content", ""))
    elif name == "apply_patch":
        raw_res = tool_apply_patch(args.get("path", ""), args.get("patch", ""))
    elif name == "list_directory":
        raw_res = tool_list_directory(args.get("path", "."))
    elif name == "search_codebase":
        raw_res = tool_search_codebase(args.get("query", ""), args.get("path", "."))
    elif name == "view_image":
        raw_res = tool_view_image(args.get("path", ""))
    elif name == "request_user_input":
        raw_res = tool_request_user_input(args.get("question", ""))
    elif name == "run_tests":
        raw_res = tool_run_tests(args.get("test_command"))
    elif name == "get_git_status":
        raw_res = tool_get_git_status()
    else:
        raw_res = f"Unknown tool call: {name}"

    # Gemini API требует JSON-объект {"result": ...}!
    return json.dumps({"result": raw_res}, ensure_ascii=False)

# ===== ОБРАБОТКА КАРТОЧЕК FUNCTION CALLING B AI STUDIO =====

VALID_TOOLS = {
    "exec_command", "read_file", "write_file", "apply_patch", 
    "list_directory", "search_codebase", "view_image", 
    "request_user_input", "run_tests", "get_git_status"
}

def check_and_process_function_calls(page):
    inputs = page.locator("input[placeholder='Enter function response'], input[aria-label='Enter a function response']").all()
    
    for input_elem in inputs:
        try:
            if not input_elem.is_visible():
                continue
            
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
            
            input_elem.evaluate("el => el.setAttribute('data-processed', 'true')")
            
            args = extract_json_args(text_content)
            now_str = datetime.now().strftime("%H:%M:%S")
            
            print(Fore.BLUE + Style.BRIGHT + f"\n[{now_str}] [AI Studio Function Call Found]: {fn_name}")
            if args:
                print(Fore.CYAN + f"   Parsed Arguments: {json.dumps(args, ensure_ascii=False)[:180]}...")
            else:
                print(Fore.YELLOW + f"   [Warning]: Could not parse arguments dict from container text!")

            # Выполняем команду локально
            json_result = execute_tool_call(fn_name, args)
            
            # Вставляем JSON-ответ в инпут
            input_elem.focus()
            input_elem.fill(json_result)
            time.sleep(0.3)
            
            # Отправляем через Enter
            input_elem.press("Enter")
            print(Fore.GREEN + Style.BRIGHT + f"[{now_str}] [Bridge]: Submitted JSON result via Enter for '{fn_name}'!\n" + "-"*60)
            
            time.sleep(3)
            break

        except Exception as e:
            print(Fore.RED + f"[Error processing card]: {e}")

# ===== ОСНОВНОЙ ЦИКЛ СВЯЗИ С CHROME CDP =====

def main():
    print(Fore.GREEN + Style.BRIGHT + "==========================================================")
    print(Fore.GREEN + Style.BRIGHT + "   Codex-Gemini Chrome Bridge Agent Started (v2.0 Fixed)   ")
    print(Fore.GREEN + Style.BRIGHT + "   Connecting to open Chrome via CDP (port 9222)...        ")
    print(Fore.GREEN + Style.BRIGHT + "==========================================================\n")

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            context = browser.contexts[0]
            
            ai_studio_page = None
            for page in context.pages:
                if "aistudio.google.com" in page.url:
                    ai_studio_page = page
                    break
            
            if not ai_studio_page:
                print(Fore.RED + "Error: Could not find open 'aistudio.google.com' tab in Chrome!")
                print(Fore.YELLOW + "Please open https://aistudio.google.com in Chrome first.")
                sys.exit(1)

            print(Fore.GREEN + f"[Connected]: Found AI Studio tab -> {ai_studio_page.title()}")
            print(Fore.YELLOW + "Waiting for incoming Function Calls or Messages from Gemini in Chrome...\n")

            while True:
                time.sleep(1.5)
                check_and_process_function_calls(ai_studio_page)

        except KeyboardInterrupt:
            print(Fore.YELLOW + "\nExiting Chrome Bridge...")
        except Exception as e:
            print(Fore.RED + f"\n[CDP Connection Error]: {e}")
            print(Fore.YELLOW + "Ensure Chrome is launched with: chrome.exe --remote-debugging-port=9222")

if __name__ == "__main__":
    main()