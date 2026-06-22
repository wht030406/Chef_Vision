import ast, sys
try:
    src = open("d:/Chef_Vision/core/TrackFood.py", encoding="utf-8").read()
    ast.parse(src)
    print("SYNTAX_OK")
except SyntaxError as e:
    print(f"SYNTAX_ERROR: {e}")
    sys.exit(1)
