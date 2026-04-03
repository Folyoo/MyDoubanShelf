from __future__ import annotations

import argparse
import queue
import threading
import traceback
from pathlib import Path
from tkinter import BooleanVar, StringVar, Tk, filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from douban_exporter import (
    DEFAULT_CATEGORIES,
    DEFAULT_STATUSES,
    DoubanExportError,
    DoubanExporter,
    open_in_file_explorer,
    parse_comma_separated_values,
)


class ExportApp(Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("\u8c46\u74e3\u8bb0\u5f55\u5bfc\u51fa")
        self.geometry("900x700")
        self.minsize(760, 600)

        self.account_var = StringVar()
        self.output_dir_var = StringVar(value=str((Path.cwd() / "exports").resolve()))
        self.incremental_var = BooleanVar(value=True)
        self.status_var = StringVar(value="\u7b49\u5f85\u5f00\u59cb")
        self.worker_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.export_button: ttk.Button | None = None
        self.open_button: ttk.Button | None = None
        self.last_output_dir: Path | None = None

        self._build_layout()
        self.after(120, self._poll_worker_queue)

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        root = ttk.Frame(self, padding=16)
        root.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(4, weight=1)

        ttk.Label(root, text="\u8c46\u74e3\u8bb0\u5f55\u5bfc\u51fa", font=("Microsoft YaHei UI", 18, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(
            root,
            text="\u8f93\u5165\u8c46\u74e3\u8d26\u53f7\u6216\u4e3b\u9875\u94fe\u63a5\uff0c\u6293\u53d6\u6807\u8bb0\u4fe1\u606f\uff0c\u5e76\u751f\u6210\u5206\u7c7b\u8868\u548c\u7f51\u9875\uff0c\u53cc\u51fb\u6253\u5f00\u7ed3\u679c\u76ee\u5f55\u4e0b\u7684index.html\u67e5\u770b\u3002",
            wraplength=820,
            justify="left",
        ).grid(row=1, column=0, sticky="we", pady=(8, 16))

        form = ttk.LabelFrame(root, text="\u5bfc\u51fa\u53c2\u6570", padding=14)
        form.grid(row=2, column=0, sticky="nsew")
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="\u8c46\u74e3\u8d26\u53f7 / \u94fe\u63a5").grid(row=0, column=0, sticky="w", pady=(0, 10))
        ttk.Entry(form, textvariable=self.account_var).grid(row=0, column=1, sticky="we", pady=(0, 10))

        ttk.Label(form, text="\u5bfc\u51fa\u76ee\u5f55").grid(row=1, column=0, sticky="w", pady=(0, 10))
        output_row = ttk.Frame(form)
        output_row.grid(row=1, column=1, sticky="we", pady=(0, 10))
        output_row.columnconfigure(0, weight=1)
        ttk.Entry(output_row, textvariable=self.output_dir_var).grid(row=0, column=0, sticky="we")
        ttk.Button(output_row, text="\u9009\u62e9\u76ee\u5f55", command=self._choose_output_dir).grid(row=0, column=1, padx=(8, 0))

        ttk.Label(form, text="\u66f4\u65b0\u65b9\u5f0f").grid(row=2, column=0, sticky="w", pady=(0, 10))
        ttk.Checkbutton(
            form,
            text="\u4f18\u5148\u590d\u7528\u4e0a\u6b21\u5bfc\u51fa\uff0c\u53ea\u66f4\u65b0\u5dee\u5f02\u90e8\u5206\uff08\u66f4\u5feb\uff09",
            variable=self.incremental_var,
        ).grid(row=2, column=1, sticky="w", pady=(0, 10))

        ttk.Label(form, text="Cookie\uff08\u53ef\u9009\uff09").grid(row=3, column=0, sticky="nw")
        ttk.Label(
            form,
            text="\u5982\u679c\u516c\u5f00\u9875\u9762\u6293\u4e0d\u5230\uff0c\u53ef\u4ee5\u628a\u6d4f\u89c8\u5668\u91cc\u7684\u8c46\u74e3 Cookie \u8d34\u5230\u8fd9\u91cc\u3002\u5de5\u5177\u53ea\u5728\u672c\u6b21\u5bfc\u51fa\u4e2d\u4f7f\u7528\uff0c\u4e0d\u4f1a\u5355\u72ec\u4fdd\u5b58\u3002",
            wraplength=660,
            justify="left",
        ).grid(row=3, column=1, sticky="we")

        self.cookie_text = ScrolledText(form, height=6, wrap="word")
        self.cookie_text.grid(row=4, column=1, sticky="nsew", pady=(8, 0))

        action_row = ttk.Frame(root)
        action_row.grid(row=3, column=0, sticky="we", pady=(16, 12))
        action_row.columnconfigure(1, weight=1)

        self.export_button = ttk.Button(action_row, text="\u5f00\u59cb\u5bfc\u51fa", command=self._start_export)
        self.export_button.grid(row=0, column=0, sticky="w")
        self.open_button = ttk.Button(action_row, text="\u6253\u5f00\u7ed3\u679c\u76ee\u5f55", command=self._open_output_dir, state="disabled")
        self.open_button.grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Label(action_row, textvariable=self.status_var).grid(row=0, column=2, sticky="e")

        log_frame = ttk.LabelFrame(root, text="\u8fd0\u884c\u65e5\u5fd7", padding=12)
        log_frame.grid(row=4, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = ScrolledText(log_frame, wrap="word")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.log_text.configure(state="disabled")

    def _choose_output_dir(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.output_dir_var.get() or str(Path.cwd()))
        if selected:
            self.output_dir_var.set(selected)

    def _start_export(self) -> None:
        account_input = self.account_var.get().strip()
        output_dir = self.output_dir_var.get().strip()
        cookie = self.cookie_text.get("1.0", "end").strip()
        incremental = self.incremental_var.get()
        if not account_input:
            messagebox.showerror("\u7f3a\u5c11\u8d26\u53f7", "\u8bf7\u5148\u8f93\u5165\u8c46\u74e3\u8d26\u53f7\u6216\u4e3b\u9875\u94fe\u63a5\u3002")
            return
        if not output_dir:
            messagebox.showerror("\u7f3a\u5c11\u76ee\u5f55", "\u8bf7\u5148\u9009\u62e9\u5bfc\u51fa\u76ee\u5f55\u3002")
            return
        self._set_running(True)
        self.status_var.set("\u6b63\u5728\u5bfc\u51fa")
        self._append_log("\u5f00\u59cb\u5bfc\u51fa...")
        threading.Thread(target=self._run_export, args=(account_input, output_dir, cookie, incremental), daemon=True).start()

    def _run_export(self, account_input: str, output_dir: str, cookie: str, incremental: bool) -> None:
        def progress(message: str) -> None:
            self.worker_queue.put(("log", message))

        try:
            result = DoubanExporter(cookie=cookie or None).export(
                account_input=account_input,
                output_root=output_dir,
                categories=DEFAULT_CATEGORIES,
                statuses=DEFAULT_STATUSES,
                incremental=incremental,
                progress=progress,
            )
            self.worker_queue.put(("done", result))
        except Exception as error:
            self.worker_queue.put(("error", error))

    def _poll_worker_queue(self) -> None:
        while True:
            try:
                event_name, payload = self.worker_queue.get_nowait()
            except queue.Empty:
                break
            if event_name == "log":
                self._append_log(str(payload))
            elif event_name == "done":
                self._handle_done(payload)
            elif event_name == "error":
                self._handle_error(payload)
        self.after(120, self._poll_worker_queue)

    def _handle_done(self, result: object) -> None:
        export_result = result
        self.last_output_dir = export_result.output_dir
        self._set_running(False)
        self.status_var.set("\u5bfc\u51fa\u5b8c\u6210")
        self._append_log(f"\u7ed3\u679c\u76ee\u5f55: {export_result.output_dir}")
        self._append_log(f"\u603b\u8868 CSV: {export_result.detail_csv_path}")
        self._append_log(f"\u6c47\u603b CSV: {export_result.summary_csv_path}")
        self._append_log(f"HTML \u9996\u9875: {export_result.report_html_path}")
        for category, path in export_result.category_csv_paths.items():
            self._append_log(f"{category} CSV: {path}")
        for category, path in export_result.category_html_paths.items():
            self._append_log(f"{category} HTML: {path}")
        messagebox.showinfo(
            "\u5bfc\u51fa\u5b8c\u6210",
            f"\u5df2\u5bfc\u51fa {export_result.total_rows} \u6761\u8bb0\u5f55\u3002\n\u7ed3\u679c\u76ee\u5f55:\n{export_result.output_dir}",
        )

    def _handle_error(self, error: object) -> None:
        self._set_running(False)
        self.status_var.set("\u5bfc\u51fa\u5931\u8d25")
        message = str(error) if isinstance(error, DoubanExportError) else "".join(traceback.format_exception_only(type(error), error)).strip()
        self._append_log(f"\u9519\u8bef: {message}")
        messagebox.showerror("\u5bfc\u51fa\u5931\u8d25", message)

    def _set_running(self, running: bool) -> None:
        if self.export_button is not None:
            self.export_button.configure(state="disabled" if running else "normal")
        if self.open_button is not None:
            self.open_button.configure(state="disabled" if running or self.last_output_dir is None else "normal")

    def _open_output_dir(self) -> None:
        if self.last_output_dir is None:
            messagebox.showwarning("\u6682\u65e0\u7ed3\u679c", "\u5f53\u524d\u8fd8\u6ca1\u6709\u53ef\u6253\u5f00\u7684\u5bfc\u51fa\u76ee\u5f55\u3002")
            return
        open_in_file_explorer(self.last_output_dir)

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="\u5bfc\u51fa\u8c46\u74e3\u6807\u8bb0\u8bb0\u5f55\u4e3a CSV \u548c HTML \u9875\u9762\u3002")
    parser.add_argument("--account", help="\u8c46\u74e3\u8d26\u53f7\u6216\u4e3b\u9875\u94fe\u63a5\u3002")
    parser.add_argument("--output-dir", default=str((Path.cwd() / "exports").resolve()), help="\u5bfc\u51fa\u6839\u76ee\u5f55\uff0c\u9ed8\u8ba4\u4e3a\u5f53\u524d\u9879\u76ee\u4e0b\u7684 exports\u3002")
    parser.add_argument("--cookie", help="\u53ef\u9009\uff0c\u624b\u52a8\u63d0\u4f9b\u8c46\u74e3 Cookie\u3002")
    parser.add_argument("--categories", help="\u53ef\u9009\uff0c\u9017\u53f7\u5206\u9694\uff0c\u4f8b\u5982 book,movie,music\u3002")
    parser.add_argument("--statuses", help="\u53ef\u9009\uff0c\u9017\u53f7\u5206\u9694\uff0c\u4f8b\u5982 wish,do,collect\u3002")
    parser.add_argument("--full-refresh", action="store_true", help="\u5ffd\u7565\u672c\u5730\u65e7\u5bfc\u51fa\uff0c\u5f3a\u5236\u5168\u91cf\u91cd\u65b0\u6293\u53d6\u3002")
    parser.add_argument("--no-gui", action="store_true", help="\u53ea\u8fd0\u884c\u547d\u4ee4\u884c\u5bfc\u51fa\uff0c\u4e0d\u6253\u5f00\u684c\u9762\u7a97\u53e3\u3002")
    return parser


def run_cli(args: argparse.Namespace) -> int:
    if not args.account:
        raise DoubanExportError("\u547d\u4ee4\u884c\u6a21\u5f0f\u9700\u8981\u901a\u8fc7 --account \u4f20\u5165\u8c46\u74e3\u8d26\u53f7\u6216\u94fe\u63a5\u3002")
    categories = parse_comma_separated_values(args.categories, DEFAULT_CATEGORIES)
    statuses = parse_comma_separated_values(args.statuses, DEFAULT_STATUSES)
    result = DoubanExporter(cookie=args.cookie).export(
        account_input=args.account,
        output_root=args.output_dir,
        categories=categories,
        statuses=statuses,
        incremental=not args.full_refresh,
        progress=print,
    )
    print("")
    print(f"\u5bfc\u51fa\u5b8c\u6210\uff0c\u5171 {result.total_rows} \u6761\u8bb0\u5f55\u3002")
    print(f"\u7ed3\u679c\u76ee\u5f55: {result.output_dir}")
    print(f"\u603b\u8868 CSV: {result.detail_csv_path}")
    print(f"\u6c47\u603b CSV: {result.summary_csv_path}")
    print(f"HTML \u9996\u9875: {result.report_html_path}")
    for category, path in result.category_csv_paths.items():
        print(f"{category} CSV: {path}")
    for category, path in result.category_html_paths.items():
        print(f"{category} HTML: {path}")
    return 0


def main() -> int:
    args = build_parser().parse_args()
    if args.no_gui or args.account:
        try:
            return run_cli(args)
        except DoubanExportError as error:
            print(f"\u5bfc\u51fa\u5931\u8d25: {error}")
            return 1
    app = ExportApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
