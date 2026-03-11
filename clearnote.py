#!/usr/bin/env python3
"""
ClearNote - A lightweight, cross-platform text editor
Features: Find/Replace, line numbers, status bar with encoding/line-ending detection
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, font
import os
import sys
import re
import chardet

# ── Encoding detection ──────────────────────────────────────────────────────

def detect_file_info(raw_bytes: bytes) -> dict:
    """Detect encoding, BOM, and line-ending style from raw bytes."""
    info = {"encoding": "UTF-8", "bom": False, "line_endings": "LF", "confidence": 1.0}

    # BOM detection
    if raw_bytes.startswith(b'\xff\xfe\x00\x00') or raw_bytes.startswith(b'\x00\x00\xfe\xff'):
        info["encoding"] = "UTF-32"
        info["bom"] = True
    elif raw_bytes.startswith(b'\xff\xfe'):
        info["encoding"] = "UTF-16 LE"
        info["bom"] = True
    elif raw_bytes.startswith(b'\xfe\xff'):
        info["encoding"] = "UTF-16 BE"
        info["bom"] = True
    elif raw_bytes.startswith(b'\xef\xbb\xbf'):
        info["encoding"] = "UTF-8 BOM"
        info["bom"] = True
    else:
        # Try chardet for best-effort detection
        result = chardet.detect(raw_bytes)
        if result and result.get("encoding"):
            enc = result["encoding"].upper()
            conf = result.get("confidence", 0)
            info["confidence"] = conf
            # Normalise common names
            if enc in ("ASCII", "UTF-8"):
                info["encoding"] = "UTF-8"
            elif enc == "UTF-8-SIG":
                info["encoding"] = "UTF-8 BOM"
                info["bom"] = True
            elif enc in ("WINDOWS-1252", "CP1252"):
                info["encoding"] = "Windows-1252"
            elif enc in ("ISO-8859-1", "LATIN-1"):
                info["encoding"] = "ISO-8859-1"
            else:
                info["encoding"] = enc

    # Line ending detection (work on raw bytes)
    crlf = raw_bytes.count(b'\r\n')
    cr   = raw_bytes.count(b'\r') - crlf
    lf   = raw_bytes.count(b'\n') - crlf
    if crlf >= lf and crlf >= cr and crlf > 0:
        info["line_endings"] = "CRLF"
    elif cr > lf and cr > 0:
        info["line_endings"] = "CR"
    else:
        info["line_endings"] = "LF"

    return info


# ── Find / Replace dialog ────────────────────────────────────────────────────

class FindReplaceDialog(tk.Toplevel):
    def __init__(self, parent, text_widget):
        super().__init__(parent)
        self.text = text_widget
        self.title("Find / Replace")
        self.resizable(False, False)
        self.transient(parent)

        self._last_search = ""
        self._search_results = []
        self._current_idx = -1

        PAD = dict(padx=6, pady=4)

        # ── Row 0: Find
        tk.Label(self, text="Find:", anchor="e", width=8).grid(row=0, column=0, **PAD)
        self.find_var = tk.StringVar()
        self.find_entry = tk.Entry(self, textvariable=self.find_var, width=32)
        self.find_entry.grid(row=0, column=1, columnspan=2, **PAD, sticky="ew")
        self.find_entry.bind("<Return>", lambda e: self.find_next())

        # ── Row 1: Replace
        tk.Label(self, text="Replace:", anchor="e", width=8).grid(row=1, column=0, **PAD)
        self.replace_var = tk.StringVar()
        tk.Entry(self, textvariable=self.replace_var, width=32).grid(row=1, column=1, columnspan=2, **PAD, sticky="ew")

        # ── Row 2: Options
        self.case_var = tk.BooleanVar(value=False)
        self.regex_var = tk.BooleanVar(value=False)
        self.wrap_var  = tk.BooleanVar(value=True)
        tk.Checkbutton(self, text="Case sensitive", variable=self.case_var).grid(row=2, column=0, columnspan=2, sticky="w", padx=6)
        tk.Checkbutton(self, text="Regex", variable=self.regex_var).grid(row=2, column=1, sticky="w")
        tk.Checkbutton(self, text="Wrap", variable=self.wrap_var).grid(row=2, column=2, sticky="w")

        # ── Row 3-6: Buttons
        btn_cfg = dict(width=14, pady=2)
        tk.Button(self, text="Find Next",    command=self.find_next,    **btn_cfg).grid(row=3, column=1, **PAD, sticky="ew")
        tk.Button(self, text="Find Prev",    command=self.find_prev,    **btn_cfg).grid(row=3, column=2, **PAD, sticky="ew")
        tk.Button(self, text="Replace",      command=self.replace_one,  **btn_cfg).grid(row=4, column=1, **PAD, sticky="ew")
        tk.Button(self, text="Replace All",  command=self.replace_all,  **btn_cfg).grid(row=4, column=2, **PAD, sticky="ew")
        tk.Button(self, text="Close",        command=self.destroy,      **btn_cfg).grid(row=5, column=1, columnspan=2, **PAD)

        self.status_var = tk.StringVar()
        tk.Label(self, textvariable=self.status_var, fg="grey40", font=("TkDefaultFont", 8)).grid(
            row=6, column=0, columnspan=3, padx=6, pady=2, sticky="w")

        self.find_entry.focus_set()

        # Highlight tag
        self.text.tag_configure("highlight_all", background="#ffe082")
        self.text.tag_configure("highlight_cur", background="#ff6f00", foreground="white")

    # ── helpers ─────────────────────────────────────────────────────────────

    def _build_pattern(self):
        term = self.find_var.get()
        if not term:
            return None
        flags = 0 if self.case_var.get() else re.IGNORECASE
        try:
            return re.compile(term if self.regex_var.get() else re.escape(term), flags)
        except re.error as e:
            self.status_var.set(f"Regex error: {e}")
            return None

    def _collect_matches(self, pattern):
        content = self.text.get("1.0", "end-1c")
        return list(pattern.finditer(content))

    def _offset_to_index(self, offset):
        content = self.text.get("1.0", "end-1c")
        line = content[:offset].count('\n') + 1
        col  = offset - content[:offset].rfind('\n') - 1
        return f"{line}.{col}"

    def _highlight_all(self, matches):
        self.text.tag_remove("highlight_all", "1.0", "end")
        self.text.tag_remove("highlight_cur", "1.0", "end")
        for m in matches:
            s = self._offset_to_index(m.start())
            e = self._offset_to_index(m.end())
            self.text.tag_add("highlight_all", s, e)

    def _highlight_current(self, match):
        self.text.tag_remove("highlight_cur", "1.0", "end")
        s = self._offset_to_index(match.start())
        e = self._offset_to_index(match.end())
        self.text.tag_add("highlight_cur", s, e)
        self.text.see(s)
        self.text.mark_set("insert", s)

    def _find_direction(self, forward=True):
        pattern = self._build_pattern()
        if pattern is None:
            return
        matches = self._collect_matches(pattern)
        if not matches:
            self.status_var.set("No matches found.")
            self._highlight_all([])
            return

        self._highlight_all(matches)
        # Current cursor offset
        cursor = self.text.index("insert")
        line, col = map(int, cursor.split('.'))
        content = self.text.get("1.0", "end-1c")
        lines = content.split('\n')
        offset = sum(len(l) + 1 for l in lines[:line - 1]) + col

        if forward:
            for i, m in enumerate(matches):
                if m.start() > offset:
                    self._highlight_current(m)
                    self.status_var.set(f"Match {i+1} of {len(matches)}")
                    return
            if self.wrap_var.get():
                self._highlight_current(matches[0])
                self.status_var.set(f"Wrapped — Match 1 of {len(matches)}")
            else:
                self.status_var.set("No more matches.")
        else:
            for i, m in reversed(list(enumerate(matches))):
                if m.end() < offset:
                    self._highlight_current(m)
                    self.status_var.set(f"Match {i+1} of {len(matches)}")
                    return
            if self.wrap_var.get():
                self._highlight_current(matches[-1])
                self.status_var.set(f"Wrapped — Match {len(matches)} of {len(matches)}")
            else:
                self.status_var.set("No more matches.")

    def find_next(self): self._find_direction(forward=True)
    def find_prev(self): self._find_direction(forward=False)

    def replace_one(self):
        pattern = self._build_pattern()
        if pattern is None:
            return
        # Replace only if current selection matches
        try:
            sel_start = self.text.index("sel.first")
            sel_end   = self.text.index("sel.last")
            selected  = self.text.get(sel_start, sel_end)
            if pattern.fullmatch(selected):
                replacement = pattern.sub(self.replace_var.get(), selected)
                self.text.delete(sel_start, sel_end)
                self.text.insert(sel_start, replacement)
                self.status_var.set("Replaced 1 occurrence.")
                self.find_next()
                return
        except tk.TclError:
            pass
        self.find_next()

    def replace_all(self):
        pattern = self._build_pattern()
        if pattern is None:
            return
        content = self.text.get("1.0", "end-1c")
        new_content, count = pattern.subn(self.replace_var.get(), content)
        if count:
            self.text.delete("1.0", "end")
            self.text.insert("1.0", new_content)
            self.status_var.set(f"Replaced {count} occurrence(s).")
        else:
            self.status_var.set("No matches found.")


# ── Line-number canvas ───────────────────────────────────────────────────────

class LineNumbers(tk.Canvas):
    def __init__(self, parent, text_widget, **kwargs):
        super().__init__(parent, **kwargs)
        self._font = None
        self.text = None
        self.bind("<ButtonRelease-1>", self._on_click)
        if text_widget is not None:
            self.attach(text_widget)

    def attach(self, text_widget):
        self.text = text_widget
        self._font = font.Font(font=text_widget.cget("font"))

    def _on_click(self, event):
        """Click on line number selects that line."""
        index = self.text.index(f"@0,{event.y}")
        line = index.split('.')[0]
        self.text.tag_remove("sel", "1.0", "end")
        self.text.tag_add("sel", f"{line}.0", f"{line}.end")
        self.text.mark_set("insert", f"{line}.0")

    def redraw(self, *_):
        self.delete("all")
        i = self.text.index("@0,0")
        while True:
            dline = self.text.dlineinfo(i)
            if dline is None:
                break
            y = dline[1]
            linenum = str(i).split('.')[0]
            self.create_text(
                self.winfo_width() - 6, y,
                anchor="ne", text=linenum,
                font=self._font, fill="#888888"
            )
            i = self.text.index(f"{i}+1line")
            if self.text.compare(i, "==", "end"):
                break


# ── Main Editor ──────────────────────────────────────────────────────────────

class ClearNote(tk.Tk):

    APP_NAME = "ClearNote"
    VERSION  = "1.0"

    def __init__(self):
        super().__init__()
        self.title(self.APP_NAME)
        self.geometry("960x680")
        self.minsize(500, 300)

        # State
        self._filepath     = None
        self._modified     = False
        self._file_info    = {"encoding": "UTF-8", "line_endings": "LF", "bom": False}
        self._find_dialog  = None

        self._setup_style()
        self._build_menu()
        self._build_ui()
        self._bind_events()
        self._update_status()
        self._schedule_line_update()

        # Handle file passed on CLI
        if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
            self._open_file(sys.argv[1])

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Style ────────────────────────────────────────────────────────────────

    def _setup_style(self):
        self.configure(bg="#1e1e2e")
        self._editor_bg   = "#1e1e2e"
        self._editor_fg   = "#cdd6f4"
        self._sel_bg      = "#313244"
        self._cursor_col  = "#f5c2e7"
        self._lineno_bg   = "#181825"
        self._lineno_fg   = "#585b70"
        self._status_bg   = "#11111b"
        self._status_fg   = "#a6adc8"
        self._menu_bg     = "#1e1e2e"
        self._menu_fg     = "#cdd6f4"
        self._editor_font = ("JetBrains Mono", 11)   if self._font_exists("JetBrains Mono")   else \
                            ("Consolas", 11)          if self._font_exists("Consolas")         else \
                            ("Menlo", 11)             if self._font_exists("Menlo")            else \
                            ("DejaVu Sans Mono", 11)  if self._font_exists("DejaVu Sans Mono") else \
                            ("Liberation Mono", 11)   if self._font_exists("Liberation Mono")  else \
                            ("Courier New", 11)

    def _font_exists(self, name):
        return name in font.families()

    # ── Menu ─────────────────────────────────────────────────────────────────

    def _build_menu(self):
        menubar = tk.Menu(self, bg=self._menu_bg, fg=self._menu_fg,
                          activebackground="#313244", activeforeground="#cdd6f4",
                          tearoff=False, borderwidth=0)
        self.configure(menu=menubar)

        def m(label):
            return tk.Menu(menubar, bg=self._menu_bg, fg=self._menu_fg,
                           activebackground="#313244", activeforeground="#cdd6f4",
                           tearoff=False)

        # File
        file_menu = m("File")
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="New",              command=self._new,              accelerator="Ctrl+N")
        file_menu.add_command(label="Open…",            command=self._open,             accelerator="Ctrl+O")
        file_menu.add_command(label="Save",             command=self._save,             accelerator="Ctrl+S")
        file_menu.add_command(label="Save As…",         command=self._save_as,         accelerator="Ctrl+Shift+S")
        file_menu.add_separator()
        file_menu.add_command(label="Exit",             command=self._on_close)

        # Edit
        edit_menu = m("Edit")
        menubar.add_cascade(label="Edit", menu=edit_menu)
        edit_menu.add_command(label="Undo",             command=lambda: self.text.edit_undo(),  accelerator="Ctrl+Z")
        edit_menu.add_command(label="Redo",             command=lambda: self.text.edit_redo(),  accelerator="Ctrl+Y")
        edit_menu.add_separator()
        edit_menu.add_command(label="Cut",              command=lambda: self.text.event_generate("<<Cut>>"),   accelerator="Ctrl+X")
        edit_menu.add_command(label="Copy",             command=lambda: self.text.event_generate("<<Copy>>"),  accelerator="Ctrl+C")
        edit_menu.add_command(label="Paste",            command=lambda: self.text.event_generate("<<Paste>>"), accelerator="Ctrl+V")
        edit_menu.add_separator()
        edit_menu.add_command(label="Select All",       command=lambda: self.text.tag_add("sel","1.0","end"),  accelerator="Ctrl+A")
        edit_menu.add_separator()
        edit_menu.add_command(label="Find / Replace…",  command=self._open_find_replace, accelerator="Ctrl+H")
        edit_menu.add_command(label="Find Next",        command=lambda: self._find_dialog and self._find_dialog.find_next(), accelerator="F3")

        # View
        view_menu = m("View")
        menubar.add_cascade(label="View", menu=view_menu)
        self._wordwrap_var = tk.BooleanVar(value=True)
        view_menu.add_checkbutton(label="Word Wrap", variable=self._wordwrap_var, command=self._toggle_wrap)
        self._lineno_var = tk.BooleanVar(value=True)
        view_menu.add_checkbutton(label="Line Numbers", variable=self._lineno_var, command=self._toggle_line_numbers)

        # Format → Line Endings submenu
        format_menu = m("Format")
        menubar.add_cascade(label="Format", menu=format_menu)
        le_menu = tk.Menu(format_menu, bg=self._menu_bg, fg=self._menu_fg,
                          activebackground="#313244", activeforeground="#cdd6f4", tearoff=False)
        format_menu.add_cascade(label="Line Endings", menu=le_menu)
        self._le_var = tk.StringVar(value="LF")
        for le in ("LF", "CRLF", "CR"):
            le_menu.add_radiobutton(label=le, variable=self._le_var, value=le,
                                    command=self._change_line_endings)

        # Encoding submenu
        enc_menu = tk.Menu(format_menu, bg=self._menu_bg, fg=self._menu_fg,
                           activebackground="#313244", activeforeground="#cdd6f4", tearoff=False)
        format_menu.add_cascade(label="Encoding", menu=enc_menu)
        self._enc_var = tk.StringVar(value="UTF-8")
        for enc in ("UTF-8", "UTF-8 BOM", "UTF-16 LE", "UTF-16 BE", "Windows-1252", "ISO-8859-1"):
            enc_menu.add_radiobutton(label=enc, variable=self._enc_var, value=enc)

        # Help
        help_menu = m("Help")
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label=f"About {self.APP_NAME}", command=self._about)

    # ── UI Layout ────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Main pane
        self._main_frame = tk.Frame(self, bg=self._editor_bg)
        self._main_frame.pack(fill="both", expand=True)

        # Line numbers
        self._lineno_canvas = LineNumbers(
            self._main_frame, None,
            width=52, bg=self._lineno_bg, bd=0, highlightthickness=0
        )
        self._lineno_canvas.pack(side="left", fill="y")

        # Divider
        self._divider = tk.Frame(self._main_frame, bg="#313244", width=1)
        self._divider.pack(side="left", fill="y")

        # Text + scrollbars
        text_frame = tk.Frame(self._main_frame, bg=self._editor_bg)
        text_frame.pack(side="left", fill="both", expand=True)

        v_scroll = tk.Scrollbar(text_frame, orient="vertical", bg="#313244",
                                 troughcolor=self._lineno_bg, activebackground="#585b70")
        v_scroll.pack(side="right", fill="y")

        self._h_scroll = tk.Scrollbar(text_frame, orient="horizontal", bg="#313244",
                                       troughcolor=self._lineno_bg, activebackground="#585b70")
        self._h_scroll.pack(side="bottom", fill="x")
        self._h_scroll.pack_forget()   # hidden while word-wrap on

        self.text = tk.Text(
            text_frame,
            bg=self._editor_bg, fg=self._editor_fg,
            insertbackground=self._cursor_col,
            selectbackground=self._sel_bg, selectforeground=self._editor_fg,
            font=self._editor_font,
            wrap="word",
            undo=True, autoseparators=True, maxundo=-1,
            relief="flat", bd=0, padx=10, pady=8,
            spacing1=2, spacing3=2,
            yscrollcommand=v_scroll.set,
            xscrollcommand=self._h_scroll.set,
            highlightthickness=0,
            insertwidth=2,
        )
        self.text.pack(fill="both", expand=True)

        v_scroll.config(command=self.text.yview)
        self._h_scroll.config(command=self.text.xview)

        # Wire line numbers now that text exists
        self._lineno_canvas.attach(self.text)

        # Status bar
        status_frame = tk.Frame(self, bg=self._status_bg, height=22)
        status_frame.pack(fill="x", side="bottom")
        status_frame.pack_propagate(False)

        status_inner = tk.Frame(status_frame, bg=self._status_bg)
        status_inner.pack(fill="both", expand=True, padx=8)

        lbl_cfg = dict(bg=self._status_bg, fg=self._status_fg,
                       font=("TkDefaultFont", 8), anchor="w")

        self._status_pos    = tk.Label(status_inner, text="Ln 1, Col 1", **lbl_cfg)
        self._status_chars  = tk.Label(status_inner, text="0 chars", **lbl_cfg)
        self._status_lines  = tk.Label(status_inner, text="1 line", **lbl_cfg)
        self._status_le     = tk.Label(status_inner, text="LF", **lbl_cfg)
        self._status_enc    = tk.Label(status_inner, text="UTF-8", **lbl_cfg)
        self._status_mod    = tk.Label(status_inner, text="", fg="#f38ba8", bg=self._status_bg,
                                        font=("TkDefaultFont", 8))

        sep_cfg = dict(bg="#313244", width=1, relief="flat")
        def sep(): return tk.Frame(status_inner, **sep_cfg)

        for w in (self._status_pos, sep(), self._status_chars, sep(),
                  self._status_lines, sep(), self._status_le, sep(),
                  self._status_enc, sep(), self._status_mod):
            w.pack(side="left", padx=4, fill="y")

    # ── Events / Bindings ────────────────────────────────────────────────────

    def _bind_events(self):
        self.bind_all("<Control-n>",       lambda e: self._new())
        self.bind_all("<Control-N>",       lambda e: self._new())
        self.bind_all("<Control-o>",       lambda e: self._open())
        self.bind_all("<Control-O>",       lambda e: self._open())
        self.bind_all("<Control-s>",       lambda e: self._save())
        self.bind_all("<Control-S>",       lambda e: self._save_as())
        self.bind_all("<Control-h>",       lambda e: self._open_find_replace())
        self.bind_all("<Control-H>",       lambda e: self._open_find_replace())
        self.bind_all("<Control-f>",       lambda e: self._open_find_replace())
        self.bind_all("<Control-F>",       lambda e: self._open_find_replace())
        self.bind_all("<F3>",              lambda e: self._find_next_shortcut())
        self.text.bind("<<Modified>>",     self._on_text_modified)
        self.text.bind("<KeyRelease>",     self._update_status)
        self.text.bind("<ButtonRelease>",  self._update_status)
        self.text.bind("<Configure>",      self._lineno_canvas.redraw)

    def _on_text_modified(self, *_):
        self._modified = True
        self._update_title()
        self._update_status()
        self.text.edit_modified(False)

    def _schedule_line_update(self):
        self._lineno_canvas.redraw()
        self.after(150, self._schedule_line_update)

    def _find_next_shortcut(self):
        if self._find_dialog and self._find_dialog.winfo_exists():
            self._find_dialog.find_next()
        else:
            self._open_find_replace()

    # ── Status + Title ────────────────────────────────────────────────────────

    def _update_title(self):
        name  = os.path.basename(self._filepath) if self._filepath else "Untitled"
        dirty = " ●" if self._modified else ""
        self.title(f"{name}{dirty} — {self.APP_NAME}")

    def _update_status(self, *_):
        idx  = self.text.index("insert")
        line, col = map(int, idx.split('.'))
        content = self.text.get("1.0", "end-1c")
        chars   = len(content)
        lines   = content.count('\n') + 1 if content else 1

        self._status_pos.config(text=f"Ln {line}, Col {col + 1}")
        self._status_chars.config(text=f"{chars:,} chars")
        self._status_lines.config(text=f"{lines:,} {'line' if lines == 1 else 'lines'}")
        self._status_le.config(text=self._file_info.get("line_endings", "LF"))
        enc = self._file_info.get("encoding", "UTF-8")
        self._status_enc.config(text=enc)
        self._status_mod.config(text="Modified" if self._modified else "")

    # ── Toggle helpers ────────────────────────────────────────────────────────

    def _toggle_wrap(self):
        if self._wordwrap_var.get():
            self.text.config(wrap="word")
            self._h_scroll.pack_forget()
        else:
            self.text.config(wrap="none")
            self._h_scroll.pack(side="bottom", fill="x")

    def _toggle_line_numbers(self):
        if self._lineno_var.get():
            self._lineno_canvas.pack(side="left", fill="y", before=self._divider)
            self._divider.pack(side="left", fill="y", before=self.text.master)
        else:
            self._lineno_canvas.pack_forget()
            self._divider.pack_forget()

    def _change_line_endings(self):
        self._file_info["line_endings"] = self._le_var.get()
        self._modified = True
        self._update_status()
        self._update_title()

    # ── File operations ───────────────────────────────────────────────────────

    def _confirm_discard(self) -> bool:
        if not self._modified:
            return True
        name = os.path.basename(self._filepath) if self._filepath else "Untitled"
        ans  = messagebox.askyesnocancel("Unsaved Changes",
                                          f"'{name}' has unsaved changes.\nSave before closing?",
                                          parent=self)
        if ans is None:
            return False
        if ans:
            return self._save()
        return True

    def _new(self):
        if not self._confirm_discard():
            return
        self.text.delete("1.0", "end")
        self._filepath  = None
        self._modified  = False
        self._file_info = {"encoding": "UTF-8", "line_endings": "LF", "bom": False}
        self.text.edit_reset()
        self._update_title()
        self._update_status()

    def _open(self):
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(
            title="Open File",
            filetypes=[("Text Files", "*.txt *.md *.csv *.log *.ini *.cfg *.py *.js *.ts *.html *.css *.json *.xml *.yaml *.yml *.sh *.bat *.ps1"),
                       ("All Files", "*.*")]
        )
        if path:
            self._open_file(path)

    def _open_file(self, path: str):
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except OSError as e:
            messagebox.showerror("Open Error", str(e))
            return

        info = detect_file_info(raw)
        self._file_info = info

        # Decode
        enc_map = {
            "UTF-8": "utf-8", "UTF-8 BOM": "utf-8-sig",
            "UTF-16 LE": "utf-16-le", "UTF-16 BE": "utf-16-be",
            "UTF-32": "utf-32",
            "Windows-1252": "cp1252", "ISO-8859-1": "latin-1",
        }
        py_enc = enc_map.get(info["encoding"], info["encoding"].lower())
        try:
            text = raw.decode(py_enc, errors="replace")
        except (LookupError, UnicodeDecodeError):
            text = raw.decode("utf-8", errors="replace")

        # Normalise line endings to LF for the editor
        text = text.replace('\r\n', '\n').replace('\r', '\n')

        self.text.delete("1.0", "end")
        self.text.insert("1.0", text)
        self.text.edit_reset()

        self._filepath  = path
        self._modified  = False
        self._enc_var.set(info["encoding"])
        self._le_var.set(info["line_endings"])
        self._update_title()
        self._update_status()
        self.text.mark_set("insert", "1.0")
        self.text.see("1.0")

    def _save(self) -> bool:
        if self._filepath:
            return self._write_file(self._filepath)
        return self._save_as()

    def _save_as(self) -> bool:
        path = filedialog.asksaveasfilename(
            title="Save As",
            defaultextension=".txt",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")]
        )
        if path:
            return self._write_file(path)
        return False

    def _write_file(self, path: str) -> bool:
        content = self.text.get("1.0", "end-1c")

        # Apply chosen line endings
        le = self._le_var.get()
        if le == "CRLF":
            content = content.replace('\n', '\r\n')
        elif le == "CR":
            content = content.replace('\n', '\r')

        # Encode
        enc_str = self._enc_var.get()
        enc_map = {
            "UTF-8": "utf-8", "UTF-8 BOM": "utf-8-sig",
            "UTF-16 LE": "utf-16-le", "UTF-16 BE": "utf-16-be",
            "UTF-32": "utf-32",
            "Windows-1252": "cp1252", "ISO-8859-1": "latin-1",
        }
        py_enc = enc_map.get(enc_str, "utf-8")

        try:
            raw = content.encode(py_enc, errors="replace")
            with open(path, "wb") as f:
                f.write(raw)
        except (OSError, LookupError) as e:
            messagebox.showerror("Save Error", str(e))
            return False

        self._filepath   = path
        self._modified   = False
        self._file_info["encoding"]     = enc_str
        self._file_info["line_endings"] = le
        self._update_title()
        self._update_status()
        return True

    # ── Find / Replace ────────────────────────────────────────────────────────

    def _open_find_replace(self):
        if self._find_dialog and self._find_dialog.winfo_exists():
            self._find_dialog.lift()
            self._find_dialog.find_entry.focus_set()
        else:
            self._find_dialog = FindReplaceDialog(self, self.text)

    # ── Close ─────────────────────────────────────────────────────────────────

    def _on_close(self):
        if self._confirm_discard():
            self.destroy()

    # ── About ─────────────────────────────────────────────────────────────────

    def _about(self):
        messagebox.showinfo(
            f"About {self.APP_NAME}",
            f"{self.APP_NAME} v{self.VERSION}\n"
            "A clean, cross-platform text editor.\n\n"
            "Features:\n"
            "  • Encoding detection (UTF-8/16/32, Windows-1252…)\n"
            "  • Line ending detection & conversion (LF/CRLF/CR)\n"
            "  • Find & Replace with regex support\n"
            "  • Line numbers, word wrap\n"
            "  • Status bar with char count & file info\n\n"
            "No telemetry. No bloat.",
            parent=self
        )


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = ClearNote()
    app.mainloop()
