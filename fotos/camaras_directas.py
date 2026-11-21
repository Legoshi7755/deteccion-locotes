"""Cámaras directas: los celulares mandan sus fotos al servidor sin pasar por VDO.Ninja.

Cada celular abre /camara?lado=izq|der&clave=... (página camara_celular.html). La página:
  - abre la cámara trasera, permite bloquear enfoque, exposición y balance de blancos, y fijar el zoom;
  - recorta a 9:16 / 16:9, reduce el tamaño y envía JPEG a /frame a un ritmo máximo configurable.

El servidor guarda las últimas fotos de cada lado con la hora de llegada y, al analizar, empareja
la foto más reciente del lado más atrasado con la del otro lado más cercana en el tiempo
(desfase típico en la misma red Wi-Fi: decenas de ms).

Las páginas de la PC (aplicación y captura de calibración) se usan igual que con VDO.Ninja:
inyectar_visor() cambia los iframes por vistas que se actualizan desde el servidor, y foto() devuelve
'directo', que el servidor reemplaza por el par emparejado (resolver_directo).

Seguridad: en modo directo el servidor escucha en la red local (o detrás de un túnel), así que todas
las páginas y fotos exigen la clave de acceso (?clave=...). Las acciones POST siguen exigiendo además
el token de la página.
"""
import base64
import html
import io
import ipaddress
import json
import re
import secrets
import socket
import ssl
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

BASE = Path(__file__).resolve().parent
LADOS = ("izq", "der")
NOMBRES = {"izq": "Izquierda", "der": "Derecha"}
MAX_FOTO = 5 * 1024 * 1024


class Config:
    activo = False      # modo directo encendido
    clave = ""          # clave de acceso de las páginas (en la URL)
    https = False       # el servidor sirve HTTPS con certificado propio
    puerto = None
    url_publica = None  # p. ej. el túnel de Colab; si no, se arma con la IP local


CONFIG = Config()


# --------------------------------------------------------------------------- fotos recibidas
class Foto:
    __slots__ = ("seq", "t", "jpeg", "ancho", "alto", "ajustes")

    def __init__(self, seq, t, jpeg, ancho, alto, ajustes):
        self.seq, self.t, self.jpeg, self.ancho, self.alto, self.ajustes = seq, t, jpeg, ancho, alto, ajustes


class Buffer:
    def __init__(self):
        self.cond = threading.Condition()
        self.fotos = {lado: deque(maxlen=8) for lado in LADOS}
        self.seq = {lado: 0 for lado in LADOS}
        self.llegadas = {lado: deque(maxlen=60) for lado in LADOS}
        self.ultimo_usado = {}  # sesión de video -> (seq izq, seq der)

    def guardar(self, lado, jpeg, ancho, alto, ajustes):
        with self.cond:
            self.seq[lado] += 1
            ahora = time.monotonic()
            self.fotos[lado].append(Foto(self.seq[lado], ahora, jpeg, ancho, alto, ajustes))
            self.llegadas[lado].append(ahora)
            self.cond.notify_all()
            return self.seq[lado]

    def ultima(self, lado):
        with self.cond:
            return self.fotos[lado][-1] if self.fotos[lado] else None

    def par(self, sesion=None, espera=1.5):
        """Devuelve (foto_izq, foto_der). Con sesión (video), espera un par más nuevo que el último usado."""
        limite = time.monotonic() + espera
        with self.cond:
            usado = self.ultimo_usado.get(sesion, (0, 0)) if sesion else (0, 0)
            while True:
                listos = all(self.fotos[l] for l in LADOS)
                nuevos = listos and self.fotos["izq"][-1].seq > usado[0] and self.fotos["der"][-1].seq > usado[1]
                restante = limite - time.monotonic()
                if nuevos or (listos and restante <= 0):
                    break
                if restante <= 0:
                    faltan = [NOMBRES[l].lower() for l in LADOS if not self.fotos[l]]
                    raise ValueError(f"No llegan fotos del celular {' y '.join(faltan)}. "
                                     "Revisá que su página de cámara esté abierta y enviando.")
                self.cond.wait(restante)
            # El lado más atrasado manda: su foto más nueva, con la del otro lado más cercana en el tiempo.
            ultimo = {l: self.fotos[l][-1] for l in LADOS}
            lento = min(LADOS, key=lambda l: ultimo[l].t)
            otro = "der" if lento == "izq" else "izq"
            ancla = ultimo[lento]
            pareja = min(self.fotos[otro], key=lambda f: abs(f.t - ancla.t))
            fi, fd = (ancla, pareja) if lento == "izq" else (pareja, ancla)
            if sesion:
                self.ultimo_usado[sesion] = (fi.seq, fd.seq)
                if len(self.ultimo_usado) > 32:
                    self.ultimo_usado.pop(next(iter(self.ultimo_usado)))
            return fi, fd

    def estado(self):
        ahora = time.monotonic()
        salida = {}
        with self.cond:
            for lado in LADOS:
                f = self.fotos[lado][-1] if self.fotos[lado] else None
                recientes = [t for t in self.llegadas[lado] if ahora - t <= 3]
                fps = (len(recientes) - 1) / (recientes[-1] - recientes[0]) if len(recientes) > 2 else 0.0
                salida[lado] = {
                    "conectado": bool(f and ahora - f.t < 2.5),
                    "fps": round(fps, 1),
                    "edad_ms": round((ahora - f.t) * 1000) if f else None,
                    "resolucion": f"{f.ancho}x{f.alto}" if f else None,
                    "kb": round(len(f.jpeg) / 1024, 1) if f else None,
                    "ajustes": f.ajustes if f else {},
                }
        return salida


BUFFER = Buffer()


def tamano_jpeg(jpeg):
    """(ancho, alto) leyendo los marcadores SOF del JPEG, sin decodificarlo."""
    i = 2
    while i + 9 < len(jpeg):
        if jpeg[i] != 0xFF:
            i += 1
            continue
        marca = jpeg[i + 1]
        if marca in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            return int.from_bytes(jpeg[i + 7:i + 9], "big"), int.from_bytes(jpeg[i + 5:i + 7], "big")
        i += 2 + int.from_bytes(jpeg[i + 2:i + 4], "big")
    raise ValueError("JPEG sin tamaño")


def data_url(foto):
    return "data:image/jpeg;base64," + base64.b64encode(foto.jpeg).decode()


def resolver_directo(datos):
    """Si la página pidió fotos 'directo', las reemplaza por el par emparejado del buffer."""
    if not isinstance(datos, dict) or datos.get("izq") != "directo" or datos.get("der") != "directo":
        return datos
    sesion = str(datos.get("sesion_video") or "") if datos.get("video") else None
    fi, fd = BUFFER.par(sesion=sesion)
    datos = dict(datos)
    datos["izq"], datos["der"] = data_url(fi), data_url(fd)
    datos["_desfase_ms"] = round(abs(fi.t - fd.t) * 1000)
    return datos


# --------------------------------------------------------------------------- red, certificado y QR
def ip_local():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))   # no envía nada: solo elige la interfaz de salida
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def certificado(carpeta=BASE / "certificado"):
    """Certificado autofirmado para la IP local (Chrome exige HTTPS para usar la cámara)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    carpeta.mkdir(exist_ok=True)
    crt, key = carpeta / "watsocote.crt", carpeta / "watsocote.key"
    ip = ip_local()
    marca = carpeta / "ip.txt"
    if crt.exists() and key.exists() and marca.exists() and marca.read_text() == ip:
        return crt, key
    clave = ec.generate_private_key(ec.SECP256R1())
    nombre = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Watsocote local")])
    alternativos = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    if ip != "127.0.0.1":
        alternativos.append(x509.IPAddress(ipaddress.ip_address(ip)))
    ahora = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(nombre).issuer_name(nombre).public_key(clave.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(ahora - timedelta(days=1))
            .not_valid_after(ahora + timedelta(days=825))
            .add_extension(x509.SubjectAlternativeName(alternativos), critical=False)
            .sign(clave, hashes.SHA256()))
    key.write_bytes(clave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption()))
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    marca.write_text(ip)
    return crt, key


def url_base(handler=None):
    if CONFIG.url_publica:
        return CONFIG.url_publica.rstrip("/")
    host = handler.headers.get("Host", "") if handler is not None else ""
    # Si la PC abrió la página como localhost/127.0.0.1, los celulares no llegarían a esa dirección:
    # en ese caso se usa la IP de la red local.
    if host and not host.split(":")[0] in ("localhost", "127.0.0.1", "[::1]"):
        esquema = handler.headers.get("X-Forwarded-Proto") or ("https" if CONFIG.https else "http")
        return f"{esquema}://{host}"
    return f"{'https' if CONFIG.https else 'http'}://{ip_local()}:{CONFIG.puerto}"


def url_camara(lado, handler=None):
    return f"{url_base(handler)}/camara?lado={lado}&clave={quote(CONFIG.clave)}"


def qr_png(texto):
    import qrcode
    buf = io.BytesIO()
    qrcode.make(texto, box_size=8, border=2).save(buf, format="PNG")
    return buf.getvalue()


def imprimir_qr(texto):
    try:
        import qrcode
        q = qrcode.QRCode(border=1)
        q.add_data(texto)
        q.print_ascii(invert=True)
    except Exception:
        pass


# --------------------------------------------------------------------------- HTTP
def _consulta(handler):
    partes = urlparse(handler.path)
    return partes.path, {k: v[0] for k, v in parse_qs(partes.query).items()}


def clave_valida(handler):
    if not CONFIG.activo:
        return True
    _, q = _consulta(handler)
    return secrets.compare_digest(q.get("clave", ""), CONFIG.clave)


def _enviar(handler, codigo, cuerpo, tipo):
    if isinstance(cuerpo, str):
        cuerpo = cuerpo.encode("utf-8")
        tipo += "; charset=utf-8"
    handler.send_response(codigo)
    handler.send_header("Content-Type", tipo)
    handler.send_header("Content-Length", str(len(cuerpo)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(cuerpo)


def manejar_get(handler):
    """Rutas del modo directo. Devuelve True si atendió la solicitud."""
    if not CONFIG.activo:
        return False
    ruta, q = _consulta(handler)
    if ruta not in ("/camara", "/ultimo.jpg", "/estado-camaras", "/qr.png"):
        return False
    if not clave_valida(handler):
        _enviar(handler, 403, "Falta la clave de acceso o no es correcta.", "text/plain")
        return True
    lado = q.get("lado", "")
    if ruta in ("/camara", "/ultimo.jpg", "/qr.png") and lado not in LADOS:
        _enviar(handler, 400, "lado debe ser izq o der", "text/plain")
        return True
    if ruta == "/camara":
        pagina = (BASE / "camara_celular.html").read_text(encoding="utf-8")
        pagina = pagina.replace("__LADO__", lado).replace("__NOMBRE_LADO__", NOMBRES[lado])
        pagina = pagina.replace("__CLAVE__", html.escape(CONFIG.clave, quote=True))
        _enviar(handler, 200, pagina, "text/html")
    elif ruta == "/ultimo.jpg":
        f = BUFFER.ultima(lado)
        if f is None:
            _enviar(handler, 404, "Todavía no llegó ninguna foto de este lado.", "text/plain")
        else:
            _enviar(handler, 200, f.jpeg, "image/jpeg")
    elif ruta == "/qr.png":
        _enviar(handler, 200, qr_png(url_camara(lado, handler)), "image/png")
    else:
        _enviar(handler, 200, json.dumps(BUFFER.estado()), "application/json")
    return True


def manejar_post(handler):
    if not CONFIG.activo:
        return False
    ruta, q = _consulta(handler)
    if ruta != "/frame":
        return False
    if not clave_valida(handler):
        _enviar(handler, 403, json.dumps({"error": "clave incorrecta"}), "application/json")
        return True
    lado = q.get("lado", "")
    try:
        if lado not in LADOS:
            raise ValueError("lado debe ser izq o der")
        n = int(handler.headers.get("Content-Length", "0"))
        if not 0 < n <= MAX_FOTO:
            raise ValueError("Foto vacía o demasiado grande")
        jpeg = handler.rfile.read(n)
        if jpeg[:2] != b"\xff\xd8":
            raise ValueError("Se esperaba un JPEG")
        ancho, alto = tamano_jpeg(jpeg)
        try:
            ajustes = json.loads(handler.headers.get("X-Ajustes", "{}"))
            if not isinstance(ajustes, dict):
                ajustes = {}
        except ValueError:
            ajustes = {}
        seq = BUFFER.guardar(lado, jpeg, ancho, alto, ajustes)
        _enviar(handler, 200, json.dumps({"ok": True, "n": seq}), "application/json")
    except ValueError as exc:
        _enviar(handler, 400, json.dumps({"error": str(exc)}), "application/json")
    return True


# --------------------------------------------------------------------------- páginas de la PC
ESTILO_VISTA = ('<style>img.vistaDirecta{display:block;width:100%;height:min(61vh,600px);object-fit:contain;'
                'background:#080f12}.celulares{display:flex;gap:18px;flex-wrap:wrap}.celulares figure{margin:0}'
                '.celulares img{width:150px;height:150px;background:#fff;padding:4px}'
                '#estadoCelulares{white-space:pre-line;font-family:ui-monospace,monospace;font-size:13px}</style>')


def panel_html(calibracion=False):
    figuras = "".join(
        f'<figure><img src="/qr.png?lado={l}&clave={quote(CONFIG.clave)}" alt="QR cámara {NOMBRES[l].lower()}">'
        f'<figcaption>{NOMBRES[l]}: escanear con ESE celular<br><a href="/camara?lado={l}&clave={quote(CONFIG.clave)}" '
        f'target="_blank">abrir enlace</a></figcaption></figure>' for l in LADOS)
    return ('<details class="ajustes" open><summary>Celulares (modo directo)</summary>'
            '<p>Escaneá cada código con la cámara del celular que corresponde, permití la cámara y tocá '
            '<b>Iniciar envío</b>. En cada celular podés bloquear el enfoque y fijar el zoom.</p>'
            + ('<p><b>Para calibrar:</b> en cada celular elegí <b>Tamaño 1280 px</b> y <b>Calidad 90 %</b>, '
               'y bloqueá el enfoque, la exposición y el zoom antes de la primera foto. No los cambies después: '
               'la detección tiene que usar el mismo enfoque y zoom.</p>' if calibracion else '')
            + f'<div class="celulares">{figuras}</div><p id="estadoCelulares">Esperando celulares…</p></details>')


SCRIPT_VISOR = r"""
<script>
(()=>{
 const CLAVE=__CLAVE_JSON__;
 // Las fotos las toma el servidor: foto() solo avisa que use el par emparejado.
 window.foto=async()=> 'directo'; try{foto=window.foto;}catch(e){}
 // Vista en vivo: varias pedidas en camino (con un túnel cada una tarda ~0,5 s); se muestra siempre la más nueva.
 for(const lado of ['izq','der']){
  const img=document.getElementById(lado); if(!img||img.tagName!=='IMG')continue;
  img.src='data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="540" height="960">'+
   '<rect width="100%" height="100%" fill="#080f12"/><text x="50%" y="50%" fill="#9bb0b7" font-size="34" '+
   'font-family="sans-serif" text-anchor="middle">Esperando celular '+(lado==='izq'?'izquierdo':'derecho')+'…</text></svg>');
  let pedido=0, mostrado=0, enCamino=0, url=null;
  setInterval(async()=>{
   if(enCamino>=6||document.hidden)return;
   const n=++pedido; enCamino++;
   try{
    const r=await fetch('/ultimo.jpg?lado='+lado+'&clave='+encodeURIComponent(CLAVE)+'&n='+n,{cache:'no-store'});
    if(r.ok&&n>mostrado){const b=await r.blob(); if(n>mostrado){mostrado=n; const viejo=url; url=URL.createObjectURL(b); img.src=url; if(viejo)setTimeout(()=>URL.revokeObjectURL(viejo),1000);}}
   }catch(e){}finally{enCamino--;}
  },70);
 }
 const caja=document.getElementById('estadoCelulares');
 const texto=(nombre,e)=>{
  if(!e||!e.resolucion)return nombre+': sin conexión';
  const a=e.ajustes||{};
  const partes=[e.conectado?'conectado':'SIN SEÑAL ('+Math.round((e.edad_ms||0)/1000)+' s)',
    e.fps+' fotos/s', e.resolucion, e.kb+' KB'];
  if(a.enfoque)partes.push('enfoque '+a.enfoque);
  if(a.zoom!==undefined&&a.zoom!==null)partes.push('zoom '+a.zoom);
  if(a.exposicion)partes.push('exposición '+a.exposicion);
  return nombre+': '+partes.join(' · ');
 };
 async function actualizar(){
  try{const r=await fetch('/estado-camaras?clave='+encodeURIComponent(CLAVE));const d=await r.json();
   if(caja)caja.textContent=texto('Izquierda',d.izq)+'\n'+texto('Derecha',d.der);}catch(e){if(caja)caja.textContent='Sin conexión con el servidor.';}
 }
 setInterval(actualizar,1000);actualizar();
})();
</script>
"""


def inyectar_visor(pagina, panel_vdo=None):
    """Adapta una página de la PC (app o captura de calibración) al modo directo."""
    if not CONFIG.activo:
        return pagina
    pagina = re.sub(r'<iframe id="(izq|der)"[^>]*></iframe>',
                    lambda m: f'<img id="{m.group(1)}" class="vistaDirecta" alt="Cámara {NOMBRES[m.group(1)].lower()}">',
                    pagina)
    if '<details id="herramientasManual"' in pagina:
        # Aplicación: el panel de los celulares va visible debajo de las cámaras, no dentro de "Diagnóstico".
        if panel_vdo:
            pagina = pagina.replace(panel_vdo, "")
        pagina = pagina.replace('<details id="herramientasManual"', panel_html() + '<details id="herramientasManual"', 1)
    elif panel_vdo and panel_vdo in pagina:
        pagina = pagina.replace(panel_vdo, panel_html(calibracion=True))
    else:
        pagina = pagina.replace("</h1>", "</h1>" + panel_html(calibracion=True), 1)
    script = SCRIPT_VISOR.replace("__CLAVE_JSON__", json.dumps(CONFIG.clave))
    pagina = pagina.replace("</head>", ESTILO_VISTA + "</head>", 1) if "</head>" in pagina else ESTILO_VISTA + pagina
    return pagina.replace("</body>", script + "</body>", 1) if "</body>" in pagina else pagina + script


# --------------------------------------------------------------------------- arranque
def configurar(directo=False, https=None, clave=None, puerto=None, url_publica=None):
    CONFIG.activo = bool(directo)
    CONFIG.https = bool(directo) if https is None else bool(https)
    CONFIG.clave = clave or secrets.token_urlsafe(9)
    CONFIG.puerto = puerto
    CONFIG.url_publica = url_publica


def servir(handler_clase, puerto, host=None, titulo="la aplicación"):
    """Crea el servidor (con hilos; HTTPS si corresponde) e imprime las direcciones."""
    CONFIG.puerto = puerto
    host = host or ("0.0.0.0" if CONFIG.activo else "127.0.0.1")
    servidor = ThreadingHTTPServer((host, puerto), handler_clase)
    servidor.daemon_threads = True
    if CONFIG.activo and CONFIG.https:
        crt, key = certificado()
        contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        contexto.load_cert_chain(crt, key)
        servidor.socket = contexto.wrap_socket(servidor.socket, server_side=True)
    if CONFIG.activo:
        base = url_base()
        print(f"\nModo directo: abrí {titulo} en la PC:\n  {base}/?clave={quote(CONFIG.clave)}")
        if CONFIG.https:
            print("  (certificado propio: la primera vez el navegador avisa que no es seguro; elegí "
                  "'Configuración avanzada' > 'Continuar'. En los celulares, lo mismo.)")
        for lado in LADOS:
            print(f"\nCelular {NOMBRES[lado].upper()}: {url_camara(lado)}")
            imprimir_qr(url_camara(lado))
        print("Si los celulares no cargan la página: misma red Wi-Fi y permitir Python en el firewall (red privada).")
    else:
        print(f"Abrí http://127.0.0.1:{puerto} en Chrome. Ctrl+C para finalizar.")
    return servidor


def argumentos(parser):
    parser.add_argument("--directo", action="store_true",
                        help="los celulares mandan las fotos directo a este servidor (sin VDO.Ninja)")
    parser.add_argument("--sin-https", action="store_true",
                        help="con --directo, servir HTTP (p. ej. detrás de un túnel HTTPS en Colab)")
    parser.add_argument("--host", default=None, help="dirección de escucha (por defecto 0.0.0.0 con --directo)")
    parser.add_argument("--clave", default=None, help="clave de acceso (por defecto, una al azar)")
    parser.add_argument("--url-publica", default=None, help="URL pública (túnel) para los enlaces y QR")
    return parser


def configurar_desde(args, puerto):
    configurar(directo=args.directo, https=not args.sin_https, clave=args.clave, puerto=puerto,
               url_publica=args.url_publica)
