import ast, sys
paths = ['managers/rpa_manager.py', 'config.py']
for path in paths:
    with open(path, 'r', encoding='utf-8') as f:
        src = f.read()
    try:
        ast.parse(src, filename=path)
        print(f'OK: {path}')
    except SyntaxError as e:
        print(f'ERROR: {path}: {e}')
        sys.exit(1)
