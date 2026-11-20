"""Prueba del detector de locotes con fotos o videos, sin celulares ni servidor.

Usa el mismo modelo, umbrales y filtros que la aplicación en vivo
(yolo_segmentacion_video_ampliado.py): YOLO-seg, filtro de rojo y búsqueda
por recortes cuando no detecta nada. Funciona con GPU o en CPU.

Uso por consola (desde la raíz del repositorio):
    python fotos/prueba_imagenes.py foto1.jpg carpeta_fotos/ video.mp4 --salida resultados
"""
import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import yolo_triangulacion_webrtc as app  # noqa: E402
import yolo_segmentacion_video_ampliado as receptor  # noqa: E402

EXT_IMAGEN = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
EXT_VIDEO = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}


def cargar_modelo(conf=0.40, img_size=960):
    """Carga el modelo activo con la misma configuración que la aplicación."""
    import torch
    from ultralytics import YOLO
    app.CONF = conf
    app.IMG_SIZE = img_size
    app.dispositivo = 0 if torch.cuda.is_available() else "cpu"
    pesos = receptor.seleccionar()
    app.modelo = YOLO(str(pesos))
    app.modelo.to("cuda:0" if app.dispositivo == 0 else "cpu")
    nombre = torch.cuda.get_device_name(0) if app.dispositivo == 0 else "CPU"
    print(f"Modelo: {pesos.name} | clases: {app.modelo.names} | dispositivo: {nombre}")
    return app.modelo


def detectar(imagen, sam=False):
    """Devuelve (vista anotada, lista de detecciones) para una imagen BGR."""
    if app.modelo is None:
        cargar_modelo()
    resultado = app.modelo.predict(imagen, conf=app.CONF, imgsz=app.IMG_SIZE, device=app.dispositivo,
                                   verbose=False, save=False, retina_masks=True)[0]
    resultado = app.buscar_en_recortes(imagen, resultado)
    return anotar(imagen, resultado, sam)


def anotar(imagen, resultado, sam=False):
    detecciones = []
    if resultado.boxes is not None:
        for xy, cl, cf in zip(resultado.boxes.xyxy.cpu().numpy(), resultado.boxes.cls.cpu().numpy(),
                              resultado.boxes.conf.cpu().numpy()):
            detecciones.append(([float(v) for v in xy], int(cl), float(cf)))
    if sam and detecciones:
        vista, _ = app.segmentar_imagen(imagen, detecciones)
    else:
        masks = [] if resultado.masks is None else list(resultado.masks.data.cpu().numpy())
        vista, _ = app.pintar_mascaras(imagen, masks)
    grosor = max(1, round(max(imagen.shape[:2]) / 700))
    for xy, clase, confianza in detecciones:
        x, y = int(xy[0]), max(20 * grosor, int(xy[1]) - 6)
        cv2.putText(vista, f"{app.modelo.names[clase]} {confianza:.2f}", (x, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6 * grosor, (0, 255, 0), 2 * grosor)
    return vista, [{"caja_xyxy": [round(v, 1) for v in xy], "clase": app.modelo.names[c], "confianza": round(f, 3)}
                   for xy, c, f in detecciones]


def procesar_video(entrada, salida, cada=1, confirmar=True, max_segundos=None):
    """Anota un video. Con confirmar=True exige dos cuadros seguidos, como el modo en vivo."""
    from filtro_video import confirmar_video
    if app.modelo is None:
        cargar_modelo()
    cap = cv2.VideoCapture(str(entrada))
    if not cap.isOpened():
        raise ValueError(f"No se pudo abrir el video {entrada}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    limite = int(max_segundos * fps) if max_segundos else None
    salida = Path(salida)
    escritor, n, con_deteccion, inicio = None, 0, 0, time.perf_counter()
    sesion = f"video_{time.time_ns()}"
    vista = None
    while True:
        ok, cuadro = cap.read()
        if not ok or (limite and n >= limite):
            break
        if n % cada == 0:
            resultado = app.modelo.predict(cuadro, conf=app.CONF, imgsz=app.IMG_SIZE, device=app.dispositivo,
                                           verbose=False, save=False, retina_masks=True)[0]
            resultado = app.buscar_en_recortes(cuadro, resultado)
            if confirmar:
                resultado = confirmar_video(resultado, "video", sesion)
            vista, dets = anotar(cuadro, resultado)
            con_deteccion += bool(dets)
        if escritor is None:
            h, w = cuadro.shape[:2]
            escritor = cv2.VideoWriter(str(salida), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
        escritor.write(vista if vista is not None else cuadro)
        n += 1
        if n % 100 == 0:
            print(f"  {n}/{total or '?'} cuadros…")
    cap.release()
    if escritor is not None:
        escritor.release()
    analizados = (n + cada - 1) // cada
    segundos = time.perf_counter() - inicio
    print(f"Video: {n} cuadros, {analizados} analizados en {segundos:.1f} s "
          f"({analizados / max(segundos, 1e-6):.1f} cuadros/s). Con locote: {con_deteccion}/{analizados}.")
    return salida


def recolectar(rutas):
    for ruta in map(Path, rutas):
        if ruta.is_dir():
            yield from sorted(p for p in ruta.rglob("*") if p.suffix.lower() in EXT_IMAGEN | EXT_VIDEO)
        else:
            yield ruta


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("entradas", nargs="+", help="fotos, videos o carpetas")
    parser.add_argument("--salida", default="resultados", help="carpeta de salida (por defecto: resultados)")
    parser.add_argument("--conf", type=float, default=0.40, help="confianza mínima (por defecto 0.40)")
    parser.add_argument("--sam", action="store_true", help="refinar contornos de fotos con MobileSAM (más lento)")
    parser.add_argument("--cada", type=int, default=1, help="en videos, analizar 1 de cada N cuadros")
    args = parser.parse_args()
    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)
    cargar_modelo(conf=args.conf)
    for ruta in recolectar(args.entradas):
        ext = ruta.suffix.lower()
        if ext in EXT_VIDEO:
            print(f"\n{ruta.name}:")
            procesar_video(ruta, salida / f"{ruta.stem}_anotado.mp4", cada=args.cada)
        elif ext in EXT_IMAGEN:
            imagen = cv2.imread(str(ruta))
            if imagen is None:
                print(f"{ruta.name}: no se pudo leer")
                continue
            t = time.perf_counter()
            vista, dets = detectar(imagen, sam=args.sam)
            cv2.imwrite(str(salida / f"{ruta.stem}_anotado.jpg"), vista)
            confs = ", ".join(f"{d['confianza']:.2f}" for d in dets)
            print(f"{ruta.name}: {len(dets)} locote(s) [{confs}] en {(time.perf_counter() - t) * 1000:.0f} ms")
        else:
            print(f"{ruta.name}: formato no admitido")
    print(f"\nResultados en {salida.resolve()}")


if __name__ == "__main__":
    main()
