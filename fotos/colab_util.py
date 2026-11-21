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


# ----------------------------------------------------------------------------- modo directo en Colab
CLOUDFLARED = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"


def nueva_clave():
    import secrets
    return secrets.token_urlsafe(9)


def cerrar_tunel():
    import subprocess
    subprocess.run(["pkill", "-f", "cloudflared tunnel"])


def iniciar_tunel(puerto, espera=60):
    """Túnel HTTPS temporal de Cloudflare hacia el puerto local; devuelve la URL pública.

    Los celulares no pueden llegar a la máquina de Colab directamente: el túnel les da una dirección
    https://...trycloudflare.com con certificado válido. Todas las páginas exigen además la clave.
    """
    import re
    import subprocess
    import time
    import urllib.request
    binario = CONTENT / "cloudflared"
    if not binario.exists():
        print("Descargando cloudflared…")
        urllib.request.urlretrieve(CLOUDFLARED, binario)
        binario.chmod(0o755)
    cerrar_tunel()
    log = CONTENT / "tunel.log"
    proceso = subprocess.Popen([str(binario), "tunnel", "--no-autoupdate", "--url", f"http://localhost:{puerto}"],
                               stdout=log.open("w"), stderr=subprocess.STDOUT)
    for _ in range(espera):
        time.sleep(1)
        encontrado = re.search(r"https://[-a-z0-9]+\.trycloudflare\.com", log.read_text(errors="replace"))
        if encontrado:
            return encontrado.group(0)
        if proceso.poll() is not None:
            break
    cerrar_tunel()
    raise RuntimeError("No se pudo abrir el túnel de Cloudflare. Probá de nuevo en un minuto o usá CELULARES = "
                       "'VDO.Ninja'.\n" + log.read_text(errors="replace")[-1500:])


def mostrar_qr(texto, titulo):
    """Muestra un QR grande en el notebook (para escanearlo con el celular) y el enlace."""
    print(f"{titulo}: {texto}")
    try:
        import io
        import qrcode
        from IPython.display import Image, display
        buf = io.BytesIO()
        qrcode.make(texto, box_size=6, border=2).save(buf, format="PNG")
        display(Image(data=buf.getvalue(), width=220))
    except Exception as exc:  # sin qrcode o fuera de Colab: queda el enlace
        print("  (no se pudo dibujar el QR:", exc, ")")


def arrancar_directo(script, puerto, log, extra_env=None, titulo="la aplicación"):
    """Abre el túnel, arranca el servidor en modo directo y muestra los enlaces y QR."""
    import os
    import subprocess
    import sys
    import time
    clave = nueva_clave()
    url = iniciar_tunel(puerto)
    servidor = subprocess.Popen([sys.executable, "-u", script, "--directo", "--sin-https", "--host", "127.0.0.1",
                                 "--clave", clave, "--url-publica", url], cwd=str(REPO),
                                stdout=log.open("w"), stderr=subprocess.STDOUT, env={**os.environ, **(extra_env or {})})
    for _ in range(180):
        time.sleep(1)
        texto = log.read_text(errors="replace")
        if "Modo directo" in texto or servidor.poll() is not None:
            break
    if servidor.poll() is not None:
        cerrar_tunel()
        raise RuntimeError("El servidor se detuvo:\n" + log.read_text(errors="replace")[-3000:])
    print(f"✅ Listo. Abrí {titulo} en la PC (en cualquier navegador):\n   {url}/?clave={clave}\n")
    for lado, nombre in (("izq", "Celular IZQUIERDO"), ("der", "Celular DERECHO")):
        mostrar_qr(f"{url}/camara?lado={lado}&clave={clave}", nombre + " (escanealo con ESE celular)")
    return servidor, url, clave
