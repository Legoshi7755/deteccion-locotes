"""Receptor del modelo de frutos ampliado; no carga el modelo experimental de tallos."""
import json
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
    app.CONF=0.40
    app.IMG_SIZE=960
    app.REFINAR_SAM_VIDEO=False
    app.main(seleccionar())
