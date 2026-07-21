import httpx
import json
import asyncio
import time
import subprocess
import os
import signal

URL = "http://localhost:7878/api/stream-all"
TEST_PROMPT = "Create a project 'harness-test'. 1. Create a folder 'harness-test'. 2. Create a file 'hello.py' that prints 'Harness Verified'. 3. List the files to confirm."

async def run_test():
    print(f"🚀 Starting Test Harness...")
    print(f"📝 Prompt: {TEST_PROMPT}")

    phases_seen = set()
    files_created = False

    timeout = httpx.Timeout(600.0, read=None) # Long timeout for LLM reasoning
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", URL, json={
                "prompt": TEST_PROMPT,
                "model": "qwen2.5:14b" # Using a medium model for stable testing
            }) as response:
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = json.loads(line[6:])

                        agent = data.get("agent")
                        msg_type = data.get("type")
                        state = data.get("state")

                        if msg_type == "status":
                            print(f"[{agent}] Phase: {state} | {data.get('step')}")
                            if state:
                                phases_seen.add(state)

                        if msg_type == "token":
                            # Optional: print(data.get("chunk"), end="", flush=True)
                            pass

                        if msg_type == "done":
                            content = data.get("content", "")
                            print(f"\n✅ {agent} completed turn.")
                            if "harness-test/hello.py" in content or "hello.py" in content:
                                files_created = True

        print("\n" + "="*30)
        print("📊 TEST SUMMARY")
        print("="*30)

        required_phases = {"RESEARCH", "DESIGN", "IMPLEMENT", "VERIFY", "FINISHED"}
        missing_phases = required_phases - phases_seen

        if not missing_phases:
            print("✅ All phases executed successfully.")
        else:
            print(f"❌ Missing phases: {missing_phases}")

        if files_created:
            print("✅ File creation verified in logs.")
        else:
            print("❌ File creation NOT detected in logs.")

        # Verify physical disk
        workspace_path = os.path.join(os.getcwd(), "workspace", "harness-test")
        file_path = os.path.join(workspace_path, "hello.py")

        if os.path.exists(file_path):
            print(f"✅ Disk Check: {file_path} EXISTS.")
            with open(file_path, 'r') as f:
                content = f.read()
                if "Harness Verified" in content:
                    print("✅ Content Check: 'Harness Verified' found in file.")
                else:
                    print("❌ Content Check: Expected text NOT found in file.")
        else:
            print(f"❌ Disk Check: {file_path} NOT FOUND.")

    except Exception as e:
        print(f"❗ Test Failed with Error: {e}")

if __name__ == "__main__":
    # Ensure server is running (usually it is if user is asking this)
    # We assume the user has the server running via port 7878
    asyncio.run(run_test())
