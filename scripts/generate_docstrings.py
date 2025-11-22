#!/usr/bin/env python3
"""
Script to generate docstrings for MCP tool files.
Outputs the docstrings that need to be added manually.
"""

import os
import ast
from pathlib import Path

def has_docstring(node):
    """Check if a function/class has a docstring."""
    return (ast.get_docstring(node) is not None)

def analyze_function(func_node):
    """Analyze a function to generate a docstring template."""
    func_name = func_node.name
    args = []
    returns = "Dict[str, Any]"
    
    # Get function arguments
    for arg in func_node.args.args:
        arg_name = arg.arg
        # Try to get type hint if available
        if arg.annotation:
            if isinstance(arg.annotation, ast.Name):
                arg_type = arg.annotation.id
            elif isinstance(arg.annotation, ast.Subscript):
                arg_type = "complex type"
            else:
                arg_type = "Any"
        else:
            arg_type = "str"  # default assumption
        args.append((arg_name, arg_type))
    
    return func_name, args, returns

def generate_docstring(func_name, args, returns, is_mcp_tool=False, indent=4):
    """Generate a docstring template for a function."""
    ind = ' ' * indent
    lines = [f'{ind}"""']
    
    # Add a description based on function name
    desc = func_name.replace('_', ' ').title()
    lines.append(f'{ind}{desc}')
    lines.append(f'{ind}')
    
    # Add Args section if there are arguments
    if args:
        lines.append(f'{ind}Args:')
        for arg_name, arg_type in args:
            if arg_name not in ['self', 'cls', 'ctx']:
                lines.append(f'{ind}    {arg_name}: {arg_type}')
    
    # Add Returns section
    if args:
        lines.append(f'{ind}')
    lines.append(f'{ind}Returns:')
    lines.append(f'{ind}    {returns}')
    
    lines.append(f'{ind}"""')
    return '\n'.join(lines)

def process_file(filepath):
    """Process a Python file and output needed docstrings."""
    print(f"\n{'='*70}")
    print(f"FILE: {filepath.name}")
    print('='*70)
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        print(f"❌ Syntax error: {e}")
        return
    
    # Find functions without docstrings
    functions_without_docs = []
    
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not has_docstring(node):
                # Check if it's an MCP tool
                is_mcp_tool = any(
                    isinstance(dec, ast.Call) and 
                    isinstance(dec.func, ast.Attribute) and
                    dec.func.attr == 'tool'
                    for dec in node.decorator_list
                )
                
                func_name, args, returns = analyze_function(node)
                
                # Get the actual line content to determine indent
                lines = content.split('\n')
                if node.lineno - 1 < len(lines):
                    func_line = lines[node.lineno - 1]
                    indent = len(func_line) - len(func_line.lstrip())
                else:
                    indent = 4
                
                functions_without_docs.append({
                    'name': func_name,
                    'line': node.lineno,
                    'args': args,
                    'returns': returns,
                    'is_mcp_tool': is_mcp_tool,
                    'indent': indent
                })
    
    if not functions_without_docs:
        print("✅ All functions already have docstrings!")
        return
    
    print(f"Found {len(functions_without_docs)} functions without docstrings\n")
    
    # Output docstrings for each function
    for func in functions_without_docs:
        marker = "🔧 MCP TOOL" if func['is_mcp_tool'] else "📝 FUNCTION"
        print(f"\n{marker}: {func['name']} (line {func['line']})")
        print("-" * 70)
        docstring = generate_docstring(
            func['name'],
            func['args'], 
            func['returns'],
            func['is_mcp_tool'],
            func['indent']
        )
        print(docstring)
        print()

def main():
    """Main function to process all MCP files."""
    script_path = Path(__file__).resolve()
    # MCP directory is ../MCP from scripts
    mcp_dir = script_path.parent.parent / "MCP"
    
    print(f"Scanning MCP directory: {mcp_dir}\n")
    
    if not mcp_dir.exists():
        print(f"❌ MCP directory not found: {mcp_dir}")
        return
    
    # Get all Python files
    py_files = sorted([f for f in mcp_dir.glob("*.py")])
    
    print(f"Found {len(py_files)} Python files to analyze")
    
    for py_file in py_files:
        process_file(py_file)
    
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    print("Copy the docstrings above and paste them after each function definition.")
    print("The docstrings should be placed right after the 'def' or 'async def' line.")

if __name__ == "__main__":
    main()
