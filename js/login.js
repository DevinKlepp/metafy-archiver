// Best-effort login detection: 'in', 'out' or 'unknown'.
() => {
  const vis = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const txt = el => (el.innerText || el.getAttribute('aria-label') || '').trim().toLowerCase();
  const els = [...document.querySelectorAll('a[href], button, [role=button]')].filter(vis);
  if (els.some(e => /(^|\/)(logout|log-out|signout|sign-out)(\/|$|\?)/i.test(e.getAttribute('href') || ''))) return 'in';
  if (els.some(e => /^(log ?in|sign ?in)$/.test(txt(e)))) return 'out';
  return 'unknown';
}
