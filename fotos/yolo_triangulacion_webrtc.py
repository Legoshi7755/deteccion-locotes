"""YOLO + segmentación + triangulación de centros de cajas vía VDO.Ninja.
Ejecutar con .venv-cuda y abrir http://127.0.0.1:8766.
YOLO guía las máscaras; medir requiere marcar el mismo punto físico.
No sincroniza los celulares. Se procesa un par por pulsación.
Usa la misma rotación y escala de captura_webrtc.py. No guarda fotos.
"""
import base64
import json
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import captura_webrtc as captura
import camaras_directas as directas

BASE = Path(__file__).resolve().parent
MODELO = BASE / "best_2k.pt"
CALIBRACION = captura.SESION / "calibracion_charuco.npz"
CONF = 0.5
IMG_SIZE = 960
REFINAR_SAM = True
REFINAR_SAM_VIDEO = False
MAX_ERROR_EPIPOLAR = 5.0  # px; filtro geométrico, no garantía de correspondencia
RECORTES_VIDEO = False  # en detección continua, no repetir YOLO en 4 recortes por lado (muy costoso)
VISTA_VIDEO = (640, 360)  # tamaño de las vistas devueltas en video (el lienzo las dibuja a 640x360)
CALIDAD_VISTA_VIDEO = 70
LOCK_ANALISIS = threading.Lock()  # el servidor atiende con hilos: un análisis a la vez sobre el modelo
modelo = None
segmentador = None
cal = None
dispositivo = "cpu"


def normalizar(valor):
    if not isinstance(valor, str) or not valor.startswith(("data:image/png;base64,", "data:image/jpeg;base64,")):
        raise ValueError("Se esperaba una imagen PNG o JPEG de VDO.Ninja")
    raw = base64.b64decode(valor.split(",", 1)[1], validate=True)
    im = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if im is None:
        raise ValueError("Imagen ilegible")
    h, w = im.shape[:2]
    origen = f"{w}x{h}"
    if h > w:
        im = cv2.rotate(im, cv2.ROTATE_90_CLOCKWISE)
        h, w = im.shape[:2]
    if abs((w / h) / (1280 / 720) - 1) > 0.01:
        raise ValueError("Se necesita proporción 16:9 o 9:16, igual que al calibrar")
    modo = cv2.INTER_AREA if w > 1280 else cv2.INTER_LINEAR
    return cv2.resize(im, (1280, 720), interpolation=modo), origen


def triangulacion(p, q, c):
    """Puntos originales de imagen -> XYZ en mm, marco de cámara izquierda."""
    p = np.asarray(p, np.float64).reshape(1, 1, 2)
    q = np.asarray(q, np.float64).reshape(1, 1, 2)
    a = cv2.undistortPoints(p, c["K1"], c["d1"], P=c["K1"]).reshape(2)
    b = cv2.undistortPoints(q, c["K2"], c["d2"], P=c["K2"]).reshape(2)
    x1, x2 = np.r_[a, 1.], np.r_[b, 1.]
    line2, line1 = c["F"] @ x1, c["F"].T @ x2
    den1, den2 = np.linalg.norm(line1[:2]), np.linalg.norm(line2[:2])
    if min(den1, den2) < 1e-12:
        raise ValueError("Geometría epipolar degenerada")
    error = float(abs(x2 @ c["F"] @ x1) * (1 / den1 + 1 / den2) / 2)
    if error > MAX_ERROR_EPIPOLAR:
        raise ValueError(f"Centros incompatibles: error epipolar {error:.1f} px. No se publica distancia.")
    ray1 = np.linalg.solve(c["K1"], x1)
    ray2 = c["R"].T @ np.linalg.solve(c["K2"], x2)
    angulo = np.degrees(np.arccos(np.clip(np.dot(ray1, ray2) / (np.linalg.norm(ray1)*np.linalg.norm(ray2)), -1, 1)))
    if angulo < 0.2:
        raise ValueError("Rayos casi paralelos; distancia demasiado inestable")
    h = cv2.triangulatePoints(c["P1"], c["P2"], a.reshape(2,1), b.reshape(2,1)).ravel()
    if abs(h[3]) < 1e-12:
        raise ValueError("Punto en el infinito")
    xyz = h[:3] / h[3]
    derecha = c["R"] @ xyz + c["T"].ravel()
    if not np.isfinite(xyz).all() or xyz[2] <= 0 or derecha[2] <= 0:
        raise ValueError("Triangulación detrás de una cámara o no válida")
    return xyz, error


def pintar_mascaras(imagen, masks):
    vista = imagen.copy()
    total = 0
    for mask in masks:
        if mask.shape != imagen.shape[:2]:
            mask = cv2.resize(mask, (imagen.shape[1], imagen.shape[0]), interpolation=cv2.INTER_NEAREST)
        seleccion = mask > 0.5
        if not seleccion.any():
            continue
        total += 1
        color = np.array([40, 220, 70], dtype=np.float32)
        vista[seleccion] = (vista[seleccion].astype(np.float32)*0.65 + color*0.35).astype(np.uint8)
        contornos, _ = cv2.findContours(seleccion.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(vista, contornos, -1, (0,255,0), 2)
    return vista, total


def segmentar_imagen(imagen, boxes, punto=None):
    """YOLO propone cajas; MobileSAM produce máscaras en coordenadas originales."""
    global segmentador
    vista = imagen.copy()
    if not boxes and punto is None:
        return vista, 0
    if segmentador is None:
        from ultralytics import SAM
        segmentador = SAM(str(BASE / 'mobile_sam.pt'))
    prompts = {"points": [punto], "labels": [1]} if punto is not None else {"bboxes": [b[0] for b in boxes]}
    resultados = segmentador.predict(imagen, **prompts, device=dispositivo, verbose=False, save=False)
    total = 0
    for r in resultados:
        if r.masks is None:
            continue
        for mask in r.masks.data.cpu().numpy():
            if mask.shape != imagen.shape[:2]:
                mask = cv2.resize(mask, (imagen.shape[1], imagen.shape[0]), interpolation=cv2.INTER_NEAREST)
            seleccion = mask > 0.5
            if not seleccion.any():
                continue
            total += 1
            color = np.array([40, 220, 70], dtype=np.float32)
            vista[seleccion] = (vista[seleccion].astype(np.float32)*0.65 + color*0.35).astype(np.uint8)
            contornos, _ = cv2.findContours(seleccion.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(vista, contornos, -1, (0, 255, 0), 2)
    return vista, total


def buscar_en_recortes(imagen, resultado):
    """Fallback para objetos pequeños. Devuelve coordenadas de imagen completa."""
    from filtro_video import filtrar_rojos
    resultado = filtrar_rojos(imagen, resultado)
    if resultado.boxes is not None and len(resultado.boxes):
        return resultado
    from ultralytics.engine.results import Results
    import torch
    h,w=imagen.shape[:2];cw,ch=round(w*0.65),round(h*0.65)
    coordenadas=[(0,0),(w-cw,0),(0,h-ch),(w-cw,h-ch)]
    crops=[imagen[y:y+ch,x:x+cw] for x,y in coordenadas]
    pred=modelo.predict(crops,conf=CONF,imgsz=IMG_SIZE,device=dispositivo,
                        verbose=False,retina_masks=True,save=False)
    boxes=[];masks=[]
    for (x,y),r in zip(coordenadas,pred):
        r = filtrar_rojos(imagen[y:y+ch,x:x+cw], r)
        if r.boxes is None:continue
        for i,b in enumerate(r.boxes.data.cpu().numpy()):
            b=b.copy();b[[0,2]]+=x;b[[1,3]]+=y;boxes.append(b)
            if modelo.task=='segment':
                mask=np.zeros((h,w),np.float32)
                if r.masks is not None:
                    local=r.masks.data[i].cpu().numpy()
                    if local.shape!=(ch,cw):local=cv2.resize(local,(cw,ch),interpolation=cv2.INTER_NEAREST)
                    mask[y:y+ch,x:x+cw]=local
                masks.append(mask)
    if not boxes:return resultado
    b=np.asarray(boxes)
    rects=np.column_stack([b[:,0],b[:,1],b[:,2]-b[:,0],b[:,3]-b[:,1]])
    keep=np.asarray(cv2.dnn.NMSBoxes(rects.tolist(),b[:,4].tolist(),CONF,0.5)).reshape(-1).astype(int)
    if not len(keep):return resultado
    return Results(imagen,path='recortes',names=resultado.names,boxes=torch.from_numpy(b[keep]),
                   masks=torch.from_numpy(np.stack(masks)[keep]) if masks else None)


def analizar(datos):
    inicio = time.perf_counter()
    entradas = [normalizar(datos[lado]) for lado in ("izq", "der")]
    tiempo_yolo = time.perf_counter()
    resultados = modelo.predict([cv2.rotate(x[0], cv2.ROTATE_90_COUNTERCLOCKWISE) for x in entradas], conf=CONF, imgsz=IMG_SIZE,
                                device=dispositivo, quantize=16 if dispositivo != 'cpu' else 32, verbose=False, save=False, retina_masks=True)
    tiempo_yolo = (time.perf_counter()-tiempo_yolo)*1000
    dispositivo_real = str(resultados[0].boxes.data.device) if resultados[0].boxes is not None else str(next(modelo.model.parameters()).device)
    imagenes, cajas, mascaras = [], [], []
    resultados_datos = []
    vistas, masks_estereo = [], []
    refinar = REFINAR_SAM and (not datos.get("video") or REFINAR_SAM_VIDEO)
    for entrada, resultado in zip(entradas, resultados):
        natural = cv2.rotate(entrada[0], cv2.ROTATE_90_COUNTERCLOCKWISE)
        if datos.get("video") and not RECORTES_VIDEO:
            from filtro_video import filtrar_rojos
            resultado = filtrar_rojos(natural, resultado)
        else:
            resultado = buscar_en_recortes(natural, resultado)
        if datos.get("video"):
            from filtro_video import confirmar_video
            sesion_video = str(datos.get("sesion_video", "default"))[:100]
            resultado = confirmar_video(resultado, "izq" if len(cajas)==0 else "der", sesion_video)
        resultados_datos.append(resultado)
        boxes = resultado.boxes
        detecciones = [] if boxes is None else [
            ([1280-float(xy[3]), float(xy[0]), 1280-float(xy[1]), float(xy[2])], int(cl), float(cf)) for xy, cl, cf in zip(
                boxes.xyxy.cpu().numpy(), boxes.cls.cpu().numpy(), boxes.conf.cpu().numpy())]
        cajas.append(detecciones)
        if modelo.task == "segment" and not refinar:
            masks = [] if resultado.masks is None else [
                cv2.rotate(mask, cv2.ROTATE_90_CLOCKWISE) for mask in resultado.masks.data.cpu().numpy()]
            vista, cantidad = pintar_mascaras(entrada[0], masks)
        else:
            vista, cantidad = segmentar_imagen(entrada[0], detecciones)
        masks_estereo.append(masks if modelo.task == "segment" and not refinar else [])
        mascaras.append(cantidad)
        # Mostrar contornos, no cajas. La clasificación sigue siendo de YOLO.
        for xy, clase, confianza in detecciones:
            x, y = int(xy[0]), max(20, int(xy[1])-5)
            cv2.putText(vista, f"{modelo.names[clase]} {confianza:.2f}", (x,y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 2)
        vistas.append(vista)
    from distancia_video import estimar
    tiempo_estereo = time.perf_counter()
    medidas = estimar([x[0] for x in entradas], masks_estereo, triangulacion, cal) if datos.get('video') else []
    tiempo_estereo = (time.perf_counter()-tiempo_estereo)*1000
    for numero, medida in enumerate(medidas, 1):
        for vista, punto in zip(vistas, medida['puntos']):
            p = tuple(np.round(punto).astype(int))
            cv2.drawMarker(vista, p, (255,255,0), cv2.MARKER_CROSS, 16, 2)
            cv2.putText(vista, str(numero), (p[0]+8,p[1]-8), cv2.FONT_HERSHEY_SIMPLEX,.6,(255,255,0),2)
    for vista in vistas:
        calidad = 85
        if datos.get('video'):
            vista = cv2.resize(vista, VISTA_VIDEO, interpolation=cv2.INTER_AREA)
            calidad = CALIDAD_VISTA_VIDEO
        ok, jpg = cv2.imencode(".jpg", vista, [cv2.IMWRITE_JPEG_QUALITY, calidad])
        if not ok:
            raise ValueError("No se pudo preparar la vista")
        imagenes.append("data:image/jpeg;base64," + base64.b64encode(jpg).decode())
    mensaje = (f"YOLO: izquierda {len(cajas[0])}, derecha {len(cajas[1])}. "
               f"Máscaras {'YOLO-seg' if modelo.task == 'segment' and not refinar else 'MobileSAM refinado'}: izquierda {mascaras[0]}, derecha {mascaras[1]}. ")
    if min(mascaras) == 0:
        mensaje += "En video, un candidato nuevo requiere dos observaciones. Si YOLO no detecta, marcá un punto DENTRO del locote en cada imagen y usá Segmentar puntos marcados. "
    mensaje += ("Distancia: seleccioná el mismo punto de la cruz en ambas imágenes. "
                "Los centros de las máscaras no son correspondencias estéreo fiables. "
                f"Origen: izq {entradas[0][1]}, der {entradas[1][1]}. Proceso {time.perf_counter()-inicio:.2f} s.")
    if datos.get('video'):
        mensaje += (' Distancia estimada a superficie próxima al centro: '+ '; '.join(f"P{i}: {m['distancia_cm']:.1f} cm" for i,m in enumerate(medidas,1))
                    if medidas else ' Sin distancia automática: falta correspondencia de textura consistente.')
        mensaje += f' Dispositivo real YOLO: {dispositivo_real}. YOLO {tiempo_yolo:.0f} ms; correspondencias {tiempo_estereo:.0f} ms. Distancias {len(medidas)}; detecciones {len(cajas[0])}/{len(cajas[1])}.'
    from datos_carrito import guardar_muestra
    guardado = guardar_muestra(datos, entradas, resultados_datos)
    if guardado:
        mensaje += ' ' + guardado
    originales = None
    if not datos.get('video'):
        originales = []
        for im, _ in entradas:
            ok, png = cv2.imencode(".png", im)
            if not ok:raise ValueError("No se pudo preparar el original")
            originales.append("data:image/png;base64," + base64.b64encode(png).decode())
    return {"mensaje": mensaje, "imagenes": imagenes, "originales": originales, "medida": None, "medidas_video": medidas,
            "objetos_video": [[[float((d[0][0]+d[0][2])/2),float((d[0][1]+d[0][3])/2)] for d in lado] for lado in cajas],
            "dispositivo": dispositivo_real, "yolo_ms": round(tiempo_yolo,1), "estereo_ms": round(tiempo_estereo,1),
            "proceso_ms": round((time.perf_counter()-inicio)*1000,1)}



class Handler(captura.Handler):
    def do_GET(self):
        if directas.manejar_get(self):
            return
        if self.path.split("?")[0] != "/":
            self.responder(404, "{}")
            return
        if not directas.clave_valida(self):
            self.responder(403, "Falta la clave de acceso (?clave=...) o no es correcta.", "text/plain")
            return
        from configurar_video import panel
        from interfaz_vision import pagina
        self.responder(200, directas.inyectar_visor(pagina(captura.TOKEN), panel_vdo=panel()), "text/html")

    def do_POST(self):
        if directas.manejar_post(self):
            return
        if self.path not in ("/analizar", "/triangular-manual", "/segmentar-manual") or self.headers.get("X-Capture-Token") != captura.TOKEN:
            self.responder(403, '{}')
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if not 0 < n <= captura.LIMIT:
                raise ValueError("Solicitud demasiado grande o vacía")
            datos = json.loads(self.rfile.read(n))
            if self.path == "/analizar":
                datos = directas.resolver_directo(datos)
            with LOCK_ANALISIS:
                resultado = self._procesar(datos)
            if resultado is not None:
                self.responder(200, json.dumps(resultado, allow_nan=False))
        except Exception as exc:
            self.responder(400, json.dumps({"error": str(exc)}))

    def _procesar(self, datos):
        if self.path in ("/triangular-manual", "/segmentar-manual"):
            puntos = np.asarray([datos["izq"], datos["der"]], dtype=np.float64)
            if puntos.shape != (2, 2) or not np.isfinite(puntos).all():
                raise ValueError("Se necesitan dos puntos 2D válidos")
            if np.any(puntos < 0) or np.any(puntos[:,0] >= 1280) or np.any(puntos[:,1] >= 720):
                raise ValueError("Punto fuera de la imagen calibrada")
            if self.path == "/segmentar-manual":
                imagenes, cantidades = [], []
                for i, lado in enumerate(("izq", "der")):
                    im, _ = normalizar(datos["originales"][i])
                    vista, cantidad = segmentar_imagen(im, [], puntos[i].tolist())
                    ok, jpg = cv2.imencode(".jpg", vista, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    if not ok:
                        raise ValueError("No se pudo codificar la máscara")
                    imagenes.append("data:image/jpeg;base64," + base64.b64encode(jpg).decode())
                    cantidades.append(cantidad)
                return {"imagenes": imagenes, "mensaje": f"SAM guiado por puntos: máscaras izquierda {cantidades[0]}, derecha {cantidades[1]}. Revisá el contorno; no es una detección automática de locote. Para medir, volvé a seleccionar el mismo centro de la cruz."}
            xyz, error = triangulacion(puntos[0], puntos[1], cal)
            resultado = {"mensaje": f"PUNTO MANUAL: distancia desde cámara izquierda {np.linalg.norm(xyz)/10:.2f} cm; profundidad Z {xyz[2]/10:.2f} cm; error epipolar {error:.2f} px. Compará la cinta desde la lente hasta el centro de la cruz."}
        else:
            resultado = analizar(datos)
            if "_desfase_ms" in datos:
                resultado["desfase_ms"] = datos["_desfase_ms"]
                resultado["mensaje"] += f" Celulares directos: desfase entre fotos {datos['_desfase_ms']} ms."
        return resultado


def main(modelo_ruta=None):
    global modelo, segmentador, cal, dispositivo
    import torch
    cv2.setNumThreads(2)
    torch.set_num_threads(2)
    try:
        from ultralytics import YOLO, SAM
    except ImportError:
        raise SystemExit("Falta Ultralytics en el intérprete seleccionado. Usá .venv-cuda.")
    pesos_yolo = Path(modelo_ruta) if modelo_ruta else MODELO
    if not pesos_yolo.is_file() or not CALIBRACION.is_file():
        raise SystemExit("Falta best_2k.pt o calibracion_charuco.npz junto al script")
    with np.load(CALIBRACION, allow_pickle=False) as datos:
        cal = {k: datos[k] for k in datos.files}
    for key in ("size_l", "size_r"):
        if tuple(cal[key]) != (1280, 720):
            raise SystemExit("La calibración debe corresponder a 1280x720")
    dispositivo = 0 if torch.cuda.is_available() else "cpu"
    modelo = YOLO(str(pesos_yolo))
    pesos_sam = BASE / "mobile_sam.pt"
    if not pesos_sam.is_file():
        raise SystemExit("Falta mobile_sam.pt junto al script")
    print("MobileSAM se cargará solo si se solicita una captura manual refinada.")
    modelo.to('cuda:0' if dispositivo == 0 else 'cpu')
    print(f"Entrada YOLO: {IMG_SIZE}; confianza mínima: {CONF}; búsqueda por recortes si no detecta.")
    print("Video: filtro ROJO, duplicados por máscaras y dos observaciones. YOLO-seg usa sus máscaras en video; MobileSAM refina capturas manuales.")
    print("Calibración activa:", CALIBRACION)
    print("Modelo:", pesos_yolo, "Clases:", modelo.names, "Dispositivo:", dispositivo)
    modelo.predict(np.zeros((720,1280,3), np.uint8), device=dispositivo, verbose=False)
    with directas.servir(Handler, 8766, titulo="la aplicación") as servidor:
        try:
            servidor.serve_forever()
        except KeyboardInterrupt:
            print("Finalizado.")


if __name__ == "__main__":
    main()
