const fs = require('fs');

// 1. Поиск входного файла
let filename = 'p.js';
if (!fs.existsSync(filename) && fs.existsSync('input_file_0.js')) {
    filename = 'input_file_0.js';
}

if (!fs.existsSync(filename)) {
    console.error("❌ Ошибка: Файл p.js не найден в текущей директории!");
    process.exit(1);
}

console.log(`[1/4] Чтение файла ${filename}...`);
const code = fs.readFileSync(filename, 'utf8');

// 2. Распаковка массива байт-кода H -> t
const A = function(r, v, f) {
    for (var l = v.length, a = l - f, p = [], x = 0, n = new Map, u = 0; u < l; u++) n.set(v[u], u);
    for (; x < r.length; ) for (var h = 0, t = 1; ; ) {
        var M = n.get(r[x++]) || 0;
        if (M < f) { h += t * M; p.push(h | 0); break; }
        h += t * (M % f + f); t *= a;
    }
    return p;
};

const H_match = code.match(/var H="([^"]+)";/);
if (!H_match) {
    console.error("❌ Не удалось найти H в файле p.js");
    process.exit(1);
}

const H = H_match[1];
const t = A(H, "ZBpfykUL|VSP0>NiWXhOEmAGvtuT2+41M3eDYFbsHa^Rz=<x~KwJҳIr9Ql6$ndo875qCjcg", 45);

// 3. Точный расчет m и извлечение таблицы P.K из p.js
console.log(`[2/4] Точный расчет таблицы P.K...`);
const f_val = t.length;
const p_val = f_val + 32; // (L + true).length = 28 + 4 = 32
const m = t[f_val - 1] ^ p_val;

const I_w0 = 1; // Из I.w[0] = 1 в p.js
const K_len = t[m + I_w0] + 2;
const K = t.splice(m, K_len);

const y = [28, 14, 42, 36, 48, 40];
const g = function(r, v, f, l) {
    var a = r[v[0]++];
    if (a & 1) return a >> 1;
    if (a === f[0]) return !1;
    if (a === f[3]) return null;
    if (a === f[4]) {
        if (l != null && l.X) return l.X(r[v[0]++], r[v[0]++]);
        for (var p = "", x = r[v[0]++], n = 0; n < x; n++) {
            var u = r[v[0]++];
            p += String.fromCharCode(u & 4294967232 | u * 41 & 63);
        }
        return p;
    }
    if (a !== f[2]) {
        if (a === f[1]) return !0;
        if (a === f[5]) {
            var h = r[v[0]++], t_val = r[v[0]++], M = h & 2147483648 ? -1 : 1, I = (h & 2146435072) >> 20, S = (h & 1048575) * Math.pow(2, 32) + (t_val < 0 ? t_val + Math.pow(2, 32) : t_val);
            return I === 2047 ? (S ? NaN : M * Infinity) : ((I !== 0 ? S += Math.pow(2, 52) : I++), M * S * Math.pow(2, I - 1075));
        }
        return v[a >> 5];
    }
};

const PK = g(K, [0], y, null);
console.log(`✅ Таблица P.K извлечена! Длина: ${PK.length} символов.`);

// Экранируем непечатные бинарные байты для all_strings.txt
function escapeNonPrintable(str) {
    return str.replace(/[\x00-\x1F\x7F-\x9F]/g, c => '\\x' + c.charCodeAt(0).toString(16).padStart(2, '0'));
}
fs.writeFileSync('all_strings.txt', escapeNonPrintable(PK), 'utf8');

// Объект P для VM
const P = {
    K: PK,
    X: function(e, n) { return P.K.slice(n, n + e); }
};

// 4. Декомпиляция байт-кода ВМ в читаемый JS-псевдокод
console.log(`[3/4] Декомпиляция байт-кода ВМ в псевдокод...`);

function fetchOperand(codeArr, state) {
    var a = codeArr[state.pc++];
    if (a & 1) return a >> 1;
    if (a === 28) return false;
    if (a === 14) return true;
    if (a === 36) return null;
    if (a === 48) {
        var len = codeArr[state.pc++];
        var off = codeArr[state.pc++];
        return P.X(len, off);
    }
    if (a === 40) {
        var h = codeArr[state.pc++], t_val = codeArr[state.pc++];
        var M = h & 2147483648 ? -1 : 1, I = (h & 2146435072) >> 20, S = (h & 1048575) * Math.pow(2, 32) + (t_val < 0 ? t_val + Math.pow(2, 32) : t_val);
        return I === 2047 ? (S ? NaN : M * Infinity) : ((I !== 0 ? S += Math.pow(2, 52) : I++), M * S * Math.pow(2, I - 1075));
    }
    if (a === 42) {
        var regIdx = codeArr[state.pc++] >> 5;
        return `r${regIdx}`;
    }
    return `r${a >> 5}`;
}

function fetchReg(codeArr, state) {
    var b = codeArr[state.pc++];
    return `r${b >> 5}`;
}

function formatVal(v) {
    if (typeof v === 'string' && !v.startsWith('r') && !v.startsWith('window')) {
        return JSON.stringify(v);
    }
    return String(v);
}

function decompileFunction(startPc, name = "main") {
    let state = { pc: startPc };
    let lines = [];
    let discoveredFunctions = [];

    while (state.pc < t.length) {
        let currentPc = state.pc;
        let op = t[state.pc++];

        if (op === undefined) break;

        switch (op) {
            case 0: { // DEFINE_FUNCTION
                let entryPc = fetchOperand(t, state);
                let funcName = fetchOperand(t, state) || `sub_${entryPc}`;
                let argLen = fetchOperand(t, state);
                let outerScope = fetchReg(t, state);
                let destReg = fetchReg(t, state);
                lines.push(`${destReg} = function ${funcName}(${Array.from({length: argLen}, (_, i) => `p${i+1}`).join(', ')}) { /* entry @ PC ${entryPc} */ };`);
                discoveredFunctions.push({ pc: entryPc, name: funcName });
                break;
            }
            case 28: { // LOAD_GLOBAL
                let globalName = fetchOperand(t, state);
                let dest = fetchReg(t, state);
                lines.push(`${dest} = window[${formatVal(globalName)}];`);
                break;
            }
            case 45: { // LOAD_SCOPE_VAR
                let varName = fetchOperand(t, state);
                let dest = fetchReg(t, state);
                lines.push(`${dest} = ${varName};`);
                break;
            }
            case 68: { // SET_SCOPE_VAR
                let varName = fetchOperand(t, state);
                let src = fetchReg(t, state);
                lines.push(`${varName} = ${src};`);
                break;
            }
            case 65: { // GET_PROP
                let obj = fetchOperand(t, state);
                let prop = fetchOperand(t, state);
                let dest = fetchReg(t, state);
                lines.push(`${dest} = ${formatVal(obj)}[${formatVal(prop)}];`);
                break;
            }
            case 35: { // SET_PROP
                let obj = fetchOperand(t, state);
                let prop = fetchOperand(t, state);
                let val = fetchOperand(t, state);
                lines.push(`${formatVal(obj)}[${formatVal(prop)}] = ${formatVal(val)};`);
                break;
            }
            case 30: { // CALL_1
                let fn = fetchOperand(t, state);
                let arg = fetchOperand(t, state);
                let dest = fetchReg(t, state);
                lines.push(`${dest} = ${formatVal(fn)}(${formatVal(arg)});`);
                break;
            }
            case 67: { // CALL_2
                let fn = fetchOperand(t, state);
                let a1 = fetchOperand(t, state);
                let a2 = fetchOperand(t, state);
                let dest = fetchReg(t, state);
                lines.push(`${dest} = ${formatVal(fn)}(${formatVal(a1)}, ${formatVal(a2)});`);
                break;
            }
            case 85: { // CALL_3
                let fn = fetchOperand(t, state);
                let a1 = fetchOperand(t, state);
                let a2 = fetchOperand(t, state);
                let a3 = fetchOperand(t, state);
                let dest = fetchReg(t, state);
                lines.push(`${dest} = ${formatVal(fn)}(${formatVal(a1)}, ${formatVal(a2)}, ${formatVal(a3)});`);
                break;
            }
            case 72: { // CALL_0
                let fn = fetchOperand(t, state);
                let dest = fetchReg(t, state);
                lines.push(`${dest} = ${formatVal(fn)}();`);
                break;
            }
            case 56: { // CALL_APPLY
                let thisObj = fetchOperand(t, state);
                let fn = fetchOperand(t, state);
                let args = fetchOperand(t, state);
                let dest = fetchReg(t, state);
                lines.push(`${dest} = ${formatVal(fn)}.apply(${formatVal(thisObj)}, ${formatVal(args)});`);
                break;
            }
            case 37: case 74: { // LOAD_VAL / STORE_RES
                let val = fetchOperand(t, state);
                let dest = fetchReg(t, state);
                lines.push(`${dest} = ${formatVal(val)};`);
                break;
            }
            case 49: { // RETURN
                let val = fetchOperand(t, state);
                lines.push(`return ${formatVal(val)};`);
                return { lines, discoveredFunctions };
            }
            case 10: { // JUMP_IF_TRUTHY
                let cond = fetchOperand(t, state);
                let target = fetchOperand(t, state);
                lines.push(`if (${formatVal(cond)}) goto PC_${target};`);
                break;
            }
            case 50: { // JUMP_IF_FALSEY
                let cond = fetchOperand(t, state);
                let target = fetchOperand(t, state);
                lines.push(`if (!${formatVal(cond)}) goto PC_${target};`);
                break;
            }
            case 18: { // JUMP UNCONDITIONAL
                let target = fetchOperand(t, state);
                lines.push(`goto PC_${target};`);
                break;
            }
            case 19: case 27: case 61: case 64: { // ADD
                let left = fetchOperand(t, state);
                let right = fetchOperand(t, state);
                let dest = fetchReg(t, state);
                lines.push(`${dest} = ${formatVal(left)} + ${formatVal(right)};`);
                break;
            }
            case 13: case 39: case 40: { // SUB
                let left = fetchOperand(t, state);
                let right = fetchOperand(t, state);
                let dest = fetchReg(t, state);
                lines.push(`${dest} = ${formatVal(left)} - ${formatVal(right)};`);
                break;
            }
            case 7: case 63: { // MUL
                let left = fetchOperand(t, state);
                let right = fetchOperand(t, state);
                let dest = fetchReg(t, state);
                lines.push(`${dest} = ${formatVal(left)} * ${formatVal(right)};`);
                break;
            }
            case 6: case 48: case 82: { // DIV
                let left = fetchOperand(t, state);
                let right = fetchOperand(t, state);
                let dest = fetchReg(t, state);
                lines.push(`${dest} = ${formatVal(left)} / ${formatVal(right)};`);
                break;
            }
            case 1: case 70: case 77: { // STRICT EQ
                let left = fetchOperand(t, state);
                let right = fetchOperand(t, state);
                let dest = fetchReg(t, state);
                lines.push(`${dest} = (${formatVal(left)} === ${formatVal(right)});`);
                break;
            }
            case 81: { // NEW_OBJECT
                let dest = fetchReg(t, state);
                lines.push(`${dest} = {};`);
                break;
            }
            case 83: { // NEW_ARRAY
                let dest = fetchReg(t, state);
                lines.push(`${dest} = [];`);
                break;
            }
            default: {
                if (op > 86) {
                    state.pc--;
                    return { lines, discoveredFunctions };
                }
                break;
            }
        }
    }

    return { lines, discoveredFunctions };
}

// 5. Сборка decompiled.js
console.log(`[4/4] Генерация файла decompiled.js...`);
let entry = decompileFunction(0, "main");
let output = `// =======================================================\n`;
output += `// Decompiled JavaScript Output from VM Bytecode\n`;
output += `// =======================================================\n\n`;

output += `// --- MAIN SCRIPT EXECUTION ENTRY POINT ---\n`;
output += entry.lines.map(l => "  " + l).join("\n") + "\n\n";

let processedPcs = new Set([0]);
let queue = [...entry.discoveredFunctions];

while (queue.length > 0) {
    let fnInfo = queue.shift();
    if (processedPcs.has(fnInfo.pc)) continue;
    processedPcs.add(fnInfo.pc);

    let decompiledFn = decompileFunction(fnInfo.pc, fnInfo.name);
    output += `// --- FUNCTION ${fnInfo.name} (entry @ PC ${fnInfo.pc}) ---\n`;
    output += `function ${fnInfo.name}() {\n`;
    output += decompiledFn.lines.map(l => "  " + l).join("\n") + "\n";
    output += `}\n\n`;

    queue.push(...decompiledFn.discoveredFunctions);
}

fs.writeFileSync('decompiled.js', output, 'utf8');

console.log(`🎉 ГОТОВО!`);
console.log(`- Таблица строк сохранена в 'all_strings.txt'`);
console.log(`- ПСЕВДОКОД ИСПОЛНЕНИЯ находится в 'decompiled.js'! Откройте его в VS Code.`);