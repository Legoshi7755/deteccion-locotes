"""Detecta locotes y tallos (y opcionalmente hojas y ramas) y los pinta con colores distintos.

  locote -> rojo   tallo -> cian (cruz = centro, candidato a punto de agarre)
  hoja   -> verde  rama  -> magenta

Modo combinado (por defecto): usa DOS modelos.
  - v2 (2 clases) decide locote y tallo: es el más preciso para eso.
  - el de 4 clases solo aporta hojas y ramas. Con eso cada tallo se marca como
    'tapado' si una hoja lo cubre y 'rama_cerca' si una rama pasa junto al punto de agarre.
Con --sin-hojas se usa solo el v2 (más rápido).

Uso:
  ..\\.venv-cuda\\Scripts\\python.exe probar_locote_tallo.py <imagen|carpeta|video|0> [--sin-hojas]
       [--pesos v2.pt] [--pesos-hojas 4clases.pt] [--conf 0.4] [--salida carpeta]
"""
import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

BASE = Path(__file__).resolve().parent
ROOT = BASE / 'resultados_tallo'
MODELO_TALLO = BASE / 'modelos' / 'locote_tallo_v2.pt'      # locote + tallo
MODELO_HOJAS = BASE / 'modelos' / 'locote_tallo_hojas.pt'   # 4 clases; se usa solo para hojas/ramas


def _dispositivo():
    import torch
    return 0 if torch.cuda.is_available() else 'cpu'


DISPOSITIVO = _dispositivo()
# BGR
COLORES = {0: (0, 0, 255), 1: (255, 255, 0), 2: (0, 200, 0), 3: (255, 0, 255)}
NOMBRES = {0: 'locote', 1: 'tallo', 2: 'hoja', 3: 'rama'}

CONF_LOCOTE = 0.4      # confianza mínima para locote
CONF_TALLO = 0.15      # el tallo puede ser más bajo porque además debe tocar un locote
CONF_HOJA_RAMA = 0.4
TAPADO = 0.3           # fracción del tallo cubierta por hojas para marcarlo como tapado
RADIO_RAMA = 25        # px alrededor del centro del tallo donde una rama molesta


def tallo_de_locote(caja_t, cajas_locote):
    """Índice del locote al que pertenece el tallo, o None.

    El tallo debe cruzarse con la caja del locote agrandada (60 % de su alto hacia
    arriba, 20 % de su ancho a los lados y 20 % de su alto hacia abajo, por si el
    fruto está acostado). Así se descartan objetos verdes sueltos del fondo.
    """
    tx1, ty1, tx2, ty2 = caja_t
    for i, (x1, y1, x2, y2) in enumerate(cajas_locote):
        w, h = x2 - x1, y2 - y1
        ex1, ey1, ex2, ey2 = x1 - .2 * w, y1 - .6 * h, x2 + .2 * w, y2 + .2 * h
        if tx1 < ex2 and tx2 > ex1 and ty1 < ey2 and ty2 > ey1:
            return i
    return None


def es_verde(hsv, mascara):
    """Descarta 'hojas' que no son verdes (sillas, mesas, cortinas en el laboratorio)."""
    px = hsv[mascara > 0]
    if len(px) == 0:
        return False
    h, s = np.median(px[:, 0]), np.median(px[:, 1])
    return 25 <= h <= 95 and s >= 40


def capas_hoja_rama(img, res_hojas):
    """Máscaras binarias de hojas y ramas del modelo de 4 clases."""
    h, w = img.shape[:2]
    hojas = np.zeros((h, w), np.uint8)
    ramas = np.zeros((h, w), np.uint8)
    if res_hojas is None or res_hojas.masks is None:
        return hojas, ramas
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    for poly, cls, conf in zip(res_hojas.masks.xy, res_hojas.boxes.cls.int().tolist(), res_hojas.boxes.conf.tolist()):
        if cls not in (2, 3) or conf < CONF_HOJA_RAMA or len(poly) < 3:
            continue
        pts = poly.astype(np.int32)
        x0, y0 = np.maximum(pts.min(0), 0)
        x1, y1 = np.minimum(pts.max(0) + 1, [w, h])
        if x1 <= x0 or y1 <= y0:
            continue
        m = np.zeros((y1 - y0, x1 - x0), np.uint8)  # máscara solo del recuadro: mucho más rápido
        cv2.fillPoly(m, [pts - [x0, y0]], 1)
        if not es_verde(hsv[y0:y1, x0:x1], m):
            continue
        (hojas if cls == 2 else ramas)[y0:y1, x0:x1] |= m
    return hojas, ramas


def dibujar(img, res, res_hojas=None):
    out = img.copy()
    capa = img.copy()
    tallos = []
    hojas, ramas = capas_hoja_rama(img, res_hojas)
    capa[hojas > 0] = COLORES[2]
    capa[ramas > 0] = COLORES[3]
    if res.masks is not None:
        clases = res.boxes.cls.int().tolist()
        confs = res.boxes.conf.tolist()
        cajas = res.boxes.xyxy.tolist()
        locotes = [b for b, c, p in zip(cajas, clases, confs) if c == 0 and p >= CONF_LOCOTE]
        usados = set()  # un solo tallo por locote: el de mayor confianza (vienen ordenados)
        for poly, cls, conf, caja in zip(res.masks.xy, clases, confs, cajas):
            if len(poly) < 3 or cls not in (0, 1):
                continue
            if cls == 0 and conf < CONF_LOCOTE:
                continue
            if cls == 1:
                duenio = tallo_de_locote(caja, locotes)
                if conf < CONF_TALLO or duenio is None or duenio in usados:
                    continue
                usados.add(duenio)
            pts = poly.astype(np.int32)
            color = COLORES[cls]
            cv2.fillPoly(capa, [pts], color)
            cv2.polylines(out, [pts], True, color, 2)
            x, y = pts.min(0)
            cv2.putText(out, f'{NOMBRES[cls]} {conf:.2f}', (int(x), max(15, int(y) - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            if cls == 1:
                m = cv2.moments(pts)
                if m['m00'] > 0:
                    c = (int(m['m10'] / m['m00']), int(m['m01'] / m['m00']))
                    t = {'centro_px': c, 'conf': round(conf, 3), 'locote': duenio, '_poligono': pts}
                    if res_hojas is not None:
                        mt = np.zeros(hojas.shape, np.uint8)
                        cv2.fillPoly(mt, [pts], 1)
                        t['tapado'] = bool((mt & hojas).sum() > TAPADO * max(mt.sum(), 1))
                        y0, y1 = max(0, c[1] - RADIO_RAMA), c[1] + RADIO_RAMA
                        x0, x1 = max(0, c[0] - RADIO_RAMA), c[0] + RADIO_RAMA
                        t['rama_cerca'] = bool(ramas[y0:y1, x0:x1].any())
                    tallos.append(t)
    out = cv2.addWeighted(capa, 0.45, out, 0.55, 0)
    for t in tallos:
        aviso = t.get('tapado') or t.get('rama_cerca')
        cv2.drawMarker(out, t['centro_px'], (0, 165, 255) if aviso else (255, 255, 255), cv2.MARKER_CROSS, 18, 2)
        if aviso:
            txt = ' '.join(k for k in ('tapado', 'rama_cerca') if t.get(k))
            cv2.putText(out, txt, (t['centro_px'][0] + 10, t['centro_px'][1] + 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 165, 255), 2)
    return out, tallos


def main():
    global CONF_LOCOTE
    ap = argparse.ArgumentParser()
    ap.add_argument('fuente')
    ap.add_argument('--pesos', default=None, help='modelo de locote/tallo (por defecto v2)')
    ap.add_argument('--pesos-hojas', default=None, help='modelo de 4 clases para hojas/ramas')
    ap.add_argument('--sin-hojas', action='store_true', help='usar solo el modelo de locote/tallo')
    ap.add_argument('--conf', type=float, default=CONF_LOCOTE, help='confianza mínima del locote')
    ap.add_argument('--salida', default=str(ROOT / 'prueba_locote_tallo'))
    a = ap.parse_args()
    CONF_LOCOTE = a.conf
    modelo = YOLO(str(a.pesos or MODELO_TALLO))
    modelo_hojas = None
    if not a.sin_hojas:
        modelo_hojas = YOLO(str(a.pesos_hojas or MODELO_HOJAS))
    salida = Path(a.salida)
    salida.mkdir(parents=True, exist_ok=True)
    fuente = 0 if a.fuente == '0' else a.fuente
    es_video = fuente == 0 or str(a.fuente).lower().endswith(('.mp4', '.avi', '.mov', '.mkv'))
    tiempos = []
    for i, res in enumerate(modelo.predict(fuente, conf=min(CONF_TALLO, a.conf), imgsz=960, device=DISPOSITIVO,
                                           stream=True, verbose=False)):
        t0 = time.perf_counter()
        res_hojas = None
        if modelo_hojas is not None:
            res_hojas = modelo_hojas.predict(res.orig_img, conf=CONF_HOJA_RAMA, imgsz=640, device=DISPOSITIVO,
                                             verbose=False, classes=[2, 3], max_det=400)[0]
        img, tallos = dibujar(res.orig_img, res, res_hojas)
        tiempos.append(sum(res.speed.values()) + (time.perf_counter() - t0) * 1000)
        nombre = Path(res.path).stem if res.path and not es_video else f'frame{i:05d}'
        if es_video:
            cv2.imshow('locote / tallo / hoja / rama', img)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
        else:
            cv2.imwrite(str(salida / f'{nombre}.jpg'), img)
            print(nombre, 'tallos:', [{k: v for k, v in t.items() if not k.startswith('_')} for t in tallos])
    if tiempos:
        t = np.array(tiempos[1:] or tiempos)  # la primera imagen incluye la carga en la GPU
        print(f'TIEMPO por imagen: {t.mean():.0f} ms (≈{1000 / t.mean():.1f} imágenes/s)')
    cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
