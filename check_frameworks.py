import crewai
import langgraph
import autogen_agentchat
import autogen_core
import pydantic_ai
import smolagents
import pydantic

print(f"crewai: {crewai.__version__ if hasattr(crewai, '__version__') else 'unknown'}")
print(f"langgraph: {langgraph.__version__ if hasattr(langgraph, '__version__') else 'unknown'}")
print(f"pydantic_ai: {pydantic_ai.__version__ if hasattr(pydantic_ai, '__version__') else 'unknown'}")
print(f"smolagents: {smolagents.__version__ if hasattr(smolagents, '__version__') else 'unknown'}")
print(f"pydantic: {pydantic.__version__}")

try:
    from autogen_agentchat.agents import CodeExecutorAgent
    print("autogen_agentchat: OK")
except ImportError as e:
    print(f"autogen_agentchat: FAILED ({e})")
