"""Guarda originales y sugerencias separadas: nunca se entrenan sin revisar."""
import json,re,time
from pathlib import Path
import cv2

BASE=Path(__file__).resolve().parent/'dataset_carrito_pendiente'
ULTIMO={}


def guardar_muestra(datos,entradas,resultados):
    if not datos.get('guardar_entrenamiento'):return None
    sesion=str(datos.get('sesion_video','manual'))
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',sesion):raise ValueError('Identificador de sesión no válido')
    ahora=time.monotonic()
    if ahora-ULTIMO.get(sesion,0)<2:return None
    ULTIMO[sesion]=ahora
    carpeta=BASE/sesion
    for nombre in ('images','labels_sugeridas','metadata'):(carpeta/nombre).mkdir(parents=True,exist_ok=True)
    contador=len(list((carpeta/'metadata').glob('*.json')))+1
    nombre=f'par_{contador:05d}'
    info={'sesion':sesion,'par':contador,'timestamp_ns':time.time_ns(),'estado':'PENDIENTE_REVISION',
          'nota':'Las máscaras del detector son sugerencias, no verdad de referencia. Revisar también objetos omitidos.'}
    for lado,(imagen,origen),resultado in zip(('izq','der'),entradas,resultados):
        natural=cv2.rotate(imagen,cv2.ROTATE_90_COUNTERCLOCKWISE)
        path=carpeta/'images'/f'{nombre}_{lado}.jpg'
        if not cv2.imwrite(str(path),natural,[cv2.IMWRITE_JPEG_QUALITY,95]):raise OSError(str(path))
        lines=[]
        if resultado.masks is not None:
            h,w=natural.shape[:2]
            for xy in resultado.masks.xy:
                if len(xy)>=3:
                    normal=xy/[w,h]
                    lines.append('0 '+' '.join(f'{min(1,max(0,float(v))):.7f}' for v in normal.ravel()))
        (carpeta/'labels_sugeridas'/f'{nombre}_{lado}.txt').write_text('\n'.join(lines)+('\n' if lines else ''))
        info[lado]={'archivo':path.name,'origen':origen,'sugerencias':len(lines)}
    (carpeta/'metadata'/(nombre+'.json')).write_text(json.dumps(info,indent=2),encoding='utf-8')
    return f'Par original {contador} guardado para revisión en {carpeta.name}'
