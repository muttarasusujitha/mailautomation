import importlib
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

if __name__ == "__main__":
    importlib.import_module("generate_token").main()
