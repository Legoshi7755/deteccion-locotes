# Detección de locotes — WATSOCOTE visión estéreo

Repositorio de pruebas para la detección y segmentación de locotes rojos con YOLO, más la estimación de distancia con dos celulares que funcionan como cámaras estéreo.

Las instrucciones originales del proyecto están en [`LEEME.txt`](LEEME.txt).

## Probar sin GPU: Google Colab

[![Abrir en Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Legoshi7755/deteccion-locotes/blob/main/colab_prueba_locotes.ipynb)

El notebook [`colab_prueba_locotes.ipynb`](colab_prueba_locotes.ipynb) usa la GPU gratuita de Colab y tiene tres partes:

1. **Fotos:** detecta y segmenta locotes en fotos subidas o de Google Drive.
2. **Video:** anota un video completo y lo descarga.
3. **En vivo (experimental):** corre la aplicación estéreo con los dos celulares.
4. **Calibrar:** imprime el tablero ChArUco, captura pares con los dos celulares y calcula una calibración nueva. Se guarda en una sesión aparte y en tu Google Drive (`watsocote_calibraciones`), y la app en vivo la usa automáticamente. Hay que recalibrar cada vez que se mueven o cambian los soportes, la cámara o el zoom.

En la celda de preparación, `VERSION` elige qué rama usar: `main` o `modelo-tallo` (locote + tallo y punto de agarre 3D).

## Probar con fotos o videos en tu PC (CPU)

```bash
python fotos/prueba_imagenes.py foto.jpg carpeta_con_fotos/ video.mp4 --salida resultados
```

Usa el mismo modelo, umbral (0,40) y filtros que la aplicación. Opciones:
- `--sam`: refina los contornos con MobileSAM.
- `--conf 0.3`: cambia la confianza mínima.
- `--cada 3`: en videos, analiza 1 de cada 3 cuadros.

## Celulares en modo directo (sin VDO.Ninja)

Cada celular abre una página propia que manda las fotos **directo al servidor**. Comparado con VDO.Ninja:
- **Más fluido:** sin el paso por VDO.Ninja ni la captura en el navegador de la PC.
- **Fotos sincronizadas:** el servidor empareja las dos fotos por hora de llegada (desfase típico de 5–30 ms en la misma red Wi-Fi).
- **Control de la cámara desde el celular:** bloqueo del **enfoque**, de la **exposición y los blancos**, **zoom** fijo, tamaño (640/960/1280 px), calidad JPEG, fotos por segundo, elección de cámara y linterna. Los ajustes quedan guardados en cada celular.

El bloqueo de enfoque y el zoom dependen de que Chrome para Android los ofrezca en ese modelo. La página muestra qué permite cada celular.

### En la PC o notebook (misma red Wi-Fi)

```bash
python fotos/yolo_segmentacion_video_ampliado.py --directo
```

1. La consola muestra la dirección de la app (`https://<IP de la PC>:8766/?clave=...`) y un código QR por celular.
2. Abre la app en la PC. También muestra los QR.
3. Escanea cada QR con **su** celular, permite la cámara y toca **Iniciar envío**.
4. En cada celular apunta al objeto a la distancia de trabajo y toca **Bloquear aquí** (enfoque). Después fija el zoom y bloquea exposición y blancos.

Notas:
- **Advertencia del navegador:** el certificado HTTPS es propio (Chrome exige HTTPS para usar la cámara). La primera vez, la PC y los celulares avisan que la conexión "no es privada": entra en *Configuración avanzada → Continuar*.
- **Firewall de Windows:** si pregunta, permite Python en **redes privadas**. Si los celulares no cargan la página, revisa que estén en la misma red Wi-Fi que la PC.
- **Clave de acceso:** la dirección incluye una clave al azar. Sin ella, el servidor no muestra nada. Para fijarla: `--clave miclave`.

### Calibrar en modo directo

```bash
python fotos/captura_webrtc.py --directo
```

Usa el mismo procedimiento. En cada celular elige **Tamaño 1280 px** y **Calidad 90 %**, y bloquea enfoque, exposición y zoom **antes** de la primera foto. No los cambies después: la detección debe usar los mismos.

**Hay que recalibrar al pasar de VDO.Ninja al modo directo**, porque el recorte de la imagen puede ser distinto. Para elegir la sesión de calibración: `WATSOCOTE_SESION=nombre` (en Windows PowerShell: `$env:WATSOCOTE_SESION="nombre"`).

### En Colab

En las celdas **Iniciar servidor** (parte 3) y **4.2** (calibración), elige `CELULARES = "Directo (túnel)"`. El notebook abre un túnel HTTPS temporal de Cloudflare (sin advertencias de certificado) y muestra el enlace de la app y los QR de los celulares.

## Contenido

```
├── calibracion_estereo_charuco.py   # calibración estéreo con tablero ChArUco
├── config_calibracion.py            # tablero 8x6, cuadro 27 mm, marcador 20 mm, DICT_4X4_50
├── requirements.txt                 # dependencias (torch CUDA 12.4, ultralytics, opencv)
├── VERSIONES_ENTORNO.txt            # versiones con las que se probó (Python 3.13.6, Windows)
├── SHA256.json                      # hashes de los archivos entregados
└── fotos/
    ├── yolo_segmentacion_video_ampliado.py   # ▶ punto de entrada
    ├── yolo_triangulacion_webrtc.py          # servidor, detección y triangulación
    ├── prueba_imagenes.py                    # prueba con fotos/videos, sin celulares
    ├── camaras_directas.py                   # modo directo: recibe y empareja las fotos de los celulares
    ├── camara_celular.html                   # página de cámara para cada celular (enfoque, zoom, envío)
    ├── best_frutos_video_ampliado.pt         # modelo YOLO de frutos rojos (activo)
    ├── mobile_sam.pt                         # MobileSAM para el refinamiento manual
    ├── entrenamiento_locote_rojo/            # métricas del modelo entrenado
    ├── sesiones/calibracion_2026-10-31_02/   # calibración vigente del montaje
    └── ...                                   # captura WebRTC, interfaz web, filtros, etc.
```

## Puesta en marcha

```bash
python -m venv .venv
```

```bash
# Windows: .venv\Scripts\activate    ·    Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

Sin GPU, no instales `requirements.txt` (trae torch para CUDA, ~2,5 GB). Usa en su lugar:

```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
```

```bash
pip install ultralytics opencv-python numpy
```

1. Conectá la PC y los dos celulares a la misma red Wi-Fi.
2. En cada celular abrí su enlace de transmisión (están en `LEEME.txt`) y permití el uso de la cámara trasera.
3. Ejecutá el programa desde la raíz del repositorio:
   ```bash
   python fotos/yolo_segmentacion_video_ampliado.py
   ```
4. Abrí http://127.0.0.1:8766/ en la misma PC.

## Notas

- La calibración incluida **solo sirve para el montaje con el que se obtuvo**. Si cambiás la posición, el lente, el recorte o el zoom de los celulares, tenés que recalibrar.
- CUDA acelera YOLO. Sin GPU el programa pasa solo a CPU: funciona, pero más lento.
- Las distancias son estimadas. Las cámaras no están sincronizadas, así que la medición durante el movimiento no es fiable.
- Para verificar la integridad de los archivos, compará sus hashes con `SHA256.json`.
