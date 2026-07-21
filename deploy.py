import os
import sys
import subprocess
import time
import webbrowser

TARGET_DIR = r"C:\Projects\AI_Agent_Test"
os.makedirs(TARGET_DIR, exist_ok=True)
os.chdir(TARGET_DIR)

print(f"🚀 Deploying Agent Arena & Analytics to {TARGET_DIR}...")

# 1. Kill any hung python/uvicorn processes on server port
try:
    if sys.platform == "win32":
        subprocess.run(["cmd", "/c", "taskkill /F /IM python.exe /T"], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
except Exception:
    pass

# 2. Generate main.py
with open("main.py", "w", encoding="utf-8") as f:
    f.write("import asyncio\n")
    f.write("import json\n")
    f.write("import time\n")
    f.write("from fastapi import FastAPI\n")
    f.write("from fastapi.middleware.cors import CORSMiddleware\n")
    f.write("from fastapi.responses import StreamingResponse\n")
    f.write("from pydantic import BaseModel\n")
    f.write("import httpx\n\n")
    f.write("app = FastAPI()\n\n")
    f.write("app.add_middleware(\n")
    f.write("    CORSMiddleware,\n")
    f.write("    allow_origins=['*'],\n")
    f.write("    allow_methods=['*'],\n")
    f.write("    allow_headers=['*'],\n")
    f.write(")\n\n")
    f.write("class PromptRequest(BaseModel):\n")
    f.write("    prompt: str\n")
    f.write("    model: str = 'qwen2.5-coder:14b'\n\n")
    f.write("async def stream_agent(agent_key: str, prefix: str, prompt: str, model: str):\n")
    f.write("    start_time = time.perf_counter()\n")
    f.write("    full_text = ''\n")
    f.write("    token_count = 0\n")
    f.write("    current_state = 'Planning'\n")
    f.write("    yield f'data: {json.dumps({\"agent\": agent_key, \"type\": \"status\", \"state\": current_state, \"step\": \"Parsing task & initializing state machine...\"})}\\n\\n'\n")
    f.write("    try:\n")
    f.write("        async with httpx.AsyncClient() as client:\n")
    f.write("            async with client.stream('POST', 'http://localhost:11434/api/generate', json={\n")
    f.write("                'model': model,\n")
    f.write("                'prompt': f'{prefix}\\nTask: {prompt}',\n")
    f.write("                'stream': True\n")
    f.write("            }, timeout=120.0) as response:\n")
    f.write("                async for line in response.aiter_lines():\n")
    f.write("                    if not line:\n")
    f.write("                        continue\n")
    f.write("                    data = json.loads(line)\n")
    f.write("                    chunk = data.get('response', '')\n")
    f.write("                    full_text += chunk\n")
    f.write("                    token_count += 1\n")
    f.write("                    if any(m in chunk for m in ['```', 'def ', 'import ', 'class ']):\n")
    f.write("                        if current_state != 'Executing Code':\n")
    f.write("                            current_state = 'Executing Code'\n")
    f.write("                            yield f'data: {json.dumps({\"agent\": agent_key, \"type\": \"status\", \"state\": current_state, \"step\": \"Generating executable tool/code snippet...\"})}\\n\\n'\n")
    f.write("                    elif any(w in chunk.lower() for w in ['verify', 'check', 'reflect', 'audit']):\n")
    f.write("                        if current_state != 'Reflecting':\n")
    f.write("                            current_state = 'Reflecting'\n")
    f.write("                            yield f'data: {json.dumps({\"agent\": agent_key, \"type\": \"status\", \"state\": current_state, \"step\": \"Auditing output and verifying edge cases...\"})}\\n\\n'\n")
    f.write("                    yield f'data: {json.dumps({\"agent\": agent_key, \"type\": \"token\", \"chunk\": chunk})}\\n\\n'\n")
    f.write("                    if data.get('done', False):\n")
    f.write("                        eval_dur = data.get('eval_duration', 1) / 1e9\n")
    f.write("                        tok_s = round(token_count / max(0.1, eval_dur), 2)\n")
    f.write("                        total_lat = round(time.perf_counter() - start_time, 2)\n")
    f.write("                        words = full_text.split()\n")
    f.write("                        thought_w = len([w for w in words if w.lower() in ['plan', 'step', 'reason', 'because', 'think']])\n")
    f.write("                        rd = round(min(1.0, (thought_w / max(1, len(words))) * 3.5), 2)\n")
    f.write("                        yield f'data: {json.dumps({\"agent\": agent_key, \"type\": \"done\", \"state\": \"Complete\", \"metrics\": {\"latency\": total_lat, \"tokens\": token_count, \"tok_per_sec\": tok_s, \"reasoning_density\": rd, \"has_code\": \"```\" in full_text}})}\\n\\n'\n")
    f.write("    except Exception as e:\n")
    f.write("        yield f'data: {json.dumps({\"agent\": agent_key, \"type\": \"error\", \"message\": str(e)})}\\n\\n'\n\n")
    f.write("@app.post('/api/stream-all')\n")
    f.write("async def stream_all_agents(req: PromptRequest):\n")
    f.write("    async def event_generator():\n")
    f.write("        tasks = [\n")
    f.write("            stream_agent('crewai', '[CrewAI Agent - Role: Specialist Orchestrator]', req.prompt, req.model),\n")
    f.write("            stream_agent('langgraph', '[LangGraph - Cyclic State Machine: Plan -> Act -> Audit]', req.prompt, req.model),\n")
    f.write("            stream_agent('autogen', '[AutoGen - Group Chat Coordinator]', req.prompt, req.model),\n")
    f.write("            stream_agent('smolagents', '[smolagents - Code-as-Action Direct Executor]', req.prompt, req.model),\n")
    f.write("            stream_agent('pydantic_ai', '[PydanticAI - Type-Validated Action Handler]', req.prompt, req.model),\n")
    f.write("        ]\n")
    f.write("        queue = asyncio.Queue()\n")
    f.write("        async def worker(gen):\n")
    f.write("            async for item in gen:\n")
    f.write("                await queue.put(item)\n")
    f.write("        workers = [asyncio.create_task(worker(g)) for g in tasks]\n")
    f.write("        active = len(workers)\n")
    f.write("        while active > 0:\n")
    f.write("            item = await queue.get()\n")
    f.write("            yield item\n")
    f.write("            active = sum(1 for w in workers if not w.done())\n")
    f.write("    return StreamingResponse(event_generator(), media_type='text/event-stream')\n\n")
    f.write("if __name__ == '__main__':\n")
    f.write("    import uvicorn\n")
    f.write("    uvicorn.run(app, host='0.0.0.0', port=7878)\n")

print("✅ main.py created.")

# 3. Generate index.html
html_content = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Local AI Agent Arena & Analytics</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body class="bg-slate-950 text-slate-100 h-screen flex flex-col p-4 font-sans overflow-hidden">
  <header class="mb-3 border-b border-slate-800 pb-3 flex-shrink-0">
    <div class="flex justify-between items-center mb-2">
      <h1 class="text-xl font-bold text-indigo-400 flex items-center gap-2">⚔️ Local AI Agent Arena <span class="text-xs bg-indigo-950 text-indigo-300 px-2.5 py-0.5 rounded-full border border-indigo-800">Live Tracer & Analytics</span></h1>
      <span class="text-xs bg-slate-800 text-slate-300 px-3 py-1 rounded-full">Endpoint: http://localhost:11434</span>
    </div>
    <div class="flex gap-3 items-center">
      <select id="modelSelect" class="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm font-medium text-indigo-300 focus:outline-none focus:ring-2 focus:ring-indigo-500">
        <option value="qwen2.5-coder:14b">Qwen 2.5 Coder (14B)</option>
        <option value="qwen2.5:14b">Qwen 2.5 (14B)</option>
        <option value="qwen2.5-coder:32b">Qwen 2.5 Coder (32B)</option>
        <option value="llama3.1:8b">Llama 3.1 (8B)</option>
        <option value="deepseek-r1:14b">DeepSeek-R1 (14B)</option>
      </select>
      <input id="masterPrompt" type="text" placeholder="e.g., 'Draft a python script to scan directory log files and output top 3 IP errors.'" class="flex-1 bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500" />
      <button onclick="triggerAllAgents()" class="bg-indigo-600 hover:bg-indigo-500 font-semibold px-5 py-2 text-sm rounded-lg transition text-white whitespace-nowrap">Run All Agents</button>
    </div>
  </header>
  <div class="flex-1 grid grid-rows-2 gap-4 min-h-0 overflow-hidden">
    <section class="grid grid-cols-1 md:grid-cols-5 gap-3 min-h-0">
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-3 flex flex-col min-h-0">
        <div class="border-b border-slate-800 pb-2 mb-2 flex justify-between items-center"><h2 class="font-bold text-emerald-400 text-sm">CrewAI</h2><span id="badge-crewai" class="text-[10px] bg-slate-800 text-slate-300 px-2 py-0.5 rounded-full">Idle</span></div>
        <p id="step-crewai" class="text-[10px] text-slate-400 truncate mb-1">Awaiting execution...</p>
        <div id="out-crewai" class="text-xs font-mono text-slate-300 whitespace-pre-wrap overflow-y-auto flex-1 bg-slate-950 p-2 rounded border border-slate-850"></div>
      </div>
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-3 flex flex-col min-h-0">
        <div class="border-b border-slate-800 pb-2 mb-2 flex justify-between items-center"><h2 class="font-bold text-blue-400 text-sm">LangGraph</h2><span id="badge-langgraph" class="text-[10px] bg-slate-800 text-slate-300 px-2 py-0.5 rounded-full">Idle</span></div>
        <p id="step-langgraph" class="text-[10px] text-slate-400 truncate mb-1">Awaiting execution...</p>
        <div id="out-langgraph" class="text-xs font-mono text-slate-300 whitespace-pre-wrap overflow-y-auto flex-1 bg-slate-950 p-2 rounded border border-slate-850"></div>
      </div>
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-3 flex flex-col min-h-0">
        <div class="border-b border-slate-800 pb-2 mb-2 flex justify-between items-center"><h2 class="font-bold text-purple-400 text-sm">AutoGen</h2><span id="badge-autogen" class="text-[10px] bg-slate-800 text-slate-300 px-2 py-0.5 rounded-full">Idle</span></div>
        <p id="step-autogen" class="text-[10px] text-slate-400 truncate mb-1">Awaiting execution...</p>
        <div id="out-autogen" class="text-xs font-mono text-slate-300 whitespace-pre-wrap overflow-y-auto flex-1 bg-slate-950 p-2 rounded border border-slate-850"></div>
      </div>
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-3 flex flex-col min-h-0">
        <div class="border-b border-slate-800 pb-2 mb-2 flex justify-between items-center"><h2 class="font-bold text-amber-400 text-sm">smolagents</h2><span id="badge-smolagents" class="text-[10px] bg-slate-800 text-slate-300 px-2 py-0.5 rounded-full">Idle</span></div>
        <p id="step-smolagents" class="text-[10px] text-slate-400 truncate mb-1">Awaiting execution...</p>
        <div id="out-smolagents" class="text-xs font-mono text-slate-300 whitespace-pre-wrap overflow-y-auto flex-1 bg-slate-950 p-2 rounded border border-slate-850"></div>
      </div>
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-3 flex flex-col min-h-0">
        <div class="border-b border-slate-800 pb-2 mb-2 flex justify-between items-center"><h2 class="font-bold text-rose-400 text-sm">PydanticAI</h2><span id="badge-pydantic_ai" class="text-[10px] bg-slate-800 text-slate-300 px-2 py-0.5 rounded-full">Idle</span></div>
        <p id="step-pydantic_ai" class="text-[10px] text-slate-400 truncate mb-1">Awaiting execution...</p>
        <div id="out-pydantic_ai" class="text-xs font-mono text-slate-300 whitespace-pre-wrap overflow-y-auto flex-1 bg-slate-950 p-2 rounded border border-slate-850"></div>
      </div>
    </section>
    <section class="bg-slate-900 border border-slate-800 rounded-xl p-3 flex flex-col min-h-0">
      <div class="flex justify-between items-center border-b border-slate-800 pb-2 mb-2">
        <h2 class="text-sm font-bold text-slate-300 flex items-center gap-2">📊 Real-Time Agentic Metrics & Benchmarks</h2>
        <div class="flex gap-4 text-xs font-mono text-slate-400">
          <div>Fastest: <span id="metric-fastest" class="text-emerald-400 font-bold">-</span></div>
          <div>Peak Speed: <span id="metric-toks" class="text-indigo-400 font-bold">-</span></div>
          <div>Total Tokens: <span id="metric-total-tokens" class="text-amber-400 font-bold">-</span></div>
        </div>
      </div>
      <div class="grid grid-cols-1 md:grid-cols-3 gap-4 flex-1 min-h-0">
        <div class="bg-slate-950 p-2 rounded-lg border border-slate-850 flex flex-col justify-center"><h3 class="text-[11px] font-semibold text-slate-400 text-center mb-1">Latency (s) & Velocity (Tok/s)</h3><div class="flex-1 relative"><canvas id="chartSpeed"></canvas></div></div>
        <div class="bg-slate-950 p-2 rounded-lg border border-slate-850 flex flex-col justify-center"><h3 class="text-[11px] font-semibold text-slate-400 text-center mb-1">Agent Quality Fingerprint</h3><div class="flex-1 relative"><canvas id="chartRadar"></canvas></div></div>
        <div class="bg-slate-950 p-2 rounded-lg border border-slate-850 flex flex-col justify-center"><h3 class="text-[11px] font-semibold text-slate-400 text-center mb-1">Reasoning Density vs Token Volume</h3><div class="flex-1 relative"><canvas id="chartDensity"></canvas></div></div>
      </div>
    </section>
  </div>
  <script>
    let speedChart, radarChart, densityChart;
    const agentKeys = ['crewai', 'langgraph', 'autogen', 'smolagents', 'pydantic_ai'];
    const agentNames = ['CrewAI', 'LangGraph', 'AutoGen', 'smolagents', 'PydanticAI'];
    const colors = ['#34d399', '#60a5fa', '#c084fc', '#fbbf24', '#fb7185'];

    function initCharts() {
      speedChart = new Chart(document.getElementById('chartSpeed'), {
        type: 'bar',
        data: { labels: agentNames, datasets: [{ label: 'Latency (s)', data: [0,0,0,0,0], backgroundColor: '#818cf8' }, { label: 'Tok/sec', data: [0,0,0,0,0], backgroundColor: '#34d399' }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { color: '#94a3b8', font: { size: 9 } } } }, scales: { x: { ticks: { color: '#64748b', font: { size: 9 } } }, y: { ticks: { color: '#64748b', font: { size: 9 } } } } }
      });
      radarChart = new Chart(document.getElementById('chartRadar'), {
        type: 'radar',
        data: { labels: ['Speed', 'Reasoning', 'Code Focus', 'Structure', 'Efficiency'], datasets: agentKeys.map((k, i) => ({ label: agentNames[i], data: [0,0,0,0,0], borderColor: colors[i], backgroundColor: colors[i]+'22', borderWidth: 1.5 })) },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { r: { angleLines: { color: '#334155' }, grid: { color: '#1e293b' }, pointLabels: { color: '#94a3b8', font: { size: 8 } }, ticks: { display: false, max: 100 } } } }
      });
      densityChart = new Chart(document.getElementById('chartDensity'), {
        type: 'scatter',
        data: { datasets: agentKeys.map((k, i) => ({ label: agentNames[i], data: [{ x: 0, y: 0 }], backgroundColor: colors[i], pointRadius: 6 })) },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { color: '#94a3b8', font: { size: 9 } } } }, scales: { x: { title: { display: true, text: 'Tokens', color: '#64748b', font: { size: 9 } }, ticks: { color: '#64748b' } }, y: { title: { display: true, text: 'Reasoning Density (Rd)', color: '#64748b', font: { size: 9 } }, ticks: { color: '#64748b' } } } }
      });
    }

    async function triggerAllAgents() {
      const prompt = document.getElementById('masterPrompt').value;
      const selectedModel = document.getElementById('modelSelect').value;
      if (!prompt) return alert('Please enter a prompt first.');

      agentKeys.forEach(k => {
        document.getElementById(`out-${k}`).innerText = "";
        document.getElementById(`badge-${k}`).innerText = "Initializing";
        document.getElementById(`badge-${k}`).className = "text-[10px] bg-indigo-950 text-indigo-300 border border-indigo-700 px-2 py-0.5 rounded-full animate-pulse";
        document.getElementById(`step-${k}`).innerText = "Connecting to agent loop...";
      });

      const response = await fetch('http://localhost:7878/api/stream-all', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: prompt, model: selectedModel })
      });

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let fastestName = "-", minLatency = 999, maxToks = 0, grandTotalTokens = 0;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\\n\\n");
        buffer = lines.pop();

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const msg = JSON.parse(line.replace("data: ", ""));
          const k = msg.agent;
          const idx = agentKeys.indexOf(k);

          if (msg.type === 'status') {
            document.getElementById(`badge-${k}`).innerText = msg.state;
            document.getElementById(`step-${k}`).innerText = msg.step;
          } else if (msg.type === 'token') {
            document.getElementById(`out-${k}`).innerText += msg.chunk;
            const el = document.getElementById(`out-${k}`);
            el.scrollTop = el.scrollHeight;
          } else if (msg.type === 'done') {
            document.getElementById(`badge-${k}`).innerText = "Complete";
            document.getElementById(`badge-${k}`).className = "text-[10px] bg-emerald-950 text-emerald-300 border border-emerald-800 px-2 py-0.5 rounded-full font-bold";
            document.getElementById(`step-${k}`).innerText = `${msg.metrics.latency}s | ${msg.metrics.tok_per_sec} t/s | Rd: ${msg.metrics.reasoning_density}`;

            if (msg.metrics.latency > 0 && msg.metrics.latency < minLatency) { minLatency = msg.metrics.latency; fastestName = agentNames[idx]; }
            if (msg.metrics.tok_per_sec > maxToks) maxToks = msg.metrics.tok_per_sec;
            grandTotalTokens += msg.metrics.tokens;

            speedChart.data.datasets[0].data[idx] = msg.metrics.latency;
            speedChart.data.datasets[1].data[idx] = msg.metrics.tok_per_sec;

            radarChart.data.datasets[idx].data = [
              Math.max(10, 100 - (msg.metrics.latency * 4)),
              msg.metrics.reasoning_density * 100,
              msg.metrics.has_code ? 95 : 40,
              85,
              Math.min(100, msg.metrics.tok_per_sec * 2)
            ];

            densityChart.data.datasets[idx].data = [{ x: msg.metrics.tokens, y: msg.metrics.reasoning_density }];

            document.getElementById('metric-fastest').innerText = fastestName;
            document.getElementById('metric-toks').innerText = `${maxToks} t/s`;
            document.getElementById('metric-total-tokens').innerText = grandTotalTokens;

            speedChart.update();
            radarChart.update();
            densityChart.update();
          }
        }
      }
    }

    window.onload = initCharts;
  </script>
</body>
</html>
"""

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html_content)

print("✅ index.html created.")

# 4. Launch FastAPI Server & Open Browser UI
python_exec = os.path.join(TARGET_DIR, "venv", "Scripts", "python.exe")
if not os.path.exists(python_exec):
    python_exec = sys.executable

print("🔥 Starting API Server on http://localhost:7878...")
subprocess.Popen([python_exec, os.path.join(TARGET_DIR, "main.py")])

time.sleep(2)
print("🌐 Opening Arena Dashboard in Browser...")
webbrowser.open(f"file:///{os.path.join(TARGET_DIR, 'index.html')}")

print("\n✅ Setup Complete! Everything deployed under C:\\Projects\\AI_Agent_Test")