"""Filtros explícitos para locotes ROJOS y confirmación temporal sin máscaras fantasma."""
import time
import cv2
import numpy as np

ESTADOS={}


def proporcion_roja(imagen, region):
    hsv=cv2.cvtColor(imagen,cv2.COLOR_BGR2HSV)
    rojo=(((hsv[:,:,0]<=12)|(hsv[:,:,0]>=168))&(hsv[:,:,1]>=95)&(hsv[:,:,2]>=35))
    n=np.count_nonzero(region)
    return float(np.count_nonzero(rojo&region)/n) if n else 0.0


def filtrar_rojos(imagen, resultado, minimo=0.18):
    if resultado.boxes is None or not len(resultado.boxes):return resultado
    h,w=imagen.shape[:2];keep=[]
    for i,xy in enumerate(resultado.boxes.xyxy.cpu().numpy()):
        region=np.zeros((h,w),bool)
        if resultado.masks is not None:
            mask=resultado.masks.data[i].cpu().numpy()
            if mask.shape!=(h,w):mask=cv2.resize(mask,(w,h),interpolation=cv2.INTER_NEAREST)
            region=mask>0.5
        else:
            x1,y1,x2,y2=np.round(xy).astype(int)
            region[max(0,y1):min(h,y2),max(0,x1):min(w,x2)]=True
        if region.sum()>=30 and proporcion_roja(imagen,region)>=minimo:keep.append(i)
    if len(keep)>1:
        boxes=resultado.boxes.xyxy.cpu().numpy()
        scores=resultado.boxes.conf.cpu().numpy()
        orden=sorted(keep,key=lambda i:float(scores[i]),reverse=True)
        elegidos=[]
        for i in orden:
            duplicado=False
            for j in elegidos:
                if resultado.masks is not None:
                    a=resultado.masks.data[i].cpu().numpy()>0.5
                    b=resultado.masks.data[j].cpu().numpy()>0.5
                    union=np.count_nonzero(a|b)
                    iou=np.count_nonzero(a&b)/union if union else 0
                    # Máscaras distintas de frutos que se tocan deben sobrevivir.
                    duplicado=iou>0.65
                else:
                    xy1=np.maximum(boxes[i,:2],boxes[j,:2]);xy2=np.minimum(boxes[i,2:],boxes[j,2:])
                    inter=np.prod(np.maximum(0,xy2-xy1))
                    union=np.prod(boxes[i,2:]-boxes[i,:2])+np.prod(boxes[j,2:]-boxes[j,:2])-inter
                    duplicado=inter/max(union,1)>0.65
                if duplicado:break
            if not duplicado:elegidos.append(i)
        keep=elegidos
    return resultado[keep]


def confirmar_video(resultado, lado, sesion):
    """Dos observaciones consecutivas; no reutiliza detecciones ausentes."""
    ahora=time.monotonic()
    for k in list(ESTADOS):
        if ahora-ESTADOS[k]['time']>30:del ESTADOS[k]
    clave=(sesion,lado)
    anterior=ESTADOS.get(clave,{'tracks':[],'time':0})
    prev=anterior['tracks'] if ahora-anterior['time']<10 else []
    nuevas=[];keep=[];usados=set()
    boxes=[] if resultado.boxes is None else resultado.boxes.xyxy.cpu().numpy()
    h,w=resultado.orig_shape
    for i,xy in enumerate(boxes):
        centro=(xy[:2]+xy[2:])/2;area=max(1.,float(np.prod(xy[2:]-xy[:2])))
        mejor=None;score=float('inf')
        for j,t in enumerate(prev):
            if j in usados:continue
            distancia=np.linalg.norm(centro-t['center'])/np.hypot(w,h)
            ratio=area/t['area']
            if distancia<0.12 and 0.35<ratio<2.85 and distancia<score:mejor=j;score=distancia
        hits=1
        if mejor is not None:usados.add(mejor);hits=prev[mejor]['hits']+1
        nuevas.append({'center':centro,'area':area,'hits':hits})
        if hits>=2:keep.append(i)
    ESTADOS[clave]={'time':ahora,'tracks':nuevas}
    if len(ESTADOS)>32:ESTADOS.pop(next(iter(ESTADOS)))
    return resultado[keep]
