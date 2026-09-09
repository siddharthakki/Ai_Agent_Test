# BigModel Desktop

A Windows desktop app for running text models larger than GPU memory. Search Hugging Face, download a GGUF variant, then measure GPU/RAM configurations on your own PC. This tunes inference settings; it does not train or shrink model weights.

## Start without commands

Download the **BigModelDesktop-Windows-x64** artifact from this repository's successful **BigModel Desktop Windows** workflow. Extract the entire ZIP to a writable folder, then double-click **BigModelDesktop.exe**. Keep the `_internal` folder beside the executable. Python is included in the portable build.

1. **Setup:** choose your existing `llama-server.exe`, or find and download an official Windows build. CUDA builds include matching CUDA libraries; your graphics driver must support the chosen version.
2. **Discover:** search public Hugging Face GGUF repositories, select a repository, then choose a quantized variant. Read the model card and license. Choose a download folder with room for every shard.
3. **Optimize & run:** import the first GGUF shard or use the downloaded model. Start with a 2,048-token context and click **Optimize for my PC**.
4. **Chat:** try the running model. Copy its local API address and per-session API key to connect compatible clients.
5. On a later launch, choose the same model, runtime and context, then click **Start saved profile**.

Existing model servers are never stopped by this application. Free GPU/RAM by closing other workloads before optimizing a large model. Available memory is measured at the beginning; other applications can affect results.

## What optimization does

- Reads GGUF architecture, block count, expert count and context limit without loading weights.
- Estimates a conservative initial GPU/RAM budget, reserving 2 GiB of GPU memory and 4 GiB of RAM.
- Tests partial GPU layer placement and, for supported MoE architectures, CPU expert placement.
- Compares normal and memory-mapped loading, then refines CPU threads, prompt batching and expert placement.
- Excludes warm-up runs, takes the median of two measured runs, and ranks by estimated latency for a 512-token prompt plus 128 generated tokens.
- Validates the best candidate with a 256-token generation before saving it. A failed candidate is never saved as the winner.
- Preserves results and runtime logs. Saved profiles are tied to model file sizes/timestamps, runtime identity, GPU, CPU thread count and context.
- Stops its owned runtime if available RAM drops below 2 GiB. This is a periodic safeguard, not a guarantee against every out-of-memory event.

The search is a bounded heuristic, not proof of a globally optimal configuration. Prefill/generation numbers are measured on a fixed synthetic prompt. A successful short benchmark does not establish stability for every prompt length, concurrency level, tool loop, or task. Test your real workload before relying on a profile.

## Models larger than combined memory

**Allow experimental disk assistance** permits memory-mapped loading beyond the initial combined-memory estimate. The operating system controls paging. This may be extremely slow or fail, especially for dense models. No claim is made that an arbitrary large model will run usefully. Memory mapping can also hurt MoE performance; the normal optimization path compares it against ordinary loading.

## Downloads and privacy

Model downloads are pinned to a repository commit, resumable, and checked against published byte sizes and LFS SHA-256 hashes when available. All shards are downloaded before a model becomes selectable. Interrupted downloads retain `.part` files. Runtime archives come from official `ggml-org/llama.cpp` releases and are checked against GitHub's published digest when available.

Search/downloads contact Hugging Face; runtime discovery/downloads contact GitHub. Chat stays on localhost. There is no telemetry, cloud inference fallback, model-code execution, or driver modification. Runtime logs and profiles stay in the portable application's `data/` folder and are excluded from Git.

## Current boundaries

Windows x64 and NVIDIA are the initial supported target. GPU 0 is used; multi-GPU scheduling is not implemented. Public, non-gated Hugging Face GGUF text models and local GGUF imports are supported. A format match is not an architecture-support guarantee: the selected llama.cpp version must support the model. Multimodal projectors, token-authenticated/gated downloads, other catalog providers, weight training, and distributed inference are not included in v0.1. Recommendations estimate memory placement, not model quality. Runtime and model downloads require an internet connection; downloaded models run offline.

The desktop build is unsigned. Release signing and a full installer are future distribution work. The app is portable and should not be extracted into a read-only system directory.

Some Windows system-integrity policies can reject a newly downloaded llama.cpp executable or DLL. The app reports this explicitly and preserves Windows security settings. Choose an existing approved runtime in Setup if this occurs. Runtime downloads can be verified successfully while execution is still blocked by the operating system.

## Development

Python 3.11+ with Tk is enough to run from source. Double-click `Start BigModel.cmd`, or:

```powershell
python launch.py
python -m unittest discover -s tests -v
```

To build the portable Windows app:

```powershell
python -m pip install pyinstaller==6.16.0
python -m PyInstaller --noconfirm --clean --windowed --onedir --name BigModelDesktop launch.py
```

Components: `core.py` handles hardware/GGUF/catalog/downloads; `engine.py` handles owned runtime processes, benchmarking and profiles; `runtime.py` manages official runtime bundles; `app.py` is a Tk UI with worker-thread event queues.

## Together-test checklist

1. Confirm Setup finds the existing runtime and the displayed available memory is plausible.
2. Search/download a small instruction model; optimize, chat, stop, and restart the saved profile.
3. Close other model workloads, then import the first shard of the large Flash model.
4. Inspect the total size and architecture. Begin at 2K context with disk assistance off.
5. Optimize and compare recorded prompt/generation speed with the previous manual baseline under the same context and workload.
6. Increase to 16K only after the first profile is stable; run optimization again and test a genuinely long prompt.

## References

- [Hugging Face Hub API](https://huggingface.co/docs/hub/en/api)
- [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/tree/master/tools/server)
- [Official llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases)
