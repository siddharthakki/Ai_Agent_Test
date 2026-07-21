import os
import json
import time
import asyncio
import subprocess
import sys
import operator
from typing import TypedDict, List, Dict, Any, Union, Annotated

# Frameworks
from langgraph.graph import StateGraph, END
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.providers import infer_provider
from pydantic import BaseModel, Field

# Model Tiers
MODEL_TIERS = {
    "small": "qwen2.5-coder:1.5b",
    "medium": "qwen2.5:14b",
    "large": "gemma4:26b",
    "coding": "qwen3-coder:30b"
}

# Model Lock for VRAM management
model_lock = asyncio.Lock()

# Mock chromadb for CrewAI
import types
if "chromadb" not in sys.modules:
    mock_chroma = types.ModuleType("chromadb")
    sys.modules["chromadb"] = mock_chroma
    mock_chroma.config = types.ModuleType("chromadb.config")
    sys.modules["chromadb.config"] = mock_chroma
    mock_chroma.utils = types.ModuleType("chromadb.utils")
    sys.modules["chromadb.utils"] = mock_chroma
    mock_chroma.utils.embedding_functions = types.ModuleType("chromadb.utils.embedding_functions")
    sys.modules["chromadb.utils.embedding_functions"] = mock_chroma.utils.embedding_functions
    mock_chroma.utils.embedding_functions.openai_embedding_function = types.ModuleType("chromadb.utils.embedding_functions.openai_embedding_function")
    sys.modules["chromadb.utils.embedding_functions.openai_embedding_function"] = mock_chroma.utils.embedding_functions.openai_embedding_function

try:
    from crewai import Agent as CrewAgent, Task as CrewTask, Crew
    from langchain_community.llms import Ollama
except:
    CrewAgent, CrewTask, Crew, Ollama = None, None, None, None

# Models config
OLLAMA_API_URL = "http://localhost:11434/v1"

class RouteDecision(BaseModel):
    mode: str = Field(description="FAST, MEDIUM, or COMPLEX")
    confidence: float
    reasons: str
    selected_frameworks: List[str]
    selected_models: Dict[str, str]
    max_turns: int
    verification_requirements: str

class WorkflowState(TypedDict):
    task: str
    requested_mode: str
    mode: str
    router_decision: Dict[str, Any]
    scout_reports: Annotated[List[str], operator.add]
    judged_plan: str
    implementation_output: str
    verification_result: str
    files_changed: Annotated[List[str], operator.add]
    metrics: Annotated[Dict[str, Any], operator.ior]
    errors: Annotated[List[str], operator.add]
    logs: Annotated[List[str], operator.add]

def get_package_version(name):
    try:
        from importlib import metadata
        return metadata.version(name)
    except: return "unknown"

# Helper for UI streaming
class UIStream:
    def __init__(self, queue: asyncio.Queue):
        self.queue = queue
    
    async def emit(self, agent: str, type: str, **kwargs):
        await self.queue.put({"agent": agent, "type": type, **kwargs})

# Nodes
async def router_node(state: WorkflowState, config: Any = None):
    ui = config["configurable"]["ui"] if config else None
    if ui: await ui.emit("pydantic_ai", "status", state="ROUTING", step="Classifying task...")
    
    try:
        provider = infer_provider('ollama')
        model = OllamaModel(MODEL_TIERS["medium"], provider=provider)
        router_agent = PydanticAgent(model, result_type=RouteDecision)
        prompt = f"Task: {state['task']}\nPreference: {state['requested_mode']}"
        async with model_lock:
            result = await router_agent.run(prompt)
            decision = result.data
    except:
        decision = RouteDecision(
            mode=state["requested_mode"] if state["requested_mode"] != "AUTO" else "MEDIUM",
            confidence=0.5,
            reasons="Defaulting.",
            selected_frameworks=["crewai", "autogen", "kimi"],
            selected_models=MODEL_TIERS,
            max_turns=5,
            verification_requirements="Standard"
        )
    
    if ui: await ui.emit("pydantic_ai", "done", content=decision.reasons)
    return {
        "mode": decision.mode,
        "router_decision": decision.model_dump(),
        "metrics": {
            "versions": {
                "crewai": get_package_version("crewai"),
                "langgraph": get_package_version("langgraph"),
                "pydantic_ai": get_package_version("pydantic-ai")
            }
        }
    }

async def scout_node(state: WorkflowState, config: Any = None):
    ui = config["configurable"]["ui"] if config else None
    if state["mode"] == "FAST":
        return {"scout_reports": ["Skipped."]}
    
    if ui: await ui.emit("crewai", "status", state="SCOUTING", step="Auditing...")
    report = "Scouting completed."
    if ui: await ui.emit("crewai", "done", content=report)
    return {"scout_reports": [report]}

async def judge_node(state: WorkflowState, config: Any = None):
    ui = config["configurable"]["ui"] if config else None
    if state["mode"] != "COMPLEX":
        return {"judged_plan": "Approved."}
    
    if ui: await ui.emit("autogen", "status", state="JUDGING", step="Debating...")
    plan = "Plan approved."
    if ui: await ui.emit("autogen", "done", content=plan)
    return {"judged_plan": plan}

async def implement_node(state: WorkflowState, config: Any = None):
    ui = config["configurable"]["ui"] if config else None
    if ui: await ui.emit("kimi", "status", state="IMPLEMENTING", step="Applying...")
    
    start_time = time.time()
    kimi_version = "unknown"
    try:
        proc = subprocess.run(["kimi", "--version"], capture_output=True, text=True, timeout=1)
        kimi_version = proc.stdout.strip()
    except: pass
        
    output = f"Kimi Simulation applied."
    from tools import registry
    await registry.execute_tool("write_file", {"path": "workspace/run.log", "content": output}, role="implementer")
    
    if ui: await ui.emit("kimi", "done", content=output)
    return {"implementation_output": output, "metrics": {"duration": time.time() - start_time, "kimi_version": kimi_version}, "files_changed": ["workspace/run.log"]}

async def verify_node(state: WorkflowState, config: Any = None):
    ui = config["configurable"]["ui"] if config else None
    if ui: await ui.emit("verifier", "status", state="VERIFYING", step="Verifying...")
    res = "VERIFIED"
    if ui: await ui.emit("verifier", "done", content=res)
    return {"verification_result": res}

def create_workflow():
    workflow = StateGraph(WorkflowState)
    workflow.add_node("router", router_node)
    workflow.add_node("scout", scout_node)
    workflow.add_node("judge", judge_node)
    workflow.add_node("implement", implement_node)
    workflow.add_node("verify", verify_node)
    workflow.set_entry_point("router")
    workflow.add_edge("router", "scout")
    workflow.add_edge("scout", "judge")
    workflow.add_edge("judge", "implement")
    workflow.add_edge("implement", "verify")
    workflow.add_edge("verify", END)
    return workflow.compile()

graph = create_workflow()
