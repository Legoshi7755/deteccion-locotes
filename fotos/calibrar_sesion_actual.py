"""Calibrar únicamente la sesión activa de captura WebRTC."""
import sys
from pathlib import Path
import importlib.util
import captura_webrtc as captura

if __name__ == "__main__":
    # Misma elección de sesión que la captura: --sesion NOMBRE o WATSOCOTE_SESION.
    captura.sesion_desde_argumentos()
    if not (captura.SESION / "fotos_izq").is_dir():
        raise SystemExit(f"No hay fotos en {captura.SESION}. Revisá el nombre de la sesión.")
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
        raise SystemExit("Ya existe una calibración de esta sesión; no se sobrescribe.")
    cal.mostrar_configuracion = lambda: print(f"Calibrando sesión: {captura.SESION}")
    cal.main()
