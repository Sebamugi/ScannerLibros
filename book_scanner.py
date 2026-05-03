import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox
import sqlite3
import requests
import threading
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
                    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
    
    def add_book(self, isbn: Optional[str], titulo: str, autor: str = "", editorial: str = "") -> int:
        """Add a new book to the database."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO libros (isbn, titulo, autor, editorial)
                VALUES (?, ?, ?, ?)
            """, (isbn, titulo, autor, editorial))
            conn.commit()
            return cursor.lastrowid
    
    def get_recent_books(self, limit: int = 50) -> list:
        """Get the most recently added books."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, isbn, titulo, autor, editorial, fecha_registro
                FROM libros
                ORDER BY fecha_registro DESC
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
    
    def update_book(self, book_id: int, isbn: Optional[str], titulo: str, autor: str, editorial: str) -> bool:
        """Update an existing book in the database."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE libros 
                SET isbn = ?, titulo = ?, autor = ?, editorial = ?
                WHERE id = ?
            """, (isbn, titulo, autor, editorial, book_id))
            conn.commit()
            return cursor.rowcount > 0


class OpenLibraryAPI:
    """Handles communication with the Open Library API."""
    
    def __init__(self):
        self.base_url = "https://openlibrary.org/api"
        self.search_url = "https://openlibrary.org/search.json"
        self.translation_url = "https://translate.googleapis.com/translate_a/single"
    
    def search_by_isbn(self, isbn: str) -> Optional[Dict[str, Any]]:
        """Search for a book by ISBN using Open Library API."""
        try:
            # Clean ISBN (remove hyphens and spaces)
            clean_isbn = isbn.replace("-", "").replace(" ", "")
            
            # First try ISBN search
            url = f"{self.search_url}?q=isbn:{clean_isbn}&fields=key,title,author_name,publisher,first_publish_year&limit=1"
            
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get("numFound", 0) > 0:
                    return self._extract_book_info(data["docs"][0])
                else:
                    # Try alternative ISBN search method
                    isbn_url = f"https://openlibrary.org/isbn/{clean_isbn}.json"
                    isbn_response = requests.get(isbn_url, timeout=10)
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
            
            response = requests.get(self.translation_url, params=params, timeout=5)
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
                    author_response = requests.get(author_url, timeout=5)
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
        self.book_tree = ttk.Treeview(tree_frame, columns=("id", "isbn", "titulo", "autor", "editorial", "fecha"), 
                                     show="headings", height=15)
        
        # Define column headings and widths
        self.book_tree.heading("id", text="ID")
        self.book_tree.heading("isbn", text="ISBN")
        self.book_tree.heading("titulo", text="Título")
        self.book_tree.heading("autor", text="Autor")
        self.book_tree.heading("editorial", text="Editorial")
        self.book_tree.heading("fecha", text="Fecha")
        
        self.book_tree.column("id", width=50, minwidth=50)
        self.book_tree.column("isbn", width=120, minwidth=100)
        self.book_tree.column("titulo", width=200, minwidth=150)
        self.book_tree.column("autor", width=150, minwidth=100)
        self.book_tree.column("editorial", width=120, minwidth=100)
        self.book_tree.column("fecha", width=120, minwidth=100)
        
        # Add scrollbar
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.book_tree.yview)
        self.book_tree.configure(yscrollcommand=scrollbar.set)
        
        # Pack treeview and scrollbar
        self.book_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
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
        else:
            # Otherwise, search for the book
            self.search_book()
    
    def search_book(self):
        """Search for book information using ISBN."""
        isbn = self.isbn_entry.get().strip()
        if not isbn:
            messagebox.showwarning("Advertencia", "Por favor ingrese un ISBN")
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
            if self.editing_book_id:
                # Update existing book
                success = self.db.update_book(self.editing_book_id, isbn, titulo, autor, editorial)
                if success:
                    messagebox.showinfo("Éxito", "Libro actualizado correctamente")
                    self.editing_book_id = None
                    self.save_btn.configure(text="💾 Guardar Libro")
                else:
                    messagebox.showerror("Error", "No se pudo actualizar el libro")
                    return
            else:
                # Add new book
                self.db.add_book(isbn, titulo, autor, editorial)
                messagebox.showinfo("Éxito", "Libro guardado correctamente")
            
            # Clear fields and refresh
            self.clear_fields()
            self.refresh_book_table()
            
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo guardar el libro: {str(e)}")
    
    def clear_fields(self):
        """Clear all input fields."""
        self.isbn_entry.delete(0, "end")
        self.title_entry.delete(0, "end")
        self.author_entry.delete(0, "end")
        self.publisher_entry.delete(0, "end")
        
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
        
        for book in books:
            # Format date
            fecha = book[5]
            if isinstance(fecha, str):
                try:
                    # Parse and reformat date
                    dt = datetime.strptime(fecha, "%Y-%m-%d %H:%M:%S")
                    fecha = dt.strftime("%d/%m/%Y")
                except:
                    pass
            
            # Insert into treeview
            self.book_tree.insert("", "end", values=(
                book[0],  # id
                book[1] or "-",  # isbn
                book[2],  # titulo
                book[3] or "-",  # autor
                book[4] or "-",  # editorial
                fecha  # fecha
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
        
        # Set editing mode
        self.editing_book_id = book_id
        self.save_btn.configure(text="💾 Actualizar Libro")
        
        # Focus on title field
        self.title_entry.focus_set()
        self.title_entry.select_range(0, "end")
        
        self.status_label.configure(text="Modo edición activado")
    
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
                success = self.db.delete_book(book_id)
                if success:
                    messagebox.showinfo("Éxito", "Libro eliminado correctamente")
                    self.refresh_book_table()
                else:
                    messagebox.showerror("Error", "No se pudo eliminar el libro")
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo eliminar el libro: {str(e)}")
    
    def run(self):
        """Start the application."""
        self.root.mainloop()


if __name__ == "__main__":
    app = BookScannerApp()
    app.run()
