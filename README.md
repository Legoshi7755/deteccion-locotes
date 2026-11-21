# Detección de locotes — WATSOCOTE visión estéreo

Repositorio de pruebas para la detección y segmentación de locotes rojos con YOLO, más la estimación de distancia con dos celulares que funcionan como cámaras estéreo.

Las instrucciones originales del proyecto están en [`LEEME.txt`](LEEME.txt).

## Probar sin GPU: Google Colab

[![Abrir en Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Legoshi7755/deteccion-locotes/blob/main/colab_prueba_locotes.ipynb)

El notebook [`colab_prueba_locotes.ipynb`](colab_prueba_locotes.ipynb) usa la GPU gratuita de Colab y tiene tres partes:

1. **Fotos:** detecta y segmenta locotes en fotos subidas o de Google Drive.
2. **Video:** anota un video completo y lo descarga.
3. **En vivo (experimental):** corre la aplicación estéreo con los dos celulares.

## Probar con fotos o videos en tu PC (CPU)

```bash
python fotos/prueba_imagenes.py foto.jpg carpeta_con_fotos/ video.mp4 --salida resultados
```

Usa el mismo modelo, umbral (0,40) y filtros que la aplicación. Opciones:
- `--sam`: refina los contornos con MobileSAM.
- `--conf 0.3`: cambia la confianza mínima.
- `--cada 3`: en videos, analiza 1 de cada 3 cuadros.

## Modelo de tallo (punto de agarre)

Además del detector de frutos, hay un modelo que segmenta **locote** (rojo) y **tallo** (cian), y otro que agrega **hojas** (verde) y **ramas** (magenta). Están en `fotos/modelos/`:

| Archivo | Clases | Uso |
|---|---|---|
| `locote_tallo_v2.pt` | locote, tallo | decide locote y tallo (AP50 de máscara en test: tallo 0,76, locote 0,83) |
| `locote_tallo_hojas.pt` | locote, tallo, hoja, rama | solo aporta hojas y ramas |

Entrenados con datasets públicos de Roboflow Universe (CC BY 4.0): *Bell Peppers Segmentation 2* (VisionFrutas), *sweet pepper* (Luis Montoya, vía Eszie) y *pepper-project* (Sean Somogyvari / Vineland).

Reglas: un tallo solo cuenta si toca un locote detectado, y se toma uno por locote. Cada tallo indica `tapado` si una hoja lo cubre y `rama_cerca` si una rama pasa junto al punto de agarre.

**Fotos y videos:**
```bash
python fotos/prueba_imagenes.py carpeta_fotos/ --tallo
```
`--sin-hojas` usa solo el modelo de locote/tallo (más rápido).

**Aplicación estéreo:** `yolo_triangulacion_webrtc.py` calcula en cada análisis la posición 3D del punto de agarre (`tallos_3d`: XYZ en mm en el marco de la cámara izquierda, distancia, `tapado`, `rama_cerca`). Usa la línea epipolar de la calibración para encontrar el mismo punto del tallo en la imagen derecha (`fotos/tallo_3d.py`). Se desactiva con `USAR_TALLO = False`, o solo las hojas con `USAR_HOJAS = False`. Las distancias del tallo **todavía no están validadas con cinta métrica**.

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
