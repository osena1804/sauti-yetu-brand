r"""Lists the third-party packages your project imports, so you can write requirements.txt.

Run from the project folder:   python check_requirements.py
Then compare the output with requirements.txt, and test in a FRESH virtual environment:
    python -m venv .venv
    .venv\Scripts\activate          (Windows)   or   source .venv/bin/activate   (Mac/Linux)
    pip install -r requirements.txt
    streamlit run <your main file>.py
"""
import ast
import os
import sys

# Import name -> package name on PyPI, where they differ
PYPI_NAMES = {
    "google": "google-genai",
    "PIL": "pillow",
    "yaml": "pyyaml",
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    "dotenv": "python-dotenv",
    "Crypto": "pycryptodome",
    "jwt": "pyjwt",
}

here = os.path.abspath(os.getcwd())
local = {os.path.splitext(f)[0] for f in os.listdir(here) if f.endswith(".py")}
local |= {d for d in os.listdir(here) if os.path.isdir(os.path.join(here, d))}
stdlib = set(sys.stdlib_module_names)

found = {}
for name in sorted(os.listdir(here)):
    if not name.endswith(".py"):
        continue
    try:
        with open(os.path.join(here, name), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
    except (SyntaxError, UnicodeDecodeError) as e:
        print(f"! could not read {name}: {e}")
        continue
    for node in ast.walk(tree):
        mods = []
        if isinstance(node, ast.Import):
            mods = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            mods = [node.module.split(".")[0]]
        for m in mods:
            if m not in stdlib and m not in local:
                found.setdefault(m, set()).add(name)

if not found:
    print("No third-party imports found.")
else:
    print("Third-party packages imported by your code:\n")
    for m in sorted(found):
        pkg = PYPI_NAMES.get(m, m)
        print(f"  {pkg:24} (import {m}; used in {', '.join(sorted(found[m]))})")
    print("\nPut these in requirements.txt (one per line). Check the PyPI name if an install fails.")