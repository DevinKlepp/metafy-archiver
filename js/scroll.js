// Scroll every scrollable area to the bottom so lazy-loaded content appears, then back to the top.
async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const targets = [document.scrollingElement || document.documentElement];
  for (const el of document.querySelectorAll('*')) {
    if (el.clientHeight >= 200 && el.scrollHeight > el.clientHeight + 200) {
      const oy = getComputedStyle(el).overflowY;
      if (oy === 'auto' || oy === 'scroll') targets.push(el);
    }
  }
  for (const el of targets) {
    let last = -1, guard = 0;
    while (guard++ < 150) {
      el.scrollBy(0, Math.max(400, window.innerHeight * 0.8));
      await sleep(100);
      const pos = el.scrollTop;
      if (pos === last) break;
      last = pos;
    }
    el.scrollTo(0, 0);
  }
  await sleep(300);
}
