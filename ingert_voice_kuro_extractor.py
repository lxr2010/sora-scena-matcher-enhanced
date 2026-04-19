import os
import re
import json
import ast
import bisect
import argparse
from dataclasses import dataclass
from typing import List, Optional, Dict


@dataclass
class FunctionBlock:
    name: str
    signature: str
    calltable: str
    body: str
    calltable_abs_start: Optional[int]
    body_abs_start: int


@dataclass
class SystemCall:
    file: str
    line: int
    column: int
    type: str
    code: str
    normalized_args: str
    args: List
    command: Optional[str] = None


_FN_HEAD_RE = re.compile(r'\bfn\s+([A-Za-z_][A-Za-z0-9_]*|`[^`]*`)')
_SYSTEM_HEAD_RE = re.compile(r'(?:(\d+)@)?system\[(\d+)\s*,\s*(\d+)\]\s*\(')
_LINE_PREFIX_RE = re.compile(
    r'(?<![\w])(\d+)@(?=(?:system\b|[A-Za-z_][A-Za-z0-9_]*\b|`|"|-?\d))'
)
_NUMBER_RE = re.compile(r'^[+-]?(?:\d+\.\d+|\d+|\d+\.)(?:[eE][+-]?\d+)?$')


def read_quoted(text: str, i: int) -> int:
    quote = text[i]
    i += 1
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '\\':
            i += 2
            continue
        if ch == quote:
            return i + 1
        i += 1
    raise ValueError("unterminated quoted literal")


def skip_ws(text: str, i: int) -> int:
    n = len(text)
    while i < n and text[i].isspace():
        i += 1
    return i


def find_matching(text: str, i: int, open_ch: str, close_ch: str) -> int:
    if text[i] != open_ch:
        raise ValueError(f"expected {open_ch!r} at {i}")

    depth = 0
    n = len(text)
    j = i
    while j < n:
        ch = text[j]
        if ch == '"' or ch == '`':
            j = read_quoted(text, j)
            continue
        if ch == '/' and j + 1 < n and text[j + 1] == '/':
            j += 2
            while j < n and text[j] != '\n':
                j += 1
            continue
        if ch == '/' and j + 1 < n and text[j + 1] == '*':
            j += 2
            while j + 1 < n and not (text[j] == '*' and text[j + 1] == '/'):
                j += 1
            j += 2
            continue

        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return j
        j += 1

    raise ValueError(f"unmatched {open_ch!r}")


class LineIndex:
    def __init__(self, text: str):
        self.newlines = [i for i, ch in enumerate(text) if ch == '\n']

    def line_of_offset(self, offset: int) -> int:
        return bisect.bisect_right(self.newlines, offset) + 1


def strip_special_commands(value: str) -> str:
    return re.sub(r'<.+?>', '', value)


def strip_line_prefixes(text: str) -> str:
    out = []
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        if ch == '"' or ch == '`':
            j = read_quoted(text, i)
            out.append(text[i:j])
            i = j
            continue

        m = _LINE_PREFIX_RE.match(text, i)
        if m:
            i = m.end()
            continue

        out.append(ch)
        i += 1

    return ''.join(out)


def split_top_level_args(arg_text: str) -> List[str]:
    parts: List[str] = []
    start = 0
    depth_paren = 0
    depth_brack = 0
    depth_brace = 0
    i = 0
    n = len(arg_text)

    while i < n:
        ch = arg_text[i]
        if ch == '"' or ch == '`':
            i = read_quoted(arg_text, i)
            continue

        if ch == '(':
            depth_paren += 1
        elif ch == ')':
            depth_paren -= 1
        elif ch == '[':
            depth_brack += 1
        elif ch == ']':
            depth_brack -= 1
        elif ch == '{':
            depth_brace += 1
        elif ch == '}':
            depth_brace -= 1
        elif ch == ',' and depth_paren == 0 and depth_brack == 0 and depth_brace == 0:
            parts.append(arg_text[start:i].strip())
            start = i + 1
        i += 1

    tail = arg_text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def parse_atom(token: str):
    token = strip_line_prefixes(token).strip()
    if len(token) >= 2 and token[0] == '"' and token[-1] == '"':
        return ast.literal_eval(token)

    if _NUMBER_RE.match(token):
        if any(c in token for c in ".eE"):
            return float(token)
        return int(token)

    return token


def normalize_value(value) -> str:
    if isinstance(value, float):
        return format(value, "g")
    return str(value)


def process_values(values: List) -> List:
    args: List = []
    text_parts: List[str] = []

    for value in values:
        if isinstance(value, str):
            stripped = strip_special_commands(value)
            text_parts.append(stripped)
        elif value == 10 and text_parts:
            continue
        else:
            args.append(value)

    if text_parts:
        args.append(''.join(text_parts))

    return args


def extract_functions(text: str) -> List[FunctionBlock]:
    out: List[FunctionBlock] = []
    pos = 0

    while True:
        m = _FN_HEAD_RE.search(text, pos)
        if not m:
            break

        sig_start = m.start()
        fn_name = m.group(1)
        i = m.end()

        while i < len(text):
            ch = text[i]
            if ch == '"' or ch == '`':
                i = read_quoted(text, i)
                continue
            if ch == '/' and i + 1 < len(text) and text[i + 1] == '/':
                i += 2
                while i < len(text) and text[i] != '\n':
                    i += 1
                continue
            if ch == '/' and i + 1 < len(text) and text[i + 1] == '*':
                i += 2
                while i + 1 < len(text) and not (text[i] == '*' and text[i + 1] == '/'):
                    i += 1
                i += 2
                continue
            if ch == '{':
                break
            i += 1

        if i >= len(text) or text[i] != '{':
            raise ValueError(f"function {fn_name}: no block found")

        sig_text = text[sig_start:i].strip()

        first_open = i
        first_close = find_matching(text, first_open, '{', '}')
        first_block = text[first_open + 1:first_close]

        j = skip_ws(text, first_close + 1)
        if j < len(text) and text[j] == '{':
            body_open = j
            body_close = find_matching(text, body_open, '{', '}')
            out.append(FunctionBlock(
                name=fn_name,
                signature=sig_text,
                calltable=first_block,
                body=text[body_open + 1:body_close],
                calltable_abs_start=first_open + 1,
                body_abs_start=body_open + 1,
            ))
            pos = body_close + 1
        else:
            out.append(FunctionBlock(
                name=fn_name,
                signature=sig_text,
                calltable="",
                body=first_block,
                calltable_abs_start=None,
                body_abs_start=first_open + 1,
            ))
            pos = first_close + 1

    return out


def build_entry(
    source: str,
    file_path: str,
    line: int,
    raw_call: str,
    category: int,
    func_id: int,
    arg_values: List,
) -> SystemCall:
    type_name = "add_struct" if source == "calltable" else "Command"
    command = None
    if source == "body":
        command = f"Cmd_text_{func_id:02d}"

    normalized_parts = [str(category), str(func_id)] + [normalize_value(v) for v in arg_values]
    normalized_args = ",".join(normalized_parts)

    processed_args = process_values([category, func_id] + arg_values)

    return SystemCall(
        file=file_path,
        line=line,
        column=0,
        type=type_name,
        code=strip_line_prefixes(raw_call).strip(),
        normalized_args=normalized_args,
        args=processed_args,
        command=command,
    )


def extract_system_entries(
    block_text: str,
    block_abs_start: Optional[int],
    source: str,
    file_path: str,
    text_line_index: LineIndex,
) -> List[SystemCall]:
    if block_abs_start is None:
        return []

    out: List[SystemCall] = []
    pos = 0

    while True:
        m = _SYSTEM_HEAD_RE.search(block_text, pos)
        if not m:
            break

        category = int(m.group(2))
        func_id = int(m.group(3))
        if category != 5 or func_id not in (0, 6):
            pos = m.end()
            continue

        open_paren = m.end() - 1
        close_paren = find_matching(block_text, open_paren, '(', ')')
        raw_call = block_text[m.start():close_paren + 1]

        line_prefix = int(m.group(1)) if m.group(1) else None
        abs_start = block_abs_start + m.start()
        line = line_prefix if line_prefix is not None else text_line_index.line_of_offset(abs_start)

        normalized_call = strip_line_prefixes(raw_call)
        normalized_open = normalized_call.find('(')
        normalized_close = normalized_call.rfind(')')
        inner = normalized_call[normalized_open + 1:normalized_close] if normalized_open >= 0 and normalized_close >= 0 else ""
        tokens = split_top_level_args(inner)
        values = [parse_atom(t) for t in tokens]

        out.append(build_entry(source, file_path, line, raw_call, category, func_id, values))
        pos = close_paren + 1

    return out


def parse_ingert_file(file_path: str) -> List[Dict]:
    with open(file_path, 'r', encoding='utf-8') as f:
        text = f.read()

    file_abs = os.path.abspath(file_path)
    line_index = LineIndex(text)
    entries: List[Dict] = []

    for fn in extract_functions(text):
        entries.extend(
            e.__dict__
            for e in extract_system_entries(fn.calltable, fn.calltable_abs_start, "calltable", file_abs, line_index)
        )
        entries.extend(
            e.__dict__
            for e in extract_system_entries(fn.body, fn.body_abs_start, "body", file_abs, line_index)
        )

    add_struct_map = {e['normalized_args']: e for e in entries if e['type'] == 'add_struct'}
    command_map = {e['normalized_args']: e for e in entries if e['type'] == 'Command'}

    for e in entries:
        if e['type'] == 'add_struct':
            e.pop('command', None)

    for e in entries:
        if e['type'] == 'add_struct' and e['normalized_args'] in command_map:
            e['line_corr'] = command_map[e['normalized_args']]['line']
        elif e['type'] == 'Command' and e['normalized_args'] in add_struct_map:
            e['line_corr'] = add_struct_map[e['normalized_args']]['line']

    return entries


def collect_ing_files(input_path: str) -> List[str]:
    if os.path.isfile(input_path):
        return [input_path] if input_path.lower().endswith('.ing') else []

    ing_files: List[str] = []
    for root, _, files in os.walk(input_path):
        for name in files:
            if name.lower().endswith('.ing'):
                ing_files.append(os.path.join(root, name))
    return sorted(ing_files)


def extract_from_input(input_path: str) -> List[Dict]:
    ing_files = collect_ing_files(input_path)
    if not ing_files:
        print(f"No .ing files found under: {input_path}")
        return []

    all_entries: List[Dict] = []
    for ing_file in ing_files:
        try:
            all_entries.extend(parse_ingert_file(ing_file))
        except Exception as ex:
            print(f"Error parsing {ing_file}: {ex}")
            raise

    all_entries.sort(key=lambda x: (x['file'], x['line'], x['type']))
    print(f"Extracted {len(all_entries)} entries from {len(ing_files)} files: {input_path}")
    return all_entries


def write_outputs(entries: List[Dict], output_file: str) -> None:
    output = os.path.abspath(output_file)
    output_dir = os.path.dirname(output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(output, 'w', encoding='utf-8') as f:
        json.dump(entries, f, indent=4, ensure_ascii=False)

    stem, ext = os.path.splitext(output)
    for typ in ("Command", "add_struct"):
        out_typ = f"{stem}_{typ}{ext}"
        subset = [e for e in entries if e['type'] == typ]
        with open(out_typ, 'w', encoding='utf-8') as f:
            json.dump(subset, f, indent=4, ensure_ascii=False)

    print(f"Saved: {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract Cmd_text_00/06 equivalent entries from Ingert .ing files")
    parser.add_argument("input", nargs="?", default=os.path.join(os.path.dirname(os.path.dirname(__file__)), "disasm"), help="Input .ing file or directory")
    parser.add_argument("--output", default=os.path.join(os.path.dirname(__file__), "ingert_data.json"), help="Output json file")
    parser.add_argument("--jp-input", help="JP Ingert input file or directory")
    parser.add_argument("--sc-input", help="SC Ingert input file or directory")
    parser.add_argument("--output-dir", default=os.path.dirname(__file__), help="Output directory for jp/sc batch mode")
    args = parser.parse_args()

    if args.jp_input or args.sc_input:
        if not (args.jp_input and args.sc_input):
            raise ValueError("--jp-input and --sc-input must be provided together")

        os.makedirs(args.output_dir, exist_ok=True)

        jp_entries = extract_from_input(args.jp_input)
        sc_entries = extract_from_input(args.sc_input)

        write_outputs(jp_entries, os.path.join(args.output_dir, "ingert_data_jp.json"))
        write_outputs(sc_entries, os.path.join(args.output_dir, "ingert_data_sc.json"))
        print(f"Extraction complete. Found a total of {len(jp_entries) + len(sc_entries)} entries.")
        return

    all_entries = extract_from_input(args.input)
    write_outputs(all_entries, args.output)


if __name__ == '__main__':
    main()
