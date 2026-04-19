import os
import ast
import json
import re

def parse_node_value(node):
    """Recursively parse AST nodes to get their Python values."""
    if isinstance(node, ast.Constant):
        return node.value
    elif isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Call):
        func = parse_node_value(node.func)
        args = [parse_node_value(arg) for arg in node.args]
        return { 'func': func, 'args': args }
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        operand_value = parse_node_value(node.operand)
        if isinstance(operand_value, (int, float)):
            return -operand_value
    elif isinstance(node, ast.List):
        return [parse_node_value(e) for e in node.elts]
    else:
        return ast.unparse(node)
# Check if a node is an INT(10) node
def is_newline_node(node):
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'INT' and \
        node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == 10

def is_int_node(node):
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'INT'

def is_float_node(node):
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'FLOAT'

def is_undef_node(node):
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'UNDEF' and \
        node.args and isinstance(node.args[0], ast.Constant)

def is_str_node(node):
    return isinstance(node, ast.Constant) and isinstance(node.value, str)

def get_node_value(node):
    value = None
    if is_str_node(node):
        value = node.value
    else:
        value = parse_node_value(node)
        if isinstance(value,dict):
            if value['func'] in ['INT','FLOAT']:
                value = value['args'][0]
    return value

# delete all "<.+?>" stuff
def strip_special_commands(str) -> str:
    return re.sub(r'<.+?>', '', str)

def normalize_args(arg_nodes, category=None, funcid=None) -> str:
    normalized = []
    if category is not None and funcid is not None:
        normalized.append(str(category))
        normalized.append(str(funcid))
    for node in arg_nodes:
        if is_undef_node(node):
            continue
        value = get_node_value(node)
        normalized.append(str(value))
    return ",".join(normalized)



def process_arguments(arg_nodes):
    """Process a list of AST nodes to extract arguments and concatenate strings."""
    args = []
    text_parts = []

    for node in arg_nodes:
        if is_undef_node(node):
            continue

        value = get_node_value(node)
        if isinstance(value, str):
            stripped = strip_special_commands(value)
            text_parts.append(stripped)
        elif is_newline_node(node) and text_parts:
            continue
        else:
            args.append(value)
    
    if text_parts:
        args.append("".join(text_parts))

    return args

class VoiceExtractor(ast.NodeVisitor):
    """
    An AST visitor to extract specific call expressions from scena scripts.

    This visitor walks the Abstract Syntax Tree of a Python script and collects
    information about two types of function calls:
    1. Calls to 'add_struct' where the 'array2' list starts with 'INT(5)'.
    2. Calls to 'Command' where the first argument is 'Cmd_text_00' or 'Cmd_text_06'.
    """
    def __init__(self, file_path):
        self.file_path = file_path
        self.results = []

    def visit_Call(self, node):
        # Ensure we have a simple function call like `func(...)`
        if not isinstance(node.func, ast.Name):
            self.generic_visit(node)
            return

        func_name = node.func.id

        if func_name == 'add_struct':
            self._handle_add_struct(node)
        elif func_name == 'Command': # Changed from CallFunction
            self._handle_command(node)

        # Continue traversing the tree
        self.generic_visit(node)

    def _handle_add_struct(self, node):
        """Handles 'add_struct' call nodes by checking keyword arguments."""
        for kw in node.keywords:
            if kw.arg == 'array2' and isinstance(kw.value, ast.List):
                arg_list = kw.value
                # Check if the list has elements and the first one is a Call node
                if not arg_list.elts or not isinstance(arg_list.elts[0], ast.Call):
                    continue

                first_elt_call = arg_list.elts[0]
                # Check if it's a call to 'INT'
                if not isinstance(first_elt_call.func, ast.Name) or first_elt_call.func.id != 'INT':
                    continue

                # Check if the 'INT' call has arguments and the first is a Constant(5)
                if not first_elt_call.args or not isinstance(first_elt_call.args[0], ast.Constant) or first_elt_call.args[0].value != 5:
                    continue

                # Found a match, record it
                # Process the arguments in array2
                processed_args = process_arguments(arg_list.elts)

                self.results.append({
                    'file': self.file_path,
                    'line': node.lineno,
                    'column': node.col_offset,
                    'type': 'add_struct',
                    'code': ast.unparse(node),
                    'normalized_args': normalize_args(arg_list.elts),
                    'args': processed_args
                })
                # No need to check other arguments for this call
                break

    def _handle_command(self, node):
        """Handles 'Command' call nodes."""
        if not node.args:
            return

        first_arg = node.args[0]
        # Check if the first argument is a Constant string with the target value
        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
            if first_arg.value in ('Cmd_text_00', 'Cmd_text_06'):
                # The arguments for Command are in the second parameter, which is a list
                if len(node.args) > 1 and isinstance(node.args[1], ast.List):
                    arg_nodes = node.args[1].elts
                    processed_args = process_arguments(arg_nodes)
                else:
                    processed_args = []

                self.results.append({
                    'file': self.file_path,
                    'line': node.lineno,
                    'column': node.col_offset,
                    'type': 'Command',
                    'code': ast.unparse(node),
                    'normalized_args': normalize_args(arg_nodes, 0x5, int(first_arg.value[-2:])),
                    'command': first_arg.value,
                    'args': processed_args
                })

def parse_script(file_path):
    """Parses a single Python script and returns extracted voice data."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        tree = ast.parse(content, filename=file_path)
        extractor = VoiceExtractor(file_path)
        extractor.visit(tree)
        add_struct_map = { a['normalized_args']: a for a in extractor.results if a['type'] == 'add_struct'}
        command_map = {c['normalized_args']: c for c in extractor.results if c['type'] == 'Command'}

        for a in extractor.results :
            if a['type'] == 'add_struct':
                if a['normalized_args'] in command_map.keys():
                    a['line_corr'] = command_map[a['normalized_args']]['line']
            elif a['type'] == 'Command':
                if a['normalized_args'] in add_struct_map.keys():
                    a['line_corr'] = add_struct_map[a['normalized_args']]['line']
        return extractor.results
    except Exception as e:      
        print(f"Error parsing {file_path}: {e}")
        raise e
        return []

def main():
    """Main function to find scripts, parse them, and save the results."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    scena_dirs = {
        'jp': os.path.join(base_dir, 'scena', 'jp'),
        'sc': os.path.join(base_dir, 'scena', 'sc')
    }

    total_entries = 0
    for lang, directory in scena_dirs.items():
        if not os.path.isdir(directory):
            print(f"Warning: Directory not found, skipping: {directory}")
            continue
        
        print(f"Scanning directory: {directory}...")
        lang_results = []
        for filename in os.listdir(directory):
            if filename.endswith('.py'):
                file_path = os.path.join(directory, filename)
                results = parse_script(file_path)
                if results:
                    lang_results.extend(results)

        # Sort results for consistency
        lang_results.sort(key=lambda x: (x['file'], x['line']))

        output_file = os.path.join(base_dir, f'scena_data_{lang}.json')
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(lang_results, f, indent=4, ensure_ascii=False)

        for typ in ["Command", "add_struct"]:
            output_file_typ = os.path.join(base_dir, f'scena_data_{lang}_{typ}.json')
            lang_results_typ = [r for r in lang_results if r['type'] == typ]
            with open(output_file_typ, 'w', encoding='utf-8') as f:
                json.dump(lang_results_typ, f, indent=4, ensure_ascii=False)
        
        total_entries += len(lang_results)
        print(f"Found {len(lang_results)} entries for '{lang}'. Results saved to {output_file}")

    print(f"\nExtraction complete. Found a total of {total_entries} entries.")

if __name__ == '__main__':
    main()
