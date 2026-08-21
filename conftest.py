# conftest.py — shared pytest fixtures and configuration
import sys
from pathlib import Path

# Ensure the agent root is importable from all test files
sys.path.insert(0, str(Path(__file__).parent))
