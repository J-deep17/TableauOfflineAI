"""Tableau Offline AI - native desktop app (no browser, no Streamlit).

Talks to your local LM Studio server. All numbers are computed exactly by pandas
(engine.py); the local AI only writes the short Tableau answer (llm.py).
"""
import json
import os
import queue
import sys
import threading
import time
import traceback

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:
    print("\nThis Python was installed without Tcl/Tk (the part that draws windows).")
    print("Fix: run the Python installer again > Modify > tick 'tcl/tk and IDLE' > Next > Install.\n")
    input("Press Enter to close...")
    sys.exit(1)

import pandas as pd

import engine
import exam_formatter
import llm
import loader

APP_NAME = "Tableau Offline AI"
CFG_PATH = os.path.join(os.path.expanduser("~"), ".tableau_offline_ai.json")
LOG_PATH = os.path.join(os.path.expanduser("~"), "TableauOfflineAI_error.log")


def log_error(text):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + "\n" + text + "\n" + "-" * 60 + "\n")
    except Exception:  # noqa: BLE001
        pass
DEFAULT_CFG = {
    "base_url": "http://localhost:1234/v1",
    "model": "Auto-detect model",
    "api_key": "lm-studio",
    "max_tokens": 1800,
    "facts_budget": 9000,
    "timeout": 300,
}

FORMULAS = exam_formatter.FORMULAS



def load_cfg():
    cfg = dict(DEFAULT_CFG)
    try:
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:  # noqa: BLE001
        pass
    return cfg


def read_table(path):
    """Load and clean table(s) from a file using the smart loader."""
    tables = loader.smart_load_file(path)
    if not tables:
        raise ValueError(f"No valid data tables found in {os.path.basename(path)}")
    return tables[0]["df"]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1240x800")
        self.minsize(1000, 650)
        try:
            ttk.Style(self).theme_use("clam")
        except tk.TclError:
            pass
        self.q = queue.Queue()
        self.all_tables = {}
        self.cleaning_reports = {}
        self.table_meta = {}
        self.model_cache = {"sig": None, "pairs": [], "tree": []}
        self.zoom_scale = 1.0
        self.is_fit_mode = True
        self.current_model = None
        self.perf = {"prefill_tps": None, "gen_tps": None, "avg_out": 600}
        self.current_state = None
        self.stopped = False
        self.last_facts = ""
        self.cfg = load_cfg()
        self.chat_history = []
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._drain)

    def report_callback_exception(self, exc, val, tb):
        """Show (and log) any error inside a button/callback instead of failing silently."""
        text = "".join(traceback.format_exception(exc, val, tb))
        log_error(text)
        messagebox.showerror(APP_NAME, f"Something went wrong:\n\n{val}\n\nDetails saved to:\n{LOG_PATH}")

    # ------------------------------------------------------------------ plumbing
    def post(self, fn):
        """Thread-safe: run fn on the UI thread."""
        self.q.put(fn)

    def _drain(self):
        try:
            while True:
                self.q.get_nowait()()
        except queue.Empty:
            pass
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(APP_NAME, f"Unexpected problem: {e}")
        self.after(100, self._drain)

    def _on_close(self):
        self._save_cfg()
        self.destroy()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        root = ttk.Frame(self, padding=8)
        root.pack(fill="both", expand=True)

        left = ttk.LabelFrame(root, text="Your tables (selected = used)", padding=6)
        left.pack(side="left", fill="y")
        self.tbl_list = tk.Listbox(left, selectmode=tk.EXTENDED, exportselection=False, width=30, height=18,
                                   font=("Segoe UI", 10))
        self.tbl_list.pack(fill="both", expand=True)
        self.tbl_list.bind("<<ListboxSelect>>", self._on_table_select)
        ttk.Button(left, text="Add files...", command=self.add_files).pack(fill="x", pady=(8, 2))
        ttk.Button(left, text="Preview selected", command=self.preview).pack(fill="x", pady=2)
        ttk.Button(left, text="Cleaning log...", command=self.show_cleaning_log).pack(fill="x", pady=2)
        ttk.Button(left, text="Remove selected", command=self.remove_selected).pack(fill="x", pady=2)
        self.load_lbl = ttk.Label(left, text="Add CSV / Excel files to begin.", wraplength=220, foreground="#555")
        self.load_lbl.pack(fill="x", pady=(8, 0))

        right = ttk.Frame(root)
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))
        nb = ttk.Notebook(right)
        nb.pack(fill="both", expand=True)
        self.nb = nb
        self._tab_model(nb)
        self._tab_ask(nb)
        self._tab_settings(nb)
        self._tab_cheats(nb)
        self._refresh_cheats()


    def _tab_model(self, nb):
        f = ttk.Frame(nb, padding=8)
        nb.add(f, text="1. Data model")
        top = ttk.Frame(f)
        top.pack(fill="x")
        ttk.Button(top, text="Generate schema & drag guide", command=self.generate_schema).pack(side="left")
        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=8, pady=2)
        ttk.Button(top, text="Fit to Screen", command=self.fit_to_screen).pack(side="left", padx=2)
        ttk.Button(top, text="Zoom In (+)", width=11, command=self.zoom_in).pack(side="left", padx=2)
        ttk.Button(top, text="Zoom Out (-)", width=11, command=self.zoom_out).pack(side="left", padx=2)
        ttk.Button(top, text="Reset View", command=self.reset_view).pack(side="left", padx=2)
        self.zoom_lbl = ttk.Label(top, text="100%", foreground="#444", width=8)
        self.zoom_lbl.pack(side="left", padx=4)
        self.model_lbl = ttk.Label(top, text="", foreground="#555")
        self.model_lbl.pack(side="left", padx=10)

        pw = ttk.PanedWindow(f, orient="vertical")
        pw.pack(fill="both", expand=True, pady=(8, 0))
        cf = ttk.Frame(pw)
        pw.add(cf, weight=3)
        self.canvas = tk.Canvas(cf, background="#f7f8fa", highlightthickness=0)
        xs = ttk.Scrollbar(cf, orient="horizontal", command=self.canvas.xview)
        ys = ttk.Scrollbar(cf, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=xs.set, yscrollcommand=ys.set)
        xs.pack(side="bottom", fill="x")
        ys.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.canvas.bind("<ButtonPress-1>", self._on_canvas_press)
        self.canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self.canvas.bind("<MouseWheel>", self._on_canvas_mousewheel)
        self.canvas.bind("<Configure>", self._on_canvas_resize)

        gf = ttk.LabelFrame(pw, text="Copyable drag guide", padding=6)
        pw.add(gf, weight=2)
        self.guide_txt = tk.Text(gf, height=8, wrap="word", font=("Consolas", 10))
        self.guide_txt.pack(fill="both", expand=True)
        bf = ttk.Frame(gf)
        bf.pack(fill="x", pady=(6, 0))
        ttk.Button(bf, text="Copy guide", command=lambda: self._copy(self.guide_txt.get("1.0", "end").strip())).pack(side="left")
        ttk.Button(bf, text="Save guide...", command=lambda: self._save_text(self.guide_txt.get("1.0", "end"), "tableau_guide.txt")).pack(side="left", padx=6)

    def _tab_ask(self, nb):
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text="2. Ask & Chat Assistant")

        # Top Header Bar with Clear Conversation & Save Chat
        top_bar = ttk.Frame(f)
        top_bar.pack(fill="x", pady=(0, 4))
        ttk.Label(
            top_bar,
            text="Ask an exam question, or continue chatting if you are stuck anywhere on a step, formula, or filter.",
            foreground="#475569", font=("Segoe UI", 10)
        ).pack(side="left")

        ttk.Button(top_bar, text="🗑️ Clear Conversation", command=self.clear_chat).pack(side="right")
        ttk.Button(top_bar, text="💾 Save Chat...", command=self.save_chat).pack(side="right", padx=6)
        ttk.Button(top_bar, text="🔍 Show Verified Facts", command=self.show_facts).pack(side="right", padx=6)

        # Central Chat Transcript Window
        chat_frame = ttk.LabelFrame(f, text="Exam Conversation & Guide", padding=6)
        chat_frame.pack(fill="both", expand=True, pady=(2, 4))

        text_cont = ttk.Frame(chat_frame)
        text_cont.pack(fill="both", expand=True)

        self.ans_txt = tk.Text(
            text_cont, wrap="word", font=("Segoe UI", 10), state="disabled",
            background="#ffffff", foreground="#1e293b", relief="flat", padx=12, pady=10
        )
        exam_formatter.configure_exam_tags(self.ans_txt)
        ans_sb = ttk.Scrollbar(text_cont, orient="vertical", command=self.ans_txt.yview)
        self.ans_txt.configure(yscrollcommand=ans_sb.set)
        ans_sb.pack(side="right", fill="y")
        self.ans_txt.pack(side="left", fill="both", expand=True)

        # Initial greeting in chat transcript
        self.ans_txt.config(state="normal")
        self.ans_txt.insert("end", "👋 Welcome to Tableau Exam Helper!\n\n", ("h_task",))
        self.ans_txt.insert(
            "end",
            "Type your practical exam task below to get verified fields, shelves, steps, and expected results.\n"
            "If you are stuck on any step or get an error in Tableau, ask follow-up questions to continue chatting.\n"
            "Use '🗑️ Clear Conversation' whenever you want to begin a fresh task.\n\n"
            + "─" * 70 + "\n",
            ("base",)
        )
        self.ans_txt.config(state="disabled")

        # Chat Action / Quick-Copy Bar
        copy_bar = ttk.Frame(chat_frame)
        copy_bar.pack(fill="x", pady=(4, 2))
        ttk.Button(copy_bar, text="📋 Copy Latest Answer", command=lambda: self._copy(self._answer_text())).pack(side="left")
        ttk.Button(copy_bar, text="🔢 Copy Steps Only", command=self._copy_steps).pack(side="left", padx=4)
        ttk.Button(copy_bar, text="🧮 Copy Formula", command=self._copy_formula).pack(side="left", padx=4)
        self.check_lbl = ttk.Label(copy_bar, text="", wraplength=550, font=("Segoe UI", 9))
        self.check_lbl.pack(side="right", padx=4)

        # Quick Follow-Up Chips (when student is stuck)
        chips_frame = ttk.Frame(f)
        chips_frame.pack(fill="x", pady=(2, 4))
        ttk.Label(chips_frame, text="Stuck? Quick follow-up:", foreground="#64748b", font=("Segoe UI", 9, "italic")).pack(side="left", padx=(0, 6))

        quick_prompts = [
            ("Where to drag?", "Where exactly do I drag each field on the Tableau canvas?"),
            ("Show Formula", "What is the exact Calculated Field formula for this task?"),
            ("Fix Error", "I got an error in Tableau while following these steps. How do I fix it?"),
            ("Explain Details", "Can you explain the steps and shelf selections in more detail?"),
        ]
        for label, q_text in quick_prompts:
            ttk.Button(
                chips_frame, text=label,
                command=lambda qt=q_text: self._send_quick_prompt(qt)
            ).pack(side="left", padx=2)

        # Bottom Input Area
        in_frame = ttk.Frame(f)
        in_frame.pack(fill="x", pady=(2, 0))

        self.q_txt = tk.Text(in_frame, height=3, wrap="word", font=("Segoe UI", 11), padx=8, pady=6)
        self.q_txt.pack(fill="x", pady=(2, 4))
        self.q_txt.bind("<Control-Return>", lambda _e: self.solve())

        btn_row = ttk.Frame(in_frame)
        btn_row.pack(fill="x")
        self.solve_btn = ttk.Button(btn_row, text="⚡ Send Question / Follow-up", command=self.solve)
        self.solve_btn.pack(side="left")
        self.stop_btn = ttk.Button(btn_row, text="Stop", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=6)
        ttk.Label(btn_row, text="(Press Ctrl+Enter to send)", foreground="#64748b", font=("Segoe UI", 9)).pack(side="left", padx=8)

        # Progress indicator and status bar
        self.pbar = ttk.Progressbar(in_frame, maximum=1000, mode="determinate")
        self.pbar.pack(fill="x", pady=(4, 2))

        stat_row = ttk.Frame(in_frame)
        stat_row.pack(fill="x")
        self.status_lbl = ttk.Label(stat_row, text="Ready.", foreground="#333", font=("Segoe UI", 10, "bold"))
        self.status_lbl.pack(side="left")
        self.metrics_lbl = ttk.Label(stat_row, text="", foreground="#64748b", font=("Segoe UI", 9))
        self.metrics_lbl.pack(side="right")

    def _tab_settings(self, nb):
        f = ttk.Frame(nb, padding=14)
        nb.add(f, text="Settings")
        self.v_url = tk.StringVar(value=self.cfg["base_url"])
        self.v_model = tk.StringVar(value=self.cfg["model"])
        self.v_key = tk.StringVar(value=self.cfg["api_key"])
        self.v_max = tk.StringVar(value=str(self.cfg["max_tokens"]))
        self.v_facts = tk.StringVar(value=str(self.cfg["facts_budget"]))
        self.v_to = tk.StringVar(value=str(self.cfg["timeout"]))
        rows = [
            ("LM Studio API address", self.v_url, "Default http://localhost:1234/v1"),
            ("Model name", self.v_model, "Leave 'Auto-detect model' to use whichever model is loaded"),
            ("API key", self.v_key, "Usually not needed locally"),
            ("Max output tokens", self.v_max, "Reasoning models think before answering; 1800+ recommended (auto-retries with double)"),
            ("Facts size (characters)", self.v_facts, "Lower this if LM Studio says the prompt is too long"),
            ("Wait limit (seconds)", self.v_to, "Per query"),
        ]
        for i, (label, var, hint) in enumerate(rows):
            ttk.Label(f, text=label).grid(row=i, column=0, sticky="w", pady=5)
            ttk.Entry(f, textvariable=var, width=46).grid(row=i, column=1, padx=10, pady=5)
            ttk.Label(f, text=hint, foreground="#666").grid(row=i, column=2, sticky="w")
        bf = ttk.Frame(f)
        bf.grid(row=len(rows), column=0, columnspan=3, sticky="w", pady=14)
        ttk.Button(bf, text="Test connection", command=self.test_connection).pack(side="left")
        ttk.Button(bf, text="Save settings", command=self._save_cfg).pack(side="left", padx=8)
        self.conn_lbl = ttk.Label(f, text="", wraplength=900)
        self.conn_lbl.grid(row=len(rows) + 1, column=0, columnspan=3, sticky="w")

    def _tab_cheats(self, nb):
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text="Formula cheat sheet")

        # Top Control Bar: Search and Category Filter
        top = ttk.Frame(f)
        top.pack(fill="x", pady=(0, 8))

        ttk.Label(top, text="🔍 Search:", font=("Segoe UI", 10, "bold")).pack(side="left")
        self.cheat_search_var = tk.StringVar()
        self.cheat_search_var.trace_add("write", lambda *_: self._refresh_cheats())
        s_entry = ttk.Entry(top, textvariable=self.cheat_search_var, width=24)
        s_entry.pack(side="left", padx=(4, 12))

        ttk.Label(top, text="Category:", font=("Segoe UI", 10, "bold")).pack(side="left")
        self.cheat_cat_var = tk.StringVar(value=exam_formatter.FORMULA_CATEGORIES[0])
        cat_cb = ttk.Combobox(
            top, textvariable=self.cheat_cat_var, values=exam_formatter.FORMULA_CATEGORIES,
            state="readonly", width=25
        )
        cat_cb.pack(side="left", padx=(4, 12))
        cat_cb.bind("<<ComboboxSelected>>", lambda _e: self._refresh_cheats())

        self.cheat_active_tbl_lbl = ttk.Label(
            top, text="Active dataset: None", foreground="#475569", font=("Segoe UI", 9, "italic")
        )
        self.cheat_active_tbl_lbl.pack(side="left", padx=4)

        ttk.Button(top, text="🔄 Check Active Table", command=self._refresh_cheats).pack(side="right")

        # Main PanedWindow: Upper is Table, Lower is Preview & Copy Card
        pw = ttk.PanedWindow(f, orient="vertical")
        pw.pack(fill="both", expand=True)

        # Upper Table Frame
        tree_frame = ttk.Frame(pw)
        pw.add(tree_frame, weight=3)

        cols = ("category", "name", "formula", "status", "purpose")
        self.cheat_tv = ttk.Treeview(tree_frame, columns=cols, show="headings", height=9)
        self.cheat_tv.heading("category", text="Category")
        self.cheat_tv.heading("name", text="Formula Name")
        self.cheat_tv.heading("formula", text="Tableau Formula")
        self.cheat_tv.heading("status", text="Dataset Status / Compute Using")
        self.cheat_tv.heading("purpose", text="When to Use (Exam Purpose)")

        self.cheat_tv.column("category", width=140, anchor="w")
        self.cheat_tv.column("name", width=180, anchor="w")
        self.cheat_tv.column("formula", width=280, anchor="w")
        self.cheat_tv.column("status", width=240, anchor="w")
        self.cheat_tv.column("purpose", width=380, anchor="w")

        ysb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.cheat_tv.yview)
        xsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.cheat_tv.xview)
        self.cheat_tv.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)

        ysb.pack(side="right", fill="y")
        xsb.pack(side="bottom", fill="x")
        self.cheat_tv.pack(fill="both", expand=True)

        self.cheat_tv.bind("<<TreeviewSelect>>", self._on_cheat_select)
        self.cheat_tv.bind("<Double-1>", lambda _e: self._copy_selected_formula())

        # Lower Detail & Quick-Copy Card
        card = ttk.LabelFrame(pw, text="Selected Formula Quick-Reference & Copy", padding=8)
        pw.add(card, weight=2)

        self.cf_name_lbl = ttk.Label(
            card, text="Select a formula above to preview details and copy.",
            font=("Segoe UI", 11, "bold"), foreground="#0f2d59"
        )
        self.cf_name_lbl.pack(anchor="w")

        # Large readable formula box
        self.cf_box = tk.Text(
            card, height=2, wrap="none", font=("Consolas", 11, "bold"),
            background="#f8fafc", foreground="#0f172a", relief="solid", borderwidth=1, padx=8, pady=4
        )
        self.cf_box.pack(fill="x", pady=(4, 4))

        self.cf_purpose_lbl = ttk.Label(card, text="", wraplength=950, font=("Segoe UI", 10))
        self.cf_purpose_lbl.pack(anchor="w", pady=(0, 2))

        self.cf_status_lbl = ttk.Label(card, text="", font=("Segoe UI", 10, "bold"))
        self.cf_status_lbl.pack(anchor="w", pady=(0, 6))

        c_btn_row = ttk.Frame(card)
        c_btn_row.pack(fill="x")
        ttk.Button(c_btn_row, text="📋 Copy Formula", command=self._copy_selected_formula).pack(side="left")
        ttk.Button(c_btn_row, text="📋 Copy with Steps (Create Calc Field)", command=self._copy_formula_with_steps).pack(side="left", padx=8)
        ttk.Label(
            c_btn_row, text="Tip: Double-click any row above to immediately copy formula syntax.",
            foreground="#64748b", font=("Segoe UI", 9)
        ).pack(side="right")

    def _refresh_cheats(self):
        if not hasattr(self, "cheat_tv"):
            return
        query = self.cheat_search_var.get().strip().lower()
        cat_filter = self.cheat_cat_var.get()
        sel_tables = self.selected_tables()

        active_cols = set()
        active_tbl_names = list(sel_tables.keys())
        if active_tbl_names:
            tbl_str = ", ".join(active_tbl_names[:2])
            self.cheat_active_tbl_lbl.config(text=f"Active Table: {tbl_str}", foreground="#15803d")
            for df in sel_tables.values():
                for c in df.columns:
                    active_cols.add(str(c))
        else:
            self.cheat_active_tbl_lbl.config(text="Active dataset: None (Select table on left)", foreground="#64748b")

        for item in self.cheat_tv.get_children():
            self.cheat_tv.delete(item)

        matched_first = None
        for idx, item in enumerate(exam_formatter.FORMULAS):
            if cat_filter != "All Categories" and item["category"] != cat_filter:
                continue
            if query:
                full_text = f"{item['name']} {item['formula']} {item['purpose']} {item['category']}".lower()
                if query not in full_text:
                    continue

            _status_code, status_badge = exam_formatter.validate_formula_fields(item, active_cols)
            row_id = self.cheat_tv.insert("", "end", iid=str(idx), values=(
                item["category"],
                item["name"],
                item["formula"].replace("\n", " "),
                status_badge,
                item["purpose"],
            ))
            if matched_first is None:
                matched_first = row_id

        if matched_first:
            self.cheat_tv.selection_set(matched_first)
            self._on_cheat_select(None)
        else:
            self.cf_name_lbl.config(text="No formulas matched your search/filter.")
            self.cf_box.delete("1.0", "end")
            self.cf_purpose_lbl.config(text="")
            self.cf_status_lbl.config(text="")

    def _on_cheat_select(self, _e):
        sel = self.cheat_tv.selection()
        if not sel:
            return
        idx = int(sel[0])
        item = exam_formatter.FORMULAS[idx]
        sel_tables = self.selected_tables()
        active_cols = set()
        for df in sel_tables.values():
            for c in df.columns:
                active_cols.add(str(c))
        _status_code, status_badge = exam_formatter.validate_formula_fields(item, active_cols)

        self.cf_name_lbl.config(text=f"{item['name']}   [{item['category']}]")
        self.cf_box.delete("1.0", "end")
        self.cf_box.insert("1.0", item["formula"])
        self.cf_purpose_lbl.config(text=f"Purpose: {item['purpose']}")

        fg = "#15803d" if "✓" in status_badge else ("#b45309" if "⚠️" in status_badge else "#1d4ed8")
        self.cf_status_lbl.config(text=f"Dataset Compatibility: {status_badge}", foreground=fg)

    def _copy_selected_formula(self):
        formula = ""
        name = "Formula"
        sel = self.cheat_tv.selection()
        if sel:
            idx = int(sel[0])
            formula = exam_formatter.FORMULAS[idx]["formula"]
            name = exam_formatter.FORMULAS[idx]["name"]
        elif hasattr(self, "cf_box"):
            formula = self.cf_box.get("1.0", "end").strip()

        if formula:
            self._copy(formula)
            self.status_lbl.config(text=f"Copied '{name}' formula to clipboard.", foreground="#15803d")
        else:
            messagebox.showinfo(APP_NAME, "Select a formula in the table first.")

    def _copy_formula_with_steps(self):
        item = None
        sel = self.cheat_tv.selection()
        if sel:
            idx = int(sel[0])
            item = exam_formatter.FORMULAS[idx]

        if item:
            text = (
                f"FIELD NAME: {item['name']}\n\n"
                f"FORMULA:\n{item['formula']}\n\n"
                "STEPS IN TABLEAU:\n"
                "1. Right-click anywhere in the Data pane.\n"
                "2. Select Create Calculated Field.\n"
                f"3. Enter the field name: {item['name']}\n"
                f"4. Paste the formula:\n{item['formula']}\n"
                "5. Click OK.\n"
                "6. Drag the new field into the appropriate shelf (Rows, Columns, Marks, etc.).\n"
            )
            if item.get("compute_using"):
                text += f"\nTABLE CALCULATION CONFIGURATION:\n• {item['compute_using']}\n"
            self._copy(text)
            self.status_lbl.config(text=f"Copied '{item['name']}' with step-by-step instructions.", foreground="#15803d")
        elif hasattr(self, "cf_box") and self.cf_box.get("1.0", "end").strip():
            self._copy(self.cf_box.get("1.0", "end").strip())
        else:
            messagebox.showinfo(APP_NAME, "Select a formula in the table first.")

    # ------------------------------------------------------------------ helpers
    def _copy(self, text):
        if not text:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update_idletasks()
            self.update()  # Critical for Windows Tkinter clipboard commit
            self.status_lbl.config(text="Copied to clipboard.", foreground="#15803d")
        except Exception:  # noqa: BLE001
            pass

    def _save_text(self, text, default):
        path = filedialog.asksaveasfilename(defaultextension=".txt", initialfile=default,
                                            filetypes=[("Text", "*.txt"), ("Markdown", "*.md"), ("All files", "*.*")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)

    def _answer_text(self):
        # Extract plain text of the latest assistant response
        raw = ""
        if hasattr(self, "chat_history") and self.chat_history:
            for m in reversed(self.chat_history):
                if m.get("role") == "assistant":
                    raw = m.get("content", "")
                    break
        if not raw:
            raw = getattr(self, "raw_answer", "")
        clean = exam_formatter.extract_clean_text(raw)
        return clean or self.ans_txt.get("1.0", "end").strip()

    def _set_answer(self, text):
        self.raw_answer = text
        exam_formatter.render_exam_answer(self.ans_txt, text, clear=True)

    def _copy_steps(self):
        raw = ""
        if hasattr(self, "chat_history") and self.chat_history:
            for m in reversed(self.chat_history):
                if m.get("role") == "assistant":
                    raw = m.get("content", "")
                    break
        if not raw:
            raw = getattr(self, "raw_answer", "")

        steps = exam_formatter.extract_steps(raw)
        if steps:
            self._copy(steps)
            self.status_lbl.config(text=f"Copied {len(steps.splitlines())} steps to clipboard.", foreground="#15803d")
        else:
            messagebox.showinfo(APP_NAME, "No numbered steps found in the latest answer yet.")

    def _copy_formula(self):
        # 1. If user highlighted any text in the chatbox, copy it directly
        try:
            sel = self.ans_txt.get("sel.first", "sel.last").strip()
            if sel:
                self._copy(sel)
                self.status_lbl.config(text="Copied highlighted text to clipboard.", foreground="#15803d")
                return
        except tk.TclError:
            pass

        # 2. Extract formula from the latest assistant response
        raw = ""
        if hasattr(self, "chat_history") and self.chat_history:
            for m in reversed(self.chat_history):
                if m.get("role") == "assistant":
                    raw = m.get("content", "")
                    break
        if not raw:
            raw = getattr(self, "raw_answer", "")

        formula = exam_formatter.extract_formula(raw)
        if formula:
            self._copy(formula)
            self.status_lbl.config(text=f"Copied formula to clipboard: {formula[:35]}...", foreground="#15803d")
        else:
            messagebox.showinfo(
                APP_NAME,
                "No calculated field formula found in the latest answer (or not required).\n\n"
                "Tip: You can highlight any formula or text in the chat and click 'Copy Formula' to copy it."
            )

    def clear_chat(self):
        """Reset conversation history so user can start a completely fresh exam task."""
        self.chat_history = []
        self.raw_answer = ""
        self.last_facts = ""
        self.ans_txt.config(state="normal")
        self.ans_txt.delete("1.0", "end")
        self.ans_txt.insert("end", "👋 Conversation cleared.\nType a new exam task below to begin.\n\n" + "─" * 70 + "\n", ("base",))
        self.ans_txt.config(state="disabled")
        self.check_lbl.config(text="")
        self.metrics_lbl.config(text="")
        self.status_lbl.config(text="Conversation cleared. Ready for new task.", foreground="#15803d")

    def save_chat(self):
        """Export full conversation transcript to a text or markdown file."""
        text = self.ans_txt.get("1.0", "end").strip()
        if not text:
            messagebox.showinfo(APP_NAME, "Conversation is empty.")
            return
        self._save_text(text, "tableau_exam_chat.md")

    def _send_quick_prompt(self, text):
        """Clickable quick chip: populate question box and send immediately."""
        self.q_txt.delete("1.0", "end")
        self.q_txt.insert("1.0", text)
        self.solve()

    def _on_table_select(self, _event=None):
        sel_tables = self.selected_tables()
        if sel_tables:
            self._auto_model(sel_tables)
        self._refresh_cheats()

    def _set_progress(self, frac, text):
        self.pbar["value"] = max(0.0, min(1.0, frac)) * 1000
        self.status_lbl.config(text=text, foreground="#333")

    def _cfg(self):
        def num(v, d, lo, hi):
            try:
                return max(lo, min(hi, int(float(v.get()))))
            except ValueError:
                return d
        return {
            "base_url": self.v_url.get().strip().rstrip("/") or DEFAULT_CFG["base_url"],
            "model": self.v_model.get().strip() or "Auto-detect model",
            "api_key": self.v_key.get(),
            "max_tokens": num(self.v_max, 1800, 300, 8000),
            "facts_budget": num(self.v_facts, 9000, 3000, 24000),
            "timeout": num(self.v_to, 300, 30, 1800),
        }

    def _save_cfg(self):
        try:
            self.cfg = self._cfg()
            with open(CFG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f)
            if hasattr(self, "conn_lbl"):
                self.conn_lbl.config(text="Settings saved.", foreground="#177245")
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ tables
    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="Select one or more data files",
            filetypes=[("Data files", "*.csv *.xlsx *.xlsm *.xls"), ("All files", "*.*")])
        if not paths:
            return
        self.load_lbl.config(text=f"Loading {len(paths)} file(s)...", foreground="#555")
        threading.Thread(target=self._load_worker, args=(list(paths),), daemon=True).start()

    def _load_worker(self, paths):
        ok, bad = [], []
        for p in paths:
            try:
                tables = loader.smart_load_file(p)
                for t in tables:
                    if t.get("error"):
                        bad.append(f"{t['name']}: {t['error']}")
                    else:
                        ok.append(t)
            except Exception as e:  # noqa: BLE001
                bad.append(f"{os.path.basename(p)}: {e}")
        self.post(lambda: self._after_load(ok, bad, len(paths)))

    def _after_load(self, ok, bad, file_count):
        cleaned_count = 0
        for item in ok:
            name = item["name"]
            df = item["df"]
            report = item.get("report", [])
            base, i = name, 2
            while name in self.all_tables:
                name = f"{base} ({i})"
                i += 1
            self.all_tables[name] = df
            self.cleaning_reports[name] = report
            self.table_meta[name] = {
                "source_path": item["source_path"],
                "sheet_name": item.get("sheet_name"),
                "raw_shape": item.get("raw_shape", df.shape),
                "clean_shape": df.shape,
            }
            self.tbl_list.insert("end", name)
            if not engine.is_doc_file(name):
                self.tbl_list.selection_set("end")
            rep_str = " ".join(report).lower()
            if any(w in rep_str for w in ("skipped", "removed", "dropped", "parsed", "renamed")):
                cleaned_count += 1

        if ok:
            msg = f"{len(ok)} table(s) loaded from {file_count} file(s)."
            if cleaned_count > 0:
                msg += f" {cleaned_count} table(s) cleaned (headers/title rows fixed)."
        else:
            msg = "Nothing loaded."

        if bad:
            msg += " Problems: " + " | ".join(bad)
            messagebox.showwarning(APP_NAME, "Some files or sheets could not be read:\n\n" + "\n".join(bad))
        self.load_lbl.config(text=msg + " Documentation files (data dictionary) are unticked automatically.")

        # Automatically fit the diagram when adding tables
        sel_tables = self.selected_tables()
        if sel_tables:
            self._auto_model(sel_tables)
            self.model_lbl.config(
                text=f"{len(sel_tables)} table(s) loaded. Relationships mapped automatically.",
                foreground="#15803d"
            )
        self._refresh_cheats()

    def selected_tables(self):
        return {self.tbl_list.get(i): self.all_tables[self.tbl_list.get(i)] for i in self.tbl_list.curselection()}

    def remove_selected(self):
        for i in reversed(self.tbl_list.curselection()):
            name = self.tbl_list.get(i)
            self.all_tables.pop(name, None)
            self.cleaning_reports.pop(name, None)
            self.table_meta.pop(name, None)
            self.tbl_list.delete(i)
        sel_tables = self.selected_tables()
        if sel_tables:
            self._auto_model(sel_tables)
        else:
            self.current_model = None
            self.canvas.delete("all")
            self.guide_txt.delete("1.0", "end")
            self.model_lbl.config(text="")
        self._refresh_cheats()


    def preview(self):
        sel = self.tbl_list.curselection()
        if not sel:
            messagebox.showinfo(APP_NAME, "Select a table in the list first.")
            return
        name = self.tbl_list.get(sel[0])
        df = self.all_tables[name].head(100)
        win = tk.Toplevel(self)
        win.title(f"Preview - {name}")
        win.geometry("1050x580")

        # Top banner with metadata and cleaning summary
        meta = self.table_meta.get(name, {})
        report = self.cleaning_reports.get(name, [])
        src = os.path.basename(meta.get("source_path", "Unknown"))
        sheet = meta.get("sheet_name")
        src_info = f"Source: {src}" + (f"  |  Sheet: {sheet}" if sheet else "")

        top_f = ttk.Frame(win, padding=8)
        top_f.pack(fill="x")
        ttk.Label(top_f, text=f"Table: {name}   ({len(self.all_tables[name]):,} rows x {len(self.all_tables[name].columns)} columns)",
                  font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(top_f, text=src_info, foreground="#555").pack(anchor="w", pady=(2, 4))

        if report:
            rep_text = " • " + "  • ".join(report)
            is_cleaned = any(w in rep_text.lower() for w in ("skipped", "removed", "dropped", "parsed", "renamed"))
            ttk.Label(top_f, text=f"Cleaning applied:\n{rep_text}",
                      foreground="#177245" if is_cleaned else "#444",
                      wraplength=1000).pack(anchor="w", pady=(0, 4))

        cols = [str(c) for c in df.columns][:30]
        tv = ttk.Treeview(win, columns=cols, show="headings")
        for c in cols:
            tv.heading(c, text=c)
            tv.column(c, width=120, anchor="w")
        for _, row in df.iterrows():
            tv.insert("", "end", values=[str(row[c]) for c in df.columns[:30]])
        xs = ttk.Scrollbar(win, orient="horizontal", command=tv.xview)
        tv.configure(xscrollcommand=xs.set)
        xs.pack(side="bottom", fill="x")
        tv.pack(fill="both", expand=True)

    def show_cleaning_log(self):
        if not self.all_tables:
            messagebox.showinfo(APP_NAME, "No tables loaded yet. Add files to see the cleaning report.")
            return
        win = tk.Toplevel(self)
        win.title("Data Cleaning & Audit Report")
        win.geometry("850x550")

        top = ttk.Frame(win, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Data Cleaning & Audit Report", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(top, text="Every action performed to clean messy sheets, find headers, and format columns is recorded below.",
                  foreground="#555").pack(anchor="w")

        txt = tk.Text(win, wrap="word", font=("Consolas", 10), padx=8, pady=8)
        txt.pack(fill="both", expand=True, padx=8, pady=4)

        lines = []
        for name, report in self.cleaning_reports.items():
            meta = self.table_meta.get(name, {})
            src = os.path.basename(meta.get("source_path", "Unknown"))
            sheet = meta.get("sheet_name")
            raw_s = meta.get("raw_shape", ("?", "?"))
            clean_s = meta.get("clean_shape", ("?", "?"))
            lines.append("=" * 72)
            lines.append(f"TABLE: {name}")
            lines.append(f"  Source file  : {src}")
            if sheet:
                lines.append(f"  Sheet name   : {sheet}")
            lines.append(f"  Raw layout   : {raw_s[0]:,} rows x {raw_s[1]} columns")
            lines.append(f"  Clean layout : {clean_s[0]:,} rows x {clean_s[1]} columns")
            lines.append("-" * 72)
            for item in report:
                lines.append(f"  • {item}")
            lines.append("")

        full_log = "\n".join(lines)
        txt.insert("1.0", full_log)
        txt.config(state="disabled")

        bf = ttk.Frame(win, padding=8)
        bf.pack(fill="x")
        ttk.Button(bf, text="Copy log", command=lambda: self._copy(full_log)).pack(side="left")
        ttk.Button(bf, text="Save log...", command=lambda: self._save_text(full_log, "cleaning_log.txt")).pack(side="left", padx=6)
        ttk.Button(bf, text="Close", command=win.destroy).pack(side="right")

    # ------------------------------------------------------------------ data model
    def _auto_model(self, sel_tables):
        """Rebuild schema + guide after tables are added/removed (same output as the button)."""
        try:
            pairs, tree = self._ensure_model(sel_tables)
            self._show_model(sel_tables, pairs, tree)
        except Exception as e:  # noqa: BLE001 - show the problem instead of a stale/wrong schema
            self.model_lbl.config(text=f"Could not build the data model: {e}")

    def _ensure_model(self, tables):
        # id(d) changes when a table is reloaded, so edited files never reuse an old schema
        sig = tuple((n, id(d), len(d), tuple(d.columns)) for n, d in tables.items())
        if self.model_cache.get("sig") != sig:
            analysis = engine.get_model_analysis(tables) if len(tables) > 1 else {
                "pairs": [], "tree": [], "profiles": {}, "union_candidates": {}, "disconnected": {}
            }
            self.model_cache = {
                "sig": sig,
                "pairs": analysis.get("pairs", []),
                "tree": analysis.get("tree", []),
                "analysis": analysis,
            }
        return self.model_cache["pairs"], self.model_cache["tree"]

    def generate_schema(self):
        """Generate schema and copyable drag guide instantly from opened files using deterministic rules."""
        tables = self.selected_tables()
        if not tables:
            messagebox.showinfo(APP_NAME, "Add files and select at least one table first.")
            return
        self.model_lbl.config(text="Building schema & drag guide...", foreground="#555")
        try:
            pairs, tree = self._ensure_model(tables)
            self._show_model(tables, pairs, tree)
            self.model_lbl.config(
                text=f"✓ Schema ready: {len(tree)} relationship(s) mapped.",
                foreground="#15803d"
            )
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(APP_NAME, f"Could not generate schema:\n{e}")

    # ------------------------------------------------------------------ zoom & view controls
    def fit_to_screen(self):
        """Automatically scale and position diagram so all nodes fit inside canvas."""
        self.is_fit_mode = True
        if not self.current_model or not self.current_model[0]:
            return
        tables, tree = self.current_model
        names = list(tables)
        if not names:
            return

        cw0, ch0, gx0, gy0, mx0, my0 = 250, 150, 220, 50, 30, 30
        lay = engine.layout(tables, tree)
        max_d = max((d for d, _r in lay.values()), default=0)
        max_r = max((r for _d, r in lay.values()), default=0)
        diag_w0 = mx0 * 2 + (max_d + 1) * cw0 + max_d * gx0
        diag_h0 = my0 * 2 + (max_r + 1) * ch0 + max_r * gy0

        self.canvas.update_idletasks()
        cw_avail = self.canvas.winfo_width()
        ch_avail = self.canvas.winfo_height()
        if cw_avail < 50:
            cw_avail = 800
        if ch_avail < 50:
            ch_avail = 450

        # Margin around diagram
        pad_x, pad_y = 50, 50
        scale_x = (cw_avail - pad_x) / max(diag_w0, 1)
        scale_y = (ch_avail - pad_y) / max(diag_h0, 1)
        scale = min(scale_x, scale_y)
        self.zoom_scale = max(0.20, min(scale, 1.25))
        self._render_current_model()

    def zoom_in(self):
        """Zoom in by 20%."""
        self.is_fit_mode = False
        self.zoom_scale = min(self.zoom_scale * 1.20, 3.0)
        self._render_current_model()

    def zoom_out(self):
        """Zoom out by 20%."""
        self.is_fit_mode = False
        self.zoom_scale = max(self.zoom_scale / 1.20, 0.20)
        self._render_current_model()

    def reset_view(self):
        """Reset zoom to 100%."""
        self.is_fit_mode = False
        self.zoom_scale = 1.0
        self._render_current_model()

    def _render_current_model(self):
        if self.current_model and self.current_model[0]:
            self._draw_model(self.current_model[0], self.current_model[1])
            pct = int(round(self.zoom_scale * 100))
            if hasattr(self, "zoom_lbl"):
                self.zoom_lbl.config(text=f"{pct}%" + (" (Fit)" if self.is_fit_mode else ""))

    def _on_canvas_press(self, event):
        self.canvas.scan_mark(event.x, event.y)

    def _on_canvas_drag(self, event):
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    def _on_canvas_mousewheel(self, event):
        # Ctrl + Wheel = zoom in/out; regular wheel = vertical scroll
        if event.state & 0x0004:
            if event.delta > 0:
                self.zoom_in()
            else:
                self.zoom_out()
        else:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_canvas_resize(self, event):
        if self.is_fit_mode and self.current_model and self.current_model[0]:
            self.after_idle(self.fit_to_screen)

    def _show_model(self, tables, pairs, tree):
        self.current_model = (tables, tree)
        analysis = self.model_cache.get("analysis", {})
        disconnected = analysis.get("disconnected", {})
        junction_tables = analysis.get("junction_tables", {})
        guide = engine.guide_text(tree, disconnected, junction_tables) if len(tables) > 1 else "Only one table selected. No relationship is needed."
        self.guide_txt.delete("1.0", "end")
        self.guide_txt.insert("1.0", guide)

        conf_count = sum(1 for p in tree if p.get("Status") == "Confirmed" or p.get("Confidence", 1.0) >= 0.70)
        unc_count = sum(1 for p in tree if p.get("Status") != "Confirmed" and p.get("Confidence", 1.0) < 0.70)
        union_cand = analysis.get("union_candidates", {})
        disc_count = len([t for t in disconnected if t not in union_cand])

        note_parts = []
        if conf_count:
            note_parts.append(f"{conf_count} confirmed relationship(s)")
        if unc_count:
            note_parts.append(f"{unc_count} uncertain relationship(s) needing review")
        if disc_count:
            note_parts.append(f"{disc_count} disconnected table(s)")

        if union_cand:
            note_parts.append(f"{len(union_cand)} table(s) to UNION (see guide)")
        note = " | ".join(note_parts) if note_parts else f"{len(tree)} relationship(s) found."
        self.model_lbl.config(text=note)
        self.fit_to_screen()

    def _draw_model(self, tables, tree):
        c = self.canvas
        c.delete("all")
        names = list(tables)
        if not names:
            return

        analysis = self.model_cache.get("analysis", {})
        union_cand = analysis.get("union_candidates", {})
        disconnected = analysis.get("disconnected", {})
        junction_tables = analysis.get("junction_tables", {})
        profiles = analysis.get("profiles", {})

        scale = self.zoom_scale
        cw0, ch0, gx0, gy0, mx0, my0 = 250, 150, 220, 50, 30, 30
        cw = cw0 * scale
        ch = ch0 * scale
        gx = gx0 * scale
        gy = gy0 * scale

        lay = engine.layout(tables, tree)
        max_d = max((d for d, _r in lay.values()), default=0)
        max_r = max((r for _d, r in lay.values()), default=0)
        total_w = mx0 * 2 * scale + (max_d + 1) * cw + max_d * gx
        total_h = my0 * 2 * scale + (max_r + 1) * ch + max_r * gy

        # Canvas visible size to center diagram
        cw_avail = max(self.canvas.winfo_width(), 100)
        ch_avail = max(self.canvas.winfo_height(), 100)

        offset_x = max(0.0, (cw_avail - total_w) / 2.0)
        offset_y = max(0.0, (ch_avail - total_h) / 2.0)

        mx = mx0 * scale + offset_x
        my = my0 * scale + offset_y

        pos = {n: (mx + lay[n][0] * (cw + gx), my + lay[n][1] * (ch + gy)) for n in names}

        scroll_w = max(cw_avail, total_w + offset_x)
        scroll_h = max(ch_avail, total_h + offset_y)
        c.configure(scrollregion=(0, 0, scroll_w, scroll_h))
        if self.is_fit_mode:
            c.xview_moveto(0)
            c.yview_moveto(0)

        # Scaled fonts
        title_font = ("Segoe UI", max(7, int(round(10 * scale))), "bold")
        sub_font = ("Segoe UI", max(6, int(round(8 * scale))))
        body_font = ("Segoe UI", max(6, int(round(9 * scale))))
        rel_font = ("Segoe UI", max(6, int(round(8 * scale))))
        badge_font = ("Segoe UI", max(6, int(round(7.5 * scale))), "bold")
        head_h = max(18.0, 32.0 * scale)

        # Draw relationship lines and labels
        for p in tree:
            a, b = p["Table A"], p["Table B"]
            if a not in pos or b not in pos:
                continue
            left, right = (a, b) if lay[a][0] <= lay[b][0] else (b, a)
            sx, sy = pos[left][0] + cw, pos[left][1] + ch / 2
            ex, ey = pos[right][0], pos[right][1] + ch / 2
            mid = (sx + ex) / 2
            line_w = max(1.5, 2.5 * scale)

            is_confirmed = p.get("Status") == "Confirmed" or p.get("Confidence", 1.0) >= 0.70
            line_color = "#2563eb" if is_confirmed else "#d97706"
            dash_pattern = None if is_confirmed else (5, 3)

            if dash_pattern:
                c.create_line(sx, sy, mid, sy, mid, ey, ex, ey, smooth=True, width=line_w, fill=line_color, dash=dash_pattern)
            else:
                c.create_line(sx, sy, mid, sy, mid, ey, ex, ey, smooth=True, width=line_w, fill=line_color)

            # Pill label
            ly = (sy + ey) / 2
            if p.get("is_composite"):
                col_a = " & ".join(p.get("Fields A", []))
                col_b = " & ".join(p.get("Fields B", []))
            else:
                col_a = str(p.get("Field A", ""))
                col_b = str(p.get("Field B", ""))

            card_short = "1:1" if p.get("Cardinality") == "ONE-to-ONE" else ("1:M" if p.get("Cardinality") == "ONE-to-MANY" else "M:M")
            lbl_txt = f"{col_a} = {col_b} ({card_short})"
            if len(lbl_txt) > 42:
                lbl_txt = lbl_txt[:39] + "..."

            pill_hw = max(38 * scale, min(140 * scale, (len(lbl_txt) * 3.8 + 10) * scale))
            pill_hh = max(9 * scale, 13 * scale)

            if is_confirmed:
                pill_bg = "#eff6ff"
                pill_outline = "#93c5fd"
                pill_txt_color = "#1e40af"
            else:
                pill_bg = "#fef3c7"
                pill_outline = "#fcd34d"
                pill_txt_color = "#92400e"

            c.create_rectangle(mid - pill_hw, ly - pill_hh, mid + pill_hw, ly + pill_hh,
                               fill=pill_bg, outline=pill_outline, width=max(1.0, 1.2 * scale))
            c.create_text(mid, ly, text=lbl_txt, font=rel_font, fill=pill_txt_color)

        # Draw table cards
        for n in names:
            x, y = pos[n]
            df = tables[n]
            prof = profiles.get(n, {})
            pks = prof.get("primary_keys", [])
            key = pks[0] if pks else None

            is_union = n in union_cand
            is_disc = n in disconnected
            is_bridge = n in junction_tables

            # Card background colors based on status
            if is_union:
                head_bg = "#fef3c7"
                head_text_color = "#92400e"
                border_color = "#f59e0b"
                badge = "[Union Candidate]"
            elif is_disc:
                head_bg = "#f3f4f6"
                head_text_color = "#4b5563"
                border_color = "#9ca3af"
                badge = "[Disconnected]"
            elif is_bridge:
                head_bg = "#f0fdf4"
                head_text_color = "#166534"
                border_color = "#22c55e"
                badge = "[Bridge Table]"
            else:
                head_bg = "#dce8f7"
                head_text_color = "#1e334c"
                border_color = "#8a96a5"
                badge = ""

            card_border_w = max(1.0, 1.5 * scale)
            c.create_rectangle(x, y, x + cw, y + ch, fill="white", outline=border_color, width=card_border_w)
            c.create_rectangle(x, y, x + cw, y + head_h, fill=head_bg, outline=border_color, width=card_border_w)

            # Header text & Badge
            c.create_text(x + 10 * scale, y + head_h / 2, text=n[:24], anchor="w",
                          font=title_font, fill=head_text_color)
            if badge:
                c.create_text(x + cw - 10 * scale, y + head_h / 2, text=badge, anchor="e",
                              font=badge_font, fill=head_text_color)

            # Header subtitle: row & col counts
            c.create_text(x + 10 * scale, y + head_h + 12 * scale,
                          text=f"{len(df):,} rows - {len(df.columns)} columns", anchor="w",
                          font=sub_font, fill="#5a6574")

            # Field list
            fi_step = max(10 * scale, 15 * scale)
            fi_start_y = y + head_h + 26 * scale
            avail_h_for_fields = ch - head_h - 32 * scale
            max_fields = max(2, min(5, int(avail_h_for_fields / max(fi_step, 1))))

            cols_to_show = list(df.columns)[:max_fields]
            for fi, col in enumerate(cols_to_show):
                is_key = str(col) in pks or str(col).lower().endswith("id")
                bullet = "\u25c6 " if is_key else "\u2022 "
                c.create_text(x + 10 * scale, fi_start_y + fi * fi_step,
                              text=bullet + str(col)[:32], anchor="w",
                              font=body_font, fill="#177245" if is_key else "#303844")

            # Footer notice / key
            footer_y = y + ch - 10 * scale
            if is_union:
                target = union_cand[n]
                c.create_text(x + 10 * scale, footer_y,
                              text=f"Union with: {target[:20]}", anchor="w",
                              font=sub_font, fill="#b45309")
            elif is_disc:
                c.create_text(x + 10 * scale, footer_y,
                              text="No key match found", anchor="w",
                              font=sub_font, fill="#6b7280")
            elif is_bridge:
                parents_str = ", ".join(junction_tables[n])
                c.create_text(x + 10 * scale, footer_y,
                              text=f"Bridges: {parents_str[:22]}", anchor="w",
                              font=sub_font, fill="#166534")
            elif len(df.columns) > max_fields:
                c.create_text(x + 10 * scale, footer_y,
                              text=f"+ {len(df.columns) - max_fields} more fields", anchor="w",
                              font=sub_font, fill="#697586")
            elif key:
                c.create_text(x + 10 * scale, footer_y,
                              text=f"\u25c6 key: {key[:24]}", anchor="w",
                              font=sub_font, fill="#177245")

    # ------------------------------------------------------------------ settings
    def test_connection(self):
        cfg = self._cfg()
        self.conn_lbl.config(text="Testing...", foreground="#555")

        def work():
            try:
                models = llm.get_models(cfg["base_url"], cfg["api_key"])
                if models:
                    msg, col = "Connected. Loaded model(s): " + ", ".join(models), "#177245"
                else:
                    msg, col = "Connected, but no model is loaded. Load one in LM Studio.", "#a06000"
            except Exception as e:  # noqa: BLE001
                msg, col = f"Could not reach LM Studio: {e}", "#b00020"
            self.post(lambda: self.conn_lbl.config(text=msg, foreground=col))
        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------ solve
    def solve(self):
        question = self.q_txt.get("1.0", "end").strip()
        tables = self.selected_tables()
        if not tables:
            messagebox.showinfo(APP_NAME, "Add files and select at least one table first.")
            return
        if not question:
            messagebox.showinfo(APP_NAME, "Type the question or follow-up first.")
            return
        self._save_cfg()
        cfg = dict(self.cfg)
        self.solve_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.stopped = False

        # Clear input box and append user message to chat transcript
        self.q_txt.delete("1.0", "end")
        ts = time.strftime("%H:%M")
        exam_formatter.append_user_message(self.ans_txt, question, ts)

        self.check_lbl.config(text="")
        self.metrics_lbl.config(text="")
        self._set_progress(0.02, "Thinking...")
        threading.Thread(target=self._solve_worker, args=(question, tables, cfg), daemon=True).start()

    def stop(self):
        self.stopped = True
        if self.current_state is not None:
            self.current_state["stop"] = True

    def _run_stream(self, messages, cfg, model, limit, ptoks):
        state = llm.start(messages, cfg["base_url"], cfg["api_key"], model, limit, cfg["timeout"])
        self.current_state = state
        while not state["done"]:
            frac, text = llm.progress_estimate(state, ptoks, self.perf, limit)
            el = time.time() - state["t_start"]
            self.post(lambda f=frac, t=text, e=el: self._set_progress(f, f"{t} - elapsed {e:.0f}s"))
            time.sleep(0.25)
        return state

    def _solve_worker(self, question, tables, cfg):
        try:
            is_new_conv = len(self.chat_history) == 0
            if is_new_conv:
                self.post(lambda: self._set_progress(0.05, "Step 1/4 - Checking the table relationships..."))
                _pairs, tree = self._ensure_model(tables)
                self.post(lambda: self._set_progress(0.10, "Step 2/4 - Computing exact numbers from your data..."))
                facts, notes = engine.build_facts(tables, tree, question, max_chars=cfg["facts_budget"])
                self.last_facts = facts
                user_content = llm.build_prompt(question, facts)
            else:
                self.post(lambda: self._set_progress(0.10, "Step 1/2 - Continuing exam conversation..."))
                facts = self.last_facts
                notes = []
                user_content = (
                    f"{question}\n\n"
                    "Remember: Keep the response direct, concise, and focused on helping the student complete the practical exam task in Tableau."
                )

            # Assemble conversation message history
            messages = [{"role": "system", "content": llm.SYSTEM}]
            for turn in self.chat_history:
                messages.append({"role": turn["role"], "content": turn["content"]})
            messages.append({"role": "user", "content": user_content})

            total_chars = sum(len(m.get("content", "")) for m in messages)
            ptoks = int(total_chars / 3.5)
            self.post(lambda: self._set_progress(0.15, f"Connecting to LM Studio (prompt about {ptoks:,} tokens)..."))
            model = llm.choose_model(cfg["base_url"], cfg["api_key"], cfg["model"])
            self.post(lambda: self._set_progress(0.18, f"Asking {model}..."))
            limit = cfg["max_tokens"]
            state = self._run_stream(messages, cfg, model, limit, ptoks)
            if (not self.stopped and not state["error"] and not state["content"].strip()
                    and state["finish"] == "length"):
                limit = min(limit * 2, 8000)
                self.post(lambda: self._set_progress(0.05, f"Model used all tokens while thinking. Retrying once with {limit:,} tokens..."))
                state = self._run_stream(messages, cfg, model, limit, ptoks)
            llm.learn(state, ptoks, self.perf)
            self.post(lambda: self._show_result(state, facts, notes, question, model))
        except Exception as e:  # noqa: BLE001
            msg = self._friendly_error(str(e))
            self.post(lambda: self._show_error(msg))

    @staticmethod
    def _friendly_error(err):
        low = err.lower()
        if "connection" in low and ("refused" in low or "error" in low or "max retries" in low):
            return "LM Studio server is not reachable. Start the local server in LM Studio and load a model."
        if "context" in low or "n_ctx" in low or "too long" in low:
            return ("The prompt is too long for the model's context window. Lower 'Facts size' in Settings, "
                    "or raise the context length when loading the model in LM Studio.\n\n" + err[:400])
        return err[:700]

    def _finish_ui(self):
        self.solve_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.current_state = None

    def _show_error(self, msg):
        self._finish_ui()
        self._set_progress(0, "Failed.")
        self.status_lbl.config(foreground="#b00020")
        exam_formatter.append_assistant_message(self.ans_txt, f"⚠️ Error: {msg}")

    def _show_result(self, state, facts, notes, question, model):
        self._finish_ui()
        end = state["t_end"] or time.time()
        total = end - state["t_start"]
        if state["error"]:
            self._show_error(self._friendly_error(state["error"]))
            return
        answer = state["content"].strip()
        if self.stopped and not answer:
            self._set_progress(0, "Stopped.")
            exam_formatter.append_assistant_message(self.ans_txt, "⏹️ Request stopped.")
            return
        if not answer:
            self._show_error("The model returned no answer text. Raise 'Max output tokens' in Settings (reasoning models need 1500+).")
            return
        self._set_progress(1.0, f"Done in {total:.1f}s" + (" (stopped early)" if self.stopped else ""))
        first = (state["t_first"] or state["t_start"]) - state["t_start"]
        gen = end - (state["t_first"] or state["t_start"])
        tps = f"{state['tokens'] / gen:.1f} tok/s" if gen > 0.5 else "n/a"
        self.metrics_lbl.config(text=f"Total {total:.1f}s - first token after {first:.1f}s - {state['tokens']:,} tokens - {tps} - model {model}")

        # Update chat transcript and conversation history
        self.raw_answer = answer
        self.chat_history.append({"role": "user", "content": question})
        self.chat_history.append({"role": "assistant", "content": answer})
        exam_formatter.append_assistant_message(self.ans_txt, answer)

        bad = engine.unverified_numbers(answer, facts, question)
        if bad:
            self.check_lbl.config(foreground="#b00020", text="Check these numbers, they are not in the verified data: "
                                  + ", ".join(f"{b:,.2f}" for b in bad) + ". Confirm them in Tableau.")
        else:
            self.check_lbl.config(foreground="#177245", text="✓ Every large number in the answer matches the exact figures computed from your data."
                                  + ("  Note: " + " ".join(notes) if notes else ""))

    def show_facts(self):
        if not self.last_facts:
            messagebox.showinfo(APP_NAME, "Ask a question first.")
            return
        win = tk.Toplevel(self)
        win.title("Exact facts sent to the AI")
        win.geometry("900x600")
        t = tk.Text(win, wrap="none", font=("Consolas", 10))
        t.insert("1.0", self.last_facts)
        t.config(state="disabled")
        t.pack(fill="both", expand=True)


def main():
    try:  # sharper text on high-DPI Windows screens
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        pass
    try:
        App().mainloop()
    except Exception:  # noqa: BLE001
        text = traceback.format_exc()
        log_error(text)
        print(text)
        try:
            messagebox.showerror(APP_NAME, "The program could not start:\n\n" + text[-1500:] + "\nSaved to: " + LOG_PATH)
        except Exception:  # noqa: BLE001
            pass
        input("Press Enter to close...")
        sys.exit(1)


if __name__ == "__main__":
    main()
