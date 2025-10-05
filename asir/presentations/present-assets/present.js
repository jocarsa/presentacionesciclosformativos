(function(){
  const deck = document.getElementById('deck');
  if(!deck) return;
  const slides = Array.from(deck.querySelectorAll('.slide'));
  let idx = 0;
  const bar = document.getElementById('progressBar');
  function updateProgress(){ if(!bar||slides.length===0) return; const pct = Math.round(((idx+1)/slides.length)*100); bar.style.width = pct+'%'; }
  const supportsZoom = ('zoom' in document.documentElement.style) || (typeof CSS!=='undefined' && CSS.supports && CSS.supports('zoom','1'));
  const ZMIN=0.5, ZMAX=2.0, ZSTEP=0.1; let zoom=1.0;
  const zoomPctEl=document.getElementById('zoomPct'), btnIn=document.getElementById('zoomIn'), btnOut=document.getElementById('zoomOut'), btnReset=document.getElementById('zoomReset');
  function clamp(n,a,b){return Math.min(b,Math.max(a,n));}
  function setZoomValue(z){
    zoom = clamp(+z.toFixed(2), ZMIN, ZMAX);
    if(supportsZoom){ document.documentElement.style.zoom=String(zoom); document.body.style.zoom=''; document.documentElement.classList.remove('zoom-fb'); }
    else{ document.documentElement.style.zoom=''; document.documentElement.classList.add('zoom-fb'); document.documentElement.style.setProperty('--zf', String(zoom)); }
    if(zoomPctEl) zoomPctEl.textContent = Math.round(zoom*100)+'%';
  }
  function zoomIn(){ setZoomValue(zoom+ZSTEP); } function zoomOut(){ setZoomValue(zoom-ZSTEP); } function zoomReset(){ setZoomValue(1.0); }
  if(btnIn) btnIn.addEventListener('click', zoomIn); if(btnOut) btnOut.addEventListener('click', zoomOut); if(btnReset) btnReset.addEventListener('click', zoomReset);
  function show(i){ if(slides.length===0) return; idx=(i+slides.length)%slides.length; slides.forEach((s,k)=>s.classList.toggle('active',k===idx)); const id=slides[idx].getAttribute('data-id')||String(idx+1); history.replaceState(null,'','#'+encodeURIComponent(id)); deck.focus({preventScroll:true}); updateProgress(); }
  const initialHash=decodeURIComponent((location.hash||'').replace(/^#/,''));
  const initialIndex=slides.findIndex(s=>(s.getAttribute('data-id')||'')===initialHash);
  show(initialIndex>=0?initialIndex:0);
  setZoomValue(1.0);
  function next(){ show(idx+1); } function prev(){ show(idx-1); }
  window.addEventListener('keydown', (e)=>{ if(e.key==='ArrowRight'||e.key==='PageDown'||e.key===' '){e.preventDefault();next();} if(e.key==='ArrowLeft'||e.key==='PageUp'||e.key==='Backspace'){e.preventDefault();prev();} if(e.key==='Home'){e.preventDefault();show(0);} if(e.key==='End'){e.preventDefault();show(slides.length-1);} if(e.key==='+'||e.key==='='){e.preventDefault();zoomIn();} if(e.key==='-'){e.preventDefault();zoomOut();} if(e.key==='0'){e.preventDefault();zoomReset();} });
  deck.addEventListener('click',(e)=>{ const rect=deck.getBoundingClientRect(); const x=e.clientX-rect.left; if(x>rect.width/2) next(); else prev(); },false);
  let sx=null; deck.addEventListener('touchstart', e=>{ sx=e.touches[0].clientX; }, {passive:true});
  deck.addEventListener('touchend', e=>{ if(sx==null) return; const dx=(e.changedTouches[0].clientX - sx); if(Math.abs(dx)>40){ if(dx<0) next(); else prev(); } sx=null; }, {passive:true});
})();