"""Calibrar únicamente la sesión activa de captura WebRTC.

Ejemplo (celulares lado a lado, lentes a 98 mm, sin inclinación):
    python fotos/calibrar_sesion_actual.py --sesion calibracion_vdo_01 --baseline-mm 98 --rotacion-grados 0
"""
import argparse
import os
import sys
import time
from pathlib import Path
import importlib.util
import captura_webrtc as captura

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Calibra la sesión de captura elegida.")
    parser.add_argument("--sesion", help="nombre de la sesión en fotos/sesiones (por defecto, WATSOCOTE_SESION)")
    parser.add_argument("--baseline-mm", type=float,
                        help="distancia medida entre los centros de las dos lentes, en mm (solo para comparar)")
    parser.add_argument("--rotacion-grados", type=float,
                        help="ángulo total entre las cámaras: 0 si están paralelas, 60 si cada una gira 30° hacia adentro")
    parser.add_argument("--sobrescribir", action="store_true",
                        help="si ya hay una calibración, renombrarla a calibracion_charuco_anterior_<hora>.npz y calibrar de nuevo")
    args = parser.parse_args()
    # Misma elección de sesión que la captura: --sesion NOMBRE o WATSOCOTE_SESION.
    captura.sesion_desde_argumentos(["--sesion", args.sesion] if args.sesion else [])
    if not (captura.SESION / "fotos_izq").is_dir():
        raise SystemExit(f"No hay fotos en {captura.SESION}. Revisá el nombre de la sesión.")
    # Medidas del montaje real; el calibrador las lee de estas variables al cargarse (0 = no comparar).
    if args.baseline_mm is not None:
        os.environ["WATSOCOTE_BASELINE_MM"] = str(args.baseline_mm)
    if args.rotacion_grados is not None:
        os.environ["WATSOCOTE_ROTACION_GRADOS"] = str(args.rotacion_grados)
    fuente = Path(__file__).resolve().parents[1] / "calibracion_estereo_charuco.py"
    sys.path.insert(0, str(fuente.parent))
    spec = importlib.util.spec_from_file_location("calibrador_sesion", fuente)
    cal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cal)
    cal.CARPETA_IZQ = captura.SESION / "fotos_izq"
    cal.CARPETA_DER = captura.SESION / "fotos_der"
    cal.CARPETA_DEBUG = captura.SESION / "debug_charuco"
    cal.SALIDA = captura.SESION / "calibracion_charuco.npz"
    if cal.SALIDA.exists():
        if not args.sobrescribir:
            raise SystemExit("Ya existe una calibración de esta sesión; no se sobrescribe. "
                             "Usá --sobrescribir para guardar la anterior con otro nombre y calibrar de nuevo.")
        anterior = cal.SALIDA.with_name(f"calibracion_charuco_anterior_{time.strftime('%Y%m%d_%H%M%S')}.npz")
        cal.SALIDA.rename(anterior)
        print(f"Calibración anterior guardada como {anterior.name}")
    cal.mostrar_configuracion = lambda: print(f"Calibrando sesión: {captura.SESION}")
    cal.main()
