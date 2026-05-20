"""Main GUI window for CZDS Utils.

Provides a safe test harness for configuration, API testing, and zone file management.
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
import logging
import threading
import queue
from pathlib import Path
from typing import Optional
import sys
import time

# Setup path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from czds_utils.config import Config, get_config
from czds_utils.database import Database
from czds_utils.api_client import CZDSClient
from czds_utils.parser import ZoneFileParser, extract_unique_domains
from czds_utils.errors import CZDSError


class TextHandler(logging.Handler):
    """Logging handler that writes to a queue for thread-safe GUI updates."""

    def __init__(self, queue):
        super().__init__()
        self.queue = queue

    def emit(self, record):
        msg = self.format(record)
        self.queue.put({'type': 'log', 'msg': msg})


class CZDSUtilsGUI:
    """Main GUI application for CZDS Utils."""

    def __init__(self, root):
        """Initialize the GUI.

        Args:
            root: Tkinter root window
        """
        self.root = root
        self.root.title("ICANN CZDS Utils - Secure Management Tool")

        # Concurrency Queues
        self.task_queue = queue.Queue()
        self.result_queue = queue.Queue()

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
        # Set window size
        width = self.config.WINDOW_WIDTH if self.config else 1000
        height = self.config.WINDOW_HEIGHT if self.config else 700
        self.root.geometry(f"{width}x{height}")


        # Start background worker
        self.is_running = True
        threading.Thread(target=self._worker_loop, daemon=True).start()
        
        # Start UI poll loop
        self._process_queue_updates()

    def _process_queue_updates(self):
        """Poll result queue and update UI."""
        try:
            # Limit processing to prevent GUI freeze if queue is flooded
            processed = 0
            max_items = 100
            
            while processed < max_items:
                # Non-blocking get
                msg = self.result_queue.get_nowait()
                processed += 1
                
                msg_type = msg.get('type')
                
                if msg_type == 'log':
                    # Log message handled via queue to prevent flooding
                    text = msg.get('msg', '')
                    if text:
                        self.log_text.configure(state='normal')
                        self.log_text.insert(tk.END, text + '\n')
                        self.log_text.configure(state='disabled')
                        self.log_text.see(tk.END) 
                elif msg_type == 'status':
                    # Update status label
                    self._update_download_status(msg.get('log_msg', ''), msg.get('status_text', ''))
                elif msg_type == 'tree_update':
                    # Update treeview
                    item_id = msg.get('item_id')
                    status = msg.get('status')
                    if item_id and status:
                        try:
                            self.links_tree.set(item_id, "status", status)
                        except Exception:
                            pass # Item might be gone
                elif msg_type == 'progress_start':
                    self.download_progress.start()
                elif msg_type == 'progress_stop':
                    self.download_progress.stop()
                elif msg_type == 'messagebox':
                    title = msg.get('title')
                    text = msg.get('text')
                    if msg.get('error'):
                        messagebox.showerror(title, text)
                    else:
                        messagebox.showinfo(title, text)
                        
                self.result_queue.task_done()
        except queue.Empty:
            pass
        finally:
            # Reschedule
            if self.is_running:
                self.root.after(100, self._process_queue_updates)

    def _worker_loop(self):
        """Background worker loop processing tasks."""
        while self.is_running:
            try:
                # Blocking get with timeout to check is_running
                task = self.task_queue.get(timeout=1)
                
                if task['type'] == 'batch_import':
                    self._handle_batch_import(task)
                
                self.task_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                self.logger.error(f"Worker exception: {e}")

    def _handle_batch_import(self, task):
        """Handle batch import task."""
        items = task['items']
        config = task['config']
        downloads_dir = task['downloads_dir']
        
        self.result_queue.put({'type': 'progress_start'})
        
        count = len(items)
        success_count = 0
        fail_count = 0
        
        for index, (item_id, values) in enumerate(items):
            tld, _, link = values
            
            try:
                # 1. Download
                self.result_queue.put({
                    'type': 'status',
                    'log_msg': f"Processing {tld} ({index + 1}/{count})...",
                    'status_text': f"Downloading {tld}..."
                })
                self.result_queue.put({'type': 'tree_update', 'item_id': item_id, 'status': "Downloading..."})
                
                expected_filename = f"{tld}.txt.gz"
                cache_path = downloads_dir / expected_filename
                
                if not cache_path.exists():
                    stats = self.api_client.download_zone_file(link, cache_path)
                    self.database.record_download(str(tld), 'completed', file_size_bytes=stats.get('bytes_downloaded', 0))
                
                # 2. Import
                self.result_queue.put({
                    'type': 'status',
                    'log_msg': f"Importing {tld}...",
                    'status_text': f"Importing {tld}..."
                })
                self.result_queue.put({'type': 'tree_update', 'item_id': item_id, 'status': "Importing..."})
                
                # Progress callback for batch import
                last_update_time = 0
                def batch_progress(stage, count, total, imported):
                    nonlocal last_update_time
                    current_time = time.time()
                    
                    # Update status in tree occasionally (max 2 times per second)
                    if current_time - last_update_time >= 0.5:
                        last_update_time = current_time
                        status_msg = f"Imported: {imported:,}"
                        self.result_queue.put({
                            'type': 'tree_update', 
                            'item_id': item_id, 
                            'status': status_msg
                        })

                total = self._import_zone_file(
                    tld, 
                    str(cache_path),
                    validate_domains=config['validate'],
                    check_active=config['active'],
                    progress_callback=batch_progress,
                    should_stop=None,
                    skip_line_count=True # Optimize for speed
                )
                
                self.result_queue.put({'type': 'tree_update', 'item_id': item_id, 'status': f"{total:,} domains"})
                success_count += 1
                
            except Exception as e:
                self.result_queue.put({'type': 'tree_update', 'item_id': item_id, 'status': "Failed"})
                fail_count += 1
            
            # Yield to main thread after each file
            time.sleep(0.01)
                
        self.result_queue.put({'type': 'progress_stop'})
        self.result_queue.put({'type': 'status', 'log_msg': "Batch complete", 'status_text': "Done"})
        self.result_queue.put({
            'type': 'messagebox', 
            'title': 'Batch Complete', 
            'text': f"Processed {count} zones.\nSuccess: {success_count}\nFailed: {fail_count}",
            'error': False
        })

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

        # Links listbox with scrollbar -> Treeview
        list_frame = ttk.Frame(links_frame)
        list_frame.pack(fill='both', expand=True, padx=5, pady=5)

        scrollbar_y = ttk.Scrollbar(list_frame)
        scrollbar_y.pack(side='right', fill='y')

        # Treeview with columns
        columns = ("tld", "status", "url")
        self.links_tree = ttk.Treeview(
            list_frame,
            columns=columns,
            show="headings",
            selectmode="extended",
            yscrollcommand=scrollbar_y.set
        )
        
        # Configure columns
        self.links_tree.heading("tld", text="TLD")
        self.links_tree.column("tld", width=80, anchor='w')
        
        self.links_tree.heading("status", text="DB Status")
        self.links_tree.column("status", width=150, anchor='w')
        
        self.links_tree.heading("url", text="Download URL")
        self.links_tree.column("url", width=400, anchor='w')

        self.links_tree.pack(side='left', fill='both', expand=True)
        scrollbar_y.config(command=self.links_tree.yview)

        # Settings frame for batch import
        settings_frame = ttk.Frame(links_frame)
        settings_frame.pack(fill='x', padx=5, pady=(5, 0))

        self.batch_validate_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            settings_frame,
            text="Validate Domains",
            variable=self.batch_validate_var
        ).pack(side='left', padx=5)

        self.batch_active_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            settings_frame,
            text="Check Connectivity",
            variable=self.batch_active_var
        ).pack(side='left', padx=5)

        # Download frame
        download_frame = ttk.Frame(links_frame)
        download_frame.pack(fill='x', padx=5, pady=5)

        ttk.Button(
            download_frame,
            text="Download Selected",
            command=self.download_selected_zones
        ).pack(side='left', padx=5)

        ttk.Button(
            download_frame,
            text="Download & Import",
            command=self.batch_import_zones
        ).pack(side='left', padx=5)

        self.download_progress = ttk.Progressbar(
            download_frame,
            mode='indeterminate'
        )
        self.download_progress.pack(side='left', fill='x', expand=True, padx=5)

        self.download_status = ttk.Label(download_frame, text="")
        self.download_status.pack(side='left', padx=5)

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
        self.tld_entry = ttk.Combobox(tld_frame, width=10)
        self.tld_entry.pack(side='left', padx=5)

        ttk.Button(
            tld_frame,
            text="Query Domains",
            command=self.query_domains
        ).pack(side='left', padx=5)

        ttk.Button(
            tld_frame,
            text="Delete TLD Data",
            command=self.delete_tld_data
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

        self.check_active_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            options_frame,
            text="Check Connectivity",
            variable=self.check_active_var
        ).pack(side='left', padx=5)

        self.parse_button = ttk.Button(
            options_frame,
            text="Parse & Import to DB",
            command=self.parse_and_import
        )
        self.parse_button.pack(side='left', padx=5)

        self.cancel_button = ttk.Button(
            options_frame,
            text="Cancel",
            command=self.cancel_import,
            state='disabled'
        )
        self.cancel_button.pack(side='left', padx=5)

        self.progress_label = ttk.Label(options_frame, text="")
        self.progress_label.pack(side='left', padx=5)

        # Stop event for cancellation
        self.stop_import_event = threading.Event()

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
        text_handler = TextHandler(self.result_queue)
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
                    auth_url=self.config.CZDS_AUTH_URL,
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
                error_msg = e.safe_message
                self.logger.error(f"Authentication failed: {error_msg}")
                self.root.after(0, lambda: self.auth_status.config(
                    text="✗ Failed",
                    foreground="red"
                ))
                self.root.after(0, lambda: messagebox.showerror(
                    "Error",
                    error_msg
                ))

        threading.Thread(target=auth_thread, daemon=True).start()

    def fetch_zone_links(self):
        """Fetch available zone file links and update with DB status."""
        if not self.api_client:
            messagebox.showerror("Error", "Please authenticate first")
            return
        if not self.database:
             messagebox.showerror("Error", "Database not initialized")
             return

        def fetch_thread():
            try:
                links = self.api_client.get_zone_links()
                self.logger.info(f"Found {len(links)} zone file links")
                
                # Fetch DB status for all TLDs
                db_tlds = self.database.get_all_tlds()
                # Create a lookup: tld -> total_domains
                # We can handle case-sensitivity by lowercasing
                tld_stats = {row['tld'].lower(): row['total_domains'] for row in db_tlds}

                # Prepare items for Treeview
                tree_items = []
                for link in links:
                    # Extract TLD from link
                    tld = link.split('/')[-1].split('.')[0].lower()
                    
                    status = "Not Imported"
                    if tld in tld_stats:
                        count = tld_stats[tld]
                        status = f"{count:,} domains"
                    
                    tree_items.append((tld, status, link))
                
                # Sort by status (imported first?) or alpha? Let's sort alpha by TLD for now
                tree_items.sort(key=lambda x: x[0])

                self.root.after(0, lambda: self._update_links_tree(tree_items))
                self.root.after(0, lambda: messagebox.showinfo(
                    "Success",
                    f"Found {len(links)} available zone files"
                ))

            except CZDSError as e:
                error_msg = e.safe_message
                self.logger.error(f"Failed to fetch links: {error_msg}")
                self.root.after(0, lambda: messagebox.showerror(
                    "Error",
                    error_msg
                ))

        threading.Thread(target=fetch_thread, daemon=True).start()

    def _update_links_tree(self, items):
        """Update the links Treeview."""
        # Clear existing
        for item in self.links_tree.get_children():
            self.links_tree.delete(item)
            
        for tld, status, link in items:
            self.links_tree.insert("", tk.END, values=(tld, status, link))
            
    def _update_download_status(self, message: str, status: str = ""):
        """Update download status label and log message."""
        self.logger.info(message.replace('\n', ' '))
        if self.download_status:
           self.download_status.config(text=status if status else "Done")

    def download_selected_zones(self):
        """Download selected zone files (supports batch)."""
        selection = self.links_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "Please select at least one zone file")
            return
        if not self.config:
             messagebox.showerror("Error", "Configuration not loaded")
             return
        if not self.api_client:
            messagebox.showerror("Error", "Please authenticate first")
            return
            
        # Get all selected items
        selected_items = []
        for item_id in selection:
             item = self.links_tree.item(item_id)
             # values = (tld, status, link)
             selected_items.append((item_id, item['values']))
             
        count = len(selected_items)
        if count == 0:
            return

        # Use ZONE_FILES_DIR from config
        downloads_dir = self.config.ZONE_FILES_DIR
        try:
            downloads_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to create download directory: {e}")
            return
            
        # If single selection, we can behave like before (auto-switch tab)
        # If multiple, we stay on this tab and show progress
        is_batch = count > 1
        
        def download_thread():
            success_count = 0
            fail_count = 0
            
            self.root.after(0, lambda: self.download_progress.start())
            
            for index, (item_id, values) in enumerate(selected_items):
                tld, status_val, link = values
                
                try:
                    self.root.after(0, lambda: self._update_download_status(
                        f"Downloading {tld} ({index + 1}/{count})...",
                        f"Downloading {tld}..."
                    ))
                    
                    # Predict filename
                    expected_filename = f"{tld}.txt.gz"
                    cache_path = downloads_dir / expected_filename
                    
                    # Logic: If exists, skip (or assume cached)? 
                    # For batch, asking for every file is annoying. 
                    # Let's assume if it exists, we skip downloading but mark as success.
                    # Or we can overwrite? Configurable?
                    # Let's verify if cache exists.
                    
                    if cache_path.exists():
                         self.logger.info(f"Skipping download for {tld}, cached file exists.")
                         # Update tree status?
                         self.root.after(0, lambda i=item_id: self.links_tree.set(i, "status", "Downloaded (Cached)"))
                         success_count += 1
                         
                         # If single select, we still want to go to parser
                         if not is_batch:
                             # Need to trigger UI switch
                             pass
                         continue
                    
                    # Download
                    stats = self.api_client.download_zone_file(
                        link,
                        cache_path
                    )
                    
                    self.database.record_download(
                        str(tld),
                        'completed',
                        file_size_bytes=stats.get('bytes_downloaded', 0)
                    )
                    
                    # Update status in Treeview
                    self.root.after(0, lambda i=item_id: self.links_tree.set(i, "status", "Downloaded"))
                    success_count += 1
                    
                except Exception as e:
                    self.logger.error(f"Failed to download {tld}: {e}")
                    self.database.record_download(str(tld), 'failed', error_message=str(e))
                    self.root.after(0, lambda i=item_id: self.links_tree.set(i, "status", "Failed"))
                    fail_count += 1
            
            self.root.after(0, lambda: self.download_progress.stop())
            self.root.after(0, lambda: self._update_download_status(
                f"Batch completed. Success: {success_count}, Failed: {fail_count}",
                "Done"
            ))
            
            if is_batch:
                self.root.after(0, lambda: messagebox.showinfo(
                    "Batch Complete",
                    f"Processed {count} files.\nSuccess: {success_count}\nFailed: {fail_count}"
                ))
            else:
                # Single selection logic: Switch to Parser logic
                # Only if success
                if success_count > 0:
                   # We need to find the path again
                   # Last processed item
                   last_tld = selected_items[0][1][0]
                   last_path = downloads_dir / f"{last_tld}.txt.gz"
                   
                   self.root.after(0, lambda: self.notebook.select(3))
                   self.root.after(0, lambda: self.parser_file_path.set(str(last_path)))
                   self.root.after(0, lambda: self._auto_detect_tld(str(last_path)))

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

            # Update TLD dropdown
            tlds = self.database.get_all_tlds()
            tld_names = [r['tld'] for r in tlds]
            self.tld_entry['values'] = sorted(tld_names)
            if tld_names and not self.tld_entry.get():
                self.tld_entry.current(0)

        except CZDSError as e:
            messagebox.showerror("Error", e.safe_message)

    def delete_tld_data(self):
        """Delete data for the selected TLD."""
        if not self.database:
            messagebox.showerror("Error", "Database not initialized")
            return

        tld = self.tld_entry.get().strip()
        if not tld:
            messagebox.showwarning("Warning", "Please select a TLD")
            return

        if messagebox.askyesno(
            "Confirm Delete",
            f"Are you sure you want to delete ALL data for '{tld}'?\nThis cannot be undone."
        ):
            try:
                if self.database.delete_tld(tld):
                    messagebox.showinfo("Success", f"Data for '{tld}' deleted successfully")
                    self.refresh_db_stats()
                else:
                    messagebox.showinfo("Info", f"No data found for '{tld}'")
            except Exception as e:
                self.logger.error(f"Failed to delete TLD: {e}")
                messagebox.showerror("Error", f"Failed to delete data: {e}")

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
            self._auto_detect_tld(filename)

    def _auto_detect_tld(self, filename: str):
        """Auto-detect TLD from filename and populate field."""
        # Always update TLD based on filename
        path = Path(filename)
        name = path.name.lower()
        
        # Strip known extensions
        for ext in ['.txt.gz', '.zone.gz', '.gz', '.txt', '.zone']:
            if name.endswith(ext):
                name = name[:-len(ext)]
                break
        
        self.parser_tld.delete(0, tk.END)
        self.parser_tld.insert(0, name)

    def cancel_import(self):
        """Signal import cancellation."""
        self.stop_import_event.set()
        self.logger.info("Cancelling import...")
        self.cancel_button.config(state='disabled')

    def _import_zone_file(self, tld, file_path, validate_domains=True, check_active=False, progress_callback=None, should_stop=None, skip_line_count=False):
        """Reusable method to import a zone file."""
        total_imported = 0
        lines_processed = 0
        
        try:
            self.logger.info(f"Parsing zone file for .{tld}...")

            parser = ZoneFileParser(
                tld,
                validate_domains=validate_domains,
                check_active=check_active
            )

            total_lines = 0
            if not skip_line_count:
                # Calculate total lines
                if progress_callback:
                    progress_callback("Calculating lines...", 0)
                
                total_lines = parser.count_lines(Path(file_path))
                self.logger.info(f"Total lines to process: {total_lines:,}")
            else:
                self.logger.info("Skipping line count calculation for performance")

            # Local progress wrapper
            def update_progress(count):
                nonlocal lines_processed
                lines_processed = count
                if progress_callback:
                    progress_callback(None, count, total_lines, total_imported)


            # Parse in batches
            batch = []
            # Optimize: 2000 items per batch is a sweet spot for SQLite (one transaction) + GUI responsiveness
            batch_size = 2000 
            
            # Use a single connection for the entire file to avoid open/close churn
            with self.database.get_connection_context() as conn:
                for domain in parser.parse_file(
                    Path(file_path),
                    progress_callback=update_progress,
                    should_stop=should_stop
                ):
                    if should_stop and should_stop():
                        break

                    batch.append(domain)

                    if len(batch) >= batch_size:
                        # Pass batch_size to force single transaction per call
                        count = self.database.add_domains_batch(tld, batch, batch_size=batch_size, conn=conn)
                        total_imported += count
                        batch = []
                        # Force update
                        update_progress(lines_processed)
                        # Yield GIL to keep GUI responsive
                        time.sleep(0.01)

                # Import remaining
                if batch and (not should_stop or not should_stop()):
                    count = self.database.add_domains_batch(tld, batch, conn=conn)
                    total_imported += count
                    update_progress(lines_processed)

            # Final cleanup & Stats update
            if not should_stop or not should_stop():
                self.logger.info(f"Import complete: {total_imported:,} domains")
                try:
                    file_size = Path(file_path).stat().st_size
                    self.database.add_or_update_tld(
                        tld, 
                        total_domains=total_imported,
                        file_size_bytes=file_size
                    )
                except Exception as e:
                    self.logger.error(f"Failed to update TLD stats: {e}")
                    
            return total_imported

        except Exception as e:
             raise e

    def parse_and_import(self):
        """Parse zone file and import to database (GUI wrapper)."""
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

        # Reset UI state
        self.stop_import_event.clear()
        self.parse_button.config(state='disabled')
        self.cancel_button.config(state='normal')
        self.progress_label.config(text="Starting...")

        # Capture config in main thread
        validate = self.validate_domains_var.get()
        active = self.check_active_var.get()

        def parse_thread():
            try:
                # Callback adapter for GUI label
                # Callback adapter for GUI label
                last_update_time = 0
                
                def progress_adapter(stage_text, count, total=0, imported=0):
                    nonlocal last_update_time
                    current_time = time.time()
                    
                    # Determine if we should update:
                    # 1. It's a stage change (stage_text provided)
                    # 2. It's the final count (count >= total and total > 0)
                    # 3. Enough time has passed (0.1s)
                    should_update = (
                        stage_text is not None or 
                        (total > 0 and count >= total) or 
                        (current_time - last_update_time >= 0.1)
                    )
                    
                    if should_update:
                        last_update_time = current_time
                        if stage_text:
                            self.root.after(0, lambda: self.progress_label.config(text=stage_text))
                        else:
                            if total > 0:
                                percent = (count / total) * 100
                                msg = f"Processed: {count:,} / {total:,} ({percent:.1f}%) | Imported: {imported:,}"
                            else:
                                msg = f"Processed: {count:,} | Imported: {imported:,}"
                            self.root.after(0, lambda: self.progress_label.config(text=msg))

                total = self._import_zone_file(
                    tld, 
                    file_path,
                    validate_domains=validate,
                    check_active=active,
                    progress_callback=progress_adapter,
                    should_stop=self.stop_import_event.is_set
                )
                
                if self.stop_import_event.is_set():
                    self.logger.info("Import cancelled by user")
                    self.root.after(0, lambda: messagebox.showinfo(
                        "Cancelled",
                        f"Import cancelled.\nImported: {total:,}"
                    ))
                else:
                    self.logger.info(f"Import complete: {total:,} domains")
                    result_text = f"Successfully imported {total:,} domains for .{tld}\n"
                    self.root.after(0, lambda: messagebox.showinfo(
                        "Success",
                        f"Imported {total:,} domains"
                    ))
                    self.root.after(0, lambda: self._update_parser_results(result_text))

            except CZDSError as e:
                error_msg = e.safe_message
                self.logger.error(f"Parse/import failed: {error_msg}")
                self.root.after(0, lambda: messagebox.showerror("Error", error_msg))
            except Exception as e:
                self.logger.error(f"Unexpected error: {e}")
                self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
            finally:
                self.root.after(0, lambda: self._reset_buttons())

        threading.Thread(target=parse_thread, daemon=True).start()

    def batch_import_zones(self):
        """Batch download and import selected zones."""
        selection = self.links_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "Please select at least one zone file")
            return
        if not self.config or not self.api_client or not self.database:
             messagebox.showerror("Error", "System not fully initialized")
             return

        # Get all selected items
        selected_items = []
        for item_id in selection:
             item = self.links_tree.item(item_id)
             selected_items.append((item_id, item['values']))
             
        count = len(selected_items)
        downloads_dir = self.config.ZONE_FILES_DIR
        try:
            downloads_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to create download directory: {e}")
            return

        # Capture settings in main thread
        validate = self.batch_validate_var.get()
        active = self.batch_active_var.get()

        # Create task payload
        task = {
            'type': 'batch_import',
            'items': selected_items,
            'config': {
                'validate': validate,
                'active': active
            },
            'downloads_dir': downloads_dir
        }
        
        # Submit to queue
        self.task_queue.put(task)
        self.logger.info("Batch task submitted to background worker.")

    def _reset_buttons(self):
        """Reset buttons after import."""
        self.parse_button.config(state='normal')
        self.cancel_button.config(state='disabled')
        self.progress_label.config(text="")

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
