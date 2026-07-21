import sys
from unittest.mock import MagicMock

# Mock chromadb to bypass the pydantic.v1 issue on Python 3.14
mock_chroma = MagicMock()
sys.modules["chromadb"] = mock_chroma
sys.modules["chromadb.config"] = MagicMock()
sys.modules["chromadb.api"] = MagicMock()
sys.modules["chromadb.api.client"] = MagicMock()

try:
    from crewai import Agent, Task, Crew
    print("CrewAI: OK (with mock)")
except Exception as e:
    print(f"CrewAI: FAILED even with mock ({e})")
    import traceback
    traceback.print_exc()
