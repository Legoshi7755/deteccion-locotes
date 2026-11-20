"""Construcción de la página de visión, separada del receptor de calibración."""
import re
from pathlib import Path
from configurar_video import preparar_receptor

BASE=Path(__file__).resolve().parent


def pagina(token):
    base=(BASE/'captura_webrtc.html').read_text(encoding='utf-8')
    script=re.search(r'<script>(.*?)</script>',base,re.S).group(1)
    script=script.replace("fetch('/capturar'", "fetch('/analizar'")
    script=script.replace('JSON.stringify({izq,der})',"JSON.stringify({izq,der,video:typeof demoActivo!=='undefined'&&demoActivo,sesion_video:typeof demoSesion!=='undefined'?demoSesion:'',guardar_entrenamiento:!!document.getElementById('guardarDatos')?.checked})")
    script=script.replace("const [izq,der]=await Promise.all([foto('izq'),foto('der')]);", "const inicioCaptura=performance.now();let [izq,der]=await Promise.all([foto('izq'),foto('der')]);if(typeof demoActivo!=='undefined'&&demoActivo){[izq,der]=await Promise.all([comprimirVideo(izq),comprimirVideo(der)]);}ultimoTiempoCaptura=performance.now()-inicioCaptura;const inicioSolicitud=performance.now();")
    script=script.replace('const d=await r.json();if(!r.ok)', 'const d=await r.json();ultimoTiempoSolicitud=performance.now()-inicioSolicitud;ultimoTiempoServidor=d.proceso_ms||0;if(!r.ok)')
    script=script.replace('estado.textContent=d.mensaje;',"estado.textContent=d.mensaje;await mostrarResultados(d.imagenes,d.originales);demoMedidas=d.medidas_video||[];demoObjetos=d.objetos_video||[[],[]];demoDispositivo=d.dispositivo||'desconocido';demoYoloMs=d.yolo_ms||0;demoEstereoMs=d.estereo_ms||0;")
    script+='\n'+(BASE/'seleccion_puntos.js').read_text(encoding='utf-8')
    script+='\n'+(BASE/'demo_video.js').read_text(encoding='utf-8')
    script+='\n'+(BASE/'vision_presentacion.js').read_text(encoding='utf-8')
    html=preparar_receptor((BASE/'vision_demo.html').read_text(encoding='utf-8'))
    return html.replace('__SCRIPT_VISION__',script).replace('__TOKEN__',token)
