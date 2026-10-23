// Esconde o cursor do mouse (página e player). Roda cedo, antes da página desenhar.
(() => {
  if (window.__sofahubCursor) return;
  window.__sofahubCursor = true;

  function aplicar(esconder) {
    let st = document.getElementById('__sofahub_cursor');
    if (esconder && !st) {
      st = document.createElement('style');
      st.id = '__sofahub_cursor';
      st.textContent = '*,*::before,*::after{cursor:none!important}';
      (document.head || document.documentElement).appendChild(st);
    } else if (!esconder && st) st.remove();
  }

  chrome.storage.local.get('cursorOculto').then(r => aplicar(r.cursorOculto !== false)).catch(() => {});
  chrome.storage.onChanged.addListener((ch, area) => {
    if (area === 'local' && ch.cursorOculto) aplicar(ch.cursorOculto.newValue !== false);
  });
})();
