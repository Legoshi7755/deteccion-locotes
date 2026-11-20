
const puntosManual={izq:null,der:null};
const fondosManual={izq:null,der:null};
let versionManual=0;
let generacionManual=0;
const estadoManual=document.getElementById('manualEstado');
function dibujarManual(lado){
 const canvas=document.getElementById(lado==='izq'?'resultadoIzq':'resultadoDer');
 const fondo=fondosManual[lado];if(!fondo)return;
 const ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,canvas.height);ctx.drawImage(fondo,0,0);
 const p=puntosManual[lado];if(!p)return;
 ctx.strokeStyle='#00ffff';ctx.lineWidth=2;ctx.beginPath();ctx.arc(p[0],p[1],10,0,Math.PI*2);ctx.moveTo(p[0]-16,p[1]);ctx.lineTo(p[0]+16,p[1]);ctx.moveTo(p[0],p[1]-16);ctx.lineTo(p[0],p[1]+16);ctx.stroke();
}
let originalesManual=null;
function mostrarResultados(imagenes,originales){
 if(originales!==undefined)originalesManual=originales;
 versionManual++;generacionManual++;puntosManual.izq=null;puntosManual.der=null;
 estadoManual.textContent='Hacé clic en el centro de la cruz en ambas imágenes de abajo.';
 return Promise.all(['izq','der'].map((lado,i)=>new Promise((resolve,reject)=>{
  fondosManual[lado]=null;
  const img=new Image();const version=generacionManual;
  img.onload=()=>{if(version!==generacionManual){resolve();return;}fondosManual[lado]=img;const c=document.getElementById(i===0?'resultadoIzq':'resultadoDer');c.width=img.naturalWidth;c.height=img.naturalHeight;if(typeof demoActivo==='undefined'||!demoActivo)dibujarManual(lado);resolve();};img.onerror=()=>reject(new Error('No se pudo cargar la vista procesada'));img.src=imagenes[i];
 })));
}
['izq','der'].forEach(lado=>{
 const canvas=document.getElementById(lado==='izq'?'resultadoIzq':'resultadoDer');
 canvas.addEventListener('click',async e=>{
  if(typeof demoActivo!=='undefined'&&demoActivo){estadoManual.textContent='Pausá la detección continua antes de marcar puntos.';return;}
  if(!fondosManual[lado]||boton.disabled)return;
  const r=canvas.getBoundingClientRect();
  puntosManual[lado]=[(e.clientX-r.left)*canvas.width/r.width,(e.clientY-r.top)*canvas.height/r.height];
  dibujarManual(lado);const version=++versionManual;
  if(!puntosManual.izq||!puntosManual.der){estadoManual.textContent='Punto marcado. Falta seleccionar la cruz en la otra imagen.';return;}
  estadoManual.textContent='Calculando distancia del punto marcado…';
  try{
   const res=await fetch('/triangular-manual',{method:'POST',headers:{'Content-Type':'application/json','X-Capture-Token':'__TOKEN__'},body:JSON.stringify(puntosManual)});
   const d=await res.json();if(version!==versionManual)return;if(!res.ok)throw new Error(d.error);estadoManual.textContent=d.mensaje;
  }catch(err){if(version===versionManual)estadoManual.textContent='Error: '+err.message;}
 });
});

const segmentarPuntos=document.getElementById('segmentarPuntos');
if(segmentarPuntos)segmentarPuntos.onclick=async()=>{
 if(!originalesManual||!puntosManual.izq||!puntosManual.der){estadoManual.textContent='Primero capturá y marcá un punto dentro del locote en cada imagen.';return;}
 segmentarPuntos.disabled=true;boton.disabled=true;versionManual++;
 estadoManual.textContent='Segmentando los puntos con SAM…';
 try{
 const r=await fetch('/segmentar-manual',{method:'POST',headers:{'Content-Type':'application/json','X-Capture-Token':'__TOKEN__'},body:JSON.stringify({...puntosManual,originales:originalesManual})});
 const d=await r.json();if(!r.ok)throw new Error(d.error);mostrarResultados(d.imagenes);estadoManual.textContent=d.mensaje;
 }catch(e){estadoManual.textContent='Error: '+e.message;}finally{segmentarPuntos.disabled=false;boton.disabled=false;}
};
