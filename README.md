# 📚 Book Scanner - Sistema de Inventario de Libros

Una aplicación de escritorio moderna para gestionar inventario de libros utilizando escáner de ISBN y la API de Open Library.

## 🚀 Características

### Funcionalidades Principales
- **Escaneo de ISBN**: Escanea códigos de barras de libros y obtiene información automáticamente
- **Integración con Open Library API**: Obtiene título, autor y editorial automáticamente
- **Modo Manual**: Permite entrada manual de datos para libros antiguos o sin ISBN
- **Base de Datos SQLite**: Almacenamiento local y persistente de datos
- **Interfaz Moderna**: Diseño intuitivo con CustomTkinter
- **CRUD Completo**: Crear, leer, actualizar y eliminar registros

### Características Técnicas
- **Threading**: Búsquedas asíncronas que no bloquean la interfaz
- **Auto-enfoque**: El campo ISBN siempre mantiene el foco para escaneo continuo
- **Manejo de Errores**: Gestión robusta de errores de conexión y API
- **Validación de Datos**: Validación de campos obligatorios

## 📋 Requisitos del Sistema

- Python 3.7 o superior
- Conexión a internet (para búsquedas en Google Books API)
- Windows, macOS o Linux

## 🛠️ Instalación

1. **Clonar o descargar el proyecto**
   ```bash
   git clone <repository-url>
   cd BookScanner
   ```

2. **Instalar dependencias**
   ```bash
   pip install -r requirements.txt
   ```

3. **Ejecutar la aplicación**
   ```bash
   python book_scanner.py
   ```

## 📖 Uso

### Modo Escáner (Predeterminado)
1. El campo ISBN tiene el foco automáticamente
2. **Escanea el ISBN con un lector de códigos de barras o ingrésalo manualmente**
3. Presiona `Enter` para buscar en Open Library API
4. Si se encuentra el libro, los campos se autocompletarán
5. Presiona `Enter` nuevamente para guardar
6. Los campos se limpiarán automáticamente y el foco volverá al ISBN

### Modo Manual
1. Haz clic en "Modo Manual" o usa el botón `✏️ Modo Manual`
2. El campo ISBN se deshabilitará
3. Ingresa directamente el título, autor y editorial
4. Haz clic en "Guardar Libro" para almacenar

### Gestión de Libros
- **Ver libros recientes**: La tabla inferior muestra los últimos 50 libros agregados
- **Editar libro**: Selecciona un libro y haz clic en "Editar Seleccionado"
- **Eliminar libro**: Selecciona un libro y haz clic en "Eliminar Seleccionado"
- **Actualizar lista**: Haz clic en "Actualizar Lista" para recargar los datos

## 🗂️ Estructura del Proyecto

```
BookScanner/
├── book_scanner.py      # Aplicación principal
├── requirements.txt     # Dependencias de Python
├── README.md           # Documentación
└── book_inventory.db   # Base de datos SQLite (se crea automáticamente)
```

## 🏗️ Arquitectura

### Clases Principales

#### `DatabaseManager`
- Gestiona todas las operaciones con SQLite
- Métodos: `add_book()`, `get_recent_books()`, `delete_book()`, `update_book()`

#### `OpenLibraryAPI`
- Maneja la comunicación con la API de Open Library
- Métodos: `search_by_isbn()`, `_extract_book_info()`, `_extract_isbn_info()`

#### `BookScannerApp`
- Interfaz principal de la aplicación
- Gestiona eventos y actualizaciones de la GUI

### Flujo de Trabajo

1. **Entrada de ISBN** → Validación
2. **Búsqueda en API** (threading) → Procesamiento asíncrono
3. **Autocompletar campos** → Confirmación visual
4. **Guardar en BD** → Limpieza de formulario
5. **Actualizar tabla** → Retorno al paso 1

## 🔧 Configuración

### Base de Datos
- **Nombre**: `book_inventory.db` (SQLite)
- **Tabla**: `libros`
- **Campos**: 
  - `id` (PRIMARY KEY, AUTOINCREMENT)
  - `isbn` (TEXT, nullable)
  - `titulo` (TEXT, NOT NULL)
  - `autor` (TEXT)
  - `editorial` (TEXT)
  - `fecha_registro` (TIMESTAMP)

### API Configuration
- **Endpoint**: Open Library API
- **Timeout**: 10 segundos
- **Límite**: Sin límite de solicitudes (uso personal)

## 🐛 Solución de Problemas

### Problemas Comunes

**No se encuentra un libro**
- Verifica la conexión a internet
- Confirma que el ISBN sea correcto
- Algunos libros antiguos no están en Google Books

**La aplicación se bloquea**
- Reinicia la aplicación
- Verifica que no haya otra instancia ejecutándose

**Error de base de datos**
- Elimina el archivo `book_inventory.db` y reinicia
- La aplicación creará una nueva base de datos automáticamente

### Registro de Errores
Los errores se imprimen en la consola para depuración. Para verlos, ejecuta la aplicación desde la terminal:

```bash
python book_scanner.py
```

## 📝 Notas de Desarrollo

### Tecnologías Utilizadas
- **CustomTkinter**: Interfaz gráfica moderna
- **SQLite**: Base de datos ligera y sin servidor
- **Requests**: Cliente HTTP para la API
- **Threading**: Operaciones asíncronas

### Mejoras Futuras
- Exportación a CSV/Excel
- Búsqueda avanzada en la tabla
- Categorización de libros
- Soporte para múltiples idiomas
- Copias de seguridad automáticas

## 📄 Licencia

Este proyecto es de código abierto y está disponible bajo la Licencia MIT.

## 👤 Autor

Desarrollado como un sistema de inventario de libros personalizado con funcionalidades completas de escaneo y gestión.

---

**¡Disfruta escaneando y organizando tu biblioteca! 📚✨**
