"""
Calibración estéreo con tablero ChArUco (dos teléfonos).

Estructura esperada:
    fotos_izq/izq_1.jpg, izq_2.jpg, ...
    fotos_der/der_1.jpg, der_2.jpg, ...
El par N es "izq_N" con "der_N" (se emparejan por el NÚMERO del nombre).

Requiere OpenCV 4.8 o superior con aruco:  pip install -U opencv-contrib-python
"""
import cv2
import numpy as np
import glob, os, re, sys

# ======================= CONFIGURACIÓN =======================
from config_calibracion import (
    CARPETA_IZQ, CARPETA_DER, CARPETA_DEBUG, SALIDA,
    NX, NY, SQUARE_LEN, MARKER_LEN, DICCIONARIO_NOMBRE, mostrar_configuracion,
)
DICCIONARIO = getattr(cv2.aruco, DICCIONARIO_NOMBRE)

# Montaje real, solo para comprobar que el resultado tiene sentido (pon None para desactivar)
BASELINE_ESPERADA_MM = 528.0      # distancia medida entre los centros ópticos de las dos cámaras
ROTACION_ESPERADA_GRADOS = 60.0   # suma de las inclinaciones hacia adentro (30° + 30°)

MIN_ESQUINAS = 10                 # mínimo de esquinas ChArUco por foto para usarla
MIN_COMUNES = 8                   # mínimo de esquinas vistas por AMBAS cámaras en un par
# =============================================================


def crear_tablero():
    if not hasattr(cv2.aruco, "CharucoDetector"):
        sys.exit("Tu OpenCV es antiguo (cv2.aruco.CharucoDetector no existe). "
                 "Actualiza con:  pip install -U opencv-contrib-python")
    dic = cv2.aruco.getPredefinedDictionary(DICCIONARIO)
    board = cv2.aruco.CharucoBoard((NX, NY), SQUARE_LEN, MARKER_LEN, dic)
    dp = cv2.aruco.DetectorParameters()
    dp.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    detector = cv2.aruco.CharucoDetector(board, cv2.aruco.CharucoParameters(), dp)
    return board, detector


def numero(ruta):
    """izq_15.jpg -> 15"""
    return int(re.findall(r"\d+", os.path.basename(ruta))[-1])


def listar_imagenes(carpeta):
    if not carpeta.is_dir():
        sys.exit(f"No existe la carpeta de fotos: {carpeta}")
    archivos = {}
    for f in sorted(carpeta.iterdir()):
        if not f.is_file() or f.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        if not re.fullmatch(r"(?:izq|der|img)_\d+", f.stem):
            print(f"Ignorada: nombre no compatible {f.name}")
            continue
        n = numero(str(f))
        if n in archivos:
            sys.exit(f"Número duplicado {n} en {carpeta}: {archivos[n].name}, {f.name}")
        archivos[n] = f
    return archivos


def detectar_carpeta(carpeta, prefijo, detector):
    """Devuelve {n: (esquinas Nx2, ids N)} y el tamaño (ancho, alto) de las imágenes."""
    res, size = {}, None
    os.makedirs(CARPETA_DEBUG, exist_ok=True)
    for n, f in sorted(listar_imagenes(carpeta).items()):
        gray = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            print(f"Imagen ilegible, descartada: {f}")
            continue
        s = gray.shape[::-1]
        if size is None:
            size = s
        if s != size:
            print(f"  {prefijo}_{n}: DESCARTADA, tamaño {s} distinto del resto {size}")
            continue
        corners, ids, _, _ = detector.detectBoard(gray)
        if corners is None or ids is None or len(ids) == 0:
            print(f"  {prefijo}_{n}: descartada (0 esquinas, mínimo {MIN_ESQUINAS})")
            continue
        # Normalizar formas (cambian entre versiones de OpenCV): esquinas (N,2), ids (N,)
        c2 = np.asarray(corners, np.float32).reshape(-1, 2)
        i1 = np.asarray(ids).reshape(-1).astype(int)
        if len(c2) != len(i1):
            print(f"  {prefijo}_{n}: descartada (esquinas e ids no coinciden: {len(c2)} vs {len(i1)})")
            continue
        if len(i1) < MIN_ESQUINAS:
            print(f"  {prefijo}_{n}: descartada ({len(i1)} esquinas, mínimo {MIN_ESQUINAS})")
            continue
        res[n] = (c2, i1)
        # Imagen de depuración (dibujo manual: no depende de la versión de OpenCV)
        vis = cv2.cvtColor(cv2.resize(gray, None, fx=0.25, fy=0.25), cv2.COLOR_GRAY2BGR)
        for (x, y), i in zip(c2 * 0.25, i1):
            cv2.circle(vis, (int(round(x)), int(round(y))), 5, (0, 255, 0), 1)
            cv2.putText(vis, str(i), (int(x) + 4, int(y) - 4), cv2.FONT_HERSHEY_SIMPLEX,
                        0.4, (0, 0, 255), 1)
        cv2.imwrite(os.path.join(CARPETA_DEBUG, f"{prefijo}_{n:02d}.jpg"), vis)
    return res, size


def calibrar_camara(board_pts, det, size, nombre):
    """Calibra una cámara con TODAS sus fotos; quita una vez las de error alto."""
    ns = sorted(det)
    for ronda in (1, 2):
        objs = [board_pts[det[n][1]] for n in ns]
        imgs = [det[n][0].reshape(-1, 1, 2) for n in ns]
        rms, K, d, _, _, _, _, err = cv2.calibrateCameraExtended(objs, imgs, size, None, None)
        err = err.ravel()
        malos = [n for n, e in zip(ns, err) if e > max(2.5 * np.median(err), 1.0)]
        if ronda == 2 or not malos or len(ns) - len(malos) < 8:
            break
        print(f"  {nombre}: quito fotos con error alto {malos}")
        ns = [n for n in ns if n not in malos]
    print(f"  {nombre}: {len(ns)} fotos, RMS = {rms:.3f} px, f = {K[0,0]:.0f}/{K[1,1]:.0f} px, "
          f"centro = ({K[0,2]:.0f}, {K[1,2]:.0f})")
    return K, d, rms


def armar_pares(board_pts, det_l, det_r):
    """Para cada foto N presente en ambas, deja solo las esquinas vistas por las dos cámaras."""
    ids_foto, objs, a, b = [], [], [], []
    for n in sorted(set(det_l) & set(det_r)):
        cl, il = det_l[n]; cr, ir = det_r[n]
        comunes = np.intersect1d(il, ir)
        if len(comunes) < MIN_COMUNES:
            print(f"  par {n}: descartado (solo {len(comunes)} esquinas comunes)")
            continue
        ml = {i: k for k, i in enumerate(il)}; mr = {i: k for k, i in enumerate(ir)}
        objs.append(board_pts[comunes])
        a.append(cl[[ml[i] for i in comunes]].reshape(-1, 1, 2))
        b.append(cr[[mr[i] for i in comunes]].reshape(-1, 1, 2))
        ids_foto.append(n)
    return ids_foto, objs, a, b


def pose_relativa_por_par(objs, a, b, K1, d1, K2, d2):
    angs, dist = [], []
    for o, p, q in zip(objs, a, b):
        _, rl, tl = cv2.solvePnP(o, p, K1, d1)
        _, rr, tr = cv2.solvePnP(o, q, K2, d2)
        Rl, Rr = cv2.Rodrigues(rl)[0], cv2.Rodrigues(rr)[0]
        Rrel = Rr @ Rl.T
        Trel = tr - Rrel @ tl
        angs.append(np.degrees(np.linalg.norm(cv2.Rodrigues(Rrel)[0])))
        dist.append(np.linalg.norm(Trel))
    return np.array(angs), np.array(dist)


def validar_triangulacion(objs, a, b, K1, d1, K2, d2, P1, P2):
    """Triangula las esquinas y compara las distancias entre ellas con las reales del tablero."""
    errs = []
    for o, p, q in zip(objs, a, b):
        ua = cv2.undistortPoints(p, K1, d1, P=K1).reshape(-1, 2).T
        ub = cv2.undistortPoints(q, K2, d2, P=K2).reshape(-1, 2).T
        X = cv2.triangulatePoints(P1, P2, ua, ub)
        X = (X[:3] / X[3]).T
        D3 = np.linalg.norm(X[:, None] - X[None], axis=2)
        D0 = np.linalg.norm(o[:, None] - o[None], axis=2)
        iu = np.triu_indices(len(o), 1)
        errs.append(np.abs(D3 - D0)[iu].mean())
    return np.array(errs)


def comprobar_montaje(R, T):
    """Compara el resultado con las medidas reales del montaje."""
    nT = float(np.linalg.norm(T))
    ang = float(np.degrees(np.linalg.norm(cv2.Rodrigues(R)[0])))
    print("\n===== COMPARACIÓN CON TU MONTAJE =====")
    if BASELINE_ESPERADA_MM:
        dif = nT - BASELINE_ESPERADA_MM
        ok = abs(dif) <= 0.06 * BASELINE_ESPERADA_MM   # el centro óptico exacto no se conoce al mm
        print(f"|T|:      calibrado {nT:.1f} mm  |  medido {BASELINE_ESPERADA_MM:.1f} mm  "
              f"({dif:+.1f} mm)  [{'OK' if ok else 'REVISAR'}]")
    if ROTACION_ESPERADA_GRADOS:
        dif = ang - ROTACION_ESPERADA_GRADOS
        ok = abs(dif) <= 4
        print(f"Rotación: calibrado {ang:.1f}°  |  esperado {ROTACION_ESPERADA_GRADOS:.1f}°  "
              f"({dif:+.1f}°)  [{'OK' if ok else 'REVISAR'}]")
    if BASELINE_ESPERADA_MM and ROTACION_ESPERADA_GRADOS:
        a = np.radians(ROTACION_ESPERADA_GRADOS / 2)
        Te = BASELINE_ESPERADA_MM * np.array([-np.cos(a), 0.0, np.sin(a)])
        print(f"T calibrado = {T.ravel().round(0)}   T esperado (inclinación simétrica) = {Te.round(0)}")
        print("   (las diferencias en T se deben sobre todo a que las inclinaciones reales no son idénticas)")
    print(f"T_y = {float(np.ravel(T)[1]):.1f} mm: debería ser pequeño si las dos cámaras están a la misma altura.")


def validar_epipolar(a, b, K1, d1, K2, d2, R, T):
    """Distancia (px) de cada punto a la línea epipolar que le corresponde en la otra imagen.
    No depende del tamaño del tablero: solo comprueba la geometría entre las dos cámaras."""
    Tx = np.array([[0, -T[2, 0], T[1, 0]], [T[2, 0], 0, -T[0, 0]], [-T[1, 0], T[0, 0], 0]])
    E = Tx @ R                                        # matriz esencial  E = [T]x R
    F = np.linalg.inv(K2).T @ E @ np.linalg.inv(K1)   # matriz fundamental  x2' F x1 = 0
    errs = []
    for p, q in zip(a, b):
        ua = cv2.undistortPoints(p, K1, d1, P=K1).reshape(-1, 2)
        ub = cv2.undistortPoints(q, K2, d2, P=K2).reshape(-1, 2)
        x1 = np.hstack([ua, np.ones((len(ua), 1))])
        x2 = np.hstack([ub, np.ones((len(ub), 1))])
        l2 = x1 @ F.T                                  # líneas epipolares en la imagen 2
        l1 = x2 @ F                                    # líneas epipolares en la imagen 1
        e2 = np.abs((l2 * x2).sum(1)) / np.linalg.norm(l2[:, :2], axis=1)
        e1 = np.abs((l1 * x1).sum(1)) / np.linalg.norm(l1[:, :2], axis=1)
        errs.append(0.5 * (e1.mean() + e2.mean()))
    return np.array(errs)


def calibrar(board_pts, det_l, det_r, size_l, size_r):
    print("\nCalibración intrínseca (cada cámara con todas sus fotos):")
    K1, d1, _ = calibrar_camara(board_pts, det_l, size_l, "izq")
    K2, d2, _ = calibrar_camara(board_pts, det_r, size_r, "der")

    print("\nPares:")
    ids, objs, a, b = armar_pares(board_pts, det_l, det_r)
    print(f"  pares utilizables: {len(ids)}")

    if len(ids) < 8:
        sys.exit("Se necesitan al menos 8 pares con suficientes esquinas comunes.")

    # --- Filtrar pares inconsistentes (pose relativa distinta a la mayoría) ---
    angs, dist = pose_relativa_por_par(objs, a, b, K1, d1, K2, d2)
    ma, md = np.median(angs), np.median(dist)
    print(f"\nPose relativa por par (mediana: {ma:.1f}°, {md:.0f} mm):")
    keep = []
    for k, n in enumerate(ids):
        malo = abs(angs[k] - ma) > 8 or abs(dist[k] - md) > 0.15 * md
        print(f"  par {n:2d}: {angs[k]:6.1f}°  {dist[k]:7.1f} mm  ({len(objs[k])} esquinas)"
              + ("   <-- DESCARTADO" if malo else ""))
        if not malo:
            keep.append(k)
    pick = lambda L, ks: [L[k] for k in ks]
    ids, objs, a, b = pick(ids, keep), pick(objs, keep), pick(a, keep), pick(b, keep)
    if len(ids) < 8:
        sys.exit("Quedan menos de 8 pares tras el filtrado. Tomá más fotos.")

    # --- Estéreo con intrínsecos fijos; segunda ronda sin los peores pares ---
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 1e-6)
    for ronda in (1, 2):
        rms, K1, d1, K2, d2, R, T, E, F, _, _, pve = cv2.stereoCalibrateExtended(
            objs, a, b, K1, d1, K2, d2, size_l, None, None,
            flags=cv2.CALIB_FIX_INTRINSIC, criteria=crit)
        e = np.sqrt((pve ** 2).mean(axis=1))
        malos = np.where(e > max(2.5 * np.median(e), 1.5))[0]
        if ronda == 2 or len(malos) == 0 or len(ids) - len(malos) < 8:
            break
        print(f"\nQuito por error estéreo alto: pares {[ids[k] for k in malos]}")
        ks = [k for k in range(len(ids)) if k not in malos]
        ids, objs, a, b = pick(ids, ks), pick(objs, ks), pick(a, ks), pick(b, ks)

    P1 = K1 @ np.hstack([np.eye(3), np.zeros((3, 1))])
    P2 = K2 @ np.hstack([R, T])

    print("\n===== RESULTADO ESTÉREO =====")
    print(f"Pares usados: {len(ids)}")
    print(f"RMS estéreo:  {rms:.3f} px   (objetivo < 1 px)")
    print(f"|T|:          {np.linalg.norm(T):.1f} mm   (distancia entre centros ópticos)")
    print(f"Rotación:     {np.degrees(np.linalg.norm(cv2.Rodrigues(R)[0])):.1f}°")
    print(f"T = {T.ravel().round(1)} mm")

    err3d = validar_triangulacion(objs, a, b, K1, d1, K2, d2, P1, P2)
    print("\n===== VALIDACIÓN POR TRIANGULACIÓN =====")
    print("Error medio en la distancia entre esquinas del tablero (real vs. triangulada):")
    print(f"  media {err3d.mean():.2f} mm   peor par {err3d.max():.2f} mm   "
          f"(buena calibración: ~1 mm o menos)")

    err_ep = validar_epipolar(a, b, K1, d1, K2, d2, R, T)
    print("\n===== VALIDACIÓN EPIPOLAR (no depende de la escala del tablero) =====")
    print("Distancia de cada punto a su línea epipolar en la otra imagen:")
    print(f"  media {err_ep.mean():.2f} px   peor par {err_ep.max():.2f} px   (buena calibración: ~1 px o menos)")

    comprobar_montaje(R, T)

    return dict(K1=K1, d1=d1, K2=K2, d2=d2, R=R, T=T, E=E, F=F, P1=P1, P2=P2,
                size_l=np.array(size_l), size_r=np.array(size_r),
                square=SQUARE_LEN, marker=MARKER_LEN, nx=NX, ny=NY,
                dictionary=DICCIONARIO_NOMBRE, pair_ids=np.array(ids), rms=rms)


def main():
    mostrar_configuracion()
    izquierda = listar_imagenes(CARPETA_IZQ)
    derecha = listar_imagenes(CARPETA_DER)
    comunes = sorted(izquierda.keys() & derecha.keys())
    print(f"Fotos: izquierda {len(izquierda)}, derecha {len(derecha)}; pares completos {len(comunes)}")
    print(f"Sin derecha: {sorted(izquierda.keys() - derecha.keys())}")
    print(f"Sin izquierda: {sorted(derecha.keys() - izquierda.keys())}")
    if len(comunes) < 8:
        sys.exit("Se necesitan al menos 8 pares completos antes de calibrar.")
    board, detector = crear_tablero()
    board_pts = np.asarray(board.getChessboardCorners(), np.float32).reshape(-1, 3)   # (35, 3) en mm
    print("Detectando tablero en las fotos...")
    det_l, size_l = detectar_carpeta(CARPETA_IZQ, "izq", detector)
    det_r, size_r = detectar_carpeta(CARPETA_DER, "der", detector)
    print(f"Fotos con tablero detectado: izq {len(det_l)}, der {len(det_r)}")
    if len(det_l) < 8 or len(det_r) < 8:
        sys.exit("Muy pocas fotos con detección. Revisa la carpeta de debug y el tablero.")
    res = calibrar(board_pts, det_l, det_r, size_l, size_r)
    np.savez(SALIDA, **res)
    print(f"\nGuardado en {SALIDA}")


if __name__ == "__main__":
    main()
