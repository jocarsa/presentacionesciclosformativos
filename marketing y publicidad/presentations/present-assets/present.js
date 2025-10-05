(function(){
  const deck = document.getElementById('deck');
  if(!deck) return;
  const slides = Array.from(deck.querySelectorAll('.slide'));
  let idx = 0;

  /* Ensure PROGRESS exists & is OUTSIDE the footer */
  let progress = document.querySelector('.progress');
  const footer = document.querySelector('.footer');

  if(!progress){
    progress = document.createElement('div');
    progress.className = 'progress';
    const bar = document.createElement('div');
    bar.className = 'bar'; bar.id = 'progressBar';
    progress.appendChild(bar);
    (footer ? document.body.insertBefore(progress, footer) : document.body.appendChild(progress));
  }else{
    if(footer && progress.parentElement === footer){
      document.body.insertBefore(progress, footer);
    }
    if(!progress.querySelector('#progressBar')){
      const bar = document.createElement('div');
      bar.className = 'bar'; bar.id = 'progressBar';
      progress.appendChild(bar);
    }
  }
  const bar = document.getElementById('progressBar');

  function updateProgress(){
    if(!bar||slides.length===0) return;
    const pct = Math.round(((idx+1)/slides.length)*100);
    bar.style.width = pct+'%';
  }

  /* === ZOOM (reflow): cambia font-size raíz mediante --fs === */
  const BASE_FS = 16;                 // px
  const ZMIN=0.5, ZMAX=2.0, ZSTEP=0.1;
  let zoom = 1.0;

  const zoomPctEl = document.getElementById('zoomPct');
  const btnIn = document.getElementById('zoomIn');
  const btnOut = document.getElementById('zoomOut');
  const btnReset = document.getElementById('zoomReset');

  function clamp(n,a,b){return Math.min(b,Math.max(a,n));}
  function applyZoom(){
    const px = Math.max(10, Math.round(BASE_FS * zoom));
    document.documentElement.style.setProperty('--fs', px + 'px'); // reflow!
    if(zoomPctEl) zoomPctEl.textContent = Math.round(zoom*100)+'%';
  }
  function setZoomValue(z){ zoom = clamp(+z.toFixed(2), ZMIN, ZMAX); applyZoom(); }
  function zoomIn(){ setZoomValue(zoom+ZSTEP); }
  function zoomOut(){ setZoomValue(zoom-ZSTEP); }
  function zoomReset(){ setZoomValue(1.0); }

  if(btnIn) btnIn.addEventListener('click', zoomIn);
  if(btnOut) btnOut.addEventListener('click', zoomOut);
  if(btnReset) btnReset.addEventListener('click', zoomReset);

  /* === NAVIGATION === */
  function show(i){
    if(slides.length===0) return;
    idx=(i+slides.length)%slides.length;
    slides.forEach((s,k)=>s.classList.toggle('active',k===idx));
    const id=slides[idx].getAttribute('data-id')||String(idx+1);
    history.replaceState(null,'','#'+encodeURIComponent(id));
    deck.focus({preventScroll:true});
    updateProgress();
  }
  const initialHash=decodeURIComponent((location.hash||'').replace(/^#/,''));
  const initialIndex=slides.findIndex(s=>(s.getAttribute('data-id')||'')===initialHash);
  show(initialIndex>=0?initialIndex:0);
  applyZoom(); // set initial --fs

  function next(){ show(idx+1); } function prev(){ show(idx-1); }
  window.addEventListener('keydown', (e)=>{
    if(e.key==='ArrowRight'||e.key==='PageDown'||e.key===' '){ e.preventDefault(); next(); }
    if(e.key==='ArrowLeft'||e.key==='PageUp'||e.key==='Backspace'){ e.preventDefault(); prev(); }
    if(e.key==='Home'){ e.preventDefault(); show(0); }
    if(e.key==='End'){ e.preventDefault(); show(slides.length-1); }
    if(e.key==='+'||e.key==='='){ e.preventDefault(); zoomIn(); }
    if(e.key==='-'){ e.preventDefault(); zoomOut(); }
    if(e.key==='0'){ e.preventDefault(); zoomReset(); }
    if(e.key.toLowerCase()==='f'){ e.preventDefault(); toggleFullscreen(); }
  });

  deck.addEventListener('click',(e)=>{
    const rect=deck.getBoundingClientRect();
    const x=e.clientX-rect.left;
    if(x>rect.width/2) next(); else prev();
  },false);
  let sx=null; deck.addEventListener('touchstart', e=>{ sx=e.touches[0].clientX; }, {passive:true});
  deck.addEventListener('touchend', e=>{ if(sx==null) return; const dx=(e.changedTouches[0].clientX - sx); if(Math.abs(dx)>40){ if(dx<0) next(); else prev(); } sx=null; }, {passive:true});

  /* === FULLSCREEN: inyecta botón si falta, y alterna clase para CSS === */
  const controls = footer ? footer.querySelector('.controls') : null;
  let fsBtn = document.getElementById('fsToggle');
  if(!fsBtn && controls){
    fsBtn = document.createElement('button');
    fsBtn.id = 'fsToggle';
    fsBtn.title = 'Pantalla completa (tecla F)';
    fsBtn.textContent = '⛶';
    controls.appendChild(fsBtn);
  }
  function isFs(){ return document.fullscreenElement || document.webkitFullscreenElement || document.mozFullScreenElement || document.msFullscreenElement; }
  function reqFs(el){ if(el.requestFullscreen) return el.requestFullscreen(); if(el.webkitRequestFullscreen) return el.webkitRequestFullscreen(); if(el.mozRequestFullScreen) return el.mozRequestFullScreen(); if(el.msRequestFullscreen) return el.msRequestFullscreen(); }
  function exitFs(){ if(document.exitFullscreen) return document.exitFullscreen(); if(document.webkitExitFullscreen) return document.webkitExitFullscreen(); if(document.mozCancelFullScreen) return document.mozCancelFullScreen(); if(document.msExitFullscreen) return document.msExitFullscreen(); }
  function toggleFullscreen(){ if(isFs()) exitFs(); else reqFs(document.documentElement); }
  function onFsChange(){
    const fs = !!isFs();
    document.body.classList.toggle('is-fullscreen', fs);
    if(fsBtn) fsBtn.textContent = fs ? '⤢' : '⛶';
  }
  if(fsBtn) fsBtn.addEventListener('click', toggleFullscreen);
  document.addEventListener('fullscreenchange', onFsChange);
  document.addEventListener('webkitfullscreenchange', onFsChange);
  document.addEventListener('mozfullscreenchange', onFsChange);
  document.addEventListener('MSFullscreenChange', onFsChange);
})();