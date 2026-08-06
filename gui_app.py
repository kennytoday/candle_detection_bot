"""
gui_app.py
----------
Tkinter desktop app: XAUUSD (Gold) Candlestick Pattern Scanner.

Connects to a running MetaTrader 5 terminal, pulls recent OHLC candles
for XAUUSDb (configurable), scans them with candlestick_patterns.py,
and displays:
    * an embedded candlestick chart with pattern markers
    * a sortable table of detected patterns (time / pattern / bias / close)
    * connection + auto-refresh controls

Run:
    python gui_app.py

Requires (see requirements.txt / README):
    pip install MetaTrader5 pandas numpy matplotlib
"""

from __future__ import annotations
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime

import pandas as pd
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.patches import Rectangle

import mt5_data
from candlestick_patterns import detect_all

# --------------------------------------------------------------------------
# Config / constants
# --------------------------------------------------------------------------

DEFAULT_SYMBOL = "XAUUSDb"
DEFAULT_TIMEFRAME = "M15"
DEFAULT_N_CANDLES = 200
AUTO_REFRESH_MS = 30_000  # 30 seconds

BIAS_COLORS = {
    "bullish": "#1e8f4e",
    "bearish": "#c0392b",
    "neutral": "#7f8c8d",
}

BG_DARK = "#1e1e2e"
BG_PANEL = "#27293d"
FG_TEXT = "#e6e6e6"
ACCENT = "#f5c518"  # gold accent, thematically fitting for XAUUSD
UP_COLOR = "#26a65b"
DOWN_COLOR = "#e74c3c"


# --------------------------------------------------------------------------
# Main application
# --------------------------------------------------------------------------

class PatternScannerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("XAUUSD Candlestick Pattern Scanner")
        self.root.geometry("1280x800")
        self.root.configure(bg=BG_DARK)

        self.connected = False
        self.df: pd.DataFrame | None = None
        self.signals: pd.DataFrame | None = None
        self.auto_refresh_job = None
        self.work_queue: "queue.Queue" = queue.Queue()

        self._build_style()
        self._build_layout()
        self._poll_queue()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("TFrame", background=BG_PANEL)
        style.configure("TLabel", background=BG_PANEL, foreground=FG_TEXT, font=("Segoe UI", 10))
        style.configure("Header.TLabel", background=BG_DARK, foreground=ACCENT,
                         font=("Segoe UI", 16, "bold"))
        style.configure("Status.TLabel", background=BG_DARK, foreground=FG_TEXT, font=("Segoe UI", 9))
        style.configure("TButton", font=("Segoe UI", 10, "bold"), padding=6)
        style.configure("Accent.TButton", background=ACCENT)
        style.configure("TCombobox", padding=4)
        style.configure("Treeview", background="#2f3146", fieldbackground="#2f3146",
                         foreground=FG_TEXT, rowheight=26, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        style.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "#000000")])

    def _build_layout(self):
        # ---- Header ----
        header = tk.Frame(self.root, bg=BG_DARK)
        header.pack(fill="x", padx=16, pady=(12, 4))
        ttk.Label(header, text="XAUUSD Candlestick Pattern Scanner", style="Header.TLabel").pack(side="left")
        self.status_label = ttk.Label(header, text="● Disconnected", style="Status.TLabel", foreground=DOWN_COLOR)
        self.status_label.pack(side="right")

        # ---- Controls bar ----
        controls = ttk.Frame(self.root)
        controls.pack(fill="x", padx=16, pady=8)

        ttk.Label(controls, text="Symbol:").grid(row=0, column=0, padx=(4, 4), pady=6, sticky="w")
        self.symbol_var = tk.StringVar(value=DEFAULT_SYMBOL)
        ttk.Entry(controls, textvariable=self.symbol_var, width=12).grid(row=0, column=1, padx=4)

        ttk.Label(controls, text="Timeframe:").grid(row=0, column=2, padx=(16, 4))
        self.timeframe_var = tk.StringVar(value=DEFAULT_TIMEFRAME)
        tf_combo = ttk.Combobox(controls, textvariable=self.timeframe_var, width=6,
                                 values=list(mt5_data.TIMEFRAME_MAP.keys()), state="readonly")
        tf_combo.grid(row=0, column=3, padx=4)

        ttk.Label(controls, text="Candles:").grid(row=0, column=4, padx=(16, 4))
        self.n_candles_var = tk.IntVar(value=DEFAULT_N_CANDLES)
        ttk.Spinbox(controls, from_=50, to=2000, increment=50, textvariable=self.n_candles_var,
                    width=6).grid(row=0, column=5, padx=4)

        self.connect_btn = ttk.Button(controls, text="Connect to MT5", command=self.on_connect)
        self.connect_btn.grid(row=0, column=6, padx=(24, 4))

        self.scan_btn = ttk.Button(controls, text="Fetch && Scan", command=self.on_scan, state="disabled")
        self.scan_btn.grid(row=0, column=7, padx=4)

        self.auto_refresh_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(controls, text="Auto-refresh (30s)", variable=self.auto_refresh_var,
                         command=self.on_toggle_autorefresh).grid(row=0, column=8, padx=(16, 4))

        self.export_btn = ttk.Button(controls, text="Export CSV", command=self.on_export, state="disabled")
        self.export_btn.grid(row=0, column=9, padx=(16, 4))

        ttk.Button(controls, text="Demo Data", command=self.on_demo_data).grid(row=0, column=10, padx=(16, 4))

        # ---- Body: chart (left) + signal table (right) ----
        body = ttk.Frame(self.root)
        body.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        chart_frame = ttk.Frame(body)
        chart_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self._build_chart(chart_frame)

        table_frame = ttk.Frame(body)
        table_frame.grid(row=0, column=1, sticky="nsew")
        self._build_table(table_frame)

        # ---- Footer status bar ----
        self.footer_var = tk.StringVar(value="Ready. Connect to MT5 to begin.")
        footer = ttk.Label(self.root, textvariable=self.footer_var, style="Status.TLabel")
        footer.pack(fill="x", padx=16, pady=(0, 10))

    def _build_chart(self, parent):
        self.fig = Figure(figsize=(7, 6), dpi=100, facecolor=BG_PANEL)
        self.ax = self.fig.add_subplot(111)
        self._style_axes()
        self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    def _style_axes(self):
        self.ax.set_facecolor(BG_PANEL)
        self.ax.tick_params(colors=FG_TEXT, labelsize=8)
        for spine in self.ax.spines.values():
            spine.set_color("#555770")
        self.ax.grid(True, color="#3a3c55", linewidth=0.5, alpha=0.6)

    def _build_table(self, parent):
        cols = ("time", "pattern", "bias", "close")
        self.tree = ttk.Treeview(parent, columns=cols, show="headings", height=25)
        headings = {"time": "Time", "pattern": "Pattern", "bias": "Bias", "close": "Close"}
        widths = {"time": 130, "pattern": 150, "bias": 70, "close": 80}
        for c in cols:
            self.tree.heading(c, text=headings[c])
            self.tree.column(c, width=widths[c], anchor="center")
        self.tree.tag_configure("bullish", foreground=BIAS_COLORS["bullish"])
        self.tree.tag_configure("bearish", foreground=BIAS_COLORS["bearish"])
        self.tree.tag_configure("neutral", foreground=BIAS_COLORS["neutral"])

        vsb = ttk.Scrollbar(parent, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def on_connect(self):
        self.footer_var.set("Connecting to MT5 terminal...")
        self.connect_btn.config(state="disabled")
        threading.Thread(target=self._connect_worker, daemon=True).start()

    def _connect_worker(self):
        try:
            mt5_data.connect()
            resolved = mt5_data.resolve_symbol(self.symbol_var.get())
            self.work_queue.put(("connected", resolved))
        except Exception as exc:
            self.work_queue.put(("error", str(exc)))

    def on_scan(self):
        self.footer_var.set("Fetching candles and scanning for patterns...")
        self.scan_btn.config(state="disabled")
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        try:
            df = mt5_data.fetch_ohlc(
                symbol=self.symbol_var.get(),
                timeframe=self.timeframe_var.get(),
                n_candles=int(self.n_candles_var.get()),
            )
            signals = detect_all(df)
            self.work_queue.put(("scanned", (df, signals)))
        except Exception as exc:
            self.work_queue.put(("error", str(exc)))

    def on_demo_data(self):
        """Generate a synthetic random-walk OHLC series so the GUI can be
        exercised end-to-end without a live MT5 connection."""
        self.footer_var.set("Generating synthetic demo data...")
        threading.Thread(target=self._demo_worker, daemon=True).start()

    def _demo_worker(self):
        import numpy as np
        n = int(self.n_candles_var.get())
        rng = np.random.default_rng(42)
        price = 2400.0
        rows = []
        for _ in range(n):
            drift = rng.normal(0, 3.5)
            o = price
            c = o + drift
            h = max(o, c) + abs(rng.normal(0, 1.5))
            l = min(o, c) - abs(rng.normal(0, 1.5))
            rows.append({"open": o, "high": h, "low": l, "close": c})
            price = c
        df = pd.DataFrame(rows)
        df.index = pd.date_range(end=pd.Timestamp.now().floor("min"), periods=n, freq="15min")
        signals = detect_all(df)
        self.work_queue.put(("scanned", (df, signals)))

    def on_toggle_autorefresh(self):
        if self.auto_refresh_var.get():
            self._schedule_autorefresh()
        elif self.auto_refresh_job is not None:
            self.root.after_cancel(self.auto_refresh_job)
            self.auto_refresh_job = None

    def _schedule_autorefresh(self):
        if self.connected:
            self.on_scan()
        self.auto_refresh_job = self.root.after(AUTO_REFRESH_MS, self._schedule_autorefresh)

    def on_export(self):
        if self.signals is None or self.signals.empty:
            messagebox.showinfo("Export CSV", "No signals to export yet.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile=f"xauusd_patterns_{datetime.now():%Y%m%d_%H%M%S}.csv",
        )
        if path:
            self.signals.to_csv(path, index=False)
            self.footer_var.set(f"Exported {len(self.signals)} signals to {path}")

    # ------------------------------------------------------------------
    # Background -> UI thread bridge
    # ------------------------------------------------------------------

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.work_queue.get_nowait()
                if kind == "connected":
                    self.connected = True
                    self.status_label.config(text=f"● Connected ({payload})", foreground=UP_COLOR)
                    self.connect_btn.config(state="normal", text="Reconnect")
                    self.scan_btn.config(state="normal")
                    self.footer_var.set("Connected. Click 'Fetch & Scan' to load data.")
                elif kind == "scanned":
                    self.df, self.signals = payload
                    self._render_chart()
                    self._render_table()
                    self.scan_btn.config(state="normal")
                    self.export_btn.config(state="normal")
                    n = len(self.signals) if self.signals is not None else 0
                    self.footer_var.set(
                        f"Loaded {len(self.df)} candles. {n} pattern signal(s) detected. "
                        f"Last update: {datetime.now():%H:%M:%S}"
                    )
                elif kind == "error":
                    self.connect_btn.config(state="normal")
                    self.scan_btn.config(state="normal" if self.connected else "disabled")
                    self.footer_var.set(f"Error: {payload}")
                    messagebox.showerror("Error", payload)
        except queue.Empty:
            pass
        self.root.after(150, self._poll_queue)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render_chart(self):
        if self.df is None or self.df.empty:
            return
        self.ax.clear()
        self._style_axes()

        df = self.df.tail(120)  # keep the chart readable
        x = range(len(df))

        for i, (_, row) in zip(x, df.iterrows()):
            color = UP_COLOR if row["close"] >= row["open"] else DOWN_COLOR
            # wick
            self.ax.plot([i, i], [row["low"], row["high"]], color=color, linewidth=1)
            # body
            lower = min(row["open"], row["close"])
            height = abs(row["close"] - row["open"]) or 0.01
            self.ax.add_patch(Rectangle((i - 0.3, lower), 0.6, height, color=color))

        # Mark detected patterns on the visible window
        if self.signals is not None and not self.signals.empty:
            visible_times = list(df.index)
            time_to_x = {t: i for i, t in enumerate(visible_times)}
            for _, sig in self.signals.iterrows():
                if sig["time"] in time_to_x:
                    xi = time_to_x[sig["time"]]
                    y = df.loc[sig["time"], "high"] * 1.001
                    color = BIAS_COLORS.get(sig["bias"], "#ffffff")
                    self.ax.annotate(
                        sig["pattern"], xy=(xi, y), fontsize=6.5, color=color,
                        rotation=60, ha="left", va="bottom",
                    )
                    self.ax.plot(xi, y, marker="v", color=color, markersize=5)

        step = max(1, len(df) // 10)
        tick_positions = list(range(0, len(df), step))
        tick_labels = [df.index[i].strftime("%m-%d %H:%M") for i in tick_positions]
        self.ax.set_xticks(tick_positions)
        self.ax.set_xticklabels(tick_labels, rotation=30, ha="right")
        self.ax.set_title(f"{self.symbol_var.get()} — {self.timeframe_var.get()}",
                           color=FG_TEXT, fontsize=11)
        self.fig.tight_layout()
        self.canvas.draw_idle()

    def _render_table(self):
        self.tree.delete(*self.tree.get_children())
        if self.signals is None or self.signals.empty:
            return
        # Most recent first
        for _, row in self.signals.sort_values("time", ascending=False).iterrows():
            self.tree.insert(
                "", "end",
                values=(row["time"].strftime("%Y-%m-%d %H:%M"), row["pattern"],
                        row["bias"], f"{row['close']:.2f}"),
                tags=(row["bias"],),
            )

    # ------------------------------------------------------------------

    def on_close(self):
        if self.auto_refresh_job is not None:
            self.root.after_cancel(self.auto_refresh_job)
        if self.connected:
            mt5_data.disconnect()
        self.root.destroy()


def main():
    root = tk.Tk()
    app = PatternScannerApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
