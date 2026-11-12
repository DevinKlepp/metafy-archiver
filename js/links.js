// Every link on the page, in DOM order, flagged if it sits in a navigation area (sidebar / table of contents).
() => [...document.querySelectorAll('a[href]')].map(a => ({
  href: a.href,
  text: (a.innerText || a.getAttribute('aria-label') || '').trim().slice(0, 140),
  nav: !!a.closest('aside, nav, [role=navigation]'),
}))
