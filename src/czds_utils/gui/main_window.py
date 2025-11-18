"""Main GUI window for CZDS Utils.

Provides a safe test harness for configuration, API testing, and zone file management.
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
import logging
import threading
from pathlib import Path
from typing import Optional
import sys

# Setup path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from czds_utils.config import Config, get_config
from czds_utils.database import Database
from czds_utils.api_client import CZDSClient
from czds_utils.parser import ZoneFileParser, extract_unique_domains
from czds_utils.errors import CZDSError


class TextHandler(logging.Handler):
    """Logging handler that writes to a tkinter Text widget."""

    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget

    def emit(self, record):
        msg = self.format(record)
        def append():
            self.text_widget.configure(state='normal')
            self.text_widget.insert(tk.END, msg + '\n')
            self.text_widget.configure(state='disabled')
            self.text_widget.see(tk.END)

        self.text_widget.after(0, append)


class CZDSUtilsGUI:
    """Main GUI application for CZDS Utils."""

    def __init__(self, root):
        """Initialize the GUI.

        Args:
            root: Tkinter root window
        """
        self.root = root
        self.root.title("ICANN CZDS Utils - Secure Management Tool")

        # Configuration
        self.config: Optional[Config] = None
        self.database: Optional[Database] = None
        self.api_client: Optional[CZDSClient] = None

        # Setup logging
        self.setup_logging()

        # Load configuration if available
        try:
            self.config = get_config()
            self.database = Database(
                self.config.DATABASE_PATH,
                self.config.DATABASE_TIMEOUT
            )
        except Exception as e:
            self.logger.warning(f"Could not load configuration: {str(e)}")

        # Create GUI
        self.create_widgets()

        # Set window size
        width = self.config.WINDOW_WIDTH if self.config else 1000
        height = self.config.WINDOW_HEIGHT if self.config else 700
        self.root.geometry(f"{width}x{height}")

    def setup_logging(self):
        """Setup logging for the application."""
        self.logger = logging.getLogger('czds_utils')
        self.logger.setLevel(logging.INFO)

    def create_widgets(self):
        """Create all GUI widgets."""
        # Create notebook (tabs)
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True, padx=5, pady=5)

        # Create tabs
        self.create_config_tab()
        self.create_api_tab()
        self.create_database_tab()
        self.create_parser_tab()
        self.create_logs_tab()

    def create_config_tab(self):
        """Create configuration management tab."""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Configuration")

        # Config file frame
        file_frame = ttk.LabelFrame(tab, text="Configuration File", padding=10)
        file_frame.pack(fill='x', padx=10, pady=5)

        ttk.Button(
            file_frame,
            text="Load .env File",
            command=self.load_config_file
        ).pack(side='left', padx=5)

        ttk.Button(
            file_frame,
            text="Reload Current",
            command=self.reload_config
        ).pack(side='left', padx=5)

        # Configuration display
        display_frame = ttk.LabelFrame(tab, text="Current Configuration", padding=10)
        display_frame.pack(fill='both', expand=True, padx=10, pady=5)

        self.config_text = scrolledtext.ScrolledText(
            display_frame,
            height=20,
            state='disabled'
        )
        self.config_text.pack(fill='both', expand=True)

        # Update display
        self.update_config_display()

    def create_api_tab(self):
        """Create API testing tab."""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="API Test Harness")

        # Authentication frame
        auth_frame = ttk.LabelFrame(tab, text="Authentication", padding=10)
        auth_frame.pack(fill='x', padx=10, pady=5)

        ttk.Button(
            auth_frame,
            text="Test Authentication",
            command=self.test_authentication
        ).pack(side='left', padx=5)

        self.auth_status = ttk.Label(auth_frame, text="Not authenticated")
        self.auth_status.pack(side='left', padx=5)

        # Zone links frame
        links_frame = ttk.LabelFrame(tab, text="Zone File Links", padding=10)
        links_frame.pack(fill='both', expand=True, padx=10, pady=5)

        ttk.Button(
            links_frame,
            text="Fetch Available Zones",
            command=self.fetch_zone_links
        ).pack(anchor='w', padx=5, pady=5)

        # Links listbox with scrollbar
        list_frame = ttk.Frame(links_frame)
        list_frame.pack(fill='both', expand=True, padx=5, pady=5)

        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side='right', fill='y')

        self.links_listbox = tk.Listbox(
            list_frame,
            yscrollcommand=scrollbar.set
        )
        self.links_listbox.pack(side='left', fill='both', expand=True)
        scrollbar.config(command=self.links_listbox.yview)

        # Download frame
        download_frame = ttk.Frame(links_frame)
        download_frame.pack(fill='x', padx=5, pady=5)

        ttk.Button(
            download_frame,
            text="Download Selected",
            command=self.download_selected_zone
        ).pack(side='left', padx=5)

        self.download_progress = ttk.Progressbar(
            download_frame,
            mode='indeterminate'
        )
        self.download_progress.pack(side='left', fill='x', expand=True, padx=5)

    def create_database_tab(self):
        """Create database query tab."""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Database")

        # Statistics frame
        stats_frame = ttk.LabelFrame(tab, text="Database Statistics", padding=10)
        stats_frame.pack(fill='x', padx=10, pady=5)

        ttk.Button(
            stats_frame,
            text="Refresh Statistics",
            command=self.refresh_db_stats
        ).pack(anchor='w', padx=5, pady=5)

        self.stats_text = scrolledtext.ScrolledText(
            stats_frame,
            height=8,
            state='disabled'
        )
        self.stats_text.pack(fill='both', expand=True)

        # Query frame
        query_frame = ttk.LabelFrame(tab, text="Query Domains", padding=10)
        query_frame.pack(fill='both', expand=True, padx=10, pady=5)

        # TLD selection
        tld_frame = ttk.Frame(query_frame)
        tld_frame.pack(fill='x', padx=5, pady=5)

        ttk.Label(tld_frame, text="TLD:").pack(side='left', padx=5)
        self.tld_entry = ttk.Entry(tld_frame, width=10)
        self.tld_entry.pack(side='left', padx=5)

        ttk.Button(
            tld_frame,
            text="Query Domains",
            command=self.query_domains
        ).pack(side='left', padx=5)

        # Results
        self.query_results = scrolledtext.ScrolledText(
            query_frame,
            height=15,
            state='disabled'
        )
        self.query_results.pack(fill='both', expand=True, padx=5, pady=5)

    def create_parser_tab(self):
        """Create zone file parser tab."""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Zone File Parser")

        # File selection
        file_frame = ttk.LabelFrame(tab, text="Select Zone File", padding=10)
        file_frame.pack(fill='x', padx=10, pady=5)

        self.parser_file_path = tk.StringVar()
        ttk.Entry(
            file_frame,
            textvariable=self.parser_file_path,
            state='readonly'
        ).pack(side='left', fill='x', expand=True, padx=5)

        ttk.Button(
            file_frame,
            text="Browse...",
            command=self.browse_zone_file
        ).pack(side='left', padx=5)

        # Parse options
        options_frame = ttk.LabelFrame(tab, text="Parse Options", padding=10)
        options_frame.pack(fill='x', padx=10, pady=5)

        ttk.Label(options_frame, text="TLD:").pack(side='left', padx=5)
        self.parser_tld = ttk.Entry(options_frame, width=10)
        self.parser_tld.pack(side='left', padx=5)

        self.validate_domains_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            options_frame,
            text="Validate Domains",
            variable=self.validate_domains_var
        ).pack(side='left', padx=5)

        ttk.Button(
            options_frame,
            text="Parse & Import to DB",
            command=self.parse_and_import
        ).pack(side='left', padx=5)

        # Results
        results_frame = ttk.LabelFrame(tab, text="Parse Results", padding=10)
        results_frame.pack(fill='both', expand=True, padx=10, pady=5)

        self.parser_results = scrolledtext.ScrolledText(
            results_frame,
            height=15,
            state='disabled'
        )
        self.parser_results.pack(fill='both', expand=True)

    def create_logs_tab(self):
        """Create logs display tab."""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Logs")

        # Log display
        self.log_text = scrolledtext.ScrolledText(
            tab,
            height=30,
            state='disabled'
        )
        self.log_text.pack(fill='both', expand=True, padx=10, pady=10)

        # Add log handler
        text_handler = TextHandler(self.log_text)
        text_handler.setFormatter(
            logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        )
        logging.getLogger('czds_utils').addHandler(text_handler)

    # Event handlers
    def load_config_file(self):
        """Load configuration from selected file."""
        filename = filedialog.askopenfilename(
            title="Select .env file",
            filetypes=[("Environment files", "*.env"), ("All files", "*.*")]
        )

        if filename:
            try:
                self.config = Config(env_file=filename)
                self.database = Database(
                    self.config.DATABASE_PATH,
                    self.config.DATABASE_TIMEOUT
                )
                self.update_config_display()
                messagebox.showinfo("Success", "Configuration loaded successfully")
            except CZDSError as e:
                messagebox.showerror("Error", e.safe_message)

    def reload_config(self):
        """Reload current configuration."""
        try:
            self.config = get_config(reload=True)
            self.database = Database(
                self.config.DATABASE_PATH,
                self.config.DATABASE_TIMEOUT
            )
            self.update_config_display()
            messagebox.showinfo("Success", "Configuration reloaded")
        except CZDSError as e:
            messagebox.showerror("Error", e.safe_message)

    def update_config_display(self):
        """Update configuration display."""
        self.config_text.configure(state='normal')
        self.config_text.delete('1.0', tk.END)

        if self.config:
            config_dict = self.config.to_dict(mask_secrets=True)
            for key, value in sorted(config_dict.items()):
                self.config_text.insert(tk.END, f"{key}: {value}\n")
        else:
            self.config_text.insert(tk.END, "No configuration loaded\n")

        self.config_text.configure(state='disabled')

    def test_authentication(self):
        """Test API authentication."""
        if not self.config:
            messagebox.showerror("Error", "Please load configuration first")
            return

        def auth_thread():
            try:
                self.api_client = CZDSClient(
                    self.config.CZDS_API_BASE_URL,
                    self.config.CZDS_USERNAME,
                    self.config.CZDS_PASSWORD,
                    timeout=self.config.REQUEST_TIMEOUT,
                    max_retries=self.config.MAX_RETRIES,
                    validate_ssl=self.config.VALIDATE_SSL
                )

                token = self.api_client.authenticate()
                self.logger.info(f"Authentication successful! Token: {token[:20]}...")

                self.root.after(0, lambda: self.auth_status.config(
                    text="✓ Authenticated",
                    foreground="green"
                ))
                self.root.after(0, lambda: messagebox.showinfo(
                    "Success",
                    "Authentication successful!"
                ))

            except CZDSError as e:
                self.logger.error(f"Authentication failed: {e.safe_message}")
                self.root.after(0, lambda: self.auth_status.config(
                    text="✗ Failed",
                    foreground="red"
                ))
                self.root.after(0, lambda: messagebox.showerror(
                    "Error",
                    e.safe_message
                ))

        threading.Thread(target=auth_thread, daemon=True).start()

    def fetch_zone_links(self):
        """Fetch available zone file links."""
        if not self.api_client:
            messagebox.showerror("Error", "Please authenticate first")
            return

        def fetch_thread():
            try:
                links = self.api_client.get_zone_links()
                self.logger.info(f"Found {len(links)} zone file links")

                self.root.after(0, lambda: self._update_links_list(links))
                self.root.after(0, lambda: messagebox.showinfo(
                    "Success",
                    f"Found {len(links)} zone files"
                ))

            except CZDSError as e:
                self.logger.error(f"Failed to fetch links: {e.safe_message}")
                self.root.after(0, lambda: messagebox.showerror(
                    "Error",
                    e.safe_message
                ))

        threading.Thread(target=fetch_thread, daemon=True).start()

    def _update_links_list(self, links):
        """Update the links listbox."""
        self.links_listbox.delete(0, tk.END)
        for link in links:
            self.links_listbox.insert(tk.END, link)

    def download_selected_zone(self):
        """Download selected zone file."""
        selection = self.links_listbox.curselection()
        if not selection:
            messagebox.showwarning("Warning", "Please select a zone file")
            return

        link = self.links_listbox.get(selection[0])

        # Extract TLD from link
        tld = link.split('/')[-1].split('.')[0]

        # Ask for save location
        filename = filedialog.asksaveasfilename(
            title="Save zone file as",
            defaultextension=".txt.gz",
            initialfile=f"{tld}.txt.gz",
            filetypes=[("Gzip files", "*.gz"), ("All files", "*.*")]
        )

        if not filename:
            return

        def download_thread():
            try:
                self.root.after(0, lambda: self.download_progress.start())

                stats = self.api_client.download_zone_file(
                    link,
                    Path(filename)
                )

                self.logger.info(
                    f"Downloaded {stats['bytes_downloaded']:,} bytes "
                    f"in {stats['download_time_seconds']:.2f}s"
                )

                self.root.after(0, lambda: self.download_progress.stop())
                self.root.after(0, lambda: messagebox.showinfo(
                    "Success",
                    f"Downloaded {stats['bytes_downloaded']:,} bytes"
                ))

            except CZDSError as e:
                self.logger.error(f"Download failed: {e.safe_message}")
                self.root.after(0, lambda: self.download_progress.stop())
                self.root.after(0, lambda: messagebox.showerror(
                    "Error",
                    e.safe_message
                ))

        threading.Thread(target=download_thread, daemon=True).start()

    def refresh_db_stats(self):
        """Refresh database statistics."""
        if not self.database:
            messagebox.showerror("Error", "Database not initialized")
            return

        try:
            stats = self.database.get_statistics()

            self.stats_text.configure(state='normal')
            self.stats_text.delete('1.0', tk.END)

            self.stats_text.insert(tk.END, f"Total TLDs: {stats['total_tlds']:,}\n")
            self.stats_text.insert(tk.END, f"Total Domains: {stats['total_domains']:,}\n")
            self.stats_text.insert(tk.END, f"Total Downloads: {stats['total_downloads']:,}\n")
            self.stats_text.insert(tk.END, f"Successful Downloads: {stats['successful_downloads']:,}\n")
            self.stats_text.insert(tk.END, f"Database Size: {stats['database_size_bytes']:,} bytes\n")

            self.stats_text.configure(state='disabled')

        except CZDSError as e:
            messagebox.showerror("Error", e.safe_message)

    def query_domains(self):
        """Query domains for a TLD."""
        if not self.database:
            messagebox.showerror("Error", "Database not initialized")
            return

        tld = self.tld_entry.get().strip()
        if not tld:
            messagebox.showwarning("Warning", "Please enter a TLD")
            return

        try:
            domains = self.database.get_domains_by_tld(tld, limit=100)
            count = self.database.get_domain_count(tld)

            self.query_results.configure(state='normal')
            self.query_results.delete('1.0', tk.END)

            self.query_results.insert(tk.END, f"Total domains for .{tld}: {count:,}\n")
            self.query_results.insert(tk.END, f"Showing first {len(domains)} domains:\n\n")

            for domain_info in domains:
                self.query_results.insert(tk.END, f"{domain_info['domain']}\n")

            self.query_results.configure(state='disabled')

        except CZDSError as e:
            messagebox.showerror("Error", e.safe_message)

    def browse_zone_file(self):
        """Browse for a zone file."""
        filename = filedialog.askopenfilename(
            title="Select zone file",
            filetypes=[
                ("Zone files", "*.txt;*.txt.gz;*.gz"),
                ("All files", "*.*")
            ]
        )

        if filename:
            self.parser_file_path.set(filename)

    def parse_and_import(self):
        """Parse zone file and import to database."""
        file_path = self.parser_file_path.get()
        if not file_path:
            messagebox.showwarning("Warning", "Please select a zone file")
            return

        tld = self.parser_tld.get().strip()
        if not tld:
            messagebox.showwarning("Warning", "Please enter a TLD")
            return

        if not self.database:
            messagebox.showerror("Error", "Database not initialized")
            return

        def parse_thread():
            try:
                self.logger.info(f"Parsing zone file for .{tld}...")

                parser = ZoneFileParser(
                    tld,
                    validate_domains=self.validate_domains_var.get()
                )

                # Parse in batches
                batch = []
                batch_size = 1000
                total_imported = 0

                for domain in parser.parse_file(Path(file_path)):
                    batch.append(domain)

                    if len(batch) >= batch_size:
                        count = self.database.add_domains_batch(tld, batch)
                        total_imported += count
                        batch = []

                        self.logger.info(f"Imported {total_imported:,} domains so far...")

                # Import remaining
                if batch:
                    count = self.database.add_domains_batch(tld, batch)
                    total_imported += count

                self.logger.info(f"Import complete: {total_imported:,} domains")

                # Update display
                result_text = f"Successfully imported {total_imported:,} domains for .{tld}\n"

                self.root.after(0, lambda: self._update_parser_results(result_text))
                self.root.after(0, lambda: messagebox.showinfo(
                    "Success",
                    f"Imported {total_imported:,} domains"
                ))

            except CZDSError as e:
                self.logger.error(f"Parse/import failed: {e.safe_message}")
                self.root.after(0, lambda: messagebox.showerror(
                    "Error",
                    e.safe_message
                ))

        threading.Thread(target=parse_thread, daemon=True).start()

    def _update_parser_results(self, text):
        """Update parser results display."""
        self.parser_results.configure(state='normal')
        self.parser_results.insert(tk.END, text)
        self.parser_results.configure(state='disabled')


def main():
    """Main entry point for GUI."""
    root = tk.Tk()
    app = CZDSUtilsGUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()
