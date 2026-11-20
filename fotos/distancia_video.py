"""Correspondencias de textura sobre máscaras; nunca triangula centroides distintos.

Estimación de superficie visible próxima al centro, no centro volumétrico.
No resuelve la falta de sincronización de los teléfonos.
"""
from collections import defaultdict
import cv2
import numpy as np


def estimar(imagenes, grupos, triangular, calibracion):
    if calibracion is None or any(not g for g in grupos):
        return []
    preparados=[]
    for im,mascaras in zip(imagenes,grupos):
        h,w=im.shape[:2];limpias=[]
        for mascara in mascaras:
            m=cv2.resize(mascara.astype(np.float32),(w,h),interpolation=cv2.INTER_NEAREST)>.5
            limpias.append(cv2.erode(m.astype(np.uint8),np.ones((5,5),np.uint8)))
        union=np.maximum.reduce(limpias)*255
        x,y,cw,ch=cv2.boundingRect(union)
        if not cw or not ch:return []
        # SIFT construye pirámides incluso fuera de su máscara: limitar el área.
        x0,y0=max(0,x-12),max(0,y-12)
        x1,y1=min(w,x+cw+12),min(h,y+ch+12)
        gris=cv2.cvtColor(im[y0:y1,x0:x1],cv2.COLOR_BGR2GRAY)
        # Limitar la pirámide; devolver puntos a coordenadas de calibración.
        escala=min(1.,480/max(gris.shape))
        ancho,alto=max(1,round(gris.shape[1]*escala)),max(1,round(gris.shape[0]*escala))
        sx,sy=ancho/gris.shape[1],alto/gris.shape[0]
        region=union[y0:y1,x0:x1]
        if escala<1:
            gris=cv2.resize(gris,(ancho,alto),interpolation=cv2.INTER_AREA)
            region=cv2.resize(region,(ancho,alto),interpolation=cv2.INTER_NEAREST)
        puntos,descriptores=cv2.SIFT_create(nfeatures=300,contrastThreshold=.025).detectAndCompute(gris,region)
        for punto in puntos:punto.pt=(punto.pt[0]/sx+x0,punto.pt[1]/sy+y0)
        preparados.append((puntos,descriptores,limpias))
    (p,dp,mp),(q,dq,mq)=preparados
    if dp is None or dq is None or min(len(dp),len(dq))<3:return []
    matcher=cv2.BFMatcher()
    def ratios(a,b):
        return {par[0].queryIdx:par[0] for par in matcher.knnMatch(a,b,k=2)
                if len(par)==2 and par[0].distance<.7*par[1].distance}
    ida,vuelta=ratios(dp,dq),ratios(dq,dp)
    def dueno(pt,mascaras):
        x,y=np.round(pt).astype(int)
        candidatos=[i for i,m in enumerate(mascaras) if 0<=y<m.shape[0] and 0<=x<m.shape[1] and m[y,x]]
        return candidatos[0] if len(candidatos)==1 else None
    grupos_pares=defaultdict(list)
    for i,m in ida.items():
        j=m.trainIdx
        if j not in vuelta or vuelta[j].trainIdx!=i:continue
        a,b=np.array(p[i].pt),np.array(q[j].pt)
        izq,der=dueno(a,mp),dueno(b,mq)
        if izq is None or der is None:continue
        try:xyz,error=triangular(a,b,calibracion)
        except ValueError:continue
        if error>2.5 or not 100<float(np.linalg.norm(xyz))<3000:continue
        grupos_pares[izq,der].append((a,b,xyz,error))
    candidatos=[]
    for (i,j),coincidencias in grupos_pares.items():
        if len(coincidencias)<3:continue
        xyzs=np.array([v[2] for v in coincidencias]);mediana=np.median(xyzs,axis=0)
        tolerancia=max(10,float(np.linalg.norm(mediana))*.08)
        buenos=[v for v in coincidencias if np.linalg.norm(v[2]-mediana)<tolerancia]
        if len(buenos)<3:continue
        # Evitar que varias escalas del mismo punto cuenten como evidencia distinta.
        if len({tuple(np.round(v[0]/4).astype(int)) for v in buenos})<3:continue
        momentos=cv2.moments(mp[i]);centro=np.array([momentos['m10'],momentos['m01']])/max(momentos['m00'],1)
        elegido=min(buenos,key=lambda v:np.linalg.norm(v[0]-centro))
        y,x=np.nonzero(mp[i]);radio=max(10,np.hypot(np.ptp(x),np.ptp(y))*.3)
        if np.linalg.norm(elegido[0]-centro)>radio:continue
        candidatos.append({'izq':i,'der':j,'puntos':[elegido[0].tolist(),elegido[1].tolist()],
                           'distancia_cm':round(float(np.linalg.norm(elegido[2]))/10,1),
                           'z_cm':round(float(elegido[2][2])/10,1),'error_px':round(elegido[3],2),
                           'apoyos':len(buenos),'tipo':'superficie visible cercana al centro; estimada, sin sincronizacion'})
    # Si un fruto admite varias parejas, no elegir arbitrariamente una de ellas.
    return [r for r in candidatos if sum(c['izq']==r['izq'] for c in candidatos)==1
            and sum(c['der']==r['der'] for c in candidatos)==1]
