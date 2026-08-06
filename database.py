import sqlite3
import json
import os
import re
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import contextlib
import logging
import bcrypt
import secrets

# Configuración básica de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_PATH = "xatelier.db"
DB_TIMEOUT = 30  # segundos
SESSION_EXPIRE_HOURS = 24

# --- Datos base para inicialización ---
BASE_PLATOS = [
    {
        "category": "Al Ast",
        "items": [
            {"id": "a4", "name": "Galta de cerdo", "desc": "Tierna y asada en su jugo", "price": 6.50, "activo": True},
            {"id": "a5", "name": "Butifarra de Calaf", "desc": "Butifarra tradicional de alta calidad", "price": 5.50, "activo": True},
            {"id": "a7", "name": "Muslo de pollo", "desc": "Jugoso muslo asado al ast", "price": 4.50, "activo": True},
            {"id": "a6", "name": "Conejo al ast", "desc": "Hecho exclusivamente bajo encargo previo", "price": 23.00, "activo": True},
            {"id": "a1", "name": "Pollo Entero", "desc": "Pollo Groc Català de 1,35-1,40 kg", "price": 14.50, "activo": True, "stock_group": "pollo", "stock_unit": 1.0},
            {"id": "a2", "name": "½ Pollo", "desc": "Mitad de pollo rustido al ast", "price": 8.00, "activo": True, "stock_group": "pollo", "stock_unit": 0.5}
        ]
    },
    {
        "category": "Menús Completos",
        "items": [
            {
                "id": "m1", "name": "Menú Nº1", "desc": "Pollo Entero + Patatas + 12 Croquetas",
                "price": 29.00, "options": [
                    {"label": "Con Patatas Caliu", "extra": 0},
                    {"label": "Con Patatas Bravas (Normales)", "extra": 0},
                    {"label": "Con Patatas Bravas (Grandes)", "extra": 3.00}
                ], "croquetasReq": 12, "activo": True,
                "requires_all": ["a1", "c1"]
            },
            {
                "id": "m2", "name": "Menú Nº2", "desc": "Pollo Entero + Patatas + 6 Canelones",
                "price": 27.00, "options": [
                    {"label": "Con Patatas Caliu", "extra": 0},
                    {"label": "Con Patatas Bravas (Normales)", "extra": 0},
                    {"label": "Con Patatas Bravas (Grandes)", "extra": 3.00}
                ], "activo": True,
                "requires_all": ["a1", "e1"]
            },
            {
                "id": "m3", "name": "Menú Nº3", "desc": "½ Pollo + Patatas + 6 Croquetas",
                "price": 18.00, "options": [
                    {"label": "Con Patatas Caliu", "extra": 0},
                    {"label": "Con Patatas Bravas (Normales)", "extra": 0},
                    {"label": "Con Patatas Bravas (Grandes)", "extra": 3.00}
                ], "croquetasReq": 6, "activo": True,
                "requires_all": ["a2", "c1"]
            },
            {
                "id": "m4", "name": "Menú Nº4", "desc": "½ Pollo + Patatas + 6 Canelones",
                "price": 20.50, "options": [
                    {"label": "Con Patatas Caliu", "extra": 0},
                    {"label": "Con Patatas Bravas (Normales)", "extra": 0},
                    {"label": "Con Patatas Bravas (Grandes)", "extra": 3.00}
                ], "activo": True,
                "requires_all": ["a2", "e1"]
            },
            {"id": "ext_menu_can", "name": "6 Canelones extra", "desc": "Solo si has pedido un menú", "price": 9.00, "requires_menu": True, "activo": True, "requires_all": ["e1"]},
            {"id": "ext_menu_croq", "name": "6 Croquetas extra", "desc": "Solo si has pedido un menú", "price": 6.00, "croquetasReq": 6, "requires_menu": True, "activo": True, "requires_all": ["c1"]}
        ]
    },
    {
        "category": "Combos",
        "items": [
            {
                "id": "a3", "name": "Pollo + Caliu + Allioli", "desc": "El combo clásico de la casa",
                "price": 18.00, "activo": True,
                "requires_all": ["a1", "g2", "g10"]
            }
        ]
    },
    {
        "category": "Croquetas Caseras",
        "items": [
            {"id": "c1", "name": "Croquetas Sueltas", "desc": "Añade las unidades que quieras", "priceText": "1,25 € / unidad", "price": 1.25, "croquetasMin": 1, "extraPrice": 1.25, "activo": True},
            {
                "id": "c12", "name": "Pack Croquetas", "desc": "Elige tu combinación", "priceText": "12,00 € (1 € / unidad extra)",
                "price": 12.00, "croquetasMin": 12, "extraPrice": 1.00, "activo": True,
                "requires_all": ["c1"]
            }
        ]
    },
    {
        "category": "Platos Extra",
        "items": [
            {"id": "e1", "name": "Canelones de rustido", "desc": "Ración de canelones tradicionales con bechamel", "price": 10.00, "activo": True},
            {"id": "e4", "name": "½ Conejo al ajillo", "desc": "Sabroso y cocinado al momento", "price": 15.00, "activo": True},
            {"id": "e5", "name": "Calamares en salsa", "desc": "Tiernos calamares guisados en salsa casera", "price": 8.50, "activo": True},
            {"id": "e6", "name": "Berenjena rellena", "desc": "Relleno meloso horneado", "price": 4.00, "activo": True},
            {"id": "e2", "name": "Ensaladilla rusa", "desc": "Fresca, ligera y elaborada diariamente", "price": 4.50, "activo": True},
            {"id": "e7", "name": "Pastel de atún", "desc": "Ración de pastel frío suave", "price": 4.50, "activo": True},
            {"id": "e8", "name": "Macarrones", "desc": "Estilo casero tradicional", "price": 4.50, "activo": True}
        ]
    },
    {
        "category": "Guarniciones y Postres",
        "items": [
            {"id": "g2", "name": "Patatas Caliu", "desc": "Patatas asadas enteras tradicionales", "price": 3.00, "activo": True},
            {"id": "g1", "name": "Patatas Bravas", "desc": "Crujientes con nuestra salsa brava especial", "price": 4.50, "activo": True},
            {"id": "g8", "name": "Patata Panadera", "desc": "Cortadas finas al horno con hierbas", "price": 3.50, "activo": True},
            {"id": "g9", "name": "Champiñones", "desc": "Salteados con ajo y perejil", "price": 5.00, "activo": True},
            {"id": "g10", "name": "Allioli", "desc": "Tarrina de salsa alioli artesanal", "price": 1.50, "activo": True},
            {"id": "g3", "name": "Tarta de queso", "desc": "Postre dulce casero suave", "price": 2.50, "activo": True}
        ]
    }
]


# --- Gestión de conexiones con mejores prácticas ---
@contextlib.contextmanager
def get_connection():
    """Obtiene una conexión SQLite con las configuraciones óptimas para un servidor."""
    conn = sqlite3.connect(
        DB_PATH,
        timeout=DB_TIMEOUT,
        isolation_level=None  # Autocommit por defecto, pero usaremos transacciones explícitas
    )
    conn.row_factory = sqlite3.Row

    # Configuraciones esenciales por conexión
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA cache_size = -2000")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA synchronous = NORMAL")

    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Error en transacción SQLite: {e}")
        raise
    finally:
        conn.close()


# --- Inicialización de la base de datos ---
def init_database():
    """Crea las tablas, índices y datos iniciales si no existen."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # Tabla pedidos
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pedidos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha_entrega TEXT NOT NULL,
                hora_entrega TEXT NOT NULL,
                nombre TEXT NOT NULL,
                telefono TEXT NOT NULL,
                email TEXT,
                direccion TEXT,
                notas TEXT,
                metodo_entrega TEXT NOT NULL,
                total REAL NOT NULL CHECK(total >= 0),
                estado TEXT NOT NULL DEFAULT 'pendiente',
                timestamp TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                lat REAL,
                lng REAL,
                stock_consumido TEXT,
                sabores_consumidos TEXT,
                stock_restaurado INTEGER DEFAULT 0
            )
        ''')

        # Tabla pedido_items
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pedido_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pedido_id INTEGER NOT NULL,
                nombre TEXT NOT NULL,
                cantidad INTEGER NOT NULL DEFAULT 1 CHECK(cantidad > 0),
                precio REAL NOT NULL CHECK(precio >= 0),
                meta TEXT,
                plato_id TEXT,
                FOREIGN KEY (pedido_id) REFERENCES pedidos(id) ON DELETE CASCADE
            )
        ''')

        # Tabla platos
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS platos (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                price REAL,
                price_text TEXT,
                desc TEXT,
                category TEXT NOT NULL,
                activo INTEGER DEFAULT 1,
                croquetas_req INTEGER DEFAULT 0,
                croquetas_min INTEGER DEFAULT 0,
                extra_price REAL DEFAULT 0.0,
                requires_menu INTEGER DEFAULT 0,
                requires_all TEXT,
                requires_any TEXT,
                options TEXT,
                stock INTEGER,
                stock_diario INTEGER,
                stock_group TEXT,
                stock_unit REAL DEFAULT 1.0,
                es_nevera INTEGER DEFAULT 0,
                image_url TEXT,
                aparece_ticket_cocina INTEGER DEFAULT 1,
                marcable_preparado INTEGER DEFAULT 1,
                componentes TEXT
            )
        ''')

        # Tabla configuracion
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS configuracion (
                clave TEXT PRIMARY KEY,
                valor TEXT NOT NULL
            )
        ''')

        # Tabla usuarios
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                activo INTEGER DEFAULT 1
            )
        ''')

        # Tabla sesiones
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sesiones (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES usuarios(id) ON DELETE CASCADE
            )
        ''')

        # Índices
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_pedidos_estado ON pedidos(estado)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_pedidos_fecha ON pedidos(fecha_entrega)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_pedidos_telefono ON pedidos(telefono)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_pedidos_timestamp ON pedidos(timestamp)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_platos_category ON platos(category)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_platos_activo ON platos(activo)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_sesiones_user_id ON sesiones(user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_sesiones_expires_at ON sesiones(expires_at)')

        # Migraciones dinámicas para tablas existentes
        cursor.execute("PRAGMA table_info(platos)")
        columns = [row['name'] for row in cursor.fetchall()]
        if 'orden' not in columns: cursor.execute("ALTER TABLE platos ADD COLUMN orden INTEGER DEFAULT 0")
        if 'stock' not in columns: cursor.execute("ALTER TABLE platos ADD COLUMN stock INTEGER")
        if 'stock_diario' not in columns: cursor.execute("ALTER TABLE platos ADD COLUMN stock_diario INTEGER")
        if 'stock_group' not in columns: cursor.execute("ALTER TABLE platos ADD COLUMN stock_group TEXT")
        if 'stock_unit' not in columns: cursor.execute("ALTER TABLE platos ADD COLUMN stock_unit REAL DEFAULT 1.0")
        if 'es_nevera' not in columns: cursor.execute("ALTER TABLE platos ADD COLUMN es_nevera INTEGER DEFAULT 0")
        if 'image_url' not in columns: cursor.execute("ALTER TABLE platos ADD COLUMN image_url TEXT")
        if 'aparece_ticket_cocina' not in columns: cursor.execute("ALTER TABLE platos ADD COLUMN aparece_ticket_cocina INTEGER DEFAULT 1")
        if 'marcable_preparado' not in columns: cursor.execute("ALTER TABLE platos ADD COLUMN marcable_preparado INTEGER DEFAULT 1")
        if 'componentes' not in columns: cursor.execute("ALTER TABLE platos ADD COLUMN componentes TEXT")

        cursor.execute("PRAGMA table_info(pedidos)")
        columns_pedidos = [row['name'] for row in cursor.fetchall()]
        if 'stock_consumido' not in columns_pedidos: cursor.execute("ALTER TABLE pedidos ADD COLUMN stock_consumido TEXT")
        if 'sabores_consumidos' not in columns_pedidos: cursor.execute("ALTER TABLE pedidos ADD COLUMN sabores_consumidos TEXT")
        if 'stock_restaurado' not in columns_pedidos: cursor.execute("ALTER TABLE pedidos ADD COLUMN stock_restaurado INTEGER DEFAULT 0")
        if 'lat' not in columns_pedidos: cursor.execute("ALTER TABLE pedidos ADD COLUMN lat REAL")
        if 'lng' not in columns_pedidos: cursor.execute("ALTER TABLE pedidos ADD COLUMN lng REAL")

        cursor.execute("PRAGMA table_info(pedido_items)")
        columns_pi = [row['name'] for row in cursor.fetchall()]
        if 'plato_id' not in columns_pi: cursor.execute("ALTER TABLE pedido_items ADD COLUMN plato_id TEXT")

        cursor.execute("UPDATE platos SET croquetas_req = 6 WHERE id = 'ext_menu_croq' AND (croquetas_req IS NULL OR croquetas_req = 0)")

        # Inicializar platos base si la tabla está vacía
        cursor.execute("SELECT COUNT(*) FROM platos")
        if cursor.fetchone()[0] == 0:
            _insert_base_platos(cursor)

        # Inicializar configuracion si está vacía
        cursor.execute("SELECT COUNT(*) FROM configuracion")
        if cursor.fetchone()[0] == 0:
            default_sabores = ["Pollo", "Jamón", "Cocido", "Setas", "Cabrales", "Calamar"]
            cursor.execute("INSERT INTO configuracion (clave, valor) VALUES (?, ?)",
                           ("sabores_croquetas", json.dumps({s: None for s in default_sabores})))
            cursor.execute("INSERT INTO configuracion (clave, valor) VALUES (?, ?)",
                           ("dias_festivos", json.dumps({})))
            cursor.execute("INSERT INTO configuracion (clave, valor) VALUES (?, ?)",
                           ("importe_minimo_domicilio", json.dumps(18.0)))
            cursor.execute("INSERT INTO configuracion (clave, valor) VALUES (?, ?)",
                           ("delivery_fee", json.dumps(3.50)))

        # Asegurar valores de configuracion de Domicilio y Delivery si no existen por actualizaciones
        cursor.execute("SELECT clave FROM configuracion WHERE clave = 'importe_minimo_domicilio'")
        if cursor.fetchone() is None:
            cursor.execute("INSERT INTO configuracion (clave, valor) VALUES (?, ?)", ("importe_minimo_domicilio", json.dumps(18.0)))

        cursor.execute("SELECT clave FROM configuracion WHERE clave = 'delivery_fee'")
        if cursor.fetchone() is None:
            cursor.execute("INSERT INTO configuracion (clave, valor) VALUES (?, ?)", ("delivery_fee", json.dumps(3.50)))

        cursor.execute("SELECT valor FROM configuracion WHERE clave = 'sabores_croquetas'")
        row = cursor.fetchone()
        if row is not None:
            valor_actual = json.loads(row["valor"])
            if isinstance(valor_actual, list):
                nuevo_valor = {nombre: None for nombre in valor_actual}
                cursor.execute("UPDATE configuracion SET valor = ? WHERE clave = 'sabores_croquetas'",
                               (json.dumps(nuevo_valor),))

        cursor.execute("SELECT clave FROM configuracion WHERE clave = 'stock_compuestos_limpiado'")
        if cursor.fetchone() is None:
            cursor.execute('''
                UPDATE platos SET stock = NULL
                WHERE (requires_all IS NOT NULL AND requires_all != '' AND requires_all != '[]')
                   OR id IN ('c1', 'c12')
            ''')
            cursor.execute("INSERT OR IGNORE INTO configuracion (clave, valor) VALUES (?, ?)",
                           ("stock_compuestos_limpiado", json.dumps(True)))

        cursor.execute("SELECT clave FROM configuracion WHERE clave = 'stock_diario_migrado'")
        if cursor.fetchone() is None:
            cursor.execute("UPDATE platos SET stock_diario = stock WHERE stock_diario IS NULL AND stock IS NOT NULL")
            cursor.execute("SELECT valor FROM configuracion WHERE clave = 'sabores_croquetas'")
            row_sabores = cursor.fetchone()
            if row_sabores is not None:
                valor_sabores = json.loads(row_sabores["valor"])
                if isinstance(valor_sabores, dict):
                    cursor.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, ?)",
                                   ("sabores_croquetas_diario", json.dumps(valor_sabores)))
            cursor.execute("INSERT OR IGNORE INTO configuracion (clave, valor) VALUES (?, ?)",
                           ("stock_diario_migrado", json.dumps(True)))

        cursor.execute("SELECT clave FROM configuracion WHERE clave = 'stock_grupo_pollo_migrado'")
        if cursor.fetchone() is None:
            cursor.execute("UPDATE platos SET stock_group = 'pollo', stock_unit = 1.0 WHERE id = 'a1'")
            cursor.execute("UPDATE platos SET stock_group = 'pollo', stock_unit = 0.5 WHERE id = 'a2'")
            cursor.execute("SELECT stock, stock_diario FROM platos WHERE id = 'a1'")
            fila_a1 = cursor.fetchone()
            stock_inicial = fila_a1["stock"] if fila_a1 else None
            stock_diario_inicial = fila_a1["stock_diario"] if fila_a1 else None
            cursor.execute("SELECT valor FROM configuracion WHERE clave = 'stock_grupos'")
            row_grupos_existente = cursor.fetchone()
            grupos = json.loads(row_grupos_existente["valor"]) if row_grupos_existente else {}
            grupos.setdefault("pollo", {"stock": stock_inicial, "stock_diario": stock_diario_inicial})
            cursor.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, ?)",
                           ("stock_grupos", json.dumps(grupos)))
            cursor.execute("INSERT OR IGNORE INTO configuracion (clave, valor) VALUES (?, ?)",
                           ("stock_grupo_pollo_migrado", json.dumps(True)))

        cursor.execute("SELECT COUNT(*) FROM usuarios")
        if cursor.fetchone()[0] == 0:
            password_hash = bcrypt.hashpw("admin123".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            cursor.execute("INSERT INTO usuarios (username, password_hash, activo) VALUES (?, ?, ?)",
                           ("admin", password_hash, 1))

        limpiar_sesiones_expiradas()
        logger.info("Base de datos inicializada correctamente.")


def _insert_base_platos(cursor):
    for categoria in BASE_PLATOS:
        for item in categoria["items"]:
            options = json.dumps(item.get("options", []))
            requires_all = json.dumps(item.get("requires_all", []))
            requires_any = json.dumps(item.get("requires_any", []))
            cursor.execute('''
                INSERT INTO platos (
                    id, name, price, price_text, desc, category, activo,
                    croquetas_req, croquetas_min, extra_price, requires_menu,
                    requires_all, requires_any, options, stock, stock_group, stock_unit, es_nevera, image_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                item["id"],
                item["name"],
                item.get("price"),
                item.get("priceText"),
                item.get("desc", ""),
                categoria["category"],
                1 if item.get("activo", True) else 0,
                item.get("croquetasReq", 0),
                item.get("croquetasMin", 0),
                item.get("extraPrice", 0.0),
                1 if item.get("requires_menu", False) else 0,
                requires_all,
                requires_any,
                options,
                None,
                item.get("stock_group"),
                item.get("stock_unit", 1.0),
                item.get("es_nevera", 0),
                None
            ))


# --- Funciones para configuración general ---
def get_config(clave):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT valor FROM configuracion WHERE clave = ?", (clave,))
        row = cursor.fetchone()
        if row:
            return json.loads(row["valor"])
        return None

def set_config(clave, valor):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, ?)",
                       (clave, json.dumps(valor)))
        return True

# --- Funciones para categorías (secciones del menú) ---
def get_categorias():
    """Devuelve la lista de categorías en el orden guardado por el usuario."""
    orden = get_config("categorias_orden")
    if orden is None:
        orden = []

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT category FROM platos")
        existentes = [row["category"] for row in cursor.fetchall() if row["category"]]

    cambiado = False
    for cat in existentes:
        if cat not in orden:
            orden.append(cat)
            cambiado = True
    if cambiado:
        set_config("categorias_orden", orden)
    return orden


def crear_categoria(nombre: str):
    nombre = (nombre or "").strip()
    if not nombre:
        raise ValueError("El nombre de la categoría no puede estar vacío.")
    orden = get_categorias()
    if nombre in orden:
        raise ValueError(f"La categoría '{nombre}' ya existe.")
    orden.append(nombre)
    set_config("categorias_orden", orden)
    return orden


def eliminar_categoria(nombre: str):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM platos WHERE category = ?", (nombre,))
        count = cursor.fetchone()[0]
    if count > 0:
        raise ValueError("No se puede eliminar una categoría que todavía tiene platos asignados.")

    orden = get_categorias()
    if nombre in orden:
        orden.remove(nombre)
        set_config("categorias_orden", orden)
    return orden


def set_orden_categorias(nuevo_orden: list):
    actuales = get_categorias()
    if set(nuevo_orden) != set(actuales):
        raise ValueError("El nuevo orden debe contener exactamente las categorías existentes, sin añadir ni quitar ninguna.")
    set_config("categorias_orden", list(nuevo_orden))
    return nuevo_orden


# --- Funciones para festivos ---
def get_festivos():
    festivos = get_config("dias_festivos")
    return festivos if festivos is not None else {}

def añadir_festivo(fecha_ddmm: str, nombre: str):
    if not re.match(r"^\d{2}/\d{2}$", fecha_ddmm):
        raise ValueError("El formato de la fecha debe ser DD/MM")
    festivos = get_festivos()
    festivos[fecha_ddmm] = nombre
    set_config("dias_festivos", festivos)
    return True

def eliminar_festivo(fecha_ddmm: str):
    festivos = get_festivos()
    if fecha_ddmm in festivos:
        del festivos[fecha_ddmm]
        set_config("dias_festivos", festivos)
        return True
    return False

# --- Funciones para pedidos ---
def create_pedido(pedido_data, items, cantidades_por_plato=None, cantidades_por_sabor=None):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO pedidos (
                fecha_entrega, hora_entrega, nombre, telefono, email,
                direccion, notas, metodo_entrega, total, estado, timestamp,
                stock_consumido, sabores_consumidos, lat, lng
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            pedido_data["fecha_entrega"],
            pedido_data["hora_entrega"],
            pedido_data["nombre"],
            pedido_data["telefono"],
            pedido_data.get("email", ""),
            pedido_data.get("direccion", ""),
            pedido_data.get("notas", ""),
            pedido_data["metodo_entrega"],
            pedido_data["total"],
            "pendiente",
            datetime.now().isoformat(),
            json.dumps(cantidades_por_plato or {}),
            json.dumps(cantidades_por_sabor or {}),
            pedido_data.get("lat"),
            pedido_data.get("lng")
        ))
        pedido_id = cursor.lastrowid
        for item in items:
            cursor.execute('''
                INSERT INTO pedido_items (pedido_id, nombre, cantidad, precio, meta, plato_id)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                pedido_id,
                item.get("name"),
                item.get("qty", 1),
                item.get("price", 0.0),
                item.get("meta", ""),
                item.get("plato_id")
            ))
        return pedido_id


def get_pedido(pedido_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM pedidos WHERE id = ?", (pedido_id,))
        pedido = cursor.fetchone()
        if pedido is None:
            return None, None
        cursor.execute("SELECT * FROM pedido_items WHERE pedido_id = ?", (pedido_id,))
        items = cursor.fetchall()
        return dict(pedido), [dict(item) for item in items]


def list_pedidos(filters=None):
    with get_connection() as conn:
        cursor = conn.cursor()
        query = "SELECT * FROM pedidos"
        params = []
        where_clauses = []
        if filters:
            if "estado" in filters:
                where_clauses.append("estado = ?")
                params.append(filters["estado"])
            if "fecha_desde" in filters:
                where_clauses.append("fecha_entrega >= ?")
                params.append(filters["fecha_desde"])
            if "fecha_hasta" in filters:
                where_clauses.append("fecha_entrega <= ?")
                params.append(filters["fecha_hasta"])
            if "hoy" in filters and filters["hoy"]:
                hoy = datetime.now().date().isoformat()
                where_clauses.append("fecha_entrega = ?")
                params.append(hoy)
            if "q" in filters and filters["q"]:
                q = f"%{filters['q']}%"
                where_clauses.append("(nombre LIKE ? OR telefono LIKE ?)")
                params.append(q)
                params.append(q)
            if "metodo" in filters:
                where_clauses.append("metodo_entrega = ?")
                params.append(filters["metodo"])
            if "articulo" in filters and filters["articulo"]:
                articulos_filtro = filters["articulo"]
                if isinstance(articulos_filtro, str):
                    where_clauses.append("id IN (SELECT pedido_id FROM pedido_items WHERE nombre LIKE ?)")
                    params.append(f"%{articulos_filtro}%")
                else:
                    placeholders = ",".join("?" for _ in articulos_filtro)
                    where_clauses.append(f"id IN (SELECT pedido_id FROM pedido_items WHERE nombre IN ({placeholders}))")
                    params.extend(articulos_filtro)
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
        query += " ORDER BY fecha_entrega, hora_entrega"
        cursor.execute(query, params)
        pedidos = cursor.fetchall()
        result = []
        for p in pedidos:
            p_dict = dict(p)
            cursor.execute("SELECT * FROM pedido_items WHERE pedido_id = ?", (p["id"],))
            items = cursor.fetchall()
            p_dict["articulos"] = [dict(item) for item in items]
            result.append(p_dict)
        return result


def update_pedido_estado(pedido_id, estado):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE pedidos SET estado = ? WHERE id = ?", (estado, pedido_id))
        return cursor.rowcount > 0


def delete_pedido(pedido_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM pedidos WHERE id = ?", (pedido_id,))
        return cursor.rowcount > 0


def update_pedido_completo(pedido_id, pedido_data, items, nuevo_stock_consumido, nuevo_sabores_consumidos):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE pedidos SET
                fecha_entrega = ?, hora_entrega = ?, nombre = ?, telefono = ?,
                direccion = ?, notas = ?, metodo_entrega = ?, total = ?,
                lat = ?, lng = ?,
                stock_consumido = ?, sabores_consumidos = ?, stock_restaurado = 0
            WHERE id = ?
        ''', (
            pedido_data["fecha_entrega"],
            pedido_data["hora_entrega"],
            pedido_data["nombre"],
            pedido_data["telefono"],
            pedido_data.get("direccion", ""),
            pedido_data.get("notas", ""),
            pedido_data["metodo_entrega"],
            pedido_data["total"],
            pedido_data.get("lat"),
            pedido_data.get("lng"),
            json.dumps(nuevo_stock_consumido),
            json.dumps(nuevo_sabores_consumidos),
            pedido_id
        ))

        cursor.execute("DELETE FROM pedido_items WHERE pedido_id = ?", (pedido_id,))

        for item in items:
            cursor.execute('''
                INSERT INTO pedido_items (pedido_id, nombre, cantidad, precio, meta, plato_id)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                pedido_id,
                item.get("name"),
                item.get("qty", 1),
                item.get("price", 0.0),
                item.get("meta", ""),
                item.get("plato_id")
            ))
        return True


# --- Funciones para platos (con stock por fecha) ---
def get_stock_state(fecha: str) -> dict:
    key = f"stock_state_{fecha}"
    state = get_config(key)
    if state is not None: return state

    # Inicializar estado para esa fecha con el stock base (diario)
    state = {"platos": {}, "grupos": {}, "sabores": {}}
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, stock_diario, stock_group FROM platos")
        for row in cursor.fetchall():
            if not row["stock_group"]: state["platos"][row["id"]] = row["stock_diario"]

    grupos_base = get_config("stock_grupos") or {}
    for g_id, g_info in grupos_base.items():
        state["grupos"][g_id] = g_info.get("stock_diario")

    sabores_base = get_config("sabores_croquetas_diario") or {}
    state["sabores"] = dict(sabores_base)
    set_config(key, state)
    return state

def save_stock_state(fecha: str, state: dict):
    set_config(f"stock_state_{fecha}", state)

def get_platos(fecha=None):
    if not fecha: fecha = fecha_hoy()
    state = get_stock_state(fecha)

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM platos")
        rows = cursor.fetchall()

    platos = []
    for row in rows:
        p = dict(row)
        p["options"] = json.loads(p["options"]) if p["options"] else []
        p["requires_all"] = json.loads(p["requires_all"]) if p["requires_all"] else []
        p["requires_any"] = json.loads(p["requires_any"]) if p["requires_any"] else []
        p["componentes"] = json.loads(p["componentes"]) if p.get("componentes") else []
        p["activo"] = bool(p["activo"])
        p["requires_menu"] = bool(p["requires_menu"])
        p["es_nevera"] = bool(p.get("es_nevera", False))
        p["aparece_ticket_cocina"] = bool(p["aparece_ticket_cocina"]) if p.get("aparece_ticket_cocina") is not None else True
        p["marcable_preparado"] = bool(p["marcable_preparado"]) if p.get("marcable_preparado") is not None else True
        if p.get("croquetas_req"): p["croquetasReq"] = p["croquetas_req"]
        if p.get("croquetas_min"): p["croquetasMin"] = p["croquetas_min"]
        if p.get("extra_price"): p["extraPrice"] = p["extra_price"]
        p["priceText"] = p.get("price_text")

        # Asignar stock en base al state de la fecha
        if p.get("stock_group"):
            p["stock"] = state["grupos"].get(p["stock_group"])
        else:
            p["stock"] = state["platos"].get(p["id"])

        for key in ["croquetas_req", "croquetas_min", "extra_price", "requires_menu", "price_text"]:
            if key in p: del p[key]
        platos.append(p)
    return platos

def get_plato(plato_id, fecha=None):
    if not fecha: fecha = fecha_hoy()
    state = get_stock_state(fecha)
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM platos WHERE id = ?", (plato_id,))
        row = cursor.fetchone()
        if row is None: return None
        p = dict(row)
        p["options"] = json.loads(p["options"]) if p["options"] else []
        p["requires_all"] = json.loads(p["requires_all"]) if p["requires_all"] else []
        p["requires_any"] = json.loads(p["requires_any"]) if p["requires_any"] else []
        p["componentes"] = json.loads(p["componentes"]) if p.get("componentes") else []
        p["activo"] = bool(p["activo"])
        p["requires_menu"] = bool(p["requires_menu"])
        p["es_nevera"] = bool(p.get("es_nevera", False))
        p["aparece_ticket_cocina"] = bool(p["aparece_ticket_cocina"]) if p.get("aparece_ticket_cocina") is not None else True
        p["marcable_preparado"] = bool(p["marcable_preparado"]) if p.get("marcable_preparado") is not None else True
        if p.get("croquetas_req"): p["croquetasReq"] = p["croquetas_req"]
        if p.get("croquetas_min"): p["croquetasMin"] = p["croquetas_min"]
        if p.get("extra_price"): p["extraPrice"] = p["extra_price"]
        p["priceText"] = p.get("price_text")

        if p.get("stock_group"):
            p["stock"] = state["grupos"].get(p["stock_group"])
        else:
            p["stock"] = state["platos"].get(p["id"])

        for key in ["croquetas_req", "croquetas_min", "extra_price", "requires_menu", "price_text"]:
            if key in p: del p[key]
        return p

def crear_plato(datos: dict):
    plato_id = datos.get("id")
    if not plato_id:
        plato_id = str(uuid.uuid4())[:8]

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO platos (
                id, name, price, price_text, desc, category, activo,
                croquetas_req, croquetas_min, extra_price, requires_menu,
                requires_all, requires_any, options, stock, stock_diario,
                stock_group, stock_unit, es_nevera, image_url,
                aparece_ticket_cocina, marcable_preparado, componentes, orden
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            plato_id,
            datos.get("name"),
            datos.get("price"),
            datos.get("price_text"),
            datos.get("desc", ""),
            datos.get("category", "Otros"),
            datos.get("activo", 1),
            datos.get("croquetas_req", 0),
            datos.get("croquetas_min", 0),
            datos.get("extra_price", 0.0),
            datos.get("requires_menu", 0),
            json.dumps(datos.get("requires_all", [])),
            json.dumps(datos.get("requires_any", [])),
            json.dumps(datos.get("options", [])),
            datos.get("stock"),
            datos.get("stock_diario"),
            datos.get("stock_group"),
            datos.get("stock_unit", 1.0),
            datos.get("es_nevera", 0),
            datos.get("image_url"),
            datos.get("aparece_ticket_cocina", 1),
            datos.get("marcable_preparado", 1),
            json.dumps(datos.get("componentes", [])),
            datos.get("orden", 0)
        ))
    return plato_id

def editar_plato(plato_id: str, datos: dict):
    if not datos:
        return True
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM platos WHERE id = ?", (plato_id,))
        if not cursor.fetchone():
            return False

        campos = []
        valores = []
        for k, v in datos.items():
            if k == "id": continue
            # Adaptar nombres
            if k == "croquetasReq": k = "croquetas_req"
            elif k == "croquetasMin": k = "croquetas_min"
            elif k == "extraPrice": k = "extra_price"
            elif k == "priceText": k = "price_text"

            campos.append(f"{k} = ?")
            if k in ["requires_all", "requires_any", "options", "componentes"]:
                valores.append(json.dumps(v))
            else:
                valores.append(v)

        if campos:
            valores.append(plato_id)
            query = f"UPDATE platos SET {', '.join(campos)} WHERE id = ?"
            cursor.execute(query, valores)
        return True

def eliminar_plato(plato_id: str):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM platos WHERE id = ?", (plato_id,))
        row = cursor.fetchone()
        if not row:
            return None
        nombre_plato = row["name"]

        cursor.execute("SELECT COUNT(*) FROM pedido_items WHERE nombre = ?", (nombre_plato,))
        count = cursor.fetchone()[0]

        if count > 0:
            cursor.execute("UPDATE platos SET activo = 0 WHERE id = ?", (plato_id,))
            return "baja_logica"
        else:
            cursor.execute("DELETE FROM platos WHERE id = ?", (plato_id,))
            return "borrado_real"

def save_plato(plato_data):
    return editar_plato(plato_data["id"], plato_data) if get_plato(plato_data["id"]) else crear_plato(plato_data)

def update_stock(stock_updates, fecha):
    state = get_stock_state(fecha)
    with get_connection() as conn:
        cursor = conn.cursor()
        for plato_id, stock in stock_updates.items():
            cursor.execute("SELECT stock_group FROM platos WHERE id = ?", (plato_id,))
            row = cursor.fetchone()
            if row and row["stock_group"]:
                state["grupos"][row["stock_group"]] = stock
            else:
                state["platos"][plato_id] = stock
    save_stock_state(fecha, state)
    return True

def descontar_stock(cantidades, fecha):
    state = get_stock_state(fecha)
    consumo_grupos = {}
    nombres_grupos = {}

    with get_connection() as conn:
        cursor = conn.cursor()
        for plato_id, cantidad_pedida in cantidades.items():
            cursor.execute("SELECT name, stock_group, stock_unit FROM platos WHERE id = ?", (plato_id,))
            row = cursor.fetchone()
            if row is None: raise ValueError(f"El plato '{plato_id}' no existe.")
            grupo = row["stock_group"]
            if grupo:
                unidad = row["stock_unit"] if row["stock_unit"] is not None else 1.0
                consumo_grupos[grupo] = consumo_grupos.get(grupo, 0) + cantidad_pedida * unidad
                nombres_grupos.setdefault(grupo, row["name"])
                continue

            stock_actual = state["platos"].get(plato_id)
            if stock_actual is not None:
                if stock_actual < cantidad_pedida:
                    if stock_actual <= 0: raise ValueError(f"'{row['name']}' está agotado.")
                    raise ValueError(f"Solo quedan {stock_actual} unidad(es) de '{row['name']}'.")
                state["platos"][plato_id] = stock_actual - cantidad_pedida

    for grupo, consumo in consumo_grupos.items():
        stock_actual = state["grupos"].get(grupo)
        if stock_actual is not None:
            nombre = nombres_grupos.get(grupo, grupo)
            if stock_actual < consumo:
                if stock_actual <= 0: raise ValueError(f"'{nombre}' está agotado.")
                raise ValueError(f"Solo quedan {stock_actual} unidad(es) de '{nombre}'.")
            state["grupos"][grupo] = stock_actual - consumo

    save_stock_state(fecha, state)
    return True

def restaurar_stock_platos(cantidades, fecha):
    if not cantidades: return True
    state = get_stock_state(fecha)
    with get_connection() as conn:
        cursor = conn.cursor()
        for plato_id, cantidad in cantidades.items():
            cursor.execute("SELECT stock_group, stock_unit FROM platos WHERE id = ?", (plato_id,))
            row = cursor.fetchone()
            if not row: continue
            grupo = row["stock_group"]
            if grupo:
                if state["grupos"].get(grupo) is not None:
                    unidad = row["stock_unit"] if row["stock_unit"] is not None else 1.0
                    state["grupos"][grupo] += cantidad * unidad
                continue
            if state["platos"].get(plato_id) is not None:
                state["platos"][plato_id] += cantidad
    save_stock_state(fecha, state)
    return True

def get_sabores(fecha=None):
    if not fecha: fecha = fecha_hoy()
    state = get_stock_state(fecha)
    return state["sabores"]

def set_sabores_stock(stock_updates, fecha):
    state = get_stock_state(fecha)
    for nombre, stock in stock_updates.items():
        if nombre not in state["sabores"]: raise ValueError(f"El sabor '{nombre}' no existe.")
        state["sabores"][nombre] = stock
    save_stock_state(fecha, state)
    return True

def descontar_stock_sabores(cantidades, fecha):
    if not cantidades: return True
    state = get_stock_state(fecha)
    for nombre, cantidad_pedida in cantidades.items():
        if nombre not in state["sabores"]: raise ValueError(f"El sabor '{nombre}' no existe.")
        stock_actual = state["sabores"][nombre]
        if stock_actual is not None:
            if stock_actual < cantidad_pedida:
                if stock_actual <= 0: raise ValueError(f"El sabor '{nombre}' está agotado.")
                raise ValueError(f"Solo quedan {stock_actual} croqueta(s) de '{nombre}'.")
            state["sabores"][nombre] = stock_actual - cantidad_pedida
    save_stock_state(fecha, state)
    return True

def restaurar_stock_sabores(cantidades, fecha):
    if not cantidades: return True
    state = get_stock_state(fecha)
    for nombre, cantidad in cantidades.items():
        if nombre in state["sabores"] and state["sabores"][nombre] is not None:
            state["sabores"][nombre] += cantidad
    save_stock_state(fecha, state)
    return True

def restaurar_stock_pedido(pedido_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT fecha_entrega, stock_consumido, sabores_consumidos, stock_restaurado FROM pedidos WHERE id = ?", (pedido_id,))
        row = cursor.fetchone()
        if row is None or row["stock_restaurado"]: return False
        fecha = row["fecha_entrega"]
        cantidades_platos = json.loads(row["stock_consumido"]) if row["stock_consumido"] else {}
        cantidades_sabores = json.loads(row["sabores_consumidos"]) if row["sabores_consumidos"] else {}

    restaurar_stock_platos(cantidades_platos, fecha)
    restaurar_stock_sabores(cantidades_sabores, fecha)

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE pedidos SET stock_restaurado = 1 WHERE id = ?", (pedido_id,))
    return True

# --- Funciones de autenticación ---
def crear_usuario(username, password):
    password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO usuarios (username, password_hash, activo) VALUES (?, ?, ?)",
                           (username, password_hash, 1))
            return True
        except sqlite3.IntegrityError:
            return False

def obtener_usuario_por_username(username):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM usuarios WHERE username = ? AND activo = 1", (username,))
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None

def verificar_password(password, password_hash):
    return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))

def crear_sesion(user_id):
    token = secrets.token_urlsafe(32)
    now = datetime.now().isoformat()
    expires = (datetime.now() + timedelta(hours=SESSION_EXPIRE_HOURS)).isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO sesiones (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                       (token, user_id, now, expires))
        limpiar_sesiones_expiradas()
        return token

def obtener_sesion_por_token(token):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sesiones WHERE token = ?", (token,))
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None

def eliminar_sesion(token):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sesiones WHERE token = ?", (token,))
        return cursor.rowcount > 0

def limpiar_sesiones_expiradas():
    now = datetime.now().isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sesiones WHERE expires_at < ?", (now,))
        return cursor.rowcount

def fecha_hoy():
    """Devuelve la fecha actual en formato ISO (YYYY-MM-DD) según la zona horaria del servidor."""
    return datetime.now().date().isoformat()

# --- Inicialización automática al importar ---
init_database()
logger.info("Módulo database.py cargado correctamente.")
