"""Funciones auxiliares del notebook de Colab (calibraciones y Google Drive).

Están en un archivo aparte para que cada parte del notebook pueda usarlas sin
depender de haber ejecutado antes otra celda.
"""
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CONTENT = REPO.parent                      # /content en Colab
MI_UNIDAD = CONTENT / "drive" / "MyDrive"
DRIVE_CALIBRACIONES = MI_UNIDAD / "watsocote_calibraciones"
SESION_ACTIVA = CONTENT / "sesion_activa.txt"
SESION_EN_CAPTURA = CONTENT / "sesion_en_captura.txt"


def montar_drive():
    from google.colab import drive
    if not MI_UNIDAD.exists():
        drive.mount(str(CONTENT / "drive"))


def carpeta_sesion(nombre):
    return REPO / "fotos" / "sesiones" / nombre


def asegurar_sesion(nombre):
    """Usa la calibración de Colab o, si no está (Colab se reinició), la restaura desde Drive."""
    local = carpeta_sesion(nombre)
    if (local / "calibracion_charuco.npz").exists():
        return local
    montar_drive()
    remoto = DRIVE_CALIBRACIONES / nombre
    if not (remoto / "calibracion_charuco.npz").exists():
        raise FileNotFoundError(f"No encontré la calibración '{nombre}' ni en Colab ni en tu Drive ({remoto}).")
    shutil.copytree(remoto, local, dirs_exist_ok=True)
    print("Calibración restaurada desde Drive:", remoto)
    return local


def sesion_en_captura():
    if not SESION_EN_CAPTURA.exists():
        raise RuntimeError("Todavía no empezaste una captura: ejecuta primero la celda 4.2.")
    return SESION_EN_CAPTURA.read_text().strip()


def ruta_drive(texto):
    """Acepta '/content/drive/MyDrive/Claude/Fotos', 'MyDrive/Claude/Fotos' o 'Claude/Fotos'."""
    montar_drive()
    texto = texto.strip().strip("/")
    for prefijo in ("content/drive/MyDrive/", "content/drive/", "MyDrive/", "Mi unidad/"):
        if texto.startswith(prefijo):
            texto = texto[len(prefijo):]
    ruta = MI_UNIDAD / texto
    if not ruta.exists():
        raise FileNotFoundError(f"No encontré '{texto}' en tu Drive. Escribe la ruta desde 'Mi unidad', "
                                f"por ejemplo: Claude/Fotos_locote")
    print("Usando:", ruta)
    return ruta
