import asyncio
import json
from workflow import graph, UIStream

async def run_test(mode="AUTO"):
    print(f"\n--- Running Verification: {mode} ---")
    queue = asyncio.Queue()
    ui = UIStream(queue)
    
    state = {
        "task": f"Test task for {mode} mode. Create a dummy file.",
        "requested_mode": mode,
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
    
    # Run graph
    task = asyncio.create_task(graph.ainvoke(state, config={"configurable": {"ui": ui}}))
    
    while not task.done() or not queue.empty():
        try:
            item = await asyncio.wait_for(queue.get(), timeout=0.1)
            print(f"[{item.get('agent')}] {item.get('type')}: {item.get('step') or item.get('content') or item.get('state')}")
        except asyncio.TimeoutError:
            continue
            
    result = await task
    print(f"Final Mode: {result['mode']}")
    print(f"Verification Result: {result['verification_result']}")
    print(f"Versions: {result['metrics'].get('versions')}")

async def main():
    await run_test("FAST")
    await run_test("MEDIUM")
    await run_test("COMPLEX")

if __name__ == "__main__":
    asyncio.run(main())
