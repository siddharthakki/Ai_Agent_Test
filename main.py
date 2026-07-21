import asyncio
import json
import time
import os
import subprocess
import logging
import re
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from typing import List, Optional
from pydantic import BaseModel
import httpx
from tools import registry

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global state for task cancellation and live interrupts
active_tasks = {}
interrupt_queue = {} # Store live nudges from user

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount workspace for live previews
app.mount("/workspace", StaticFiles(directory="workspace"), name="workspace")

class Message(BaseModel):
    role: str
    content: str

class PromptRequest(BaseModel):
    prompt: str
    model: str
    mode: str = "medium"
    history: List[Message] = []

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

@app.get("/")
async def serve_index():
    return FileResponse("index.html")

@app.get("/api/models")
async def get_models():
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            res = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            return res.json()
    except Exception as e:
        return {"models": [], "error": str(e)}

@app.post("/api/stop")
async def stop_workflow():
    """Cancels all currently running workflows."""
    for task_id in list(active_tasks.keys()):
        active_tasks[task_id].cancel()
    return {"status": "Stopping..."}

@app.post("/api/interrupt")
async def interrupt_workflow(msg: Message):
    """Injects a live nudge into the running agent's context."""
    # We apply this to all active tasks for simplicity
    for task_id in active_tasks:
        if task_id not in interrupt_queue:
            interrupt_queue[task_id] = []
        interrupt_queue[task_id].append(msg.content)
    return {"status": "Interruption received"}

@app.get("/api/workspace")
async def list_workspace():
    """Returns a list of all files in the workspace."""
    try:
        files = []
        for root, _, filenames in os.walk("workspace"):
            for f in filenames:
                rel_path = os.path.relpath(os.path.join(root, f), "workspace")
                files.append(rel_path.replace("\\", "/"))
        return {"files": files}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/run")
async def run_file(path: str):
    """Runs a python file from the workspace and returns output."""
    try:
        full_path = registry._resolve_path(path)
        if not os.path.exists(full_path):
            return {"error": "File not found"}

        # Determine the command based on extension
        if path.endswith(".py"):
            cmd = [os.path.join(os.getcwd(), "venv", "Scripts", "python.exe"), full_path]
        else:
            return {"error": "Only .py files can be executed via this endpoint"}

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=os.path.dirname(full_path))
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {"error": "Execution timed out (30s)"}
    except Exception as e:
        return {"error": str(e)}

async def run_agent_step(agent_key: str, phase: str, prompt: str, model: str, context: str = "", task_id: str = "default"):
    """Runs an agent with Tool Execution loop and granular monitoring."""
    start_time = time.perf_counter()
    full_text = ""
    token_count = 0
    current_mode = "THINKING"

    yield f"data: {json.dumps({'agent': agent_key, 'type': 'status', 'state': phase, 'mode': current_mode, 'step': f'Running on {model}...'})}\n\n"

    system_instr = """You are a Senior Engineer. To interact with tools, output:
```tool
{"tool": "name", "args": {"arg_name": "value"}}
```
Available tools and their exact argument names:
- get_system_time: {}
- list_files: {"path": "."}
- read_file: {"path": "filename"}
- write_file: {"path": "filename", "content": "text"}
- execute_command: {"command": "dir"}
- search_workspace: {"query": "text"}
- make_directory: {"path": "dir_name"}
- delete_item: {"path": "name"}
- get_file_info: {"path": "name"}
- fetch_url: {"url": "http..."}
- pip_install: {"package": "name"}
- web_search: {"query": "text"}
- read_pdf: {"path": "file.pdf"}
- image_transform: {"path": "img.png", "action": "grayscale"}
- check_resources: {}
- comfyui_generate: {"prompt": "text"}
- vision_analyze: {"image_path": "img.png", "query": "text"}

IMPORTANT: Use 'path' as the argument for directories, NOT 'directory_path'.
STRICT RULE: Follow the user's numbered steps EXACTLY. Do not over-engineer or add extra file structures unless requested. If the user asks for 'hello.py', create 'hello.py' in the root project folder.
WINDOWS ENVIRONMENT: You are on Windows. Use 'dir' instead of 'ls', 'type' instead of 'cat', etc. Always use 'path' as the argument name.
"""

    timeout = httpx.Timeout(300.0, connect=10.0)

    for turn in range(10):
        # Check for Live Interrupts (Nudges)
        if task_id in interrupt_queue and interrupt_queue[task_id]:
            nudge = interrupt_queue[task_id].pop(0)
            nudge_msg = f"\n\n[USER INTERRUPTION/CORRECTION]: {nudge}\n\n"
            full_text += nudge_msg
            yield f"data: {json.dumps({'agent': agent_key, 'type': 'token', 'chunk': nudge_msg, 'elapsed': round(time.perf_counter() - start_time, 1), 'tokens': token_count, 'mode': 'SYSTEM'})}\n\n"

        turn_text = ""
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            async with client.stream("POST", f"{OLLAMA_BASE_URL}/api/generate", json={
                "model": model,
                "prompt": f"System: {system_instr}\nContext: {context}\nHistory: {full_text}\nTask: {prompt}",
                "stream": True
            }) as response:
                async for line in response.aiter_lines():
                    if not line: continue
                    try: data = json.loads(line)
                    except: continue

                    chunk = data.get("response", "")
                    turn_text += chunk
                    full_text += chunk
                    token_count += 1

                    mode = "IMPLEMENTING" if "```" in turn_text else "THINKING"
                    yield f"data: {json.dumps({'agent': agent_key, 'type': 'token', 'chunk': chunk, 'elapsed': round(time.perf_counter() - start_time, 1), 'tokens': token_count, 'mode': mode})}\n\n"
                    if data.get("done", False): break

        match = re.search(r"```tool\s*(.*?)\s*```", turn_text, re.DOTALL)
        if match:
            try:
                call = json.loads(match.group(1).strip())
                t_name, t_args = call.get("tool"), call.get("args", {})
                yield f"data: {json.dumps({'agent': agent_key, 'type': 'status', 'state': phase, 'mode': 'EXECUTING', 'step': f'Tool: {t_name}'})}\n\n"
                result = await registry.execute_tool(t_name, t_args)
                feedback = f"\n\n[TOOL RESULT]: {result}\n\n"
                full_text += feedback
                yield f"data: {json.dumps({'agent': agent_key, 'type': 'token', 'chunk': feedback, 'elapsed': round(time.perf_counter() - start_time, 1), 'tokens': token_count, 'mode': 'SYSTEM'})}\n\n"
            except Exception as e:
                full_text += f"\n\n[TOOL ERROR]: {str(e)}\n\n"
        else: break

    yield f"data: {json.dumps({'agent': agent_key, 'type': 'done', 'metrics': {'latency': round(time.perf_counter() - start_time, 2), 'tokens': token_count}, 'content': full_text})}\n\n"

async def unload_all_models():
    """Nuclear VRAM Flush: Forces Ollama to drop all models from GPU."""
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            ps = await client.get(f"{OLLAMA_BASE_URL}/api/ps")
            for m in ps.json().get("models", []):
                await client.post(f"{OLLAMA_BASE_URL}/api/generate", json={"model": m['name'], "keep_alive": 0})
            await asyncio.sleep(2) # Increased for Windows VRAM clearing stability
    except: pass

def get_specialist_model(phase, fallback_model, available_models, mode="medium"):
    names = [m['name'] for m in available_models]

    # Mode-based routing
    if mode == "fast":
        routing = {
            "RESEARCH": ["qwen2.5:14b", "gemma4:12b"],
            "DESIGN": ["qwen2.5:14b"],
            "IMPLEMENT": ["qwen2.5:14b"],
            "VERIFY": ["qwen2.5:14b"]
        }
    elif mode == "complex":
        routing = {
            "RESEARCH": ["gemma4:26b", "qwen2.5:14b"],
            "DESIGN": ["gemma4:26b", "qwen3.6:27b"],
            "IMPLEMENT": ["gemma4:26b", "qwen3.6:27b"],
            "VERIFY": [
                "hf.co/unsloth/DeepSeek-R1-Distill-Qwen-32B-GGUF:DeepSeek-R1-Distill-Qwen-32B-Q4_K_M.gguf",
                "deepseek-r1:32b"
            ]
        }
    else: # medium
        routing = {
            "RESEARCH": ["qwen2.5:14b", "gemma4:12b"],
            "DESIGN": ["gemma4:26b", "qwen2.5:14b"],
            "IMPLEMENT": ["qwen2.5:14b", "gemma4:26b"],
            "VERIFY": ["gemma4:26b", "qwen2.5:14b"]
        }

    for target in routing.get(phase, []):
        if target in names: return target
    return fallback_model

@app.post("/api/stream-all")
async def stream_orchestration(req: PromptRequest):
    task_id = str(time.time())

    async def orchestration_loop():
        try:
            # Register task for cancellation
            active_tasks[task_id] = asyncio.current_task()

            # Seed context with history
            history_text = "\n".join([f"{m.role.upper()}: {m.content}" for m in req.history])
            current_context = f"Conversation History:\n{history_text}\n\nNew User Request: {req.prompt}"

            # Ensure VRAM is clear before starting any workflow
            yield f"data: {json.dumps({'agent': 'system', 'type': 'status', 'state': 'HYDRATION', 'mode': 'CLEANING', 'step': 'Clearing VRAM for fresh run...'})}\n\n"
            await unload_all_models()

            try:
                async with httpx.AsyncClient(follow_redirects=True) as client:
                    res = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
                    available_models = res.json().get("models", [])
            except: available_models = []

            # Use current_context (which has history) as the starting point
            phases = [
                ("crewai", "RESEARCH", "Analyze the user request and identify the specific requirements and necessary steps."),
                ("langgraph", "DESIGN", "Create a detailed technical plan, including file structure and logic for each file."),
                ("kimi", "IMPLEMENT", "Write the actual code. Use 'write_file' for EVERY file needed. Do NOT just plan; create the files on disk."),
                ("autogen", "VERIFY", "Audit the work. Use 'list_files' and 'read_file' to confirm everything was created correctly and works.")
            ]

            for agent_id, phase, task in phases:
                model = get_specialist_model(phase, req.model, available_models, req.mode)
                yield f"data: {json.dumps({'agent': 'system', 'type': 'status', 'state': phase, 'mode': 'ROUTING', 'step': f'Loading {model} ({req.mode.upper()} mode)'})}\n\n"

                # Context Optimization: Only pass the essential history to avoid token bloat
                async for event in run_agent_step(agent_id, phase, task, model, current_context, task_id):
                    yield event
                    if '"type": "done"' in event:
                        data = json.loads(event.replace("data: ", ""))
                        # Summarize findings into the next context
                        summary = data.get("content", "")
                        if len(summary) > 2000:
                            summary = summary[:1000] + "\n... [truncated] ...\n" + summary[-1000:]
                        current_context += f"\n\n### PHASE {phase} RESULT:\n{summary}"

                # Unload after each major phase to keep VRAM clean
                await unload_all_models()

            yield f"data: {json.dumps({'agent': 'system', 'type': 'status', 'state': 'FINISHED', 'mode': 'DONE', 'step': 'Autonomous Engineering Completed.'})}\n\n"
        except asyncio.CancelledError:
            yield f"data: {json.dumps({'agent': 'system', 'type': 'status', 'state': 'STOPPED', 'mode': 'CANCELLED', 'step': 'Workflow was manually stopped.'})}\n\n"
        except Exception as e:
            error_msg = f"System Error: {str(e)}"
            yield f"data: {json.dumps({'agent': 'system', 'type': 'status', 'state': 'ERROR', 'mode': 'FAILED', 'step': error_msg})}\n\n"
            yield f"data: {json.dumps({'agent': 'system', 'type': 'token', 'chunk': f'\\n\\n[CRITICAL ERROR]: {str(e)}\\n', 'elapsed': 0, 'tokens': 0, 'mode': 'SYSTEM'})}\n\n"
        finally:
            if task_id in active_tasks:
                del active_tasks[task_id]

    return StreamingResponse(orchestration_loop(), media_type="text/event-stream")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7878)
