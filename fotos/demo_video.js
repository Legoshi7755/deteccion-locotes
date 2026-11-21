let ultimoTiempoCaptura=0,ultimoTiempoSolicitud=0,ultimoTiempoServidor=0;
// En detección continua se envían fotogramas reducidos (lado mayor 960 px, 16:9) para subir menos datos.
// El servidor los vuelve a llevar a 1280x720, el tamaño de la calibración.
const LADO_MAYOR_VIDEO=960, CALIDAD_VIDEO=0.75;
async function comprimirVideo(data){
 if(data==='directo')return data;  // modo directo: el servidor ya tiene las fotos de los celulares
 const img=await new Promise((resolve,reject)=>{const i=new Image();i.onload=()=>resolve(i);i.onerror=()=>reject(new Error('No se pudo preparar el fotograma'));i.src=data;});
 const escala=Math.min(1,LADO_MAYOR_VIDEO/Math.max(img.naturalWidth,img.naturalHeight));
 const c=document.createElement('canvas');c.width=Math.round(img.naturalWidth*escala);c.height=Math.round(img.naturalHeight*escala);
 c.getContext('2d').drawImage(img,0,0,c.width,c.height);return c.toDataURL('image/jpeg',CALIDAD_VIDEO);
}

// Un solo análisis pendiente; el video registra las vistas procesadas, sin audio.
let demoSesion='';
let demoMedidas=[];
let demoDispositivo='pendiente',demoYoloMs=0,demoEstereoMs=0;
let demoObjetos=[[],[]];
let demoActivo=false, demoPendiente=false, demoVersion=0, demoGrabador=null;
let demoUltimo=0,demoAnterior=0,demoFPS=0,demoTrozos=[],demoURL=null,demoInicio=0,demoStopTimer=null;
const demoCanvas=document.getElementById('demoCanvas'),demoCtx=demoCanvas.getContext('2d');
const iniciarVideo=document.getElementById('iniciarVideo'),pararVideo=document.getElementById('pararVideo');
const grabarVideo=document.getElementById('grabarVideo'),detenerGrabacion=document.getElementById('detenerGrabacion');
const estadoVideo=document.getElementById('estadoVideo'),descargarVideo=document.getElementById('descargarVideo');
const analizarUnPar=boton.onclick;
function dibujarDemo(){
 demoCtx.fillStyle='#111b26';demoCtx.fillRect(0,0,1280,800);
 demoCtx.fillStyle='white';demoCtx.font='bold 26px sans-serif';demoCtx.fillText('Watsocote',24,34);
 demoCtx.font='18px sans-serif';demoCtx.fillText('Izquierda',250,70);demoCtx.fillText('Derecha',900,70);
 ['izq','der'].forEach((lado,i)=>{
  const im=fondosManual[lado];if(!im)return;
  demoCtx.save();demoCtx.translate(i*640+320,410);demoCtx.rotate(-Math.PI/2);
  demoCtx.drawImage(im,-320,-180,640,360);demoCtx.restore();
  if(demoUltimo&&(performance.now()-demoUltimo)<=1500){
   demoMedidas.forEach((medida,n)=>{
    const p=medida.puntos[i];if(!p)return;
    const texto=`P${n+1}: ~${medida.distancia_cm.toFixed(1)} cm`;
    demoCtx.font='bold 18px sans-serif';const ancho=demoCtx.measureText(texto).width+12;
    const x=Math.max(i*640+8,Math.min((i+1)*640-ancho-8,i*640+320+(p[1]-360)*.5+12));
    const y=Math.max(100,Math.min(715,410-(p[0]-640)*.5-12));
    demoCtx.fillStyle='rgba(0,0,0,.8)';demoCtx.fillRect(x,y-21,ancho,28);
    demoCtx.fillStyle='#73ffff';demoCtx.fillText(texto,x+6,y);
   });
  }
 });
 const edad=demoUltimo?(performance.now()-demoUltimo)/1000:0;
 demoCtx.fillStyle='white';demoCtx.font='18px sans-serif';
 demoCtx.fillText(demoActivo?(edad>1.5?'Esperando actualización':'Detección y segmentación'):'Detección pausada',24,753);
 const medidasActuales=edad<=1.5?demoMedidas:[];
 const distancias=medidasActuales.map((m,i)=>`P${i+1}: ~${m.distancia_cm.toFixed(1)} cm`).join(' | ');
 demoCtx.font='16px sans-serif';
 demoCtx.fillText(distancias?`${distancias} · Distancia estimada a superficie`:'Distancias estimadas · Cámaras sin sincronización',24,782);
 if(demoGrabador&&demoGrabador.state==='recording'){
  demoCtx.fillStyle='#ff5252';demoCtx.fillText(`REC ${((performance.now()-demoInicio)/1000).toFixed(0)} s`,1100,35);
 }
}
// Detección continua solapada: mientras un par viaja al servidor se captura el siguiente.
// Como máximo VIDEO_EN_VUELO pares a la vez; un resultado más viejo que el último mostrado se descarta.
const VIDEO_EN_VUELO=3;
let videoEnVuelo=0;
const esperar=ms=>new Promise(r=>setTimeout(r,ms));
async function capturarParVideo(){
 const inicio=performance.now();
 let [izq,der]=await Promise.all([foto('izq'),foto('der')]);
 [izq,der]=await Promise.all([comprimirVideo(izq),comprimirVideo(der)]);
 return {izq,der,captura:performance.now()-inicio};
}
async function enviarParVideo(par){
 const inicio=performance.now();
 const r=await fetch('/analizar',{method:'POST',headers:{'Content-Type':'application/json','X-Capture-Token':'__TOKEN__'},
  body:JSON.stringify({izq:par.izq,der:par.der,video:true,sesion_video:demoSesion,guardar_entrenamiento:!!document.getElementById('guardarDatos')?.checked})});
 const d=await r.json();if(!r.ok)throw new Error(d.error||('HTTP '+r.status));
 d._solicitud=performance.now()-inicio;return d;
}
async function cicloDemo(version){
 let numero=0,ultimoMostrado=0,fallo=null;
 const vigente=()=>demoActivo&&version===demoVersion&&!fallo;
 while(vigente()){
  if(videoEnVuelo>=VIDEO_EN_VUELO||boton.disabled){await esperar(10);continue;}
  videoEnVuelo++;demoPendiente=true;const n=++numero;
  let par;
  try{par=await capturarParVideo();}
  catch(e){videoEnVuelo--;fallo=e;break;}
  if(!vigente()){videoEnVuelo--;break;}
  enviarParVideo(par).then(async d=>{
   if(!vigente()||n<=ultimoMostrado)return;
   ultimoMostrado=n;
   ultimoTiempoCaptura=par.captura;ultimoTiempoSolicitud=d._solicitud;ultimoTiempoServidor=d.proceso_ms||0;
   estado.textContent=d.mensaje;
   demoMedidas=d.medidas_video||[];demoObjetos=d.objetos_video||[[],[]];demoDispositivo=d.dispositivo||'desconocido';
   demoYoloMs=d.yolo_ms||0;demoEstereoMs=d.estereo_ms||0;
   await mostrarResultados(d.imagenes,d.originales);
   const ahora=performance.now();demoFPS=demoAnterior?1000/(ahora-demoAnterior):0;demoAnterior=ahora;demoUltimo=ahora;
   estadoVideo.textContent=`${demoFPS.toFixed(1)} actualizaciones/s · ${demoDispositivo} · ${VIDEO_EN_VUELO} pares en paralelo\nCaptura ${Math.round(ultimoTiempoCaptura)} ms · solicitud ${Math.round(ultimoTiempoSolicitud)} ms · servidor ${Math.round(ultimoTiempoServidor)} ms\nYOLO ${Math.round(demoYoloMs)} ms · estéreo ${Math.round(demoEstereoMs)} ms`;
   grabarVideo.disabled=!!(demoGrabador&&demoGrabador.state!=='inactive');
  }).catch(e=>{if(!fallo)fallo=e;}).finally(()=>{videoEnVuelo--;});
 }
 // Esperar los pares que siguen en camino antes de liberar los botones.
 while(videoEnVuelo>0)await esperar(20);
 demoPendiente=false;
 if(fallo&&version===demoVersion){estadoVideo.textContent='Detección pausada: '+fallo.message;estado.textContent='Error: '+fallo.message;pausarDemo();}
}
function pausarDemo(){
 demoActivo=false;demoVersion++;iniciarVideo.disabled=demoPendiente;pararVideo.disabled=true;
 document.body.classList.remove('modo-video');
 ['izq','der'].forEach(dibujarManual);
 if(demoGrabador&&demoGrabador.state==='recording')demoGrabador.stop();
 if(!demoPendiente)iniciarVideo.disabled=false;
}
iniciarVideo.onclick=()=>{
 if(demoActivo||demoPendiente||boton.disabled)return;
 demoSesion=crypto.randomUUID();demoMedidas=[];demoObjetos=[[],[]];demoActivo=true;demoAnterior=0;iniciarVideo.disabled=true;pararVideo.disabled=false;
 document.body.classList.add('modo-video');
 demoCanvas.scrollIntoView({block:'center',behavior:'smooth'});
 estadoVideo.textContent='Conectando detección continua…';
 cicloDemo(++demoVersion).finally(()=>{if(!demoActivo){iniciarVideo.disabled=false;grabarVideo.disabled=true;}});
};
pararVideo.onclick=()=>{pausarDemo();estadoVideo.textContent='Detección pausada. Podés volver a iniciarla.';};
boton.onclick=async()=>{if(!demoActivo&&!demoPendiente)await analizarUnPar();};
if(segmentarPuntos){const antes=segmentarPuntos.onclick;segmentarPuntos.onclick=async()=>{if(demoActivo){estadoManual.textContent='Pausá la detección continua antes de seleccionar puntos.';return;}await antes();};}
grabarVideo.onclick=()=>{
 if(!demoActivo||!demoUltimo)return;
 if(typeof MediaRecorder==='undefined'||!demoCanvas.captureStream){estadoVideo.textContent='Este navegador no permite grabar el canvas. Usá Chrome o Edge.';return;}
 let stream;
 try{
  const tipos=['video/mp4;codecs=avc1.42E01E','video/webm;codecs=vp9','video/webm;codecs=vp8','video/webm'];
  const mime=tipos.find(t=>MediaRecorder.isTypeSupported(t));
  if(!mime)throw new Error('No hay un formato de grabación compatible');
  stream=demoCanvas.captureStream(30);demoTrozos=[];
  demoGrabador=new MediaRecorder(stream,{mimeType:mime,videoBitsPerSecond:4000000});
  demoGrabador.ondataavailable=e=>{if(e.data.size)demoTrozos.push(e.data);};
  demoGrabador.onstop=()=>{
   clearTimeout(demoStopTimer);stream.getTracks().forEach(t=>t.stop());
   const blob=new Blob(demoTrozos,{type:demoGrabador.mimeType});
   if(demoURL)URL.revokeObjectURL(demoURL);demoURL=URL.createObjectURL(blob);
   const extension=demoGrabador.mimeType.includes('mp4')?'mp4':'webm';
   descargarVideo.href=demoURL;descargarVideo.download='Watsocote_demo_'+new Date().toISOString().replace(/[:.]/g,'-')+'.'+extension;
   descargarVideo.textContent='Descargar video demo ('+extension.toUpperCase()+')';descargarVideo.hidden=false;
   descargarVideo.click();detenerGrabacion.disabled=true;grabarVideo.disabled=!demoActivo;
   estadoVideo.textContent='Grabación finalizada. Si no se descargó, usá el enlace Descargar video demo.';
  };
  demoGrabador.onerror=e=>{estadoVideo.textContent='Error de grabación: '+(e.error?.message||'revisá el navegador');if(demoGrabador.state!=='inactive')demoGrabador.stop();};
  demoInicio=performance.now();demoGrabador.start(1000);grabarVideo.disabled=true;detenerGrabacion.disabled=false;descargarVideo.hidden=true;
  demoStopTimer=setTimeout(()=>{if(demoGrabador.state==='recording')demoGrabador.stop();},180000);
 }catch(e){if(stream)stream.getTracks().forEach(t=>t.stop());estadoVideo.textContent='No se pudo grabar: '+e.message;}
};
detenerGrabacion.onclick=()=>{if(demoGrabador&&demoGrabador.state==='recording')demoGrabador.stop();};
let ultimoDibujo=0,ultimoResultadoDibujado=-1;
const demoTick=setInterval(()=>{
 const ahora=performance.now();
 if(demoGrabador?.state==='recording'||demoUltimo!==ultimoResultadoDibujado||ahora-ultimoDibujo>=1000){
  dibujarDemo();ultimoDibujo=ahora;ultimoResultadoDibujado=demoUltimo;
 }
},1000/30);
dibujarDemo();
window.addEventListener('beforeunload',e=>{if(demoGrabador&&demoGrabador.state==='recording'){e.preventDefault();e.returnValue='';}});
