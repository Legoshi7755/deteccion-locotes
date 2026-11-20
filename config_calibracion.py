"""Configuración común; confirmar medidas con el tablero impreso."""
from pathlib import Path
BASE = Path(__file__).resolve().parent
CARPETA_IZQ = BASE / "fotos_izq"
CARPETA_DER = BASE / "fotos_der"
CARPETA_DEBUG = BASE / "debug_charuco"
SALIDA = BASE / "calibracion_charuco.npz"
NX, NY = 8, 6  # cuadros, no esquinas internas
SQUARE_LEN = 27.0  # mm
MARKER_LEN = 20.0  # mm
DICCIONARIO_NOMBRE = "DICT_4X4_50"


def mostrar_configuracion():
    print(f"Tablero: {NX} x {NY} cuadros; {DICCIONARIO_NOMBRE}; cuadro {SQUARE_LEN} mm; marcador {MARKER_LEN} mm")
    print(f"Fotos izquierda: {CARPETA_IZQ}")
    print(f"Fotos derecha: {CARPETA_DER}")
