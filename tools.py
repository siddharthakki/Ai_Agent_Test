import json
import os
import subprocess
import httpx
import shutil
import asyncio
import base64
import psutil
from datetime import datetime
from typing import List, Dict, Any, Union
from PIL import Image
from pathlib import Path

# Authoritative resolved path for the workspace
SCRIPT_DIR = Path(__file__).parent.resolve()
BASE_WORKSPACE = (SCRIPT_DIR / "workspace").resolve()
BASE_WORKSPACE.mkdir(exist_ok=True)

COMFYUI_URL = "http://127.0.0.1:8188"

class ToolRegistry:
    def __init__(self):
        # Master list of all available functions
        self._all_tools = {
            "get_system_time": self._get_system_time,
            "list_files": self._list_files,
            "read_file": self._read_file,
            "write_file": self._write_file,
            "execute_command": self._execute_command,
            "search_workspace": self._search_workspace,
            "make_directory": self._make_directory,
            "get_file_info": self._get_file_info,
            "fetch_url": self._fetch_url,
            "web_search": self._web_search,
            "read_pdf": self._read_pdf,
            "image_transform": self._image_transform,
            "check_resources": self._check_resources,
            "comfyui_generate": self._comfyui_generate,
            "vision_analyze": self._vision_analyze
        }
        
        # Role-based tool access definitions
        self.role_permissions = {
            "scout": ["read_file", "list_files", "search_workspace", "get_file_info", "get_system_time", "check_resources"],
            "judge": ["get_system_time"], 
            "implementer": ["write_file", "make_directory", "execute_command", "read_file", "list_files", "get_system_time"],
            "verifier": ["read_file", "list_files", "execute_command", "get_system_time"],
            "system": ["get_system_time", "list_files", "read_file", "write_file", "execute_command", "search_workspace", "make_directory", "get_file_info", "fetch_url", "web_search", "read_pdf", "image_transform", "check_resources", "comfyui_generate", "vision_analyze"]
        }

    def _resolve_path(self, path_str: str) -> Path:
        if not path_str: return BASE_WORKSPACE
        
        p = Path(path_str)
        if p.is_absolute():
            raise PermissionError("Absolute paths are forbidden.")
            
        try:
            full_path = (BASE_WORKSPACE / p).resolve()
        except Exception:
            raise PermissionError("Invalid path components.")

        if not full_path.is_relative_to(BASE_WORKSPACE):
            raise PermissionError("Access Denied: Path escape detected.")
            
        return full_path

    async def _fetch_url(self, url: str) -> str:
        return "SYSTEM_ERROR: fetch_url is restricted in this environment."

    async def _web_search(self, query: str) -> str:
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                url = f"https://duckduckgo.com/html/?q={query}"
                res = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                import re
                text = re.sub(r'<[^>]+>', '', res.text)
                text = " ".join(text.split())
                return text[:2000]
        except Exception as e: return f"Search failed: {e}"

    def _get_free_vram(self) -> int:
        try:
            res = subprocess.check_output(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,nounits,noheader"]).decode().strip()
            return int(res)
        except: return 0

    async def _comfyui_generate(self, prompt: str) -> str:
        return "SYSTEM_ERROR: ComfyUI generate is disabled in this hardened branch."

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
                save_path = full_path.parent / (full_path.stem + "_mod" + full_path.suffix)
                img.save(save_path)
                return f"Saved to {save_path.name}"
        except Exception as e: return str(e)

    async def _read_file(self, path: str) -> str:
        try:
            p = self._resolve_path(path)
            if not p.is_file(): return "SYSTEM_ERROR: File not found."
            return p.read_text(encoding='utf-8')
        except Exception as e: return str(e)

    async def _write_file(self, path: str, content: str) -> str:
        try:
            full_path = self._resolve_path(path)
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding='utf-8')
            return f"Wrote {path}"
        except Exception as e: return str(e)

    async def _make_directory(self, path: str) -> str:
        try:
            self._resolve_path(path).mkdir(parents=True, exist_ok=True)
            return f"Created directory: {path}"
        except Exception as e: return f"SYSTEM_ERROR: {str(e)}"

    async def _execute_command(self, command: str) -> Union[str, Dict[str, Any]]:
        allowed_executables = {
            "python": [os.path.join(os.getcwd(), "venv", "Scripts", "python.exe")],
            "dir": ["cmd.exe", "/c", "dir"],
            "echo": ["cmd.exe", "/c", "echo"],
            "type": ["cmd.exe", "/c", "type"]
        }
        
        try:
            import shlex
            args = shlex.split(command)
            if not args: return "SYSTEM_ERROR: Empty command"
            
            executable_key = args[0].lower()
            if executable_key not in allowed_executables:
                return f"SYSTEM_ERROR: Command '{executable_key}' is not in the allowlist."

            base_cmd = allowed_executables[executable_key]
            final_args = base_cmd + args[1:]
            
            danger_chars = [";", "&", "|", ">", "<", "`", "$", "(", ")"]
            if any(c in command for c in danger_chars):
                 return "SYSTEM_ERROR: Shell metacharacters are forbidden."

            proc = await asyncio.create_subprocess_exec(
                *final_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(BASE_WORKSPACE)
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
                return {
                    "stdout": stdout.decode(),
                    "stderr": stderr.decode(),
                    "exit_code": proc.returncode
                }
            except asyncio.TimeoutError:
                proc.kill()
                return "SYSTEM_ERROR: Execution timed out (30s)"
        except Exception as e:
            return f"SYSTEM_ERROR: {str(e)}"

    def _get_file_info(self, path: str) -> str:
        try:
            stat = self._resolve_path(path).stat()
            return json.dumps({"size": stat.st_size, "modified": stat.st_mtime})
        except Exception as e: return str(e)

    def _search_workspace(self, query: str) -> str:
        res = []
        for p in BASE_WORKSPACE.rglob("*"):
            if p.is_file() and query in p.name:
                res.append(str(p.relative_to(BASE_WORKSPACE)))
        return json.dumps(res)

    def _get_system_time(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

    def _list_files(self, path: str = ".") -> List[str]:
        try:
            root = self._resolve_path(path)
            return [str(p.name) for p in root.iterdir()]
        except: return []

    async def execute_tool(self, tool_name: str, args: Dict[str, Any], role: str = "scout") -> str:
        if args is None: args = {}
        
        allowed_tools = self.role_permissions.get(role, [])
        if tool_name not in allowed_tools:
            return f"SYSTEM_ERROR: Role '{role}' does not have permission to use tool '{tool_name}'."
            
        if tool_name in self._all_tools:
            try:
                import inspect
                func = self._all_tools[tool_name]
                
                sig = inspect.signature(func)
                bound_args = {}
                for param_name, param in sig.parameters.items():
                    if param_name in args:
                        val = args[param_name]
                        if param.annotation == str: bound_args[param_name] = str(val)
                        elif param.annotation == int:
                            try: bound_args[param_name] = int(val)
                            except: bound_args[param_name] = val
                        else:
                            bound_args[param_name] = val
                    elif param.default is not inspect.Parameter.empty:
                        bound_args[param_name] = param.default

                if inspect.iscoroutinefunction(func):
                    result = await func(**bound_args)
                else:
                    result = func(**bound_args)
                
                return json.dumps(result) if not isinstance(result, (str, dict)) else result
            except Exception as e:
                return f"SYSTEM_ERROR: {str(e)}"
        return f"SYSTEM_ERROR: Tool '{tool_name}' not found"

registry = ToolRegistry()
