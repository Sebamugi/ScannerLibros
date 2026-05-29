import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox
import sqlite3
import requests
import threading
import time
import json
from datetime import datetime
from typing import Optional, Dict, Any
import urllib.parse


class DatabaseManager:
    """Manages SQLite database operations for the book inventory."""
    
    def __init__(self, db_name: str = "book_inventory.db"):
        self.db_name = db_name
        self.init_database()
    
    def init_database(self):
        """Initialize the database and create the books table if it doesn't exist."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS libros (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    isbn TEXT,
                    titulo TEXT NOT NULL,
                    autor TEXT,
                    editorial TEXT,
                    cantidad INTEGER NOT NULL DEFAULT 1
                )
            """)
            # Ensure old databases get the new cantidad column
            cursor.execute("PRAGMA table_info(libros)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'cantidad' not in columns:
                cursor.execute("ALTER TABLE libros ADD COLUMN cantidad INTEGER NOT NULL DEFAULT 1")
            # Table to store pending ISBNs that need background resolution
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pending_isbns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    book_id INTEGER,
                    isbn TEXT,
                    status TEXT DEFAULT 'pending',
                    attempts INTEGER DEFAULT 0,
                    last_error TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(book_id) REFERENCES libros(id) ON DELETE CASCADE
                )
            """)
            conn.commit()
    
    def add_book(self, isbn: Optional[str], titulo: str, autor: str = "", editorial: str = "", cantidad: int = 1) -> int:
        """Add a new book to the database."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO libros (isbn, titulo, autor, editorial, cantidad)
                VALUES (?, ?, ?, ?, ?)
            """, (isbn, titulo, autor, editorial, cantidad))
            conn.commit()
            return cursor.lastrowid

    def get_book_by_isbn(self, isbn: str) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, isbn, titulo, autor, editorial, cantidad FROM libros WHERE isbn = ? LIMIT 1", (isbn,))
            row = cursor.fetchone()
            if row:
                return {
                    'id': row[0],
                    'isbn': row[1],
                    'titulo': row[2],
                    'autor': row[3],
                    'editorial': row[4],
                    'cantidad': row[5]
                }
            return None

    def increment_book_quantity(self, book_id: int, amount: int = 1) -> bool:
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE libros SET cantidad = cantidad + ? WHERE id = ?", (amount, book_id))
            conn.commit()
            return cursor.rowcount > 0

    # Pending queue methods
    def enqueue_pending(self, book_id: int, isbn: str):
        """Add an entry to the pending_isbns queue for background resolution."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            # Avoid duplicate pending for same book
            cursor.execute("SELECT id FROM pending_isbns WHERE book_id = ?", (book_id,))
            if cursor.fetchone():
                return
            cursor.execute("INSERT INTO pending_isbns (book_id, isbn) VALUES (?, ?)", (book_id, isbn))
            conn.commit()

    def get_pending_items(self, limit: int = 20) -> list:
        """Return pending items with status 'pending' or 'retryable'."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, book_id, isbn, status, attempts FROM pending_isbns WHERE status IN ('pending','retry') ORDER BY created_at ASC LIMIT ?", (limit,))
            return cursor.fetchall()

    def remove_pending(self, book_id: int):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM pending_isbns WHERE book_id = ?", (book_id,))
            conn.commit()

    def increment_pending_attempts(self, book_id: int, error: str = None):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE pending_isbns SET attempts = attempts + 1, last_error = ?, status = CASE WHEN attempts + 1 >= 3 THEN 'failed' ELSE 'retry' END WHERE book_id = ?", (error, book_id))
            conn.commit()

    def get_pending_map(self) -> Dict[int, str]:
        """Return a map book_id -> status for pending items."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT book_id, status FROM pending_isbns")
            rows = cursor.fetchall()
            return {r[0]: r[1] for r in rows}
    
    def get_recent_books(self, limit: int = 50) -> list:
        """Get the most recently added books."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, isbn, titulo, autor, editorial, cantidad
                FROM libros
                ORDER BY id DESC
                LIMIT ?
            """, (limit,))
            return cursor.fetchall()
    
    def delete_book(self, book_id: int) -> bool:
        """Delete a book from the database."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM libros WHERE id = ?", (book_id,))
            conn.commit()
            return cursor.rowcount > 0
    
    def update_book(self, book_id: int, isbn: Optional[str], titulo: str, autor: str, editorial: str, cantidad: int) -> bool:
        """Update an existing book in the database."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE libros 
                SET isbn = ?, titulo = ?, autor = ?, editorial = ?, cantidad = ?
                WHERE id = ?
            """, (isbn, titulo, autor, editorial, cantidad, book_id))
            conn.commit()
            return cursor.rowcount > 0


class OpenLibraryAPI:
    """Handles communication with the Open Library API."""
    
    def __init__(self):
        self.base_url = "https://openlibrary.org/api/books"
        self.search_url = "https://openlibrary.org/search.json"
        self.translation_url = "https://translate.googleapis.com/translate_a/single"
    
    def search_by_isbn(self, isbn: str) -> Optional[Dict[str, Any]]:
        """Search for a book by ISBN using Open Library API."""
        try:
            # Clean ISBN (remove hyphens and spaces)
            clean_isbn = isbn.replace("-", "").replace(" ", "")
            # Prefer the /api/books endpoint (returns rich data keyed by ISBN)
            try:
                params = {
                    'bibkeys': f'ISBN:{clean_isbn}',
                    'format': 'json',
                    'jscmd': 'data'
                }
                api_resp = requests.get(self.base_url, params=params)
                if api_resp.status_code == 200:
                    api_data = api_resp.json()
                    key = f'ISBN:{clean_isbn}'
                    if api_data.get(key):
                        info = api_data[key]
                        # Normalize to the same shape as search.json docs
                        normalized = {
                            'title': info.get('title'),
                            'author_name': [a.get('name') for a in info.get('authors', []) if isinstance(a, dict)],
                            'publisher': [p.get('name') if isinstance(p, dict) else p for p in info.get('publishers', [])]
                        }
                        return self._extract_book_info(normalized)
            except requests.exceptions.RequestException:
                # fall through to other methods
                pass

            # Fallback: search.json (works with isbn:<value>)
            url = f"{self.search_url}?q=isbn:{clean_isbn}&fields=key,title,author_name,publisher,first_publish_year&limit=1"

            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                if data.get("numFound", 0) > 0:
                    return self._extract_book_info(data["docs"][0])
                # Try alternative ISBN endpoint
            isbn_url = f"https://openlibrary.org/isbn/{clean_isbn}.json"
            isbn_response = requests.get(isbn_url)
            if isbn_response.status_code == 200:
                isbn_data = isbn_response.json()
                return self._extract_isbn_info(isbn_data)
        except requests.exceptions.RequestException as e:
            print(f"Error searching by ISBN: {e}")
        return None
    
    def translate_to_spanish(self, text: str) -> str:
        """Translate text to Spanish using Google Translate API."""
        try:
            # Check if text is already in Spanish (basic check)
            if self._is_likely_spanish(text):
                return text
            
            # Use Google Translate API (unofficial but free)
            params = {
                'client': 'gtx',
                'sl': 'auto',  # auto-detect source language
                'tl': 'es',    # target language: Spanish
                'dt': 't',
                'q': text
            }
            
            response = requests.get(self.translation_url, params=params)
            if response.status_code == 200:
                # Parse the response
                result = response.json()
                if result and len(result) > 0 and result[0]:
                    translated_text = ''.join([item[0] for item in result[0] if item[0]])
                    return translated_text if translated_text else text
        except Exception as e:
            print(f"Translation error: {e}")
        
        return text  # Return original text if translation fails
    
    def _is_likely_spanish(self, text: str) -> bool:
        """Basic check if text is likely already in Spanish."""
        spanish_words = ['el', 'la', 'los', 'las', 'de', 'del', 'en', 'un', 'una', 'y', 'con', 'por', 'para', 'como', 'más', 'también', 'pero']
        text_lower = text.lower()
        
        # Check for common Spanish words
        spanish_word_count = sum(1 for word in spanish_words if word in text_lower)
        
        # If we find 2 or more Spanish words, assume it's already Spanish
        return spanish_word_count >= 2
    
    def _extract_book_info(self, book_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract relevant information from Open Library API search response."""
        title = book_data.get("title", "Título desconocido")
        
        # Translate title to Spanish
        title = self.translate_to_spanish(title)
        
        # Handle authors
        authors = book_data.get("author_name", [])
        author = ", ".join(authors) if authors else "Autor desconocido"
        
        # Handle publisher - only use first one
        publishers = book_data.get("publisher", [])
        publisher = publishers[0] if publishers else "Editorial desconocida"
        
        return {
            "titulo": title,
            "autor": author,
            "editorial": publisher
        }
    
    def _extract_isbn_info(self, isbn_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract information from Open Library ISBN endpoint."""
        title = isbn_data.get("title", "Título desconocido")
        
        # Translate title to Spanish
        title = self.translate_to_spanish(title)
        
        # Handle authors
        authors = isbn_data.get("authors", [])
        author_names = []
        for author in authors:
            if isinstance(author, dict) and "key" in author:
                # Get author details
                author_url = f"https://openlibrary.org{author['key']}.json"
                try:
                    author_response = requests.get(author_url)
                    if author_response.status_code == 200:
                        author_data = author_response.json()
                        author_names.append(author_data.get("name", ""))
                except:
                    pass
        
        author = ", ".join(filter(None, author_names)) if author_names else "Autor desconocido"
        
        # Handle publishers - only use first one
        publishers = isbn_data.get("publishers", [])
        publisher = None
        for pub in publishers:
            if isinstance(pub, str):
                publisher = pub
                break
            elif isinstance(pub, dict) and "name" in pub:
                publisher = pub["name"]
                break
        
        publisher = publisher if publisher else "Editorial desconocida"
        
        return {
            "titulo": title,
            "autor": author,
            "editorial": publisher
        }


class BookScannerApp:
    """Main application class for the Book Scanner."""
    
    def __init__(self):
        # Set appearance mode and color theme
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")
        
        # Initialize main window
        self.root = ctk.CTk()
        self.root.title("Book Scanner - Inventario de Libros")
        self.root.geometry("900x700")
        self.default_bg = self.root.cget("fg_color")
        
        # Initialize components
        self.db = DatabaseManager()
        self.api = OpenLibraryAPI()
        
        # State variables
        self.current_book_data = None
        self.editing_book_id = None
        self.is_searching = False
        
        # Create GUI
        self.create_widgets()
        
        # Set initial focus
        self.isbn_entry.focus_set()
        
        # Bind Enter key to ISBN entry
        self.isbn_entry.bind("<Return>", self.on_isbn_enter)
        
        # Load initial data
        self.refresh_book_table()
    
    def create_widgets(self):
        """Create all GUI widgets."""
        # Main container with padding
        main_frame = ctk.CTkFrame(self.root)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Title
        title_label = ctk.CTkLabel(main_frame, text="📚 Escáner de Libros", 
                                  font=ctk.CTkFont(size=24, weight="bold"))
        title_label.pack(pady=(0, 20))
        
        # Input section
        input_frame = ctk.CTkFrame(main_frame)
        input_frame.pack(fill="x", pady=(0, 20))
        
        # ISBN Entry (always has focus)
        isbn_frame = ctk.CTkFrame(input_frame)
        isbn_frame.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkLabel(isbn_frame, text="ISBN:", font=ctk.CTkFont(size=14, weight="bold")).pack(side="left", padx=(0, 10))
        self.isbn_entry = ctk.CTkEntry(isbn_frame, font=ctk.CTkFont(size=14), width=300)
        self.isbn_entry.pack(side="left", padx=(0, 10))
        
        # Search button
        self.search_btn = ctk.CTkButton(isbn_frame, text="🔍 Buscar", 
                                      command=self.search_book, width=100)
        self.search_btn.pack(side="left")
        
        # Status label
        self.status_label = ctk.CTkLabel(isbn_frame, text="Listo para escanear", 
                                       font=ctk.CTkFont(size=12))
        self.status_label.pack(side="left", padx=(20, 0))
        
        # Book details frame
        details_frame = ctk.CTkFrame(input_frame)
        details_frame.pack(fill="x", padx=10, pady=10)
        
        # Title
        title_frame = ctk.CTkFrame(details_frame)
        title_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(title_frame, text="Título:", font=ctk.CTkFont(size=14, weight="bold"), width=100).pack(side="left", padx=(0, 10))
        self.title_entry = ctk.CTkEntry(title_frame, font=ctk.CTkFont(size=14))
        self.title_entry.pack(side="left", fill="x", expand=True)
        
        # Author
        author_frame = ctk.CTkFrame(details_frame)
        author_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(author_frame, text="Autor:", font=ctk.CTkFont(size=14, weight="bold"), width=100).pack(side="left", padx=(0, 10))
        self.author_entry = ctk.CTkEntry(author_frame, font=ctk.CTkFont(size=14))
        self.author_entry.pack(side="left", fill="x", expand=True)
        
        # Publisher
        publisher_frame = ctk.CTkFrame(details_frame)
        publisher_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(publisher_frame, text="Editorial:", font=ctk.CTkFont(size=14, weight="bold"), width=100).pack(side="left", padx=(0, 10))
        self.publisher_entry = ctk.CTkEntry(publisher_frame, font=ctk.CTkFont(size=14))
        self.publisher_entry.pack(side="left", fill="x", expand=True)
        
        # Quantity
        quantity_frame = ctk.CTkFrame(details_frame)
        quantity_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(quantity_frame, text="Cantidad:", font=ctk.CTkFont(size=14, weight="bold"), width=100).pack(side="left", padx=(0, 10))
        self.quantity_entry = ctk.CTkEntry(quantity_frame, font=ctk.CTkFont(size=14), width=100)
        self.quantity_entry.pack(side="left", padx=(0, 10))
        self.quantity_entry.insert(0, "1")
        
        # Action buttons
        button_frame = ctk.CTkFrame(input_frame)
        button_frame.pack(fill="x", padx=10, pady=10)
        
        self.save_btn = ctk.CTkButton(button_frame, text="💾 Guardar Libro", 
                                     command=self.save_book, width=150)
        self.save_btn.pack(side="left", padx=5)
        
        self.clear_btn = ctk.CTkButton(button_frame, text="🗑️ Limpiar Campos", 
                                      command=self.clear_fields, width=150)
        self.clear_btn.pack(side="left", padx=5)
        
        self.manual_btn = ctk.CTkButton(button_frame, text="✏️ Modo Manual", 
                                       command=self.toggle_manual_mode, width=150)
        self.manual_btn.pack(side="left", padx=5)
        
        # Table section
        table_frame = ctk.CTkFrame(main_frame)
        table_frame.pack(fill="both", expand=True)
        
        # Table title
        table_title = ctk.CTkLabel(table_frame, text="Libros Recientes", 
                                  font=ctk.CTkFont(size=18, weight="bold"))
        table_title.pack(pady=(10, 5))
        
        # Create Treeview for book list
        tree_frame = ctk.CTkFrame(table_frame)
        tree_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Configure style for Treeview
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        
        # Create Treeview
        # Add an extra column `estado` to indicate pending/failed status
        self.book_tree = ttk.Treeview(tree_frame, columns=("id", "isbn", "titulo", "autor", "editorial", "cantidad", "estado"), 
                         show="headings", height=15)
        
        # Define column headings and widths
        self.book_tree.heading("id", text="ID")
        self.book_tree.heading("isbn", text="ISBN")
        self.book_tree.heading("titulo", text="Título")
        self.book_tree.heading("autor", text="Autor")
        self.book_tree.heading("editorial", text="Editorial")
        self.book_tree.heading("cantidad", text="Cantidad")
        self.book_tree.heading("estado", text="Estado")
        
        self.book_tree.column("id", width=50, minwidth=50)
        self.book_tree.column("isbn", width=120, minwidth=100)
        self.book_tree.column("titulo", width=200, minwidth=150)
        self.book_tree.column("autor", width=150, minwidth=100)
        self.book_tree.column("editorial", width=120, minwidth=100)
        self.book_tree.column("cantidad", width=80, minwidth=60)
        self.book_tree.column("estado", width=120, minwidth=100)
        
        # Add scrollbar
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.book_tree.yview)
        self.book_tree.configure(yscrollcommand=scrollbar.set)
        
        # Pack treeview and scrollbar
        self.book_tree.pack(side="left", fill="both", expand=True)
        self.book_tree.bind("<<TreeviewSelect>>", self.on_book_select)
        self.book_tree.bind("<Button-3>", self.on_tree_right_click)
        scrollbar.pack(side="right", fill="y")
        
        # Context menu for right-click delete
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="Eliminar registro", command=self.delete_selected_book)
        
        # Table action buttons
        table_button_frame = ctk.CTkFrame(table_frame)
        table_button_frame.pack(fill="x", padx=10, pady=(0, 10))
        
        self.edit_btn = ctk.CTkButton(table_button_frame, text="✏️ Editar Seleccionado", 
                                     command=self.edit_selected_book, width=150)
        self.edit_btn.pack(side="left", padx=5)
        
        self.delete_btn = ctk.CTkButton(table_button_frame, text="🗑️ Eliminar Seleccionado", 
                                        command=self.delete_selected_book, width=150)
        self.delete_btn.pack(side="left", padx=5)
        
        self.refresh_btn = ctk.CTkButton(table_button_frame, text="🔄 Actualizar Lista", 
                                        command=self.refresh_book_table, width=150)
        self.refresh_btn.pack(side="left", padx=5)
        
        # Sync pending queue and manual-fill buttons
        self.sync_btn = ctk.CTkButton(table_button_frame, text="🔁 Sincronizar pendientes", 
                          command=self.sync_pending, width=180)
        self.sync_btn.pack(side="left", padx=5)

        self.manual_fill_btn = ctk.CTkButton(table_button_frame, text="✍️ Rellenar Manual", 
                             command=self.fill_selected_manual, width=150)
        self.manual_fill_btn.pack(side="left", padx=5)
    
    def on_isbn_enter(self, event=None):
        """Handle Enter key in ISBN entry."""
        if self.is_searching:
            return
        
        isbn = self.isbn_entry.get().strip()
        if not isbn:
            # If ISBN is empty, try to save current book (manual mode)
            if self.title_entry.get().strip():
                self.save_book()
            return
        
        # If we have book data from API, save it
        if self.current_book_data:
            self.save_book()
            return

        # If there's no data yet, add a pending book entry immediately and enqueue for background resolution
        self.add_pending_book(isbn)

    def add_pending_book(self, isbn: str):
        """Insert a placeholder book row and enqueue it for background resolution."""
        if not isbn:
            return

        # If the ISBN already exists locally, increment its quantity instead of queueing
        existing = self.db.get_book_by_isbn(isbn)
        if existing:
            self.db.increment_book_quantity(existing['id'])
            self.refresh_book_table()
            self.flash_completion({
                'isbn': existing['isbn'],
                'titulo': existing['titulo'],
                'autor': existing['autor'],
                'editorial': existing['editorial']
            })
            self.status_label.configure(text=f"📈 ISBN existente. Cantidad actualizada a {existing['cantidad'] + 1}")
            return

        # Use a placeholder title so NOT NULL constraint satisfied
        placeholder_title = f"ISBN {isbn} (pendiente)"
        try:
            new_id = self.db.add_book(isbn, placeholder_title, "", "")
            self.db.enqueue_pending(new_id, isbn)
            self.clear_fields()
            self.refresh_book_table()
            self.status_label.configure(text=f"📥 ISBN {isbn} agregado a la cola")
            # focus back to ISBN for fast scanning
            self.isbn_entry.focus_set()
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo encolar ISBN: {str(e)}")
    
    def search_book(self):
        """Search for book information using ISBN."""
        isbn = self.isbn_entry.get().strip()
        if not isbn:
            messagebox.showwarning("Advertencia", "Por favor ingrese un ISBN")
            return

        existing = self.db.get_book_by_isbn(isbn)
        if existing:
            self.db.increment_book_quantity(existing['id'])
            self.refresh_book_table()
            self.flash_completion({
                'isbn': existing['isbn'],
                'titulo': existing['titulo'],
                'autor': existing['autor'],
                'editorial': existing['editorial']
            })
            self.status_label.configure(text=f"📈 ISBN existente local. Cantidad aumentada a {existing['cantidad'] + 1}")
            return
        
        # Start search in a separate thread
        self.is_searching = True
        self.status_label.configure(text="Buscando libro...")
        self.search_btn.configure(state="disabled")
        
        thread = threading.Thread(target=self._search_book_thread, args=(isbn,))
        thread.daemon = True
        thread.start()
    
    def _search_book_thread(self, isbn: str):
        """Thread function to search for book information."""
        try:
            book_data = self.api.search_by_isbn(isbn)
            
            # Update GUI from main thread
            self.root.after(0, self._update_book_fields, book_data)
        except Exception as e:
            self.root.after(0, self._show_search_error, str(e))
    
    def _update_book_fields(self, book_data: Optional[Dict[str, Any]]):
        """Update the book fields with API response."""
        self.is_searching = False
        self.search_btn.configure(state="normal")
        
        if book_data:
            self.current_book_data = book_data
            self.title_entry.delete(0, "end")
            self.title_entry.insert(0, book_data["titulo"])
            self.author_entry.delete(0, "end")
            self.author_entry.insert(0, book_data["autor"])
            self.publisher_entry.delete(0, "end")
            self.publisher_entry.insert(0, book_data["editorial"])
            
            self.status_label.configure(text="✅ Libro encontrado. Presione Enter para guardar.")
            
            # Move focus to title entry for confirmation
            self.title_entry.focus_set()
            self.title_entry.select_range(0, "end")
        else:
            self.current_book_data = None
            self.status_label.configure(text="❌ Libro no encontrado. Ingrese datos manualmente.")
            self.title_entry.focus_set()
    
    def _show_search_error(self, error_msg: str):
        """Show search error message."""
        self.is_searching = False
        self.search_btn.configure(state="normal")
        self.status_label.configure(text="❌ Error en la búsqueda")
        messagebox.showerror("Error de Búsqueda", f"No se pudo buscar el libro: {error_msg}")
    
    def save_book(self):
        """Save the current book to the database."""
        # Get form data
        isbn = self.isbn_entry.get().strip() or None
        titulo = self.title_entry.get().strip()
        autor = self.author_entry.get().strip()
        editorial = self.publisher_entry.get().strip()
        
        # Validate required fields
        if not titulo:
            messagebox.showwarning("Advertencia", "El título es obligatorio")
            self.title_entry.focus_set()
            return
        
        try:
            cantidad_str = self.quantity_entry.get().strip() or "1"
            cantidad = int(cantidad_str)
            if cantidad < 1:
                raise ValueError()
        except ValueError:
            messagebox.showwarning("Advertencia", "La cantidad debe ser un número entero mayor o igual a 1")
            self.quantity_entry.focus_set()
            return

        try:
            if self.editing_book_id:
                # Update existing book
                success = self.db.update_book(self.editing_book_id, isbn, titulo, autor, editorial, cantidad)
                if success:
                    messagebox.showinfo("Éxito", "Libro actualizado correctamente")
                    self.editing_book_id = None
                    self.save_btn.configure(text="💾 Guardar Libro")
                    self.refresh_book_table()
                    self.flash_completion({
                        'isbn': isbn or '',
                        'titulo': titulo,
                        'autor': autor,
                        'editorial': editorial
                    })
                else:
                    messagebox.showerror("Error", "No se pudo actualizar el libro")
                    return
            else:
                # Add new book
                new_id = self.db.add_book(isbn, titulo, autor, editorial, cantidad)
                # If ISBN provided, enqueue for background resolution
                if isbn:
                    self.db.enqueue_pending(new_id, isbn)
                self.refresh_book_table()
                self.flash_completion({
                    'isbn': isbn or '',
                    'titulo': titulo,
                    'autor': autor,
                    'editorial': editorial
                })
                messagebox.showinfo("Éxito", "Libro guardado correctamente")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo guardar el libro: {str(e)}")
    
    def clear_fields(self):
        """Clear all input fields."""
        self.isbn_entry.delete(0, "end")
        self.title_entry.delete(0, "end")
        self.author_entry.delete(0, "end")
        self.publisher_entry.delete(0, "end")
        self.quantity_entry.delete(0, "end")
        self.quantity_entry.insert(0, "1")
        
        self.current_book_data = None
        self.editing_book_id = None
        self.save_btn.configure(text="💾 Guardar Libro")
        self.status_label.configure(text="Listo para escanear")
        
        # Return focus to ISBN field
        self.isbn_entry.focus_set()
    
    def toggle_manual_mode(self):
        """Toggle between automatic and manual entry modes."""
        if self.isbn_entry.cget("state") == "normal":
            self.isbn_entry.configure(state="disabled")
            self.manual_btn.configure(text="📷 Modo Escáner")
            self.status_label.configure(text="Modo manual activado")
            self.title_entry.focus_set()
        else:
            self.isbn_entry.configure(state="normal")
            self.manual_btn.configure(text="✏️ Modo Manual")
            self.status_label.configure(text="Modo escáner activado")
            self.isbn_entry.focus_set()
    
    def refresh_book_table(self):
        """Refresh the book table with latest data."""
        # Clear existing items
        for item in self.book_tree.get_children():
            self.book_tree.delete(item)
        
        # Load books from database
        books = self.db.get_recent_books()
        pending_map = self.db.get_pending_map()

        for book in books:
            cantidad = book[5]
            # Determine estado from pending map
            estado = pending_map.get(book[0], "")
            if estado == 'pending':
                estado_display = '⏳ pendiente'
            elif estado == 'retry':
                estado_display = '⚠️ reintentar'
            elif estado == 'failed':
                estado_display = '❌ fallo'
            else:
                estado_display = ''

            self.book_tree.insert("", "end", values=(
                book[0],  # id
                book[1] or "-",  # isbn
                book[2],  # titulo
                book[3] or "-",  # autor
                book[4] or "-",  # editorial
                cantidad,  # cantidad
                estado_display
            ))
    
    def edit_selected_book(self):
        """Edit the selected book from the table."""
        selection = self.book_tree.selection()
        if not selection:
            messagebox.showwarning("Advertencia", "Por favor seleccione un libro para editar")
            return
        
        # Get selected item
        item = self.book_tree.item(selection[0])
        values = item["values"]
        
        # Load book data into form
        book_id = values[0]
        isbn = values[1] if values[1] != "-" else ""
        titulo = values[2]
        autor = values[3] if values[3] != "-" else ""
        editorial = values[4] if values[4] != "-" else ""
        
        self.isbn_entry.delete(0, "end")
        self.isbn_entry.insert(0, isbn)
        
        self.title_entry.delete(0, "end")
        self.title_entry.insert(0, titulo)
        
        self.author_entry.delete(0, "end")
        self.author_entry.insert(0, autor)
        
        self.publisher_entry.delete(0, "end")
        self.publisher_entry.insert(0, editorial)
        
        self.quantity_entry.delete(0, "end")
        self.quantity_entry.insert(0, str(values[5] if len(values) > 5 and values[5] not in (None, "-") else 1))
        
        # Set editing mode
        self.editing_book_id = book_id
        self.save_btn.configure(text="💾 Actualizar Libro")
        
        # Focus on title field
        self.title_entry.focus_set()
        self.title_entry.select_range(0, "end")
        
        self.status_label.configure(text="Modo edición activado")

    def fill_selected_manual(self):
        """If a pending item failed, allow manual filling of its fields."""
        selection = self.book_tree.selection()
        if not selection:
            messagebox.showwarning("Advertencia", "Por favor seleccione un libro")
            return

        item = self.book_tree.item(selection[0])
        values = item["values"]
        book_id = values[0]

        # Load book from DB
        with sqlite3.connect(self.db.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, isbn, titulo, autor, editorial, cantidad FROM libros WHERE id = ?", (book_id,))
            row = cursor.fetchone()
            if not row:
                messagebox.showerror("Error", "Libro no encontrado en la base de datos")
                return

        # Populate form for manual editing
        isbn = row[1] or ""
        titulo = row[2] or ""
        autor = row[3] or ""
        editorial = row[4] or ""
        cantidad = row[5] if row[5] is not None else 1

        self.isbn_entry.delete(0, "end")
        self.isbn_entry.insert(0, isbn)
        self.title_entry.delete(0, "end")
        self.title_entry.insert(0, titulo)
        self.author_entry.delete(0, "end")
        self.author_entry.insert(0, autor)
        self.publisher_entry.delete(0, "end")
        self.publisher_entry.insert(0, editorial)
        self.quantity_entry.delete(0, "end")
        self.quantity_entry.insert(0, str(cantidad))

        # Mark editing mode
        self.editing_book_id = book_id
        self.save_btn.configure(text="💾 Actualizar Libro")
        self.status_label.configure(text="Rellene los campos manualmente y presione Guardar")

    def on_book_select(self, event=None):
        """Load selected book row values into the form for editing."""
        selection = self.book_tree.selection()
        if not selection:
            return

        item = self.book_tree.item(selection[0])
        values = item.get("values", [])
        if len(values) < 6:
            return

        book_id = values[0]
        isbn = values[1] if values[1] != "-" else ""
        titulo = values[2] if values[2] != "-" else ""
        autor = values[3] if values[3] != "-" else ""
        editorial = values[4] if values[4] != "-" else ""

        self.isbn_entry.configure(state="normal")
        self.isbn_entry.delete(0, "end")
        self.isbn_entry.insert(0, isbn)
        self.title_entry.delete(0, "end")
        self.title_entry.insert(0, titulo)
        self.author_entry.delete(0, "end")
        self.author_entry.insert(0, autor)
        self.publisher_entry.delete(0, "end")
        self.publisher_entry.insert(0, editorial)
        self.quantity_entry.delete(0, "end")
        self.quantity_entry.insert(0, str(values[5] if len(values) > 5 and values[5] not in (None, "-") else 1))

        self.editing_book_id = book_id
        self.save_btn.configure(text="💾 Actualizar Libro")
        self.status_label.configure(text="Fila seleccionada para edición")

    def delete_selected_book(self):
        """Delete the selected book from the table."""
        selection = self.book_tree.selection()
        if not selection:
            messagebox.showwarning("Advertencia", "Por favor seleccione un libro para eliminar")
            return
        
        # Get selected item
        item = self.book_tree.item(selection[0])
        values = item["values"]
        book_id = values[0]
        titulo = values[2]
        
        # Confirm deletion
        result = messagebox.askyesno("Confirmar Eliminación", 
                                   f"¿Está seguro que desea eliminar el libro '{titulo}'?")
        
        if result:
            try:
                # Stop pending queue for this book if needed
                self.db.remove_pending(book_id)
                success = self.db.delete_book(book_id)
                if success:
                    messagebox.showinfo("Éxito", "Libro eliminado correctamente")
                    self.refresh_book_table()
                else:
                    messagebox.showerror("Error", "No se pudo eliminar el libro")
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo eliminar el libro: {str(e)}")

    def sync_pending(self):
        """Trigger background sync worker to process pending ISBNs immediately."""
        # Start a background thread to process pending items once
        thread = threading.Thread(target=self._process_pending_once, daemon=True)
        thread.start()

    def _process_pending_once(self):
        items = self.db.get_pending_items(limit=50)
        for pending in items:
            pending_id, book_id, isbn, status, attempts = pending
            try:
                info = self.api.search_by_isbn(isbn)
                if info:
                    # Update book row
                    self.db.update_book(book_id, isbn, info.get('titulo', ''), info.get('autor', ''), info.get('editorial', ''))
                    # Remove pending
                    self.db.remove_pending(book_id)
                    # Refresh UI and flash completion
                    self.root.after(0, self.refresh_book_table)
                    self.root.after(0, lambda info=info: self.flash_completion({
                        'isbn': isbn,
                        'titulo': info.get('titulo', ''),
                        'autor': info.get('autor', ''),
                        'editorial': info.get('editorial', '')
                    }))
                else:
                    # Increment attempts and mark accordingly
                    self.db.increment_pending_attempts(book_id, error='Not found')
            except Exception as e:
                self.db.increment_pending_attempts(book_id, error=str(e))
    
    def run(self):
        """Start the application."""
        self.root.mainloop()

    def flash_completion(self, book_data: Dict[str, Any]):
        """Show book data in the form and flash the background green."""
        self.isbn_entry.configure(state="normal")
        self.isbn_entry.delete(0, "end")
        self.isbn_entry.insert(0, book_data.get('isbn', ''))
        self.title_entry.delete(0, "end")
        self.title_entry.insert(0, book_data.get('titulo', ''))
        self.author_entry.delete(0, "end")
        self.author_entry.insert(0, book_data.get('autor', ''))
        self.publisher_entry.delete(0, "end")
        self.publisher_entry.insert(0, book_data.get('editorial', ''))
        self.status_label.configure(text="✅ Libro encontrado y actualizado")
        try:
            self.root.configure(fg_color="#d4f7d4")
        except Exception:
            pass
        self.root.after(500, self._clear_flash)

    def _clear_flash(self):
        try:
            self.root.configure(fg_color=self.default_bg)
        except Exception:
            pass
        self.clear_fields()

    def on_tree_right_click(self, event):
        """Show right-click menu on a treeview row."""
        row_id = self.book_tree.identify_row(event.y)
        if row_id:
            self.book_tree.selection_set(row_id)
            self.context_menu.tk_popup(event.x_root, event.y_root)
        else:
            self.context_menu.unpost()


def start_background_worker(app: BookScannerApp):
    """Background worker thread that continuously processes pending ISBNs with backoff."""
    db = app.db
    api = app.api
    backoff = 1
    while True:
        items = db.get_pending_items(limit=20)
        if not items:
            time.sleep(5)
            continue

        for pending in items:
            pending_id, book_id, isbn, status, attempts = pending
            try:
                info = api.search_by_isbn(isbn)
                if info:
                    db.update_book(book_id, isbn, info.get('titulo', ''), info.get('autor', ''), info.get('editorial', ''))
                    db.remove_pending(book_id)
                    app.root.after(0, app.refresh_book_table)
                else:
                    db.increment_pending_attempts(book_id, error='Not found')
            except Exception as e:
                db.increment_pending_attempts(book_id, error=str(e))

        # Short sleep to avoid hammering network; backoff if many failures
        time.sleep(backoff)
        backoff = min(10, backoff + 1)


if __name__ == "__main__":
    app = BookScannerApp()
    # Start background worker
    worker = threading.Thread(target=start_background_worker, args=(app,), daemon=True)
    worker.start()
    app.run()
