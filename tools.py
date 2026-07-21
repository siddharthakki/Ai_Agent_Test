import json
import os
import subprocess
import httpx
import shutil
import asyncio
import base64
import psutil
from datetime import datetime
from typing import List, Dict, Any
from PIL import Image

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_WORKSPACE = os.path.join(SCRIPT_DIR, "workspace")
os.makedirs(BASE_WORKSPACE, exist_ok=True)
COMFYUI_URL = "http://127.0.0.1:8188"

class ToolRegistry:
    def __init__(self):
        self.tools = {
            "get_system_time": self._get_system_time,
            "list_files": self._list_files,
            "read_file": self._read_file,
            "write_file": self._write_file,
            "execute_command": self._execute_command,
            "search_workspace": self._search_workspace,
            "make_directory": self._make_directory,
            "delete_item": self._delete_item,
            "get_file_info": self._get_file_info,
            "fetch_url": self._fetch_url,
            "pip_install": self._pip_install,
            "web_search": self._web_search,
            "read_pdf": self._read_pdf,
            "image_transform": self._image_transform,
            "check_resources": self._check_resources,
            "comfyui_generate": self._comfyui_generate,
            "vision_analyze": self._vision_analyze
        }

    def _get_free_vram(self) -> int:
        try:
            res = subprocess.check_output(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,nounits,noheader"]).decode().strip()
            return int(res)
        except: return 0

    async def _fetch_url(self, url: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                res = await client.get(url)
                return res.text[:5000]
        except Exception as e:
            return f"Network Error: {e}"

    async def _comfyui_generate(self, prompt: str, filename: str = "gen_image.png") -> str:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                queue_res = await client.get(f"{COMFYUI_URL}/queue")
                q = queue_res.json()
                if len(q.get("queue_running", [])) > 0 or len(q.get("queue_pending", [])) > 0:
                    return "ERROR: ComfyUI busy."
                if self._get_free_vram() < 4000:
                    return "ERROR: Low VRAM."
                workflow = {
                    "prompt": {
                        "3": {"inputs": {"text": prompt}, "class_type": "CLIPTextEncode"},
                        "5": {"inputs": {"width": 1024, "height": 1024, "batch_size": 1}, "class_type": "EmptyLatentImage"},
                        "6": {"inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}, "class_type": "CheckpointLoaderSimple"}
                    }
                }
                await client.post(f"{COMFYUI_URL}/prompt", json=workflow)
                return f"SUCCESS: Sent to ComfyUI."
        except Exception as e: return f"ComfyUI Error: {e}"

    async def _vision_analyze(self, image_path: str, query: str = "Analyze", model: str = "llava") -> str:
        try:
            full_path = self._resolve_path(image_path)
            with open(full_path, "rb") as f:
                img_str = base64.b64encode(f.read()).decode("utf-8")
            async with httpx.AsyncClient(timeout=120.0) as client:
                res = await client.post("http://localhost:11434/api/generate", json={
                    "model": model, "prompt": query, "images": [img_str], "stream": False
                })
                return res.json().get("response", "")
        except Exception as e: return str(e)

    def _check_resources(self) -> str:
        return json.dumps({"cpu": f"{psutil.cpu_percent()}%", "vram": f"{self._get_free_vram()}MB"})

    def _resolve_path(self, path: str) -> str:
        if not path: return BASE_WORKSPACE
        # Ensure path is always a string and normalized
        safe_path = os.path.normpath(str(path)).lstrip(os.sep).lstrip("..").lstrip(".")
        return os.path.join(BASE_WORKSPACE, safe_path)

    async def _web_search(self, query: str) -> str:
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                url = f"https://duckduckgo.com/html/?q={query}"
                res = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                # Basic HTML stripping to save context tokens
                import re
                text = re.sub(r'<[^>]+>', '', res.text)
                text = " ".join(text.split())
                return text[:2000]
        except Exception as e: return f"Search failed: {e}"

    def _read_pdf(self, path: str) -> str:
        try:
            import fitz
            doc = fitz.open(self._resolve_path(path))
            return "".join([p.get_text() for p in doc])[:5000]
        except Exception as e: return str(e)

    def _image_transform(self, path: str, action: str) -> str:
        try:
            full_path = self._resolve_path(path)
            with Image.open(full_path) as img:
                if action == "grayscale": img = img.convert("L")
                img.save(full_path.replace(".", "_mod."))
                return "Saved."
        except Exception as e: return str(e)

    def _pip_install(self, package: str) -> str:
        try:
            subprocess.run([os.path.join(os.getcwd(), "venv", "Scripts", "pip.exe"), "install", package], check=True)
            return "Installed."
        except Exception as e: return str(e)

    def _read_file(self, path: str) -> str:
        try:
            with open(self._resolve_path(path), 'r', encoding='utf-8') as f: return f.read()
        except Exception as e: return str(e)

    def _write_file(self, path: str, content: str) -> str:
        try:
            full_path = self._resolve_path(path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, 'w', encoding='utf-8') as f: f.write(content)
            return f"Wrote {path}"
        except Exception as e: return str(e)

    def _delete_item(self, path: str) -> str:
        try:
            full_path = self._resolve_path(path)
            if os.path.isdir(full_path): shutil.rmtree(full_path)
            else: os.remove(full_path)
            return "Deleted."
        except Exception as e: return str(e)

    def _get_file_info(self, path: str) -> str:
        try:
            stat = os.stat(self._resolve_path(path))
            return json.dumps({"size": stat.st_size})
        except Exception as e: return str(e)

    def _execute_command(self, command: str) -> str:
        try:
            # Security: Basic check to prevent escaping workspace context
            if ".." in command:
                return "Error: Command cannot escape workspace directory."

            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=60, cwd=BASE_WORKSPACE)
            return f"EXIT_CODE: {result.returncode}\nOUT: {result.stdout}\nERR: {result.stderr}"
        except Exception as e: return str(e)

    def _make_directory(self, path: str) -> str:
        try:
            os.makedirs(self._resolve_path(path), exist_ok=True)
            return "Created."
        except Exception as e: return str(e)

    def _search_workspace(self, query: str) -> str:
        res = []
        for root, _, files in os.walk(BASE_WORKSPACE):
            for f in files:
                if query in f: res.append(os.path.relpath(os.path.join(root, f), BASE_WORKSPACE))
        return json.dumps(res)

    def _get_system_time(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

    def _list_files(self, path: str = ".") -> List[str]:
        try: return os.listdir(self._resolve_path(path))
        except: return []

    async def execute_tool(self, tool_name: str, args: Dict[str, Any] = None) -> str:
        if args is None: args = {}
        if tool_name in self.tools:
            try:
                import inspect
                func = self.tools[tool_name]

                # Dynamic Type Casting for AI "Fuzziness"
                sig = inspect.signature(func)
                bound_args = {}
                for param_name, param in sig.parameters.items():
                    if param_name in args:
                        val = args[param_name]
                        # Cast to expected type if necessary
                        if param.annotation == str:
                            bound_args[param_name] = str(val)
                        elif param.annotation == int:
                            try: bound_args[param_name] = int(val)
                            except: bound_args[param_name] = val
                        else:
                            bound_args[param_name] = val
                    elif param.default is not inspect.Parameter.empty:
                        bound_args[param_name] = param.default

                if inspect.iscoroutinefunction(func):
                    return await func(**bound_args)
                return func(**bound_args)
            except Exception as e:
                return f"SYSTEM_ERROR: Tool '{tool_name}' failed: {str(e)}"
        return f"SYSTEM_ERROR: Tool '{tool_name}' not found"

registry = ToolRegistry()
