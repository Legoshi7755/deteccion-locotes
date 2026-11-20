# Detección de locotes — WATSOCOTE visión estéreo

Repositorio de pruebas para la detección y segmentación de locotes rojos con YOLO, más la estimación de distancia con dos celulares que funcionan como cámaras estéreo.

Las instrucciones originales del proyecto están en [`LEEME.txt`](LEEME.txt).

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

1. Conectá la PC y los dos celulares a la misma red Wi-Fi.
2. En cada celular abrí su enlace de transmisión (están en `LEEME.txt`) y permití el uso de la cámara trasera.
3. Ejecutá el programa desde la raíz del repositorio:
   ```bash
   python fotos/yolo_segmentacion_video_ampliado.py
   ```
4. Abrí http://127.0.0.1:8766/ en la misma PC.

## Notas

- La calibración incluida **solo sirve para el montaje con el que se obtuvo**. Si cambiás la posición, el lente, el recorte o el zoom de los celulares, tenés que recalibrar.
- CUDA acelera YOLO. Sin GPU funciona igual, pero más lento (instalá torch para CPU).
- Las distancias son estimadas. Las cámaras no están sincronizadas, así que la medición durante el movimiento no es fiable.
- Para verificar la integridad de los archivos, compará sus hashes con `SHA256.json`.
