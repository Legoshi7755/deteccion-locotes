"""Posición 3D del tallo (punto de agarre) con el par estéreo calibrado.

Flujo por par:
  1. Detecta locote/tallo (modelo v2) y hojas/ramas (modelo de 4 clases) en cada imagen,
     con las mismas reglas que probar_locote_tallo.py (tallo pegado a un locote, uno por locote).
  2. Elige el punto de agarre en la imagen izquierda: el píxel del tallo más cercano a su centro.
  3. Busca el MISMO punto en la derecha sin adivinar: toma la línea epipolar de ese punto y se
     queda con los píxeles de la máscara del tallo derecho que caen sobre ella (< 1,5 px).
     El tallo derecho correcto es el único que corta esa línea a una profundidad plausible.
  4. Triangula con triangulacion() de yolo_triangulacion_webrtc.py (mismo filtro epipolar,
     rayos casi paralelos, puntos detrás de la cámara...).
  5. Repite con dos puntos a lo largo del tallo para estimar su dirección 3D (para orientar la pinza).

Coordenadas: las imágenes de calibración son 1280x720 apaisadas; los modelos trabajan en vertical
(720x1280, como se guardan las fotos del carrito). Resultado en mm, marco de la cámara izquierda.

Limitaciones: los teléfonos no están sincronizados (si algo se mueve entre las dos capturas el
punto sale mal); si el tallo es paralelo a la línea epipolar, el punto queda ambiguo y se descarta.

Uso de prueba con pares guardados del carrito:
  ..\\.venv-cuda\\Scripts\\python.exe tallo_3d.py fotos/dataset_carrito_pendiente/<sesion>/images/par_00016
"""
import sys
from pathlib import Path

import cv2
import numpy as np

import probar_locote_tallo as plt_


BASE = Path(__file__).resolve().parent
MAX_DIST_EPIPOLAR = 8.0     # px: desvío máximo entre la línea epipolar y el tallo derecho
MAX_AMBIGUEDAD = 12.0       # px: si el tramo sobre la línea es más largo, el punto no es fiable
RANGO_MM = (100, 3000)      # profundidad plausible


def cargar_calibracion(ruta=None):
    if ruta is None:
        import captura_webrtc
        ruta = captura_webrtc.SESION / 'calibracion_charuco.npz'
    with np.load(ruta, allow_pickle=False) as d:
        cal = {k: d[k] for k in d.files}
    if tuple(cal['size_l']) != (1280, 720):
        raise ValueError('La calibración debe ser 1280x720')
    return cal


def vertical_a_calibrada(pts, alto_vertical=1280):
    """(x, y) en la foto vertical 720x1280 -> (x', y') en la imagen calibrada 1280x720."""
    pts = np.asarray(pts, np.float64).reshape(-1, 2)
    return np.column_stack([alto_vertical - 1 - pts[:, 1], pts[:, 0]])


def calibrada_a_vertical(pts, alto_vertical=1280):
    pts = np.asarray(pts, np.float64).reshape(-1, 2)
    return np.column_stack([pts[:, 1], alto_vertical - 1 - pts[:, 0]])


def detectar(img_vertical, modelo, modelo_hojas):
    res = modelo.predict(img_vertical, conf=plt_.CONF_TALLO, imgsz=960, device=plt_.DISPOSITIVO, verbose=False)[0]
    res_h = None
    if modelo_hojas is not None:
        res_h = modelo_hojas.predict(img_vertical, conf=plt_.CONF_HOJA_RAMA, imgsz=640, device=plt_.DISPOSITIVO,
                                     verbose=False, classes=[2, 3], max_det=400)[0]
    vista, tallos = plt_.dibujar(img_vertical, res, res_h)
    return vista, tallos


def pixeles(poligono, shape):
    m = np.zeros(shape[:2], np.uint8)
    cv2.fillPoly(m, [poligono.astype(np.int32)], 1)
    y, x = np.nonzero(m)
    return np.column_stack([x, y]).astype(np.float64)


def puntos_del_tallo(px):
    """Centro (ajustado a la máscara) y dos puntos a lo largo del eje principal del tallo."""
    centro = px.mean(0)
    def ajustar(p):
        return px[np.argmin(((px - p) ** 2).sum(1))]
    _, _, vt = np.linalg.svd(px - centro, full_matrices=False)
    eje = vt[0]
    proy = (px - centro) @ eje
    a, b = np.percentile(proy, [15, 85])
    return ajustar(centro), ajustar(centro + a * eje), ajustar(centro + b * eje)


def sin_distorsion(pts, K, d):
    return cv2.undistortPoints(np.asarray(pts, np.float64).reshape(-1, 1, 2), K, d, P=K).reshape(-1, 2)


def homologo(a_und, px_der_cal, cal):
    """Punto del tallo derecho que corresponde al punto izquierdo (ya sin distorsión).

    Toma los píxeles del tallo derecho más cercanos a la línea epipolar y su punto medio,
    y lo lleva SOBRE la línea. El desvío perpendicular (error de calibración/escalado de los
    teléfonos) casi no cambia la profundidad, que se decide a lo largo de la línea.
    Devuelve (punto_sin_distorsion, desvío_px, tramo_px) o None.
    """
    linea = cal['F'] @ np.r_[a_und, 1.0]
    linea /= np.linalg.norm(linea[:2])
    und = sin_distorsion(px_der_cal, cal['K2'], cal['d2'])
    dist = np.abs(und @ linea[:2] + linea[2])
    desvio = float(dist.min())
    if desvio > MAX_DIST_EPIPOLAR:
        return None
    sel = und[dist <= desvio + 1.5]
    # tramo a lo largo de la línea: si es largo, el tallo corre paralelo a la epipolar
    direccion = np.array([-linea[1], linea[0]])
    s = sel @ direccion
    q = sel[np.argsort(s)[len(s) // 2]]
    q = q - (q @ linea[:2] + linea[2]) * linea[:2]  # sobre la línea
    return q, desvio, float(s.max() - s.min())


def triangular_und(a, b, cal):
    """Triangula dos puntos sin distorsión (mismas comprobaciones que triangulacion())."""
    ray1 = np.linalg.solve(cal['K1'], np.r_[a, 1.0])
    ray2 = cal['R'].T @ np.linalg.solve(cal['K2'], np.r_[b, 1.0])
    ang = np.degrees(np.arccos(np.clip(ray1 @ ray2 / (np.linalg.norm(ray1) * np.linalg.norm(ray2)), -1, 1)))
    if ang < 0.2:
        raise ValueError('rayos casi paralelos')
    h = cv2.triangulatePoints(cal['P1'], cal['P2'], a.reshape(2, 1), b.reshape(2, 1)).ravel()
    if abs(h[3]) < 1e-12:
        raise ValueError('punto en el infinito')
    xyz = h[:3] / h[3]
    if xyz[2] <= 0 or (cal['R'] @ xyz + cal['T'].ravel())[2] <= 0:
        raise ValueError('detrás de una cámara')
    return xyz


def a_distorsionado(p_und, K, d):
    """Inverso de sin_distorsion (para dibujar en la imagen original)."""
    n = np.linalg.solve(K, np.r_[p_und, 1.0])
    pts, _ = cv2.projectPoints(n.reshape(1, 1, 3), np.zeros(3), np.zeros(3), K, d)
    return pts.reshape(2)


def triangular_punto(p_izq_vert, px_der_cal, cal):
    p_cal = vertical_a_calibrada(p_izq_vert)[0]
    a = sin_distorsion(p_cal, cal['K1'], cal['d1'])[0]
    h = homologo(a, px_der_cal, cal)
    if h is None:
        return None, 'la línea epipolar no pasa por este tallo en la imagen derecha'
    b, desvio, tramo = h
    if tramo > MAX_AMBIGUEDAD:
        return None, f'ambiguo: el tallo corre paralelo a la línea epipolar ({tramo:.0f} px)'
    try:
        xyz = triangular_und(a, b, cal)
    except ValueError as e:
        return None, str(e)
    if not RANGO_MM[0] < np.linalg.norm(xyz) < RANGO_MM[1]:
        return None, f'distancia fuera de rango ({np.linalg.norm(xyz) / 10:.0f} cm)'
    q_cal = a_distorsionado(b, cal['K2'], cal['d2'])
    return {'xyz_mm': xyz, 'error_px': desvio, 'der_vertical': calibrada_a_vertical(q_cal)[0]}, None


def tallos_3d(img_izq_vert, img_der_vert, cal, modelo, modelo_hojas=None):
    """Devuelve (vista_izq, vista_der, lista de tallos con xyz)."""
    vi, ti = detectar(img_izq_vert, modelo, modelo_hojas)
    vd, td = detectar(img_der_vert, modelo, modelo_hojas)
    der_px = [vertical_a_calibrada(pixeles(t['_poligono'], img_der_vert.shape)) for t in td]
    salida = []
    for t in ti:
        px = pixeles(t['_poligono'], img_izq_vert.shape)
        centro, extremo_a, extremo_b = puntos_del_tallo(px)
        # Emparejar: el tallo derecho cuya máscara corta la epipolar del centro a una profundidad válida.
        candidatos = []
        for j, pxd in enumerate(der_px):
            r, motivo = triangular_punto(centro, pxd, cal)
            if r is not None:
                candidatos.append((j, r))
        info = {k: v for k, v in t.items() if not k.startswith('_')}
        info['agarre_izq_px'] = [int(v) for v in centro]
        if len(candidatos) != 1:
            info['estado'] = 'sin pareja en la derecha' if not candidatos else f'{len(candidatos)} parejas posibles: descartado'
            salida.append(info)
            continue
        j, r = candidatos[0]
        xyz = r['xyz_mm']
        info.update({'estado': 'ok', 'tallo_der': j,
                     'agarre_der_px': [int(v) for v in r['der_vertical']],
                     'xyz_mm': [round(float(v), 1) for v in xyz],
                     'distancia_cm': round(float(np.linalg.norm(xyz)) / 10, 1),
                     'desvio_epipolar_px': round(float(r['error_px']), 2)})
        # Dirección del tallo en 3D (si los dos extremos se pueden triangular).
        ea, _ = triangular_punto(extremo_a, der_px[j], cal)
        eb, _ = triangular_punto(extremo_b, der_px[j], cal)
        if ea and eb:
            v = eb['xyz_mm'] - ea['xyz_mm']
            n = np.linalg.norm(v)
            if n > 3:
                info['direccion'] = [round(float(x), 3) for x in v / n]
                info['largo_visible_mm'] = round(float(n), 1)
        salida.append(info)
        # Dibujo
        for vista, p in ((vi, info['agarre_izq_px']), (vd, info['agarre_der_px'])):
            cv2.circle(vista, tuple(p), 9, (0, 255, 255), 2)
            cv2.putText(vista, f"{info['distancia_cm']} cm", (p[0] + 12, p[1] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
    return vi, vd, salida


def main():
    import json
    from ultralytics import YOLO
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    base = Path(sys.argv[1])  # .../images/par_00016  (sin _izq/_der)
    izq = cv2.imread(str(base) + '_izq.jpg')
    der = cv2.imread(str(base) + '_der.jpg')
    if izq is None or der is None:
        raise SystemExit(f'No encuentro {base}_izq.jpg / _der.jpg')
    raiz = plt_.ROOT
    modelo = YOLO(str(plt_.MODELO_TALLO))
    hojas = YOLO(str(plt_.MODELO_HOJAS))
    cal = cargar_calibracion()
    vi, vd, tallos = tallos_3d(izq, der, cal, modelo, hojas)
    salida = raiz / 'tallo_3d'
    salida.mkdir(parents=True, exist_ok=True)
    nombre = base.parent.parent.name[:4] + '_' + base.name
    cv2.imwrite(str(salida / f'{nombre}.jpg'), np.hstack([vi, vd]))
    for t in tallos:
        print(nombre, json.dumps(t, ensure_ascii=False))


if __name__ == '__main__':
    main()
