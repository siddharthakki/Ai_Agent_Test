# 🤝 AI Agent Arena: Autonomous Engineering Team

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Framework-009688.svg)](https://fastapi.tiangolo.com/)
[![Ollama](https://img.shields.io/badge/Ollama-Local_LLM-orange.svg)](https://ollama.ai/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**AI Agent Arena** is a local, high-performance autonomous engineering platform. It orchestrates a specialized team of AI agents (Researcher, Designer, Coder, and Auditor) to build, test, and preview real-world software projects directly on your machine.

> **Why this project?** It brings the power of "Devin-style" autonomous engineering to your local hardware (Ollama), giving you 100% privacy and zero API costs.

---

## 🌟 Key Features

### 🧠 The Multi-Agent Brain
- **Orchestrated Workflow**: Automatically moves through **RESEARCH → DESIGN → IMPLEMENT → VERIFY** phases.
- **Specialist Routing**: Dynamically swaps models based on the task (e.g., using **Gemma 26B** for Architecture and **DeepSeek 32B** for critical Auditing).
- **Mode Selection**:
  - ⚡ **FAST**: Optimized for simple scripts using 14B models.
  - ⚖️ **MEDIUM**: Balanced performance for daily engineering.
  - 🧠 **COMPLEX**: Full reasoning power for deep architecture and bug hunting.

### 💻 The Unified Workspace (UI)
- **ChatGPT-Style Chat**: Flowing conversation with full history and memory.
- **Smart Output Previewer**: Live rendering of HTML, images, and PDFs written by the agents.
- **Live Script Execution**: Run Python scripts created by the agents with a single click and see STDOUT/STDERR in real-time.
- **Nudge Engine (Interrupts)**: Correct the AI mid-task using the live "Nudge" injection system.
- **Persistence**: LocalStorage integration keeps your chat history and artifacts safe even after a refresh.

### 🛠️ Professional Toolbelt
- **File System**: Read/Write files, search workspace, manage directories.
- **Web Intelligence**: Real-time web search (with HTML cleaning) and URL fetching.
- **Hardware Integration**: GPU VRAM monitoring and automated memory flushing between tasks.
- **Multimedia**: Image transformation, PDF reading, and **ComfyUI/Vision** support.

---

## 📸 Screenshots

*(Add your screenshots here to make it pop!)*

| Unified Chat & Pipeline | Smart Output Previewer |
|:---:|:---:|
| ![Chat UI Placeholder](https://via.placeholder.com/600x400?text=Unified+Chat+Interface) | ![Previewer Placeholder](https://via.placeholder.com/600x400?text=Live+HTML+and+Code+Preview) |

---

## 🚀 Getting Started

### Prerequisites
1.  **Ollama**: Install [Ollama](https://ollama.ai/) and download the required models:
    - `ollama pull qwen2.5:14b`
    - `ollama pull gemma4:26b`
    - `ollama pull hf.co/unsloth/DeepSeek-R1-Distill-Qwen-32B-GGUF`
2.  **Python**: Version 3.10 or higher.

### Installation
1.  **Clone the Repo**:
    ```bash
    git clone https://github.com/siddharthakki/Ai_Agent_Test.git
    cd Ai_Agent_Test
    ```
2.  **Setup Virtual Environment**:
    ```bash
    python -m venv venv
    .\venv\Scripts\activate
    pip install -r requirements.txt
    ```

### Launching the Arena
Run the start script (Windows):
```powershell
.\start.ps1
```
The UI will automatically open at `http://localhost:7878`.

---

## 🛠️ Configuration
Model routing is handled in `main.py` via the `get_specialist_model` function. You can customize which models are used for each phase based on your hardware (RTX 3090/4090 recommended for Complex Mode).

---

## 🤝 Contributing
Contributions are welcome! Whether it's adding new tools to `tools.py` or refining the UI, feel free to fork and submit a PR.

---

## 📜 License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
