const resumenVista=document.getElementById('resumenVista'),modoActual=document.getElementById('modoActual');
function modoPresentacion(modo){
 document.body.classList.toggle('modo-manual',modo==='manual');
 modoActual.textContent=modo==='video'?'Detección continua':modo==='manual'?'Captura segmentada':'En vivo';
 resumenVista.textContent=modo==='video'?'Detección y segmentación':modo==='manual'?'Captura segmentada':'Cámaras en vivo';
}
const iniciarPresentacion=iniciarVideo.onclick;
iniciarVideo.onclick=()=>{iniciarPresentacion();if(demoActivo)modoPresentacion('video');};
const pausarPresentacion=pararVideo.onclick;
pararVideo.onclick=()=>{pausarPresentacion();modoPresentacion('vivo');};
const segmentarPresentacion=boton.onclick;
boton.onclick=async()=>{
 if(demoActivo||demoPendiente)return;
 resumenVista.textContent='Procesando captura…';
 await segmentarPresentacion();
 if(!estado.textContent.startsWith('Error:'))modoPresentacion('manual');
 else resumenVista.textContent='No se pudo obtener la captura. Revisá Diagnóstico.';
};
document.getElementById('verVivo').onclick=()=>{
 if(demoGrabador?.state==='recording')demoGrabador.stop();
 if(demoActivo)pausarDemo();modoPresentacion('vivo');
};
new MutationObserver(()=>{
 if(estadoVideo.textContent.startsWith('Detección pausada:')){
  modoPresentacion('vivo');resumenVista.textContent='Detección interrumpida. Revisá Diagnóstico.';
 }
}).observe(estadoVideo,{childList:true,characterData:true,subtree:true});
