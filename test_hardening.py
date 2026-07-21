import asyncio
import pytest
from pathlib import Path
from tools import ToolRegistry, BASE_WORKSPACE

@pytest.fixture
def registry():
    return ToolRegistry()

@pytest.mark.asyncio
async def test_workspace_containment(registry):
    # Test '..' traversal
    with pytest.raises(PermissionError):
        registry._resolve_path("../outside.txt")
    
    # Test absolute paths (Windows)
    with pytest.raises(PermissionError):
        registry._resolve_path("C:/Windows/System32/cmd.exe")
        
    # Test absolute paths (Unix-style on Windows)
    with pytest.raises(PermissionError):
        registry._resolve_path("/etc/passwd")

    # Test sibling-prefix paths (if workspace is /tmp/ws, don't allow /tmp/ws_secret)
    # This is handled by is_relative_to
    
    # Valid path should work
    valid = registry._resolve_path("subdir/file.txt")
    assert valid.is_relative_to(BASE_WORKSPACE)

@pytest.mark.asyncio
async def test_role_permissions(registry):
    # Scout should NOT have write_file
    res = await registry.execute_tool("write_file", {"path": "test.txt", "content": "hi"}, role="scout")
    assert "does not have permission" in res
    
    # Scout should NOT have execute_command
    res = await registry.execute_tool("execute_command", {"command": "dir"}, role="scout")
    assert "does not have permission" in res
    
    # Implementer SHOULD have write_file
    res = await registry.execute_tool("write_file", {"path": "test.txt", "content": "hi"}, role="implementer")
    assert "Wrote test.txt" in res
    
    # Cleanup
    (BASE_WORKSPACE / "test.txt").unlink(missing_ok=True)

@pytest.mark.asyncio
async def test_command_allowlist(registry):
    # Forbidden command
    res = await registry.execute_tool("execute_command", {"command": "powershell whoami"}, role="implementer")
    assert "not in the allowlist" in res
    
    # Chained commands (using metacharacters)
    res = await registry.execute_tool("execute_command", {"command": "dir && echo hi"}, role="implementer")
    assert "Shell metacharacters are forbidden" in res

if __name__ == "__main__":
    asyncio.run(test_workspace_containment(ToolRegistry()))
    print("Containment tests passed.")
    asyncio.run(test_role_permissions(ToolRegistry()))
    print("Role tests passed.")
    asyncio.run(test_command_allowlist(ToolRegistry()))
    print("Command tests passed.")
