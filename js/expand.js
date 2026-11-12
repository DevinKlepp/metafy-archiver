// Open collapsed sections (details, accordions) so their content is in the DOM.
async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  document.querySelectorAll('details:not([open])').forEach(d => d.open = true);
  const btns = [...document.querySelectorAll(
    'main [aria-expanded="false"], aside [aria-expanded="false"], [role=main] [aria-expanded="false"]'
  )].filter(b => !b.closest('a[href]') && b.tagName !== 'A').slice(0, 60);
  for (const b of btns) { try { b.click(); await sleep(80); } catch (e) {} }
  await sleep(300);
}
