"""Enlaces de emisión solicitados; abrir cada uno en su celular respectivo."""
import json
from pathlib import Path
from urllib.parse import urlencode
import html

BASE=Path(__file__).resolve().parent

def enlaces():
    c=json.loads((BASE/'config_video.json').read_text(encoding='utf-8'))
    return {lado:'https://vdo.ninja/?'+urlencode({'push':sid,'width':c['ancho_emision_solicitado'],
        'height':c['alto_emision_solicitado'],'maxframerate':c['fps_solicitados'],
        'contenthint':'detail','zoom':c['zoom_solicitado'],'noaudio':''})
        for lado,sid in {'izq':'jsM66LZ','der':'pEHcrM3'}.items()}


def panel():
    urls=enlaces()
    c=json.loads((BASE/'config_video.json').read_text(encoding='utf-8'))
    return f'<details><summary>Configurar emisión desde los celulares</summary><p>Solicitado: {c["ancho_emision_solicitado"]} × {c["alto_emision_solicitado"]}, máximo {c["fps_solicitados"]} FPS y zoom {c["zoom_solicitado"]} (si la cámara lo admite). Abrí el enlace de cada lado EN ESE CELULAR y seleccioná la misma cámara trasera usada al calibrar. Cerrá su emisión anterior antes. Si cambia el encuadre, hay que recalibrar. La resolución recibida puede bajar por adaptación de WebRTC.</p>'+''.join(f'<p>{lado}: <a href="{html.escape(url,quote=True)}">{html.escape(url)}</a></p>' for lado,url in urls.items())+'</details>'


def preparar_receptor(html_text):
    c=json.loads((BASE/'config_video.json').read_text(encoding='utf-8'))
    return html_text.replace('__CONFIG_VIDEO__',panel()).replace('&bitrate=4000',f"&bitrate={int(c['bitrate_kbps'])}")

if __name__=='__main__':
    for lado,url in enlaces().items():print(lado,url)
