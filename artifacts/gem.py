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

# ===== СКРИПТ ОПТИМИЗАЦИИ (ВНЕДРЯЕТСЯ В CHROME) =====
# Этот JS-код уничтожает лаги, удаляя тяжелые DOM-элементы после их использования
OPTIMIZER_SCRIPT = """
(() => {
    // Добавляем стили для отключения тяжелого рендеринга (используем textContent вместо innerHTML)
    if (!document.getElementById('ai-studio-optimizer-css')) {
        const style = document.createElement('style');
        style.id = 'ai-studio-optimizer-css';
        style.textContent = `
            /* Отключаем тени, блюр и анимации для старых сообщений */
            .optimized-turn * {
                box-shadow: none !important;
                backdrop-filter: none !important;
                animation: none !important;
                transition: none !important;
            }
            /* Стили для наших минималистичных плашек */
            .mini-badge {
                font-family: 'DM Mono', monospace;
                font-size: 12px;
                padding: 6px 12px;
                border-radius: 6px;
                background-color: rgba(0, 255, 0, 0.1);
                color: #0f9d58;
                border: 1px solid rgba(15, 157, 88, 0.3);
                margin: 4px 0;
                display: inline-block;
                font-weight: bold;
            }
            .mini-thought {
                font-size: 11px;
                color: gray;
                font-style: italic;
                padding: 4px;
            }
        `;
        document.head.appendChild(style);
    }

    function nukeHeavyDOM() {
        try {
            // 1. Оптимизируем отработанные вызовы функций
            document.querySelectorAll('input[data-processed="true"]').forEach(input => {
                let chunk = input.closest('ms-function-call-chunk');
                if (chunk && !chunk.hasAttribute('data-minified')) {
                    // Пытаемся достать имя функции для красоты
                    let titleElem = chunk.querySelector('.title-text');
                    let fnName = titleElem ? titleElem.innerText : 'Unknown_Function';
                    
                    // Создаем легкий элемент
                    let mini = document.createElement('div');
                    mini.className = 'mini-badge';
                    // Используем textContent для безопасности (обходим TrustedHTML)
                    mini.textContent = `⚡ Функция [${fnName}] успешно выполнена (UI оптимизирован)`;
                    
                    // ПОЛНОСТЬЮ очищаем тяжелый DOM (безопасный аналог innerHTML = '')
                    chunk.replaceChildren();
                    chunk.appendChild(mini);
                    chunk.setAttribute('data-minified', 'true');
                }
            });

            // 2. Схлопываем старые "Мысли" (Thoughts)
            let turns = document.querySelectorAll('ms-chat-turn');
            turns.forEach((turn, index) => {
                // Если это не последний ход в чате (т.е. старый)
                if (index < turns.length - 1) {
                    turn.classList.add('optimized-turn'); // Отрубаем CSS
                    
                    let thoughts = turn.querySelectorAll('ms-thought-chunk');
                    thoughts.forEach(thought => {
                        if (!thought.hasAttribute('data-minified')) {
                            let mini = document.createElement('div');
                            mini.className = 'mini-thought';
                            mini.textContent = '🧠 [Рассуждения ИИ скрыты для экономии ОЗУ]';
                            
                            // Безопасная очистка
                            thought.replaceChildren();
                            thought.appendChild(mini);
                            thought.setAttribute('data-minified', 'true');
                        }
                    });
                }
            });
        } catch (e) { console.error("Optimizer error:", e); }
    }

    // Запускаем очистку каждые 2 секунды
    setInterval(nukeHeavyDOM, 2000);
    console.log("🚀 Codex-Gemini Optimizer Injected (TrustedHTML Bypass)!");
})();
"""

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
            return "Error: Path is empty."
        if not os.path.exists(path):
            return f"Error: File '{path}' does not exist."
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        
        start = (start_line - 1) if start_line and start_line > 0 else 0
        end = end_line if end_line and end_line <= len(lines) else len(lines)
        selected_content = "".join(lines[start:end])
        elapsed = (time.time() - t0) * 1000
        
        print(Fore.GREEN + f"[File Read Success]: Read {end - start}/{len(lines)} lines in {elapsed:.2f} ms")
        return selected_content
    except Exception as e:
        return f"Error reading file: {str(e)}"

def tool_write_file(path: str, content: str) -> str:
    print(Fore.CYAN + f"\n[AI Writing File]: {path}")
    try:
        if not path:
            return "Error writing file: Path parameter is empty."
        full_path = os.path.abspath(path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        msg = f"Successfully wrote {len(content)} chars to {full_path}"
        print(Fore.GREEN + f"[Success]: {msg}")
        return msg
    except Exception as e:
        return f"Error writing file: {str(e)}"

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
        print(Fore.YELLOW + f"[Items Found]: {len(items)} entries in '{target}'")
        return "\n".join(items)
    except Exception as e:
        return f"Error listing directory: {str(e)}"

def tool_search_codebase(query: str, path: str = ".") -> str:
    print(Fore.CYAN + f"\n[AI Search Codebase]: '{query}' in {path}")
    cmd = f"rg --line-number \"{query}\" {path}"
    return tool_exec_command(cmd)

def tool_view_image(path: str) -> str:
    print(Fore.CYAN + f"\n[AI Viewing Image]: {path}")
    if path and os.path.exists(path):
        size = os.path.getsize(path)
        return f"Image '{path}' exists on disk, size: {size} bytes."
    return f"Image file '{path}' not found."

def tool_request_user_input(question: str) -> str:
    print(Fore.MAGENTA + f"\n[AI Question]: {question}")
    return input(Fore.GREEN + "Answer in CLI > ")

def tool_run_tests(test_command: str = None) -> str:
    cmd = test_command if test_command else "pytest"
    print(Fore.CYAN + f"\n[AI Running Tests]: {cmd}")
    return tool_exec_command(cmd)

def tool_get_git_status() -> str:
    print(Fore.CYAN + "\n[AI Checking Git Status]")
    return tool_exec_command("git status")

# ===== ПАРСЕР И МАРШРУТИЗАТОР =====

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

    return json.dumps({"result": raw_res}, ensure_ascii=False)

# ===== ОБРАБОТКА В AI STUDIO =====

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
            
            # Помечаем элемент, чтобы JS-оптимизатор смог его удалить
            input_elem.evaluate("el => el.setAttribute('data-processed', 'true')")
            
            args = extract_json_args(text_content)
            now_str = datetime.now().strftime("%H:%M:%S")
            
            print(Fore.BLUE + Style.BRIGHT + f"\n[{now_str}] [AI Studio Function Call]: {fn_name}")
            if args:
                print(Fore.CYAN + f"   Parsed Arguments: {json.dumps(args, ensure_ascii=False)[:180]}...")

            json_result = execute_tool_call(fn_name, args)
            
            input_elem.focus()
            input_elem.fill(json_result)
            time.sleep(0.3)
            
            input_elem.press("Enter")
            print(Fore.GREEN + Style.BRIGHT + f"[{now_str}] [Bridge]: Result sent to browser!\n" + "-"*60)
            
            # Принудительно вызываем функцию очистки мусора сразу после отправки
            page.evaluate("if(typeof nukeHeavyDOM !== 'undefined') nukeHeavyDOM();")
            
            time.sleep(3)
            break

        except Exception as e:
            pass # Игнорируем мелкие ошибки DOM, чтобы скрипт не падал

# ===== ПОДКЛЮЧЕНИЕ =====

def main():
    print(Fore.GREEN + Style.BRIGHT + "==========================================================")
    print(Fore.GREEN + Style.BRIGHT + "   Codex-Gemini Chrome Bridge (DOM Optimizer Edition)     ")
    print(Fore.GREEN + Style.BRIGHT + "   Connecting to Chrome (port 9222)...                    ")
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
                print(Fore.RED + "Error: Could not find 'aistudio.google.com' tab!")
                sys.exit(1)

            print(Fore.GREEN + f"[Connected]: {ai_studio_page.title()}")
            
            # Внедряем наш скрипт-антилаг в страницу!
            print(Fore.MAGENTA + "[Injecting DOM Optimizer Script into browser...]")
            ai_studio_page.evaluate(OPTIMIZER_SCRIPT)
            print(Fore.MAGENTA + "[Optimizer Active]: UI will be simplified automatically.")

            while True:
                time.sleep(1.5)
                check_and_process_function_calls(ai_studio_page)

        except KeyboardInterrupt:
            print(Fore.YELLOW + "\nExiting Chrome Bridge...")
        except Exception as e:
            print(Fore.RED + f"\n[CDP Error]: {e}")
            print(Fore.YELLOW + "Did you launch Chrome with: --remote-debugging-port=9222 ?")

if __name__ == "__main__":
    main()