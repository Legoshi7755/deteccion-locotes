"""Captura de pares VDO.Ninja. Ejecutar y abrir la URL local en Chrome.
Normaliza a 1280x720 sin recortar. La resolución del sensor no se fuerza.
No sincroniza las exposiciones. Mantener el tablero quieto.
"""
import base64
import json
import os
import re
import secrets
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Timer
from urllib.parse import parse_qs, urlsplit

import cv2
import numpy as np

BASE = Path(__file__).resolve().parent
# Sesión de calibración activa. Se elige con la variable de entorno WATSOCOTE_SESION
# (p. ej. desde el notebook de Colab); por defecto, la sesión original del montaje.
# En la PC también se puede usar --sesion NOMBRE (lo procesa sesion_desde_argumentos).
NOMBRE_SESION = os.environ.get("WATSOCOTE_SESION", "").strip() or "calibracion_2026-10-31_02"
if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", NOMBRE_SESION):
    raise SystemExit(f"Nombre de sesión no válido: {NOMBRE_SESION!r} (usar letras, números, '-' o '_')")
SESION = BASE / "sesiones" / NOMBRE_SESION
TOKEN = secrets.token_urlsafe(24)
STREAMS = {"izq": "jsM66LZ", "der": "pEHcrM3"}
LIMIT = 40 * 1024 * 1024
RESOLUCION_SALIDA = (1280, 720)  # ancho, alto; usar también en la inferencia futura
GUARDADO_LOCK = Lock()


def guardar_par(datos):
    imagenes = {}
    origenes = {}
    giradas = []
    for lado in STREAMS:
        valor = datos[lado]
        if not isinstance(valor, str) or not valor.startswith("data:image/png;base64,"):
            raise ValueError("Respuesta de imagen PNG no válida")
        raw = base64.b64decode(valor.split(",", 1)[1], validate=True)
        imagen = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if imagen is None:
            raise ValueError("No se pudo decodificar una imagen")
        alto, ancho = imagen.shape[:2]
        origenes[lado] = (ancho, alto)
        # Normalizar orientación antes de escalar, conservando la geometría.
        if alto > ancho:
            imagen = cv2.rotate(imagen, cv2.ROTATE_90_CLOCKWISE)
            giradas.append(lado)
            alto, ancho = imagen.shape[:2]
        proporcion = RESOLUCION_SALIDA[0] / RESOLUCION_SALIDA[1]
        if abs((ancho / alto) / proporcion - 1) > 0.01:
            raise ValueError(f"{lado}: llega {ancho}x{alto}. La proporción no es 16:9 ni 9:16; no se deformará la imagen.")
        if (ancho, alto) != RESOLUCION_SALIDA:
            modo = cv2.INTER_AREA if ancho > RESOLUCION_SALIDA[0] else cv2.INTER_LINEAR
            imagen = cv2.resize(imagen, RESOLUCION_SALIDA, interpolation=modo)
        ok, png = cv2.imencode(".png", imagen)
        if not ok:
            raise ValueError("No se pudo codificar la imagen")
        imagenes[lado] = (png.tobytes(), imagen.shape[:2])
    numeros = []
    for lado in STREAMS:
        carpeta = SESION / f"fotos_{lado}"
        carpeta.mkdir(parents=True, exist_ok=True)
        for f in carpeta.iterdir():
            if f.suffix.lower() not in (".jpg", ".jpeg", ".png"):
                continue
            m = re.fullmatch(r"(?:izq|der|img)_(\d+)", f.stem)
            if not m:
                continue
            numeros.append(int(m.group(1)))
            anterior = cv2.imread(str(f))
            if anterior is not None and anterior.shape[:2] != imagenes[lado][1]:
                raise ValueError(f"La foto anterior {f.name} tiene {anterior.shape[1]}x{anterior.shape[0]}. La nueva sesión usa 1280x720; separá las fotos anteriores.")
    n = max(numeros, default=0) + 1
    rutas = []
    try:
        for lado, (raw, _) in imagenes.items():
            ruta = SESION / f"fotos_{lado}" / f"{lado}_{n:04d}.png"
            with ruta.open("xb") as archivo:
                rutas.append(ruta)
                archivo.write(raw)
    except Exception:
        for ruta in rutas:
            ruta.unlink(missing_ok=True)
        raise
    mensaje = f"Par {n} guardado a 1280x720 en ambas cámaras. Origen: " + "; ".join(f"{lado} {w}x{h}" for lado, (w, h) in origenes.items())
    if giradas:
        mensaje += ". Giro de 90 grados: " + ", ".join(giradas)
    if any(max(w, h) < 1280 or min(w, h) < 720 for w, h in origenes.values()):
        mensaje += ". AVISO: se amplió una imagen; no aumenta el detalle real."
    return mensaje


class Handler(BaseHTTPRequestHandler):
    def responder(self, codigo, cuerpo, tipo="application/json"):
        raw = cuerpo.encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo + "; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        ruta = urlsplit(self.path)
        if ruta.path != "/":
            self.responder(404, "{}")
            return
        from configurar_video import preparar_receptor
        # ?codec=vp8 (o h264, vp9, av1, o vacío) permite comparar sin editar config_video.json.
        consulta = parse_qs(ruta.query, keep_blank_values=True)
        codec = consulta["codec"][0] if "codec" in consulta else None
        try:
            html = preparar_receptor((BASE / "captura_webrtc.html").read_text(encoding="utf-8"), codec)
        except ValueError as exc:
            self.responder(400, str(exc), "text/plain")
            return
        html = html.replace("<h1>Captura estéreo WebRTC</h1>", f"<h1>Captura estéreo WebRTC</h1><p>Sesión activa: {SESION.name}</p>")
        self.responder(200, html.replace("__TOKEN__", TOKEN), "text/html")

    def do_POST(self):
        if self.path != "/capturar" or self.headers.get("X-Capture-Token") != TOKEN:
            self.responder(403, json.dumps({"error": "Solicitud no autorizada"}))
            return
        try:
            longitud = int(self.headers.get("Content-Length", "0"))
            if not 0 < longitud <= LIMIT:
                raise ValueError("Tamaño de solicitud no permitido")
            datos = json.loads(self.rfile.read(longitud))
            # Varias pestañas pueden cargar sin bloquearse; guardar pares en serie.
            with GUARDADO_LOCK:
                mensaje = guardar_par(datos)
            print(mensaje)
            self.responder(200, json.dumps({"mensaje": mensaje}))
        except Exception as exc:
            self.responder(400, json.dumps({"error": str(exc)}))

    def log_message(self, *_):
        pass


def sesion_desde_argumentos(argv=None):
    """Permite elegir la sesión con --sesion NOMBRE (además de WATSOCOTE_SESION)."""
    global NOMBRE_SESION, SESION
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sesion", help="nombre de la sesión en fotos/sesiones (letras, números, '-' o '_')")
    parser.add_argument("--no-abrir", action="store_true", help="no abrir el navegador automáticamente")
    args = parser.parse_args(argv)
    if args.sesion:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", args.sesion):
            raise SystemExit(f"Nombre de sesión no válido: {args.sesion!r}")
        NOMBRE_SESION = args.sesion
        SESION = BASE / "sesiones" / NOMBRE_SESION
    return args


if __name__ == "__main__":
    args = sesion_desde_argumentos()
    print("Abrí http://127.0.0.1:8765 en Chrome. Ctrl+C aquí para finalizar.")
    print("Para comparar códecs: http://127.0.0.1:8765/?codec=vp8 (por defecto, el de config_video.json).")
    print(f"Sesión activa: {SESION}")
    print("No mezclar cámaras o montajes distintos en una sesión de calibración.")
    with ThreadingHTTPServer(("127.0.0.1", 8765), Handler) as servidor:
        if not args.no_abrir:
            import webbrowser
            Timer(0.5, webbrowser.open, ["http://127.0.0.1:8765"]).start()
        try:
            servidor.serve_forever()
        except KeyboardInterrupt:
            print("Captura finalizada.")
