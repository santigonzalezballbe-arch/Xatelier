from fastapi import FastAPI, HTTPException, Request, Depends, Cookie, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from datetime import datetime, date
import bcrypt
import secrets
import re
import os
import shutil
import html as html_lib
from PIL import Image

# Importar módulo de base de datos
import database

app = FastAPI()

# --- CONFIGURACIÓN CORS Y ESTÁTICOS ---
ALLOWED_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://192.168.1.41:8000",  # la IP donde sirves el frontend
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("uploads/platos", exist_ok=True)
app.mount("/uploads/platos", StaticFiles(directory="uploads/platos"), name="uploads_platos")

os.makedirs("uploads/brand", exist_ok=True)
app.mount("/uploads/brand", StaticFiles(directory="uploads/brand"), name="uploads_brand")
# --- TEXTOS EDITABLES DE LA WEB (index.html) ---
# Valores por defecto: si el admin no ha guardado nada desde Cocina > Configuración,
# se sirven estos. Al guardar desde Cocina, solo se sobreescriben las claves enviadas.
TEXTOS_WEB_DEFAULT = {
    "eyebrow": "Rostissería artesana · desde 1998",
    "brand_name": "XATELIER",
    "tagline": "Pollería y rotisería de barrio. Pollos y carnes al horno, croquetas caseras y guarniciones para llevar a casa fines de semana y festivos.",
    "direccion": "Carrer d'Alexandre Galí, 34, Loc F, Can Boada, 08225 Terrassa, Barcelona",
    "horario": "Lun a Sáb · 11:00 – 21:30",
    "telefono": "971 452 218",
    "instagram": "@rostisseriaxatelier",
    "loading_title": "Cargando la carta…",
    "loading_text": "Estamos consultando los productos disponibles de hoy. Tardará menos de un segundo.",
    "cart_label": "Tu pedido",
    "confirm_title": "Gracias por tu pedido",
    "confirm_text": "Hemos recibido tu pedido correctamente. El restaurante ya lo ha registrado y la elaboración ha comenzado. Te esperamos.",
    "confirm_btn": "Volver a la carta",
    "map_hint": "Arrastra el marcador para ajustar la ubicación exacta de entrega.",
    "footer_texto": "Pedidos para recogida y envío a domicilio dentro del municipio.",
}

def obtener_textos_web():
    guardados = database.get_config("textos_web") or {}
    textos = dict(TEXTOS_WEB_DEFAULT)
    textos.update({k: v for k, v in guardados.items() if k in TEXTOS_WEB_DEFAULT})
    return textos

# --- MAPEO DE OPCIONES DE MENÚ A PLATOS INDEPENDIENTES ---
OPCION_DEPENDENCIAS = {
    "Con Patatas Caliu": ("g2", 1),
    "Con Patatas Bravas (Normales)": ("g1", 1),
    "Con Patatas Bravas (Grandes)": ("g1", 2),
}

# --- FUNCIONES DE MENÚ DINÁMICO ---
def obtener_lista_sabores_activos(fecha=None):
    sabores = database.get_sabores(fecha)
    return [nombre for nombre, stock in sabores.items() if stock is None or stock > 0]
def obtener_dias_festivos():
    festivos = database.get_config("dias_festivos")
    if festivos is None:
        return {}
    return festivos

def convertir_opciones_a_grupo(opciones_flat, item_id):
    if not opciones_flat:
        return []
    choices = []
    for i, opt in enumerate(opciones_flat):
        choices.append({
            "id": f"{item_id}_opt{i}",
            "name": opt.get("label", ""),
            "price": opt.get("extra", 0)
        })
    return [{
        "id": f"{item_id}_group",
        "label": "Elige una opción",
        "choices": choices
    }]

def evaluar_dependencias(item, menu_completo):
    requires_all = item.get("requires_all", [])
    requires_any = item.get("requires_any", [])
    estados = {}
    for cat in menu_completo:
        for it in cat.get("items", []):
            estados[it["id"]] = it.get("activo", False)
    for dep_id in requires_all:
        if not estados.get(dep_id, False):
            return False
    if requires_any:
        if not any(estados.get(dep_id, False) for dep_id in requires_any):
            return False
    return True

def obtener_menu_dinamico(fecha=None):
    platos = database.get_platos(fecha)
    categorias_dict = {}
    for p in platos:
        # Si el administrador ha desmarcado "Activo" en el almacén, lo omitimos por completo
        if not p.get("activo", True):
            continue
        cat = p.get("category", "Otros")
        if cat not in categorias_dict:
            categorias_dict[cat] = []
        categorias_dict[cat].append(p)

    orden_categorias = database.get_categorias()
    menu = []
    for cat in orden_categorias:
        if cat in categorias_dict:
            menu.append({"category": cat, "subtitle": "", "items": categorias_dict[cat]})
    # Por si alguna categoría en uso no estuviera todavía en el orden guardado
    for cat, items in categorias_dict.items():
        if cat not in orden_categorias:
            menu.append({"category": cat, "subtitle": "", "items": items})

    # Si el producto está activo pero su stock llega a 0, se marca como inactivo solo para mostrarlo como "Agotado"
    for categoria in menu:
        for item in categoria["items"]:
            stock = item.get("stock")
            if stock is not None and stock <= 0:
                item["activo"] = False

    sabores_activos = obtener_lista_sabores_activos(fecha)
    if not sabores_activos:
        for categoria in menu:
            for item in categoria["items"]:
                if item["id"] in ("c1", "c12"):
                    item["activo"] = False

    for categoria in menu:
        for item in categoria["items"]:
            if "requires_all" in item or "requires_any" in item:
                if not evaluar_dependencias(item, menu):
                    item["activo"] = False
                    continue

    for categoria in menu:
        for item in categoria["items"]:
            if "options" in item and item["options"] and item.get("activo", False):
                opciones_filtradas = []
                for opt in item["options"]:
                    label = opt.get("label", "")
                    if label in OPCION_DEPENDENCIAS:
                        plato_id = OPCION_DEPENDENCIAS[label][0]
                        plato_activo = False
                        for cat in menu:
                            for p in cat["items"]:
                                if p["id"] == plato_id:
                                    plato_activo = p.get("activo", False)
                                    break
                            if plato_activo:
                                break
                        if plato_activo:
                            opciones_filtradas.append(opt)
                    else:
                        opciones_filtradas.append(opt)
                item["options"] = opciones_filtradas
                if not opciones_filtradas:
                    item["activo"] = False

    for categoria in menu:
        for item in categoria["items"]:
            if item.get("options"):
                item["options"] = convertir_opciones_a_grupo(item["options"], item["id"])

    for categoria in menu:
        categoria["items"].sort(key=lambda it: (not it.get("activo", False), it.get("orden", 0), it.get("name", "").lower()))

    menu.append({"sabores_activos": sabores_activos})
    return menu

# --- VALIDACIÓN DE FECHAS Y HORAS ---
def es_dia_permitido(fecha_str: str) -> bool:
    try:
        fecha_obj = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        if fecha_obj.weekday() >= 5:
            return True
        dia_mes = fecha_obj.strftime("%d/%m")
        festivos = obtener_dias_festivos()
        return dia_mes in festivos
    except:
        return False

FRANJAS_DOMICILIO = ["12:00-13:00", "13:00-14:00", "14:00-15:00"]

def es_hora_permitida(hora_str: str, metodo_entrega: str = "recogida") -> bool:
    if metodo_entrega in ("domicilio", "mostrador"):
        return True if metodo_entrega == "mostrador" else hora_str in FRANJAS_DOMICILIO
    try:
        hora = datetime.strptime(hora_str, "%H:%M").time()
        hora_inicio = datetime.strptime("12:00", "%H:%M").time()
        hora_fin = datetime.strptime("15:00", "%H:%M").time()
        return hora_inicio <= hora <= hora_fin
    except:
        return False

# --- MODELOS ---
class PedidoWeb(BaseModel):
    nombre: str
    telefono: str
    email: str
    direccion: str
    notas: str
    fecha_entrega: str
    hora_entrega: str
    metodo_entrega: str
    articulos: List[Dict[str, Any]]
    total: str
    lat: Optional[float] = None
    lng: Optional[float] = None

class PedidoManualRequest(BaseModel):
    nombre: Optional[str] = "Cliente en Tienda"
    telefono: Optional[str] = ""
    direccion: Optional[str] = ""
    lat: Optional[float] = None
    lng: Optional[float] = None
    notas: Optional[str] = ""
    fecha_entrega: Optional[str] = None
    hora_entrega: Optional[str] = None
    metodo_entrega: Optional[str] = "mostrador"
    articulos: List[Dict[str, Any]]

class PedidoEditRequest(BaseModel):
    nombre: str
    telefono: str
    direccion: str
    notas: str
    fecha_entrega: str
    hora_entrega: str
    metodo_entrega: str
    articulos: List[Dict[str, Any]]
    lat: Optional[float] = None
    lng: Optional[float] = None

class LoginRequest(BaseModel):
    username: str
    password: str

class StockUpdateRequest(BaseModel):
    stock: Dict[str, Optional[float]]
    fecha: str

class SaborStockUpdateRequest(BaseModel):
    stock: Dict[str, Optional[int]]
    fecha: str
class EstadoUpdateRequest(BaseModel):
    estado: str

class FestivoRequest(BaseModel):
    fecha: str
    nombre: str

class PlatoRequest(BaseModel):
    name: Optional[str] = None
    price: Optional[float] = None
    price_text: Optional[str] = None
    desc: Optional[str] = None
    category: Optional[str] = None
    activo: Optional[int] = None
    croquetas_req: Optional[int] = None
    croquetas_min: Optional[int] = None
    extra_price: Optional[float] = None
    requires_menu: Optional[int] = None
    requires_all: Optional[List[str]] = None
    requires_any: Optional[List[str]] = None
    options: Optional[List[Dict[str, Any]]] = None
    stock: Optional[int] = None
    stock_diario: Optional[int] = None
    stock_group: Optional[str] = None
    stock_unit: Optional[float] = None
    es_nevera: Optional[int] = None
    image_url: Optional[str] = None
    aparece_ticket_cocina: Optional[int] = None
    marcable_preparado: Optional[int] = None
    componentes: Optional[List[str]] = None
    orden: Optional[int] = 0

class PlatosOrdenRequest(BaseModel):
    ordenes: Dict[str, int]

class ComponentesPreparadosRequest(BaseModel):
    componentes_preparados: List[bool]

class ConfigRequest(BaseModel):
    importe_minimo_domicilio: float
    delivery_fee: float

class CategoriaRequest(BaseModel):
    nombre: str

class CategoriasOrdenRequest(BaseModel):
    orden: List[str]

class TextosWebRequest(BaseModel):
    textos: Dict[str, str]


# --- FUNCIONES AUXILIARES ---
def extraer_cantidades_sabores(articulos: List[Dict[str, Any]]) -> Dict[str, int]:
    cantidades = {}
    for art in articulos:
        meta = art.get("meta", "")
        if not meta:
            continue
        qty_linea = art.get("qty", 1)
        for cantidad_str, sabor in re.findall(r'(\d+)x\s+([A-Za-záéíóúñ]+)', meta):
            cantidades[sabor] = cantidades.get(sabor, 0) + int(cantidad_str) * qty_linea
    return cantidades

def extraer_componentes_opciones(meta: str) -> List[tuple]:
    if not meta:
        return []
    componentes = []
    for parte in meta.split(" | "):
        for label, (plato_id, multiplicador) in OPCION_DEPENDENCIAS.items():
            if label in parte:
                componentes.append((plato_id, multiplicador))
    return componentes

def calcular_cantidades_stock(articulos: List[Dict[str, Any]], platos_dict: Dict[str, Any]) -> Dict[str, int]:
    cantidades: Dict[str, int] = {}
    for articulo in articulos:
        base_id = articulo.get("baseId")
        if not base_id:
            continue
        qty = articulo.get("qty", 1)
        cantidades[base_id] = cantidades.get(base_id, 0) + qty
        plato = platos_dict.get(base_id)
        if plato:
            for dep_id in plato.get("requires_all", []):
                cantidades[dep_id] = cantidades.get(dep_id, 0) + qty
        # Aquí aplicamos el multiplicador correcto para guarniciones grandes
        for dep_id, multiplicador in extraer_componentes_opciones(articulo.get("meta", "")):
            cantidades[dep_id] = cantidades.get(dep_id, 0) + (qty * multiplicador)
    return cantidades

def validar_opciones_pedido(articulos: List[Dict[str, Any]]):
    platos = database.get_platos()
    platos_activos = {p["id"]: p for p in platos if p.get("activo", False)}
    sabores_activos = obtener_lista_sabores_activos()
    for art in articulos:
        meta = art.get("meta", "")
        if not meta:
            continue
        partes = meta.split(" | ")
        for parte in partes:
            for label, (plato_id, multiplicador) in OPCION_DEPENDENCIAS.items():
                if label in parte:
                    if plato_id not in platos_activos:
                        raise HTTPException(status_code=400, detail=f"La opción '{label}' ya no está disponible.")
    for sabor in extraer_cantidades_sabores(articulos):
        if sabor not in sabores_activos:
            raise HTTPException(status_code=400, detail=f"El sabor '{sabor}' ya no está disponible.")
    return True

def procesar_stock_pedido(fecha_entrega: str, articulos: List[Dict[str, Any]], platos_dict: Dict[str, Any]):
    cantidades_por_plato = calcular_cantidades_stock(articulos, platos_dict)
    cantidades_por_sabor = extraer_cantidades_sabores(articulos)

    try:
        database.descontar_stock(cantidades_por_plato, fecha_entrega)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        database.descontar_stock_sabores(cantidades_por_sabor, fecha_entrega)
    except ValueError as e:
        try:
            database.descontar_stock({k: -v for k, v in cantidades_por_plato.items()}, fecha_entrega)
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=str(e))

    return cantidades_por_plato, cantidades_por_sabor

# --- DEPENDENCIA DE AUTENTICACIÓN ---
async def get_current_user(session_token: Optional[str] = Cookie(None)):
    if not session_token:
        raise HTTPException(status_code=401, detail="No autenticado")

    sesion = database.obtener_sesion_por_token(session_token)
    if not sesion:
        raise HTTPException(status_code=401, detail="Sesión inválida")

    now = datetime.now().isoformat()
    if sesion['expires_at'] < now:
        database.eliminar_sesion(session_token)
        raise HTTPException(status_code=401, detail="Sesión expirada")

    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM usuarios WHERE id = ?", (sesion['user_id'],))
        usuario_row = cursor.fetchone()
        if not usuario_row:
            raise HTTPException(status_code=401, detail="Usuario no encontrado")
        usuario = dict(usuario_row)

    database.limpiar_sesiones_expiradas()
    return usuario

# --- ENDPOINTS PÚBLICOS ---
@app.get("/api/menu")
def obtener_menu(fecha: Optional[str] = Query(None)):
    return obtener_menu_dinamico(fecha)
@app.get("/api/textos")
def get_textos_publicos():
    """Textos editables de index.html (encabezado, avisos, modales, pie de página)."""
    return obtener_textos_web()

@app.get("/api/config-publica")
def get_config_publica():
    min_dom = database.get_config("importe_minimo_domicilio")
    del_fee = database.get_config("delivery_fee")
    logo_url = database.get_config("logo_url")
    return {
        "importe_minimo_domicilio": float(min_dom) if min_dom is not None else 18.0,
        "delivery_fee": float(del_fee) if del_fee is not None else 3.50,
        "logo_url": logo_url
    }

TERRASSA_LAT_MIN, TERRASSA_LAT_MAX = 41.52, 41.61
TERRASSA_LNG_MIN, TERRASSA_LNG_MAX = 1.96, 2.06

def es_direccion_en_terrassa(direccion: str, lat: Optional[float], lng: Optional[float]) -> bool:
    if lat is None or lng is None:
        return False
    if not (TERRASSA_LAT_MIN <= lat <= TERRASSA_LAT_MAX and TERRASSA_LNG_MIN <= lng <= TERRASSA_LNG_MAX):
        return False
    direccion_lower = (direccion or "").lower()
    if "terrassa" not in direccion_lower and "tarrasa" not in direccion_lower:
        return False
    return True

@app.post("/api/pedido")
def recibir_pedido(pedido: PedidoWeb):
    if not es_dia_permitido(pedido.fecha_entrega):
        raise HTTPException(status_code=400, detail="Los pedidos solo se admiten los sábados, domingos y festivos.")
    if not es_hora_permitida(pedido.hora_entrega, pedido.metodo_entrega):
        detalle_hora = (
            "La hora debe ser una de las franjas disponibles (" + ", ".join(FRANJAS_DOMICILIO) + ")."
            if pedido.metodo_entrega == "domicilio" else
            "La hora debe ser entre 12:00 y 15:00."
        )
        raise HTTPException(status_code=400, detail=detalle_hora)
    if pedido.metodo_entrega == "domicilio" and not es_direccion_en_terrassa(pedido.direccion, pedido.lat, pedido.lng):
        raise HTTPException(
            status_code=400,
            detail="Selecciona una dirección de la lista de sugerencias dentro de Terrassa. Solo repartimos en Terrassa."
        )

    platos = database.get_platos()
    platos_dict = {p["id"]: p for p in platos}
    for articulo in pedido.articulos:
        base_id = articulo.get("baseId")
        if not base_id:
            raise HTTPException(status_code=400, detail="Falta baseId en el artículo")
        plato = platos_dict.get(base_id)
        if not plato:
            raise HTTPException(status_code=400, detail=f"Plato con ID {base_id} no existe")
        if not plato.get("activo", False):
            raise HTTPException(status_code=400, detail=f"El plato '{plato['name']}' ya no está disponible.")

    validar_opciones_pedido(pedido.articulos)

    # --- BARRERA BACKEND PARA DOMICILIO (Configuración dinámica) ---
    importe_min_dom = database.get_config("importe_minimo_domicilio")
    IMPORTE_MINIMO_DOMICILIO = float(importe_min_dom) if importe_min_dom is not None else 18.0

    if pedido.metodo_entrega == "domicilio":
        subtotal = sum(art.get("price", 0) * art.get("qty", 1) for art in pedido.articulos)
        if subtotal < IMPORTE_MINIMO_DOMICILIO:
            faltan = IMPORTE_MINIMO_DOMICILIO - subtotal
            raise HTTPException(
                status_code=400,
                detail=f"Te faltan {faltan:.2f} € para poder pedir a domicilio (mínimo {IMPORTE_MINIMO_DOMICILIO:.2f} €)."
            )

    stock_consumido, sabores_consumidos = procesar_stock_pedido(
        pedido.fecha_entrega,
        pedido.articulos,
        platos_dict
    )

    pedido_data = {
        "fecha_entrega": pedido.fecha_entrega,
        "hora_entrega": pedido.hora_entrega,
        "nombre": pedido.nombre,
        "telefono": pedido.telefono,
        "email": pedido.email,
        "direccion": pedido.direccion,
        "notas": pedido.notas,
        "metodo_entrega": pedido.metodo_entrega,
        "total": pedido.total,
        "lat": pedido.lat,
        "lng": pedido.lng
    }
    items = []
    for art in pedido.articulos:
        items.append({
            "name": art.get("name", ""),
            "qty": art.get("qty", 1),
            "price": art.get("price", 0.0),
            "meta": art.get("meta", ""),
            "plato_id": art.get("baseId")
        })

    try:
        pedido_id = database.create_pedido(pedido_data, items, stock_consumido, sabores_consumidos)
    except Exception:
        if stock_consumido:
            try:
                database.descontar_stock({k: -v for k, v in stock_consumido.items()})
            except Exception:
                pass
            if sabores_consumidos:
                try:
                    database.descontar_stock_sabores({k: -v for k, v in sabores_consumidos.items()})
                except Exception:
                    pass
        raise HTTPException(status_code=500, detail="No se pudo guardar el pedido, inténtalo de nuevo.")

    return {"status": "success", "message": "Pedido procesado", "id": pedido_id}


# --- TICKET PÚBLICO POR WHATSAPP ---
def _render_item_ticket(it: Dict[str, Any]) -> str:
    nombre = html_lib.escape(str(it.get("nombre", "")))
    cantidad = html_lib.escape(str(it.get("cantidad", "")))
    meta_html = ""
    if it.get("meta"):
        meta = html_lib.escape(str(it["meta"]))
        meta_html = f'<br><small style="color:#555;">{meta}</small>'
    return f"<li style='margin-bottom:8px; font-size:15px;'><strong>{cantidad}x {nombre}</strong>{meta_html}</li>"

@app.get("/ticket/{pedido_id}", response_class=HTMLResponse)
def ver_ticket_publico(pedido_id: int):
    pedido, items = database.get_pedido(pedido_id)
    if not pedido:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")

    items_html = "".join(_render_item_ticket(it) for it in items)

    nombre = html_lib.escape(str(pedido.get("nombre", "")))
    metodo = html_lib.escape(str(pedido.get("metodo_entrega", "")).upper())
    fecha = html_lib.escape(str(pedido.get("fecha_entrega", "")))
    hora = html_lib.escape(str(pedido.get("hora_entrega", "")))
    total = html_lib.escape(str(pedido.get("total", "")))

    html_content = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Ticket #{pedido['id']} - Xatelier</title>
    </head>
    <body style="font-family: Arial, sans-serif; background:#f3f3f5; color:#1a2738; padding:20px;">
        <div style="max-width: 400px; margin: 0 auto; background: #fff; padding: 25px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">
            <h2 style="text-align: center; border-bottom: 2px solid #e85d1f; padding-bottom: 10px; margin-top:0;">XATELIER</h2>
            <p style="text-align: center; font-size: 18px; font-weight:bold;">Pedido #{pedido['id']}</p>
            <p><strong>Cliente:</strong> {nombre}</p>
            <p><strong>Método:</strong> {metodo}</p>
            <p><strong>Para el día:</strong> {fecha} a las {hora}</p>
            <hr style="border: 0; border-top: 1px dashed #ccc; margin: 15px 0;">
            <ul style="list-style: none; padding: 0; margin: 0;">
                {items_html}
            </ul>
            <hr style="border: 0; border-top: 1px dashed #ccc; margin: 15px 0;">
            <h3 style="text-align: right; color:#e85d1f;">Total: {total}</h3>
        </div>
    </body>
    </html>
    """
    return html_content

# --- ENDPOINTS DE AUTENTICACIÓN ---
@app.post("/api/login")
async def login(login_data: LoginRequest):
    usuario = database.obtener_usuario_por_username(login_data.username)
    if not usuario:
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")

    if not bcrypt.checkpw(login_data.password.encode('utf-8'), usuario['password_hash'].encode('utf-8')):
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")

    token = database.crear_sesion(usuario['id'])

    response = JSONResponse(content={"status": "ok", "username": usuario['username']})
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        secure=False,
        samesite="Lax",
        max_age=86400
    )
    return response

@app.post("/api/logout")
async def logout(session_token: Optional[str] = Cookie(None)):
    if session_token:
        database.eliminar_sesion(session_token)
    response = JSONResponse(content={"status": "ok"})
    response.delete_cookie("session_token")
    return response

@app.get("/api/me")
async def get_me(usuario: dict = Depends(get_current_user)):
    return {"username": usuario['username']}


# --- ENDPOINTS PROTEGIDOS DE COCINA ---

@app.get("/api/kitchen/config")
def get_kitchen_config(usuario: dict = Depends(get_current_user)):
    min_dom = database.get_config("importe_minimo_domicilio")
    del_fee = database.get_config("delivery_fee")
    logo_url = database.get_config("logo_url")
    return {
        "importe_minimo_domicilio": float(min_dom) if min_dom is not None else 18.0,
        "delivery_fee": float(del_fee) if del_fee is not None else 3.50,
        "logo_url": logo_url
    }

@app.post("/api/kitchen/config")
def set_kitchen_config(config: ConfigRequest, usuario: dict = Depends(get_current_user)):
    database.set_config("importe_minimo_domicilio", config.importe_minimo_domicilio)
    database.set_config("delivery_fee", config.delivery_fee)
    return {"status": "ok"}

@app.post("/api/kitchen/config/logo")
async def upload_logo(file: UploadFile = File(...), usuario: dict = Depends(get_current_user)):
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="El archivo debe ser una imagen válida")
    file_path = "uploads/brand/logo.png"
    try:
        img = Image.open(file.file)
        img = img.convert("RGBA") # Mantener transparencia
        MAX_ALTO = 200
        if img.height > MAX_ALTO:
            nuevo_ancho = int(img.width * (MAX_ALTO / img.height))
            img = img.resize((nuevo_ancho, MAX_ALTO), Image.LANCZOS)
        img.save(file_path, "PNG", optimize=True)
    except Exception:
        raise HTTPException(status_code=400, detail="No se ha podido procesar la imagen")

    logo_url = f"/uploads/brand/logo.png?v={int(datetime.now().timestamp())}"
    database.set_config("logo_url", logo_url)
    return {"status": "ok", "logo_url": logo_url}

@app.get("/api/kitchen/textos")
def get_textos_web_cocina(usuario: dict = Depends(get_current_user)):
    return obtener_textos_web()

@app.post("/api/kitchen/textos")
def set_textos_web_cocina(data: TextosWebRequest, usuario: dict = Depends(get_current_user)):
    guardados = database.get_config("textos_web") or {}
    for clave, valor in data.textos.items():
        if clave not in TEXTOS_WEB_DEFAULT:
            continue
        # No se hace escape HTML aquí: el frontend inserta estos textos con
        # `textContent` (nunca innerHTML), así que no hace falta y evitamos
        # que aparezcan entidades como "&amp;" en pantalla.
        guardados[clave] = valor.strip()
    database.set_config("textos_web", guardados)
    return {"status": "ok", "textos": obtener_textos_web()}

@app.post("/api/kitchen/pedido-manual")
def crear_pedido_manual(pedido: PedidoManualRequest, usuario: dict = Depends(get_current_user)):
    if not pedido.articulos:
        raise HTTPException(status_code=400, detail="El pedido no tiene artículos")

    platos = database.get_platos()
    platos_dict = {p["id"]: p for p in platos}

    for articulo in pedido.articulos:
        base_id = articulo.get("baseId")
        if not base_id or base_id not in platos_dict:
            raise HTTPException(status_code=400, detail=f"Plato con ID {base_id} inválido")

    validar_opciones_pedido(pedido.articulos)

    fecha_entrega = pedido.fecha_entrega if pedido.fecha_entrega else database.fecha_hoy()
    hora_entrega = pedido.hora_entrega if pedido.hora_entrega else datetime.now().strftime("%H:%M")

    stock_consumido, sabores_consumidos = procesar_stock_pedido(
        fecha_entrega,
        pedido.articulos,
        platos_dict
    )

    subtotal = sum(art.get("price", 0) * art.get("qty", 1) for art in pedido.articulos)

    pedido_data = {
        "fecha_entrega": fecha_entrega,
        "hora_entrega": hora_entrega,
        "nombre": pedido.nombre if pedido.nombre and pedido.nombre.strip() else "Cliente Tienda",
        "telefono": pedido.telefono if pedido.telefono and pedido.telefono.strip() else "",
        "email": "",
        "direccion": pedido.direccion if pedido.direccion else "",
        "notas": pedido.notas if pedido.notas and pedido.notas.strip() else "",
        "metodo_entrega": pedido.metodo_entrega if pedido.metodo_entrega else "mostrador",
        "total": f"{subtotal:.2f} €".replace('.', ','),
        "lat": pedido.lat,
        "lng": pedido.lng
    }

    items = []
    for art in pedido.articulos:
        items.append({
            "name": art.get("name", ""),
            "qty": art.get("qty", 1),
            "price": art.get("price", 0.0),
            "meta": art.get("meta", ""),
            "plato_id": art.get("baseId")
        })

    try:
        pedido_id = database.create_pedido(pedido_data, items, stock_consumido, sabores_consumidos)
    except Exception:
        if stock_consumido:
            try: database.descontar_stock({k: -v for k, v in stock_consumido.items()})
            except Exception: pass
        if sabores_consumidos:
            try: database.descontar_stock_sabores({k: -v for k, v in sabores_consumidos.items()})
            except Exception: pass
        raise HTTPException(status_code=500, detail="Error guardando pedido manual")

    return {"status": "success", "id": pedido_id}

@app.put("/api/kitchen/pedidos/{pedido_id}")
def editar_pedido_cocina(pedido_id: int, pedido: PedidoEditRequest, usuario: dict = Depends(get_current_user)):
    pedido_actual, _ = database.get_pedido(pedido_id)
    if not pedido_actual:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")

    platos = database.get_platos()
    platos_dict = {p["id"]: p for p in platos}

    for articulo in pedido.articulos:
        base_id = articulo.get("baseId")
        if not base_id or base_id not in platos_dict:
            raise HTTPException(status_code=400, detail=f"Plato con ID {base_id} inválido")

    validar_opciones_pedido(pedido.articulos)

    # 1. Restaurar stock antiguo (para hacer reset antes de aplicar el nuevo carrito)
    if pedido_actual["estado"] != "cancelado":
        database.restaurar_stock_pedido(pedido_id)

    # 2. Procesar nuevo stock (te avisará si se agotan existencias al editar)
    stock_consumido, sabores_consumidos = procesar_stock_pedido(
        pedido.fecha_entrega,
        pedido.articulos,
        platos_dict
    )

    # 3. Recalcular total (aplicando tarifa de envío si aplica)
    subtotal = sum(art.get("price", 0) * art.get("qty", 1) for art in pedido.articulos)
    delivery_fee = 0
    if pedido.metodo_entrega == "domicilio":
        del_fee = database.get_config("delivery_fee")
        delivery_fee = float(del_fee) if del_fee is not None else 3.50

    total_num = subtotal + delivery_fee
    total_str = f"{total_num:.2f} €".replace('.', ',')

    pedido_data = {
        "fecha_entrega": pedido.fecha_entrega,
        "hora_entrega": pedido.hora_entrega,
        "nombre": pedido.nombre,
        "telefono": pedido.telefono,
        "direccion": pedido.direccion,
        "notas": pedido.notas,
        "metodo_entrega": pedido.metodo_entrega,
        "total": total_str,
        "lat": pedido.lat,
        "lng": pedido.lng
    }

    items = []
    for art in pedido.articulos:
        items.append({
            "name": art.get("name", ""),
            "qty": art.get("qty", 1),
            "price": art.get("price", 0.0),
            "meta": art.get("meta", ""),
            "plato_id": art.get("baseId")
        })

    try:
        database.update_pedido_completo(pedido_id, pedido_data, items, stock_consumido, sabores_consumidos)
    except Exception:
        # Rollback en caso de fallo crítico
        if stock_consumido:
            try: database.descontar_stock({k: -v for k, v in stock_consumido.items()})
            except: pass
        if sabores_consumidos:
            try: database.descontar_stock_sabores({k: -v for k, v in sabores_consumidos.items()})
            except: pass
        raise HTTPException(status_code=500, detail="Error al actualizar pedido")

    return {"status": "success", "id": pedido_id}

@app.get("/api/kitchen/pedidos")
async def list_pedidos_kitchen(
    fecha: Optional[str] = None,
    estado: Optional[str] = None,
    metodo: Optional[str] = None,
    q: Optional[str] = None,
    articulo: Optional[List[str]] = Query(None),
    usuario: dict = Depends(get_current_user)
):
    filters = {}
    if fecha:
        filters["fecha_desde"] = fecha
        filters["fecha_hasta"] = fecha
    if estado:
        filters["estado"] = estado
    if metodo:
        filters["metodo"] = metodo
    if q:
        filters["q"] = q
    if articulo:
        filters["articulo"] = articulo
    pedidos = database.list_pedidos(filters)
    for p in pedidos:
        p.pop('stock_consumido', None)
        p.pop('sabores_consumidos', None)
        p.pop('stock_restaurado', None)
        if 'articulos' in p:
            for item in p['articulos']:
                if 'nombre' not in item:
                    item['nombre'] = item.get('name', '')
                if 'cantidad' not in item:
                    item['cantidad'] = item.get('qty', 1)
    return pedidos

@app.post("/api/kitchen/pedidos/{pedido_id}/estado")
async def update_pedido_estado_kitchen(
    pedido_id: int,
    data: EstadoUpdateRequest,
    usuario: dict = Depends(get_current_user)
):
    if data.estado not in ['pendiente', 'preparado', 'entregado', 'cancelado']:
        raise HTTPException(status_code=400, detail="Estado inválido")
    ok = database.update_pedido_estado(pedido_id, data.estado)
    if not ok:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    if data.estado == 'cancelado':
        database.restaurar_stock_pedido(pedido_id)
    return {"status": "ok"}

@app.post("/api/kitchen/pedido-items/{item_id}/preparado")
async def marcar_componentes_preparados(
    item_id: int,
    data: ComponentesPreparadosRequest,
    usuario: dict = Depends(get_current_user)
):
    ok = database.actualizar_componentes_preparados(item_id, data.componentes_preparados)
    if not ok:
        raise HTTPException(status_code=404, detail="Artículo de pedido no encontrado")
    return {"status": "ok"}

@app.delete("/api/kitchen/pedidos/{pedido_id}")
async def delete_pedido_kitchen(
    pedido_id: int,
    usuario: dict = Depends(get_current_user)
):
    database.restaurar_stock_pedido(pedido_id)
    ok = database.delete_pedido(pedido_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    return {"status": "ok"}

@app.get("/api/kitchen/nevera")
async def get_nevera(fecha: Optional[str] = None, usuario: dict = Depends(get_current_user)):
    if not fecha:
        fecha = database.fecha_hoy()

    filters = {"fecha_desde": fecha, "fecha_hasta": fecha}
    pedidos = database.list_pedidos(filters)

    platos = database.get_platos()
    platos_dict = {p["id"]: p for p in platos}

    articulos_para_calc = []
    for p in pedidos:
        if p["estado"] in ["cancelado", "entregado"]:
            continue
        for item in p.get("articulos", []):
            if item.get("plato_id"):
                articulos_para_calc.append({
                    "baseId": item.get("plato_id"),
                    "qty": item.get("cantidad", 1),
                    "meta": item.get("meta", "")
                })

    cantidades = calcular_cantidades_stock(articulos_para_calc, platos_dict)

    resultado = []
    for plato_id, qty in cantidades.items():
        if qty > 0:
            plato = platos_dict.get(plato_id)
            if plato and plato.get("es_nevera"):
                resultado.append({
                    "id": plato["id"],
                    "name": plato["name"],
                    "category": plato.get("category", "Otros"),
                    "cantidad": qty
                })

    resultado.sort(key=lambda x: (x["category"], x["name"]))
    return resultado


@app.get("/api/kitchen/stock")
async def get_stock(fecha: str = Query(...), usuario: dict = Depends(get_current_user)):
    platos = database.get_platos(fecha=fecha)
    result = []
    for p in platos:
        if p.get("requires_all") or p["id"] == "c1":
            continue
        if p.get("stock_group") and (p.get("stock_unit") or 1.0) != 1.0:
            continue
        nombre = p["name"]
        if p.get("stock_group") == "pollo":
            nombre = "Pollo Entero / ½ Pollo"
        result.append({
            "id": p["id"],
            "name": nombre,
            "category": p.get("category", "Otros"),
            "stock": p.get("stock"),
            "stock_group": p.get("stock_group"),
        })
    return result

@app.post("/api/kitchen/stock")
async def update_stock(data: StockUpdateRequest, usuario: dict = Depends(get_current_user)):
    if not data.stock:
        raise HTTPException(status_code=400, detail="No se enviaron datos de stock")
    platos = database.get_platos(fecha=data.fecha)
    ids_validos = {p["id"] for p in platos}
    for plato_id in data.stock.keys():
        if plato_id not in ids_validos:
            raise HTTPException(status_code=400, detail=f"Plato {plato_id} no existe")
    database.update_stock(data.stock, data.fecha)
    return {"status": "ok"}

@app.get("/api/kitchen/sabores/stock")
async def get_sabores_stock(fecha: str = Query(...), usuario: dict = Depends(get_current_user)):
    sabores = database.get_sabores(fecha=fecha)
    return [{"name": nombre, "stock": stock} for nombre, stock in sabores.items()]

@app.post("/api/kitchen/sabores/stock")
async def update_sabores_stock(data: SaborStockUpdateRequest, usuario: dict = Depends(get_current_user)):
    if not data.stock:
        raise HTTPException(status_code=400, detail="No se enviaron datos de stock")
    try:
        database.set_sabores_stock(data.stock, data.fecha)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok"}

# --- GESTIÓN DE FESTIVOS ---
@app.get("/api/kitchen/festivos")
async def api_get_festivos(usuario: dict = Depends(get_current_user)):
    return database.get_festivos()

@app.post("/api/kitchen/festivos")
async def api_add_festivo(data: FestivoRequest, usuario: dict = Depends(get_current_user)):
    try:
        database.añadir_festivo(data.fecha, data.nombre)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok"}

@app.delete("/api/kitchen/festivos/{fecha:path}")
async def api_delete_festivo(fecha: str, usuario: dict = Depends(get_current_user)):
    if not database.eliminar_festivo(fecha):
        raise HTTPException(status_code=404, detail="Festivo no encontrado")
    return {"status": "ok"}


# --- ALMACÉN (CRUD DE PLATOS) ---
@app.get("/api/kitchen/categorias")
def api_get_categorias(usuario: dict = Depends(get_current_user)):
    return database.get_categorias()

@app.post("/api/kitchen/categorias")
def api_crear_categoria(data: CategoriaRequest, usuario: dict = Depends(get_current_user)):
    try:
        orden = database.crear_categoria(data.nombre)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "categorias": orden}

@app.delete("/api/kitchen/categorias/{nombre:path}")
def api_eliminar_categoria(nombre: str, usuario: dict = Depends(get_current_user)):
    try:
        orden = database.eliminar_categoria(nombre)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "categorias": orden}

@app.post("/api/kitchen/categorias/orden")
def api_set_orden_categorias(data: CategoriasOrdenRequest, usuario: dict = Depends(get_current_user)):
    try:
        orden = database.set_orden_categorias(data.orden)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "categorias": orden}

@app.post("/api/kitchen/platos/orden")
async def api_reordenar_platos(data: PlatosOrdenRequest, usuario: dict = Depends(get_current_user)):
    for plato_id, nuevo_orden in data.ordenes.items():
        database.editar_plato(plato_id, {"orden": nuevo_orden})
    return {"status": "ok"}

@app.get("/api/kitchen/platos")
async def api_list_platos(usuario: dict = Depends(get_current_user)):
    return database.get_platos()

@app.post("/api/kitchen/platos")
async def api_create_plato(data: PlatoRequest, usuario: dict = Depends(get_current_user)):
    if not data.category:
        raise HTTPException(status_code=400, detail="La categoría es obligatoria")
    if data.price is None or data.price < 0:
        raise HTTPException(status_code=400, detail="El precio debe ser >= 0")
    if not data.name:
        raise HTTPException(status_code=400, detail="El nombre es obligatorio")

    plato_data = data.model_dump(exclude_unset=True)
    nuevo_id = database.crear_plato(plato_data)
    return {"status": "ok", "id": nuevo_id}

@app.put("/api/kitchen/platos/{id}")
async def api_update_plato(id: str, data: PlatoRequest, usuario: dict = Depends(get_current_user)):
    plato_data = data.model_dump(exclude_unset=True)
    if not database.editar_plato(id, plato_data):
        raise HTTPException(status_code=404, detail="Plato no encontrado")
    return {"status": "ok"}

@app.post("/api/kitchen/platos/{plato_id}/foto")
async def upload_plato_foto(plato_id: str, file: UploadFile = File(...), usuario: dict = Depends(get_current_user)):
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="El archivo debe ser una imagen válida")

    file_path = f"uploads/platos/{plato_id}.jpg"
    try:
        img = Image.open(file.file)
        img = img.convert("RGB")  # descarta transparencia y normaliza el modo de color
        MAX_ANCHO = 1200
        if img.width > MAX_ANCHO:
            nueva_altura = int(img.height * (MAX_ANCHO / img.width))
            img = img.resize((MAX_ANCHO, nueva_altura), Image.LANCZOS)
        img.save(file_path, "JPEG", quality=80, optimize=True)
    except Exception:
        raise HTTPException(status_code=400, detail="No se ha podido procesar la imagen")

    image_url = f"/uploads/platos/{plato_id}.jpg?v={int(datetime.now().timestamp())}"
    database.editar_plato(plato_id, {"image_url": image_url})

    return {"status": "ok", "image_url": image_url}

@app.delete("/api/kitchen/platos/{id}")
async def api_delete_plato(id: str, usuario: dict = Depends(get_current_user)):
    resultado = database.eliminar_plato(id)
    if not resultado:
        raise HTTPException(status_code=404, detail="Plato no encontrado")
    return {"status": "ok", "resultado": resultado}
