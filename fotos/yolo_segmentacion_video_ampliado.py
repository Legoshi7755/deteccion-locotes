"""Receptor del modelo de frutos ampliado; no carga el modelo experimental de tallos."""
import json
import os
from pathlib import Path
import yolo_triangulacion_webrtc as app


def seleccionar():
    archivo=Path(__file__).resolve().parent/'entrenamiento_locote_rojo/resultado_frutos_video_ampliado.json'
    if not archivo.is_file():
        raise SystemExit('El entrenamiento y su evaluación todavía no terminaron.')
    resultado=json.loads(archivo.read_text(encoding='utf-8'))
    comparacion=resultado['comparacion']
    clave='metrics/mAP50(M)'
    if comparacion['nuevo']['metricas'][clave] <= comparacion['anterior']['metricas'][clave]:
        raise SystemExit('El candidato no mejoró la evaluación. Conservá el receptor anterior.')
    pesos=Path(resultado['best'])
    if not pesos.is_absolute():pesos=Path(__file__).resolve().parent/pesos
    if not pesos.is_file():raise SystemExit('No se encontraron los pesos evaluados.')
    return pesos


if __name__=='__main__':
    import argparse
    import camaras_directas
    parser = camaras_directas.argumentos(argparse.ArgumentParser(description='Aplicación de visión estéreo'))
    args = parser.parse_args()
    camaras_directas.configurar_desde(args, 8766)
    # Confianza mínima de YOLO (WATSOCOTE_CONF, por defecto 0.40)
    app.CONF=float(os.environ.get('WATSOCOTE_CONF','0.40').replace(',','.'))
    # Tamaño de entrada de YOLO: 960 por defecto; 640 es ~2 veces más rápido (puede perder locotes pequeños)
    app.IMG_SIZE=int(os.environ.get('WATSOCOTE_IMG_SIZE','960'))
    app.REFINAR_SAM_VIDEO=False
    app.main(seleccionar())
