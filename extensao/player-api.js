// Roda no "mundo" da própria página (MAIN), onde fica a API do player.
// A extensão pede play/pause/seek por mensagem e este script chama o player direto — sem clicar na tela.
(() => {
  if (window.__sofahubApi) return;
  window.__sofahubApi = true;

  function jw() {
    try { const p = window.jwplayer && window.jwplayer(); return p && typeof p.play === 'function' ? p : null; } catch { return null; }
  }
  function video() {
    let best = null, area = 0;
    for (const v of document.querySelectorAll('video')) {
      const r = v.getBoundingClientRect(), a = r.width * r.height;
      if (a > area) { best = v; area = a; }
    }
    return best;
  }

  window.addEventListener('message', e => {
    const m = e.data;
    if (!m || m.__sofahub !== 'api' || e.source !== window) return;
    const p = jw(), v = video();
    try {
      if (m.acao === 'play') {
        if (p) p.play(true);
        else if (v) v.play().catch(() => {});
      } else if (m.acao === 'pause') {
        if (p) p.pause(true); else if (v) v.pause();
      }
    } catch {}
    window.postMessage({ __sofahub: 'api-ok', acao: m.acao, jw: !!p }, '*');
  });
})();
