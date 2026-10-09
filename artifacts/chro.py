import re
import os
import sys

def decompile():
    input_file = "hzzz.js"
    output_file = "decompiled.js"

    if not os.path.exists(input_file):
        print(f"Ошибка: {input_file} не найден.")
        sys.exit(1)

    with open(input_file, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Извлечение H и алфавита
    h_match = re.search(r'var H="([^"]+)";', content)
    alpha_match = re.search(r'A\(H,\s*"([^"]+)",\s*43\)', content)
    if not h_match or not alpha_match:
        print("Ошибка: не удалось извлечь H или алфавит из hzzz.js")
        sys.exit(1)

    H, alphabet = h_match.group(1), alpha_match.group(1)

    # Распаковка базового массива байткода
    def decode_A(r, v, f):
        l, a, p, x = len(v), len(v) - f, [], 0
        n = {char: idx for idx, char in enumerate(v)}
        while x < len(r):
            h, t_val = 0, 1
            while True:
                M = n.get(r[x], 0)
                x += 1
                if M < f:
                    h += t_val * M
                    h_32 = int(h) & 0xFFFFFFFF
                    if h_32 & 0x80000000:
                        h_32 -= 0x100000000
                    p.append(h_32)
                    break
                h += t_val * ((M % f) + f)
                t_val *= a
        return p

    t = decode_A(H, alphabet, 43)

    # 2. Извлечение таблицы строк
    f_len = len(t)
    m = t[f_len - 1] ^ (f_len + 4)
    k_len = t[m] + 2
    K = t[m : m + k_len]
    t = t[:m] + t[m + k_len:]

    M_count = K[1]
    P_K = "".join(chr((S & 0xFFFFFFC0) | ((S * 41) & 63)) for S in K[2 : 2 + M_count])

    # Чтение операндов
    def read_G(t, pc):
        a = t[pc[0]]
        pc[0] += 1
        if a & 1:
            return a >> 1
        if a == 2:
            p, x = t[pc[0]], t[pc[0] + 1]
            pc[0] += 2
            sign = -1 if (p & 0x80000000) else 1
            exp = (p & 0x7FF00000) >> 20
            x_val = x + (1 << 32) if x < 0 else x
            mant = (p & 0x0FFFFF) * (1 << 32) + x_val
            if exp == 2047:
                return float('nan') if mant else float('inf') * sign
            exp_val = 1 if exp == 0 else exp
            mant_val = mant if exp == 0 else mant + (1 << 52)
            return sign * mant_val * (2 ** (exp_val - 1075))
        if a == 46:
            length, offset = t[pc[0]], t[pc[0] + 1]
            pc[0] += 2
            return P_K[offset : offset + length]
        if a == 28: return None
        if a == 20: return True
        if a == 34: return False
        if a != 48: return f"r[{a >> 5}]"
        return None

    def read_j(t, pc):
        reg = f"r[{t[pc[0]] >> 5}]"
        pc[0] += 1
        return reg

    def read_F(t, pc):
        reg = f"r[{t[pc[0]] >> 5}]"
        pc[0] += 1
        return reg

    OPCODES = {
        0: ("EQ", ['G', 'j'], 'F'), 1: ("NEQ", ['G', 'j'], 'F'), 2: ("EXIT", [], None),
        3: ("STRICT_EQ", ['j', 'j'], 'F'), 4: ("MUL", ['j', 'G'], 'F'), 5: ("SET_PROP", ['G', 'G', 'G'], None),
        6: ("MOD", ['j', 'j'], 'F'), 7: ("EQ", ['G', 'G'], 'F'), 8: ("CALL_1", ['G', 'G'], 'F'),
        9: ("ADD", ['G', 'G'], 'F'), 10: ("DIV", ['j', 'j'], 'F'), 11: ("DEF_FUNC", ['G', 'G', 'G'], 'F'),
        12: ("URSH", ['j', 'G'], 'F'), 13: ("LT", ['j', 'j'], 'F'), 14: ("NEW_OBJECT", [], 'F'),
        15: ("GET_SCOPE_VAR", ['G'], 'F'), 16: ("GET_EXCEPTION", [], 'F'), 17: ("JUMP_IF_TRUE", ['G', 'G'], None),
        18: ("BIT_AND", ['j', 'G'], 'F'), 19: ("DELETE_PROP", ['G', 'G'], 'F'), 20: ("GET_THIS", [], 'F'),
        21: ("BIT_OR", ['G', 'G'], 'F'), 22: ("UNARY_PLUS", ['G'], 'F'), 23: ("UNWIND_SCOPE", ['G'], None),
        24: ("JUMP_IF_FALSE", ['G', 'G'], None), 25: ("DEL_SCOPE_VAR", ['G'], None), 26: ("XOR", ['G', 'j'], 'F'),
        27: ("NEQ_STRICT", ['j', 'j'], 'F'), 28: ("LOAD_WIN_PROP", ['G'], 'F'), 29: ("NEQ_STRICT", ['j', 'G'], 'F'),
        30: ("RETURN_VOID", [], None), 31: ("STRICT_EQ", ['j', 'G'], 'F'), 32: ("ADD", ['G', 'j'], 'F'),
        33: ("SUB", ['G', 'G'], 'F'), 34: ("NEW_BIND", ['G', 'G'], 'F'), 35: ("JUMP", ['G'], None),
        36: ("NEW_ARRAY", [], 'F'), 37: ("CLEAR_EXCEPTION", [], None), 38: ("NEW_REGEXP", ['G', 'G'], 'F'),
        39: ("SUB", ['j', 'j'], 'F'), 40: ("STRICT_EQ", ['G', 'j'], 'F'), 41: ("ADD", ['j', 'j'], 'F'),
        42: ("SET_CATCH_PC", ['G'], None), 43: ("CALL_3", ['G', 'G', 'G', 'G'], 'F'), 44: ("VAR_DECL", ['G'], None),
        45: ("SET_SCOPE_VAR", ['G', 'G'], None), 46: ("NEW_ARRAY_SIZE", ['G'], 'F'), 47: ("IN", ['j', 'j'], 'F'),
        48: ("ADD", ['j', 'G'], 'F'), 49: ("SET_FINALLY_PC", ['G'], None), 50: ("LOAD_CONST_11", [], 'F'),
        51: ("CALL_JS", ['G', 'G', 'G'], 'F'), 52: ("IN", ['G', 'j'], 'F'), 53: ("GT", ['j', 'j'], 'F'),
        54: ("BIT_OR", ['G', 'j'], 'F'), 55: ("BIND_EXCEPTION", ['G'], None), 56: ("CALL_2", ['G', 'G', 'G'], 'F'),
        57: ("SUB", ['j', 'G'], 'F'), 58: ("RETURN", ['G'], None), 59: ("MOD", ['j', 'G'], 'F'),
        60: ("MOV", ['G'], 'F'), 61: ("BIT_NOT", ['G'], 'F'), 62: ("BIT_OR", ['j', 'j'], 'F'),
        63: ("XOR", ['j', 'j'], 'F'), 64: ("TYPEOF", ['G'], 'F'), 65: ("LOAD_CONST_10", [], 'F'),
        66: ("BIT_AND", ['j', 'j'], 'F'), 67: ("SET_PARENT_SCOPE", ['G', 'j'], None), 68: ("GTE", ['j', 'G'], 'F'),
        69: ("DIV", ['j', 'G'], 'F'), 70: ("CALL_0", ['G'], 'F'), 71: ("LSH", ['j', 'j'], 'F'),
        72: ("INSTANCEOF", ['j', 'j'], 'F'), 73: ("THROW", ['G'], None), 74: ("GET_PROP", ['G', 'G'], 'F'),
        75: ("NEQ", ['j', 'G'], 'F'), 76: ("NEQ_STRICT", ['G', 'j'], 'F'), 77: ("LT", ['j', 'G'], 'F'),
        78: ("GT", ['j', 'G'], 'F'), 79: ("DIV", ['G', 'j'], 'F'), 80: ("GTE", ['j', 'j'], 'F'),
        81: ("MUL", ['j', 'j'], 'F'), 82: ("NOT", ['G'], 'F'), 83: ("SET_SCOPE_VAR", ['G', 'G'], None),
        84: ("LTE", ['j', 'G'], 'F'), 85: ("SAVE_SCOPE_STATE", ['G'], None), 86: ("LSH", ['j', 'G'], 'F'),
    }

    pc = [0]
    instructions = []

    while pc[0] < len(t):
        start_pc = pc[0]
        op_code = t[pc[0]]
        pc[0] += 1
        if op_code not in OPCODES:
            continue
        op_name, arg_types, dest_type = OPCODES[op_code]
        args = [read_G(t, pc) if at == 'G' else read_j(t, pc) for at in arg_types]
        dest = read_F(t, pc) if dest_type == 'F' else None
        instructions.append({'pc': start_pc, 'op': op_name, 'args': args, 'dest': dest})

    def fmt_val(v):
        if isinstance(v, str):
            if v.startswith("r[") and v.endswith("]"):
                return v
            escaped = v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
            return f'"{escaped}"'
        if v is None: return "null"
        if isinstance(v, bool): return "true" if v else "false"
        return str(v)

    out_lines = []
    
    for ins in instructions:
        pc_lbl = f"/* {ins['pc']:05d} */ "
        op = ins['op']
        args = ins['args']
        dest = ins['dest']

        if op == "VAR_DECL":
            out_lines.append(f"{pc_lbl}var var_{args[0]};")
        elif op in ("SET_SCOPE_VAR", "SET_PARENT_SCOPE"):
            val = fmt_val(args[1]) if len(args) > 1 else "null"
            out_lines.append(f"{pc_lbl}var_{args[0]} = {val};")
        elif op == "GET_SCOPE_VAR":
            out_lines.append(f"{pc_lbl}{dest} = var_{args[0]};")
        elif op == "MOV":
            out_lines.append(f"{pc_lbl}{dest} = {fmt_val(args[0])};")
        elif op == "LOAD_WIN_PROP":
            out_lines.append(f"{pc_lbl}{dest} = window.{args[0]};")
        elif op == "GET_PROP":
            obj, key = fmt_val(args[0]), fmt_val(args[1])
            out_lines.append(f"{pc_lbl}{dest} = {obj}[{key}];")
        elif op == "SET_PROP":
            obj, key, val = fmt_val(args[0]), fmt_val(args[1]), fmt_val(args[2])
            out_lines.append(f"{pc_lbl}{obj}[{key}] = {val};")
        elif op in ("ADD", "SUB", "MUL", "DIV", "MOD", "BIT_AND", "BIT_OR", "XOR", "LSH", "URSH", "EQ", "NEQ", "STRICT_EQ", "NEQ_STRICT", "LT", "GT", "LTE", "GTE"):
            sym_map = {"ADD": "+", "SUB": "-", "MUL": "*", "DIV": "/", "MOD": "%", "BIT_AND": "&", "BIT_OR": "|", "XOR": "^", "LSH": "<<", "URSH": ">>>", "EQ": "==", "NEQ": "!=", "STRICT_EQ": "===", "NEQ_STRICT": "!==", "LT": "<", "GT": ">", "LTE": "<=", "GTE": ">="}
            sym = sym_map.get(op, op)
            a1, a2 = fmt_val(args[0]), fmt_val(args[1])
            out_lines.append(f"{pc_lbl}{dest} = {a1} {sym} {a2};")
        elif op == "CALL_0":
            out_lines.append(f"{pc_lbl}{dest} = {fmt_val(args[0])}();")
        elif op == "CALL_1":
            out_lines.append(f"{pc_lbl}{dest} = {fmt_val(args[0])}({fmt_val(args[1])});")
        elif op == "CALL_2":
            out_lines.append(f"{pc_lbl}{dest} = {fmt_val(args[0])}({fmt_val(args[1])}, {fmt_val(args[2])});")
        elif op == "CALL_3":
            out_lines.append(f"{pc_lbl}{dest} = {fmt_val(args[0])}({fmt_val(args[1])}, {fmt_val(args[2])}, {fmt_val(args[3])});")
        elif op == "CALL_JS":
            out_lines.append(f"{pc_lbl}{dest} = {fmt_val(args[1])}.apply({fmt_val(args[0])}, {fmt_val(args[2])});")
        elif op == "NEW_OBJECT":
            out_lines.append(f"{pc_lbl}{dest} = {{}};")
        elif op == "NEW_ARRAY":
            out_lines.append(f"{pc_lbl}{dest} = [];")
        elif op == "NEW_ARRAY_SIZE":
            out_lines.append(f"{pc_lbl}{dest} = new Array({fmt_val(args[0])});")
        elif op == "NEW_BIND":
            out_lines.append(f"{pc_lbl}{dest} = new {fmt_val(args[0])}(...{fmt_val(args[1])});")
        elif op == "DEF_FUNC":
            entry_pc, name, num_args = args[0], args[1], args[2]
            fn_name = name if name else f"func_pc_{entry_pc}"
            out_lines.append(f"\n{pc_lbl}{dest} = function {fn_name}(/* args: {num_args} */) {{ /* entry: {entry_pc} */ }};")
        elif op == "JUMP":
            out_lines.append(f"{pc_lbl}goto PC_{args[0]};")
        elif op == "JUMP_IF_TRUE":
            out_lines.append(f"{pc_lbl}if ({fmt_val(args[0])}) goto PC_{args[1]};")
        elif op == "JUMP_IF_FALSE":
            out_lines.append(f"{pc_lbl}if (!{fmt_val(args[0])}) goto PC_{args[1]};")
        elif op == "RETURN":
            out_lines.append(f"{pc_lbl}return {fmt_val(args[0])};")
        elif op == "RETURN_VOID":
            out_lines.append(f"{pc_lbl}return;")
        elif op == "THROW":
            out_lines.append(f"{pc_lbl}throw {fmt_val(args[0])};")
        else:
            args_str = ", ".join(fmt_val(a) for a in args)
            out_lines.append(f"{pc_lbl}{op}({args_str});")

    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(out_lines) + "\n")

    print(f"Готово! Псевдокод сохранен в {output_file}.")

if __name__ == "__main__":
    decompile()