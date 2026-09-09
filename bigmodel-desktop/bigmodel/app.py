from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import shutil
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import urllib.request
import webbrowser
import zipfile

from .core import (GIB, HuggingFace, atomic_json, data_dir, detect_hardware,
                   download_variant, fit_label, gguf_metadata, model_files,
                   request_json, safe_destination)
from .engine import Engine
from .runtime import windows_builds, install_bundle


class App(tk.Tk):
    def __init__(self, storage=None):
        super().__init__()
        self.title('BigModel Desktop')
        self.geometry('1180x810')
        self.minsize(960, 690)
        self.configure(bg='#101821')
        self.root = Path(storage) if storage else data_dir()
        self.events = queue.Queue()
        self.engine = Engine(self.root, self.report)
        self.hub = HuggingFace()
        self.busy = False
        self.stopping = False
        self.hardware = None
        self.repos, self.variants, self.assets = [], [], []
        self.history = []
        self.settings_path = self.root / 'settings.json'
        try:
            settings = json.loads(self.settings_path.read_text())
        except (OSError, ValueError):
            settings = {}
        default_runtime = shutil.which('llama-server') or ''
        if not default_runtime and Path('C:/AI/llama-cuda/bin/llama-server.exe').exists():
            default_runtime = 'C:/AI/llama-cuda/bin/llama-server.exe'
        self.runtime = tk.StringVar(value=settings.get('runtime', default_runtime))
        self.model = tk.StringVar(value=settings.get('model', ''))
        self.context = tk.StringVar(value=str(settings.get('context', 2048)))
        self.disk = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value='Ready. Choose a local model or discover one on Hugging Face.')
        self.hardware_text = tk.StringVar(value='Scanning your PC…')
        self.model_text = tk.StringVar(value='Import a GGUF file or download a variant from Discover.')
        self.api_text = tk.StringVar(value='Start a model to enable the local API.')
        self.query = tk.StringVar(value='Qwen')
        self.style_ui()
        self.build_ui()
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.after(100, self.pump)
        self.task(self.scan)

    def style_ui(self):
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('.', background='#101821', foreground='#e5edf5', font=('Segoe UI', 10))
        style.configure('TFrame', background='#101821')
        style.configure('TLabel', background='#101821')
        style.configure('Title.TLabel', font=('Segoe UI', 26, 'bold'), foreground='#73e1c0')
        style.configure('Sub.TLabel', foreground='#a2b2c5')
        style.configure('TButton', padding=(14, 9), background='#24374a', borderwidth=0)
        style.map('TButton', background=[('active', '#365471'), ('disabled', '#1c2835')])
        style.configure('Accent.TButton', background='#176b59', font=('Segoe UI', 10, 'bold'))
        style.configure('TNotebook', borderwidth=0)
        style.configure('TNotebook.Tab', padding=(22, 12), background='#1c2835')
        style.map('TNotebook.Tab', background=[('selected', '#244d47')])
        style.configure('TEntry', fieldbackground='#1c2835', foreground='#e5edf5', padding=7)
        style.configure('TCombobox', fieldbackground='#1c2835', foreground='#e5edf5', padding=6)
        style.map('TCombobox', fieldbackground=[('readonly', '#1c2835')], foreground=[('readonly', '#e5edf5')])
        style.configure('Treeview', background='#172330', fieldbackground='#172330',
                        foreground='#e5edf5', rowheight=31, borderwidth=0)
        style.configure('Treeview.Heading', background='#24374a', foreground='#e5edf5', padding=8)
        style.map('Treeview', background=[('selected', '#255c50')])

    def build_ui(self):
        header = ttk.Frame(self, padding=(26, 20))
        header.pack(fill='x')
        ttk.Label(header, text='BigModel Desktop', style='Title.TLabel').pack(anchor='w')
        ttk.Label(header, text='Bigger than your GPU. Tuned for your PC.', style='Sub.TLabel').pack(anchor='w', pady=(4, 12))
        ttk.Label(header, textvariable=self.hardware_text).pack(anchor='w')
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill='both', expand=True, padx=24)
        self.discover_page = ttk.Frame(self.tabs, padding=16)
        self.optimize_page = ttk.Frame(self.tabs, padding=16)
        self.chat_page = ttk.Frame(self.tabs, padding=16)
        self.setup_page = ttk.Frame(self.tabs, padding=16)
        for name, page in [('Discover', self.discover_page), ('Optimize & run', self.optimize_page),
                           ('Chat', self.chat_page), ('Setup', self.setup_page)]:
            self.tabs.add(page, text=name)
        self.build_discover()
        self.build_optimize()
        self.build_chat()
        self.build_setup()
        footer = ttk.Frame(self, padding=(24, 12))
        footer.pack(fill='x')
        ttk.Label(footer, textvariable=self.status, wraplength=900).pack(side='left')
        ttk.Button(footer, text='Stop / pause', command=self.stop).pack(side='right')

    def build_discover(self):
        page = self.discover_page
        row = ttk.Frame(page)
        row.pack(fill='x')
        ttk.Entry(row, textvariable=self.query).pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='Search Hugging Face', command=self.search).pack(side='left', padx=8)
        ttk.Button(row, text='Popular GGUF models', command=lambda: self.search('')).pack(side='left')
        ttk.Label(page, text='Public GGUF catalog • estimates use currently free memory • speed is measured after download',
                  style='Sub.TLabel').pack(anchor='w', pady=10)
        self.repo_tree = self.tree(page, [('model', 'Model repository', 690), ('downloads', 'Downloads', 110)], 5)
        self.repo_tree.bind('<<TreeviewSelect>>', self.select_repo)
        self.variant_tree = self.tree(page, [('name', 'Model variant', 450), ('size', 'Total GiB', 85),
                                           ('fit', 'Estimated placement', 320)], 6)
        self.variant_tree.bind('<<TreeviewSelect>>', self.select_variant)
        self.license_text = tk.StringVar(value='Select a repository to load variants. Split files are grouped automatically.')
        ttk.Label(page, textvariable=self.license_text, wraplength=1020).pack(anchor='w', pady=8)
        row = ttk.Frame(page)
        row.pack(fill='x')
        ttk.Button(row, text='Download selected variant', style='Accent.TButton', command=self.download).pack(side='left')
        ttk.Button(row, text='Read model card', command=self.model_card).pack(side='left', padx=8)

    def tree(self, parent, columns, height):
        frame = ttk.Frame(parent)
        frame.pack(fill='both', expand=True, pady=5)
        tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show='headings', height=height, selectmode='browse')
        for name, title, width in columns:
            tree.heading(name, text=title)
            tree.column(name, width=width, minwidth=60)
        scroll = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        return tree

    def build_optimize(self):
        page = self.optimize_page
        ttk.Label(page, text='Choose a model, then let this PC find a working configuration.', font=('Segoe UI', 14, 'bold')).pack(anchor='w')
        row = ttk.Frame(page)
        row.pack(fill='x', pady=12)
        ttk.Entry(row, textvariable=self.model).pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='Import local GGUF', command=self.browse_model).pack(side='left', padx=8)
        ttk.Button(row, text='Inspect', command=self.inspect_model).pack(side='left')
        ttk.Label(page, textvariable=self.model_text, wraplength=1030, style='Sub.TLabel').pack(anchor='w', pady=5)
        row = ttk.Frame(page)
        row.pack(fill='x', pady=10)
        ttk.Label(row, text='Context budget').pack(side='left')
        ttk.Combobox(row, textvariable=self.context, values=['512', '1024', '2048', '4096', '8192', '16384', '32768'],
                     state='readonly', width=10).pack(side='left', padx=10)
        ttk.Checkbutton(row, text='Allow experimental disk assistance (may be very slow)', variable=self.disk).pack(side='left', padx=10)
        ttk.Label(page, text='Optimization reloads the model several times. It measures prompt and generation speed, keeps a RAM reserve,\n'
                  'then validates the winner. Results apply to this context budget; larger prompts need another run.',
                  style='Sub.TLabel').pack(anchor='w', pady=8)
        row = ttk.Frame(page)
        row.pack(fill='x', pady=8)
        ttk.Button(row, text='Optimize for my PC', style='Accent.TButton', command=self.optimize).pack(side='left')
        ttk.Button(row, text='Start saved profile', command=self.start_saved).pack(side='left', padx=8)
        ttk.Button(row, text='Open results folder', command=lambda: self.open_folder(self.root)).pack(side='left')
        self.log = tk.Text(page, bg='#0c131c', fg='#bad4df', insertbackground='white',
                           relief='flat', font=('Consolas', 10), height=12, wrap='word', state='disabled')
        self.log.pack(fill='both', expand=True, pady=10)

    def build_chat(self):
        page = self.chat_page
        ttk.Label(page, text='Test your local model', font=('Segoe UI', 15, 'bold')).pack(anchor='w')
        ttk.Label(page, textvariable=self.api_text, style='Sub.TLabel').pack(anchor='w', pady=8)
        row = ttk.Frame(page)
        row.pack(fill='x')
        ttk.Button(row, text='Copy API address', command=self.copy_api).pack(side='left')
        ttk.Button(row, text='Copy API key', command=self.copy_key).pack(side='left', padx=8)
        ttk.Button(row, text='Clear conversation', command=self.clear_chat).pack(side='left')
        self.chat = tk.Text(page, bg='#172330', fg='#e5edf5', relief='flat', wrap='word',
                            font=('Segoe UI', 11), padx=15, pady=15, state='disabled')
        self.chat.pack(fill='both', expand=True, pady=12)
        self.message = tk.Text(page, height=3, bg='#24374a', fg='white', insertbackground='white',
                               relief='flat', font=('Segoe UI', 11), padx=10, pady=10)
        self.message.pack(fill='x')
        ttk.Button(page, text='Send locally', style='Accent.TButton', command=self.send).pack(anchor='e', pady=8)

    def build_setup(self):
        page = self.setup_page
        ttk.Label(page, text='Inference runtime', font=('Segoe UI', 15, 'bold')).pack(anchor='w')
        ttk.Label(page, text='Use an existing llama.cpp installation, or download an official Windows build below.',
                  style='Sub.TLabel').pack(anchor='w', pady=10)
        row = ttk.Frame(page)
        row.pack(fill='x')
        ttk.Entry(row, textvariable=self.runtime).pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='Choose llama-server.exe', command=self.browse_runtime).pack(side='left', padx=8)
        ttk.Button(page, text='Find official Windows builds', command=self.find_builds).pack(anchor='w', pady=16)
        self.build_choice = ttk.Combobox(page, state='readonly', width=105)
        self.build_choice.pack(fill='x')
        ttk.Label(page, text='For NVIDIA, choose a CUDA build supported by your driver. CPU builds work without CUDA but are slower.\n'
                  'Runtime compatibility is checked when you optimize. We do not install or change graphics drivers.',
                  style='Sub.TLabel').pack(anchor='w', pady=10)
        ttk.Button(page, text='Download and use this runtime', command=self.install_runtime).pack(anchor='w')
        ttk.Separator(page).pack(fill='x', pady=24)
        ttk.Label(page, text='Version 0.1 • Windows / NVIDIA first • text GGUF models\n\n'
                  'Model discovery and downloads contact Hugging Face. Runtime downloads contact GitHub.\n'
                  'Chat and optimization stay on this computer. No telemetry. No training of model weights.\n'
                  'Gated repositories and other model libraries are not supported yet.\n'
                  'GGUF availability does not guarantee that your llama.cpp build supports the architecture.',
                  style='Sub.TLabel').pack(anchor='w')
        ttk.Button(page, text='Refresh hardware', command=lambda: self.task(self.scan)).pack(anchor='w', pady=16)

    def report(self, text):
        self.events.put(('status', text))

    def task(self, fn):
        if self.busy or self.stopping:
            self.status.set('A job is already running. Wait or use Stop / pause.')
            return
        self.busy = True
        self.engine.cancel.clear()
        def worker():
            try:
                fn()
            except InterruptedError as exc:
                self.report(str(exc))
            except Exception as exc:
                self.events.put(('error', str(exc)))
            finally:
                self.events.put(('done', None))
        threading.Thread(target=worker, daemon=True).start()

    def pump(self):
        for _ in range(200):
            try:
                event, value = self.events.get_nowait()
            except queue.Empty:
                break
            if event == 'status':
                self.status.set(value)
                self.append(self.log, value + '\n')
            elif event == 'error':
                self.status.set(value)
                self.append(self.log, 'Error: ' + value + '\n')
                messagebox.showerror('BigModel Desktop', value)
            elif event == 'done':
                self.busy = False
                if not self.engine.process:
                    self.api_text.set('Model stopped. Start a saved profile or optimize a model.')
            elif event == 'stopped':
                self.stopping = False
                self.api_text.set('Model stopped. Start a saved profile or optimize a model.')
            elif event == 'hardware':
                self.hardware = value
                self.hardware_text.set(f'{value.gpu_name}  ·  {value.vram_free/GIB:.1f} GiB GPU free  ·  '
                                       f'{value.ram_available/GIB:.1f} / {value.ram_total/GIB:.1f} GiB RAM free  ·  '
                                       f'{value.threads} CPU threads')
            elif event == 'repos':
                self.repos = value
                self.repo_tree.delete(*self.repo_tree.get_children())
                self.variant_tree.delete(*self.variant_tree.get_children())
                self.variants = []
                for i, repo in enumerate(value):
                    self.repo_tree.insert('', 'end', iid=str(i), values=(repo['id'], repo.get('downloads', 0)))
                self.status.set(f'{len(value)} repositories found. Select one to see model variants.')
            elif event == 'variants':
                self.variants, self.hardware = value
                self.variant_tree.delete(*self.variant_tree.get_children())
                for i, v in enumerate(self.variants):
                    self.variant_tree.insert('', 'end', iid=str(i), values=(v['name'],
                        f'{v["size"]/GIB:.2f}' if v['size'] else '?', fit_label(v['size'], self.hardware)))
                self.status.set(f'{len(self.variants)} complete variants found. Fit labels are estimates, not speed guarantees.')
            elif event == 'downloaded':
                self.model.set(value)
                self.save_settings()
                self.tabs.select(self.optimize_page)
                self.status.set('Download verified. Ready to inspect and optimize.')
            elif event == 'inspection':
                self.model_text.set(value)
            elif event == 'running':
                self.history = []
                self.api_text.set(f'Running locally at http://127.0.0.1:{self.engine.port}/v1 · API key required')
                self.save_settings()
            elif event == 'reply':
                user, answer = value
                self.history.extend([{'role':'user', 'content':user}, {'role':'assistant', 'content':answer}])
                self.append(self.chat, 'MODEL\n' + answer + '\n\n')
                self.status.set('Reply completed locally.')
            elif event == 'assets':
                self.assets = value
                self.build_choice['values'] = [a['name'] for a in value]
                if value:
                    self.build_choice.current(0)
            elif event == 'runtime':
                self.runtime.set(value)
                self.save_settings()
                self.status.set('Runtime ready. Import a model in Optimize & run.')
        self.after(100, self.pump)

    @staticmethod
    def append(widget, text):
        widget.configure(state='normal')
        widget.insert('end', text)
        widget.see('end')
        widget.configure(state='disabled')

    def scan(self):
        self.events.put(('hardware', detect_hardware()))

    def search(self, query=None):
        query = self.query.get() if query is None else query
        def work():
            self.report('Searching public GGUF repositories…')
            self.events.put(('repos', self.hub.search(query)))
        self.task(work)

    def select_repo(self, _=None):
        selection = self.repo_tree.selection()
        if not selection or self.busy:
            return
        repo = self.repos[int(selection[0])]['id']
        self.variants = []
        self.variant_tree.delete(*self.variant_tree.get_children())
        def work():
            self.report('Loading variants for ' + repo)
            self.events.put(('variants', (self.hub.variants(repo), detect_hardware())))
        self.task(work)

    def select_variant(self, _=None):
        selection = self.variant_tree.selection()
        if selection:
            v = self.variants[int(selection[0])]
            self.license_text.set(f'License: {v["license"]} • {len(v["files"])} file(s) • '
                                  'Read the model card for capabilities and usage terms.')

    def model_card(self):
        selection = self.repo_tree.selection()
        if selection:
            webbrowser.open('https://huggingface.co/' + self.repos[int(selection[0])]['id'])

    def download(self):
        selection = self.variant_tree.selection()
        if not selection or self.busy:
            return
        variant = self.variants[int(selection[0])]
        folder = filedialog.askdirectory(title=f'Save {variant["size"]/GIB:.2f} GiB model to…')
        if folder:
            def work():
                result = download_variant(variant, folder, self.engine.cancel, self.report)
                self.events.put(('downloaded', result))
            self.task(work)

    def browse_model(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(filetypes=[('GGUF model', '*.gguf')])
        if path:
            self.model.set(path)
            self.save_settings()
            self.inspect_model()

    def inspect_model(self):
        path = self.model.get()
        def work():
            files = model_files(path)
            meta = gguf_metadata(files[0])
            size = sum(p.stat().st_size for p in files)
            self.events.put(('inspection', f'{meta["architecture"]} · {meta["blocks"]} layers · '
                f'{meta["experts"]} experts · {len(files)} file(s) · {size/GIB:.2f} GiB · '
                + fit_label(size, detect_hardware())))
        self.task(work)

    def optimize(self):
        runtime, model, context, disk = self.runtime.get(), self.model.get(), int(self.context.get()), self.disk.get()
        def work():
            self.engine.optimize(runtime, model, context, disk)
            self.events.put(('running', None))
        self.task(work)

    def start_saved(self):
        runtime, model, context = self.runtime.get(), self.model.get(), int(self.context.get())
        def work():
            self.engine.start_saved(runtime, model, context)
            self.events.put(('running', None))
        self.task(work)

    def stop(self):
        self.stopping = True
        self.engine.cancel.set()
        def finish():
            self.engine.abort()
            self.events.put(('stopped', None))
        threading.Thread(target=finish, daemon=True).start()
        self.status.set('Stopping the app’s model process / pausing download…')
        self.api_text.set('Stopping model…')

    def send(self):
        if self.busy:
            return
        if not self.engine.process or self.engine.process.poll() is not None:
            self.status.set('Start or optimize a model first.')
            return
        user = self.message.get('1.0', 'end').strip()
        if not user:
            return
        messages = list(self.history) + [{'role':'user', 'content':user}]
        self.message.delete('1.0', 'end')
        self.append(self.chat, 'YOU\n' + user + '\n\n')
        def work():
            self.report('Generating locally…')
            response = self.engine.guarded_api('/v1/chat/completions',
                {'messages': messages, 'max_tokens': 512, 'temperature': .7})
            msg = response['choices'][0]['message']
            answer = msg.get('content') or msg.get('reasoning_content') or '(No text returned)'
            self.events.put(('reply', (user, answer)))
        self.task(work)

    def clear_chat(self):
        if self.busy:
            return
        self.history = []
        self.chat.configure(state='normal')
        self.chat.delete('1.0', 'end')
        self.chat.configure(state='disabled')

    def copy_api(self):
        if self.engine.process and self.engine.process.poll() is None:
            self.clipboard_clear()
            self.clipboard_append(f'http://127.0.0.1:{self.engine.port}/v1')

    def copy_key(self):
        if self.engine.process and self.engine.process.poll() is None:
            self.clipboard_clear()
            self.clipboard_append(self.engine.key)

    def browse_runtime(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(title='Choose llama-server.exe', filetypes=[('Executable', '*.exe')])
        if path:
            self.runtime.set(path)
            self.save_settings()

    def find_builds(self):
        def work():
            self.events.put(('assets', windows_builds()))
            self.report('Official Windows builds found. Matching CUDA libraries are included automatically.')
        self.task(work)

    def install_runtime(self):
        index = self.build_choice.current()
        if index < 0 or self.busy:
            return
        asset = self.assets[index]
        def work():
            exe = install_bundle(asset, self.root / 'runtimes', self.engine.cancel, self.report)
            self.engine.inspect_runtime(exe)
            self.events.put(('runtime', exe))
        self.task(work)

    def save_settings(self):
        atomic_json(self.settings_path, {'runtime': self.runtime.get(), 'model': self.model.get(),
                                         'context': int(self.context.get())})

    @staticmethod
    def open_folder(path):
        path.mkdir(parents=True, exist_ok=True)
        if os.name == 'nt':
            os.startfile(str(path))
        else:
            webbrowser.open(path.as_uri())

    def close(self):
        self.save_settings()
        self.engine.abort()
        self.destroy()


def main():
    import argparse
    import tempfile
    parser = argparse.ArgumentParser(description='BigModel Desktop')
    parser.add_argument('--smoke-test', metavar='RESULT_JSON', help='Run a hidden UI startup test and exit')
    args = parser.parse_args()
    if args.smoke_test:
        with tempfile.TemporaryDirectory() as folder:
            app = App(storage=folder)
            app.withdraw()
            def finish():
                atomic_json(args.smoke_test, {'ok': True, 'tabs': len(app.tabs.tabs()),
                                              'version': '0.1.0'})
                app.close()
            app.after(1500, finish)
            app.mainloop()
    else:
        App().mainloop()


if __name__ == '__main__':
    main()
