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
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
import httpx
from json_repair import repair_json
from tools import registry

# Windows Specific: Fix for async subprocesses
if os.name == 'nt':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global state for managing isolated workflows
# workflow_id -> { "tasks": Set[asyncio.Task], "interrupts": List[str], "model_lock": asyncio.Lock }
workflows = {}

app = FastAPI()

# Restrict CORS for demo laboratory safety
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:7878", "http://127.0.0.1:7878"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.mount("/workspace", StaticFiles(directory="workspace"), name="workspace")

class Message(BaseModel):
    role: str
    content: str

class PromptRequest(BaseModel):
    prompt: str
    model: str
    mode: str = "medium"
    history: List[Message] = []
    workflow_id: Optional[str] = None

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

@app.get("/api/workspace")
async def list_workspace():
    try:
        files = []
        for root, _, filenames in os.walk("workspace"):
            for f in filenames:
                rel_path = os.path.relpath(os.path.join(root, f), "workspace")
                files.append(rel_path.replace("\\", "/"))
        return {"files": files}
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/stop")
async def stop_workflow(req: Dict[str, str]):
    workflow_id = req.get("workflow_id")
    if workflow_id in workflows:
        for task in workflows[workflow_id]["tasks"]:
            task.cancel()
        return {"status": f"Stopping workflow {workflow_id}..."}
    return {"error": "Workflow not found"}

@app.post("/api/interrupt")
async def interrupt_workflow(req: Dict[str, Any]):
    workflow_id = req.get("workflow_id")
    content = req.get("content")
    if workflow_id in workflows:
        workflows[workflow_id]["interrupts"].append(content)
        return {"status": "Interruption received"}
    return {"error": "Workflow not found"}

@app.get("/api/run")
async def run_file(path: str):
    # This endpoint remains for the manual "Run" button in UI
    # It uses 'system' role for full access as it is user-triggered
    try:
        result = await registry.execute_tool("execute_command", {"command": f"python {path}"}, role="system")
        return json.loads(result) if isinstance(result, str) and result.startswith("{") else {"output": result}
    except Exception as e:
        return {"error": str(e)}

async def run_agent_step(agent_key: str, role: str, prompt: str, model: str, context: str, workflow_id: str):
    start_time = time.perf_counter()
    full_text = ""
    token_count = 0

    yield f"data: {json.dumps({'agent': agent_key, 'type': 'status', 'state': agent_key.upper(), 'mode': 'THINKING', 'step': f'Consulting {model}...'})}\n\n"

    system_instr = f"""You are a {role}. Operating in a Windows laboratory.
Tools: list_files, read_file, search_workspace, get_file_info, get_system_time.
WORKSPACE: 'workspace/'. Paths are relative.
Follow instructions exactly. Output your findings clearly.
To use tools, output:
```tool
{{"tool": "name", "args": {{"arg": "val"}}}}
```
"""
    if role == "implementer":
        system_instr += "Mutation Tools ENABLED: write_file, make_directory, execute_command (allowlisted only).\n"

    timeout = httpx.Timeout(300.0, connect=10.0)

    for turn in range(5):
        # Check for isolated workflow interrupts
        if workflows[workflow_id]["interrupts"]:
            nudge = workflows[workflow_id]["interrupts"].pop(0)
            nudge_msg = f"\n\n[USER NUDGE]: {nudge}\n\n"
            full_text += nudge_msg
            yield f"data: {json.dumps({'agent': agent_key, 'type': 'token', 'chunk': nudge_msg, 'mode': 'SYSTEM'})}\n\n"

        turn_text = ""
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            async with client.stream("POST", f"{OLLAMA_BASE_URL}/api/generate", json={
                "model": model,
                "prompt": f"System: {system_instr}\nContext: {context}\nHistory: {full_text}\nTask: {prompt}",
                "stream": True
            }) as response:
                async for line in response.aiter_lines():
                    if not line: continue
                    try:
                        data = json.loads(line)
                        chunk = data.get("response", "")
                        turn_text += chunk
                        full_text += chunk
                        token_count += 1
                        yield f"data: {json.dumps({'agent': agent_key, 'type': 'token', 'chunk': chunk, 'elapsed': round(time.perf_counter() - start_time, 1), 'tokens': token_count, 'mode': 'THINKING'})}\n\n"
                        if data.get("done", False): break
                    except: continue

        match = re.search(r"```tool\s*(.*?)\s*```", turn_text, re.DOTALL)
        if not match: match = re.search(r'\{"tool":\s*".*?"\}', turn_text, re.DOTALL)

        if match:
            try:
                json_str = match.group(1) if "```" in turn_text else match.group(0)
                repaired_json = repair_json(json_str)
                call = json.loads(repaired_json)
                t_name, t_args = call.get("tool"), call.get("args", {})
                
                yield f"data: {json.dumps({'agent': agent_key, 'type': 'status', 'state': agent_key.upper(), 'mode': 'EXECUTING', 'step': f'Tool: {t_name}'})}\n\n"
                
                # Execute with role-based restriction
                result = await registry.execute_tool(t_name, t_args, role=role)
                feedback = f"\n\n[TOOL RESULT]: {result}\n\n"
                full_text += feedback
                yield f"data: {json.dumps({'agent': agent_key, 'type': 'token', 'chunk': feedback, 'mode': 'SYSTEM'})}\n\n"
            except Exception as e:
                full_text += f"\n\n[TOOL ERROR]: {str(e)}\n"
        else: break

    yield f"data: {json.dumps({'agent': agent_key, 'type': 'done', 'metrics': {'latency': round(time.perf_counter() - start_time, 2), 'tokens': token_count}, 'content': full_text})}\n\n"

async def unload_all_models():
    # Only unload if no other workflows are active to prevent inter-workflow disruption
    if len(workflows) > 1: return
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            ps = await client.get(f"{OLLAMA_BASE_URL}/api/ps")
            for m in ps.json().get("models", []):
                await client.post(f"{OLLAMA_BASE_URL}/api/generate", json={"model": m['name'], "keep_alive": 0})
            await asyncio.sleep(2)
    except: pass

def get_specialist_model(phase, fallback_model, available_models, mode="medium"):
    names = [m['name'] for m in available_models]
    if mode == "fast":
        routing = {"SCOUT": ["qwen2.5:14b"], "JUDGE": ["qwen2.5:14b"], "IMPLEMENT": ["qwen2.5:14b"], "VERIFY": ["qwen2.5:14b"]}
    elif mode == "complex":
        routing = {"SCOUT": ["gemma4:26b"], "JUDGE": ["gemma4:26b"], "IMPLEMENT": ["gemma4:26b"], "VERIFY": ["hf.co/unsloth/DeepSeek-R1-Distill-Qwen-32B-GGUF:DeepSeek-R1-Distill-Qwen-32B-Q4_K_M.gguf"]}
    else:
        routing = {"SCOUT": ["qwen2.5:14b"], "JUDGE": ["gemma4:26b"], "IMPLEMENT": ["qwen2.5:14b"], "VERIFY": ["gemma4:26b"]}
    for target in routing.get(phase, []):
        if target in names: return target
    return fallback_model

@app.post("/api/stream-all")
async def stream_orchestration(req: PromptRequest):
    workflow_id = req.workflow_id or str(time.time())
    workflows[workflow_id] = {"tasks": set(), "interrupts": [], "lock": asyncio.Lock()}
    
    async def orchestration_loop():
        from workflow import graph, UIStream
        queue = asyncio.Queue()
        ui = UIStream(queue)
        
        try:
            workflows[workflow_id]["tasks"].add(asyncio.current_task())
            
            # Initial state
            state = {
                "task": req.prompt,
                "requested_mode": req.mode.upper(),
                "mode": "MEDIUM",
                "router_decision": {},
                "scout_reports": [],
                "judged_plan": "",
                "implementation_output": "",
                "verification_result": "",
                "files_changed": [],
                "metrics": {},
                "errors": [],
                "logs": [],
                "messages": []
            }
            
            # Run graph in background
            graph_task = asyncio.create_task(graph.ainvoke(state, config={"configurable": {"ui": ui}}))
            
            # Helper for UI event: hydration
            yield f"data: {json.dumps({'agent': 'system', 'type': 'status', 'state': 'HYDRATION', 'mode': 'CLEANING', 'step': 'Initializing Adaptive Pipeline...'})}\n\n"

            while not graph_task.done() or not queue.empty():
                try:
                    # Drain queue
                    item = await asyncio.wait_for(queue.get(), timeout=0.05)
                    yield f"data: {json.dumps(item)}\n\n"
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"Stream error: {e}")
                    break
            
            final_result = await graph_task
            
            # Save run state to workspace
            run_id = f"run_{int(time.time())}"
            run_data = {
                "run_id": run_id,
                "state": final_result,
                "timestamp": time.ctime()
            }
            from tools import registry
            await registry.execute_tool("write_file", {"path": f"runs/{run_id}.json", "content": json.dumps(run_data, indent=2)}, role="system")

            yield f"data: {json.dumps({'agent': 'system', 'type': 'status', 'state': 'FINISHED', 'mode': 'DONE', 'step': f'Pipeline Complete. Run ID: {run_id}'})}\n\n"
            
        except Exception as e:
            logger.exception("Orchestration failed")
            yield f"data: {json.dumps({'agent': 'system', 'type': 'status', 'state': 'ERROR', 'mode': 'FAILED', 'step': str(e)})}\n\n"
        finally:
            if workflow_id in workflows:
                del workflows[workflow_id]

    return StreamingResponse(orchestration_loop(), media_type="text/event-stream")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7878)
