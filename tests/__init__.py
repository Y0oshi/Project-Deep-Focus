import sys
from pathlib import Path

# Make the repo root importable so `from execution import ...` works during
# test discovery regardless of the current working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
