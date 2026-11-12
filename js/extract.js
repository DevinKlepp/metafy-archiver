// Extract one guide section from the live page: cleaned HTML, image URLs, video links, titles, author.
// Called with {selector, basePath}. Image sources are replaced by MFAIMG_<n>_ placeholders that the
// Python side swaps for local files.
({selector, basePath}) => {
  const abs = u => { if (!u) return null; try { return new URL(u, location.href).href; } catch (e) { return null; } };
  const VIDEO_HOSTS = /(youtube\.com|youtu\.be|youtube-nocookie\.com|vimeo\.com|twitch\.tv|streamable\.com|wistia\.(com|net)|loom\.com|dailymotion\.com|mux\.com|medal\.tv|gfycat\.com|bilibili\.com)/i;
  const norm = u => {
    let m;
    if ((m = u.match(/youtube(?:-nocookie)?\.com\/embed\/([\w-]{6,})/))) {
      const t = u.match(/[?&]start=(\d+)/);
      return 'https://www.youtube.com/watch?v=' + m[1] + (t ? '&t=' + t[1] + 's' : '');
    }
    if ((m = u.match(/player\.vimeo\.com\/video\/(\d+)/))) {
      const h = u.match(/[?&]h=([\w]+)/);
      return 'https://vimeo.com/' + m[1] + (h ? '/' + h[1] : '');
    }
    if ((m = u.match(/player\.twitch\.tv\/\?.*?video=v?(\d+)/))) return 'https://www.twitch.tv/videos/' + m[1];
    if ((m = u.match(/clips\.twitch\.tv\/embed\?.*?clip=([\w-]+)/))) return 'https://clips.twitch.tv/' + m[1];
    return u;
  };

  // 1. Pick the content root.
  let root = selector ? document.querySelector(selector) : null;
  const biggest = sel => {
    let best = 0, el = null;
    for (const c of document.querySelectorAll(sel)) {
      const n = (c.innerText || '').length + 500 * c.querySelectorAll('img, iframe, video').length;
      if (n > best) { best = n; el = c; }
    }
    return el;
  };
  // Metafy renders the section body in an <article>; the chapter list lives in an <aside>.
  if (!root) root = biggest('article') || biggest('main, [role=main]');
  if (!root) root = document.body;

  // 2. Tag live elements with what only the live DOM knows (visibility, size, real src).
  const ignore = [];  // media URLs of decorative players, so sniffed requests for them are skipped too
  for (const el of root.querySelectorAll('*')) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.position === 'fixed'
        || el.getAttribute('aria-hidden') === 'true' && el.tagName !== 'IMG' && el.tagName !== 'svg') {
      el.setAttribute('data-mfa-drop', '1');
      continue;
    }
    const tag = el.tagName.toLowerCase();
    if (tag === 'img' || tag === 'svg' || tag === 'video' || tag === 'iframe') {
      const r = el.getBoundingClientRect();
      el.setAttribute('data-mfa-size', Math.round(r.width) + 'x' + Math.round(r.height));
    }
    if (tag === 'img') {
      const u = el.currentSrc || el.src || el.getAttribute('data-src') || '';
      el.setAttribute('data-mfa-src', u);
      el.setAttribute('data-mfa-nat', el.naturalWidth + 'x' + el.naturalHeight);
    }
    if (tag === 'video') {
      const src = el.currentSrc || el.src || '';
      // Autoplaying muted loops without controls are decoration (testimonial animations etc.).
      // (el.muted does not reflect the attribute; check both.)
      const deco = (el.autoplay || el.hasAttribute('autoplay')) && (el.muted || el.hasAttribute('muted'))
        && (el.loop || el.hasAttribute('loop')) && !el.controls && !el.hasAttribute('controls');
      if (deco || /\/animations?\//i.test(src)) {
        el.setAttribute('data-mfa-drop', '1');
        for (const s of [src, el.getAttribute('src'), ...[...el.querySelectorAll('source')].map(x => x.getAttribute('src'))]) {
          const a = abs(s); if (a) ignore.push(a);
        }
        continue;
      }
      el.setAttribute('data-mfa-src', src);
    }
    if (tag === 'mux-player') {
      // Mux's web component keeps the stream behind a shadow root; the attributes/properties
      // carry what we need. Signed streams: https://stream.mux.com/<id>.m3u8?token=<jwt>
      const id = el.getAttribute('playback-id') || el.playbackId || '';
      const tok = el.getAttribute('playback-token') || (el.tokens && el.tokens.playback) || '';
      const thumbTok = el.getAttribute('thumbnail-token') || (el.tokens && el.tokens.thumbnail) || '';
      let src = el.getAttribute('src') || '';
      if (!src && id) src = 'https://stream.mux.com/' + id + '.m3u8' + (tok ? '?token=' + tok : '');
      el.setAttribute('data-mfa-src', src);
      if (id && (thumbTok || !tok)) {
        el.setAttribute('data-mfa-poster', 'https://image.mux.com/' + id + '/thumbnail.jpg' + (thumbTok ? '?token=' + thumbTok : ''));
      }
    }
    if (tag !== 'img' && cs.backgroundImage && cs.backgroundImage.startsWith('url(')) {
      const r = el.getBoundingClientRect();
      const m = cs.backgroundImage.match(/url\(["']?(.*?)["']?\)/);
      if (m && r.width >= 200 && r.height >= 100 && !(el.innerText || '').trim()) {
        el.setAttribute('data-mfa-bg', m[1]);
      }
    }
  }

  const clone = root.cloneNode(true);
  const TAGS = ['data-mfa-drop', 'data-mfa-size', 'data-mfa-src', 'data-mfa-nat', 'data-mfa-bg', 'data-mfa-poster'];
  root.querySelectorAll(TAGS.map(t => '[' + t + ']').join(',')).forEach(el => TAGS.forEach(t => el.removeAttribute(t)));

  // Framework render markers (<!--[0-->, <!---->) are a third of the raw markup; drop them.
  const walker = document.createTreeWalker(clone, NodeFilter.SHOW_COMMENT);
  const comments = [];
  while (walker.nextNode()) comments.push(walker.currentNode);
  comments.forEach(c => c.remove());

  // Where a video is hosted. Mirrored by video_host() in Python; keep the two in step.
  const hostOf = u => {
    let h = ''; try { h = new URL(u).hostname; } catch (e) { return ''; }
    if (/(^|\.)(youtube\.com|youtu\.be|youtube-nocookie\.com)$/i.test(h)) return 'YouTube';
    if (/(^|\.)vimeo\.com$/i.test(h)) return 'Vimeo';
    if (/(^|\.)twitch\.tv$/i.test(h)) return 'Twitch';
    if (/(^|\.)(mux\.com|metafy\.gg|videodelivery\.net|cloudflarestream\.com)$/i.test(h)) return 'Metafy';
    return h;
  };
  const images = [], videos = [];
  const seenVid = new Map();
  const addVideo = (url, label, kind) => {
    if (!url) return null;
    url = norm(url);
    if (!seenVid.has(url)) {
      seenVid.set(url, videos.length);
      videos.push({ url, label: (label || '').trim(), kind, host: hostOf(url) });
    }
    return url;
  };
  // A box standing in for the player. MFAVID_<n>_ is replaced by the Python side with the
  // saved-copy line once the video has been downloaded (or removed if it was not).
  const videoBox = (urls, label) => {
    const box = document.createElement('div');
    box.setAttribute('data-keep-class', 'mfa-video');
    const host = urls.length ? hostOf(urls[0]) : '';
    const head = document.createElement('strong');
    head.textContent = '▶ ' + (host === 'Metafy' ? 'Metafy-hosted video' : host ? host + ' video' : 'Video')
      + (label ? ': ' + label : '');
    box.appendChild(head);
    if (!urls.length) {
      const p = document.createElement('div');
      p.textContent = 'Streamed video — see the video list at the end of this chapter.';
      box.appendChild(p);
    }
    for (const u of urls) {
      const d = document.createElement('div');
      const a = document.createElement('a');
      a.href = u; a.textContent = u.length > 120 ? u.slice(0, 117) + '…' : u;
      d.appendChild(a); box.appendChild(d);
      if (seenVid.has(u)) {
        const slot = document.createElement('div');
        slot.textContent = 'MFAVID_' + seenVid.get(u) + '_';
        box.appendChild(slot);
      }
    }
    return box;
  };
  const size = el => (el.getAttribute('data-mfa-size') || '0x0').split('x').map(Number);

  clone.querySelectorAll('[data-mfa-drop], script, style, noscript, link, template, nav, aside, form, input, textarea, select, dialog').forEach(e => e.remove());

  // Click-to-play facades (lite-youtube etc.)
  clone.querySelectorAll('lite-youtube, [data-youtube-id], [data-video-id], [data-videoid], [videoid]').forEach(el => {
    const id = el.getAttribute('videoid') || el.getAttribute('data-youtube-id') || el.getAttribute('data-video-id') || el.getAttribute('data-videoid');
    if (id && /^[\w-]{11}$/.test(id)) {
      const u = addVideo('https://www.youtube.com/watch?v=' + id, el.getAttribute('title') || el.getAttribute('playlabel') || '', 'embed');
      el.replaceWith(videoBox([u], ''));
    }
  });

  clone.querySelectorAll('iframe').forEach(el => {
    const u = abs(el.getAttribute('src') || el.getAttribute('data-src') || '');
    if (!u || u.startsWith('about:')) { el.remove(); return; }
    const label = el.getAttribute('title') || '';
    el.replaceWith(videoBox([addVideo(u, label, 'embed')], label));
  });

  clone.querySelectorAll('mux-player').forEach(el => {
    const u = el.getAttribute('data-mfa-src') || '';
    const label = el.getAttribute('title') || el.getAttribute('metadata-video-title') || '';
    const box = videoBox(u ? [addVideo(u, label, 'stream')] : [], label);
    const poster = el.getAttribute('data-mfa-poster');
    if (poster) {
      const img = document.createElement('img');
      img.setAttribute('src', 'MFAIMG_' + images.length + '_');
      img.setAttribute('data-mfa-done', '1');
      images.push(poster);
      box.appendChild(img);
    }
    el.replaceWith(box);
  });

  clone.querySelectorAll('video').forEach(el => {
    const cands = [el.getAttribute('data-mfa-src'), el.getAttribute('src'),
      ...[...el.querySelectorAll('source')].map(s => s.getAttribute('src'))];
    const urls = [];
    for (const c of cands) {
      if (!c || c.startsWith('blob:') || c.startsWith('data:')) continue;
      const u = addVideo(abs(c), el.getAttribute('title') || el.getAttribute('aria-label') || '', 'video');
      if (u && !urls.includes(u)) urls.push(u);
    }
    const box = videoBox(urls, el.getAttribute('title') || '');
    const poster = abs(el.getAttribute('poster') || '');
    if (poster) {
      const img = document.createElement('img');
      img.setAttribute('src', 'MFAIMG_' + images.length + '_');
      img.setAttribute('data-mfa-done', '1');
      images.push(poster);
      box.appendChild(img);
    }
    el.replaceWith(box);
  });

  clone.querySelectorAll('picture source').forEach(e => e.remove());
  clone.querySelectorAll('img:not([data-mfa-done])').forEach(el => {
    const [w, h] = size(el);
    const [nw, nh] = (el.getAttribute('data-mfa-nat') || '0x0').split('x').map(Number);
    let u = el.getAttribute('data-mfa-src') || el.getAttribute('src') || '';
    const alt = el.getAttribute('alt') || '';
    // A YouTube thumbnail standing in for a player is a video link too.
    const yt = u.match(/ytimg\.com\/vi(?:_webp)?\/([\w-]{11})\//);
    if (yt) addVideo('https://www.youtube.com/watch?v=' + yt[1], alt, 'thumbnail');
    const small = (w && h && w < 48 && h < 48) || (nw && nh && nw < 48 && nh < 48);
    if (!u || small) { el.remove(); return; }
    [...el.attributes].forEach(a => el.removeAttribute(a.name));
    if (alt) el.setAttribute('alt', alt);
    if (u.startsWith('data:')) { el.setAttribute('src', u); return; }
    el.setAttribute('src', 'MFAIMG_' + images.length + '_');
    images.push(abs(u));
  });

  clone.querySelectorAll('[data-mfa-bg]').forEach(el => {
    const u = abs(el.getAttribute('data-mfa-bg'));
    if (!u) return;
    const img = document.createElement('img');
    img.setAttribute('src', 'MFAIMG_' + images.length + '_');
    img.setAttribute('data-mfa-done', '1');
    images.push(u);
    el.prepend(img);
  });

  clone.querySelectorAll('svg').forEach(el => {
    const [w, h] = size(el);
    if (w < 64 || h < 64) el.remove();
  });
  // The Q&A thread under a section is rendered as buttons (name, time, text). Keep it readable.
  clone.querySelectorAll('button, [role=button]').forEach(el => {
    if (!el.querySelector('time') || (el.textContent || '').trim().length < 20) return;
    const c = document.createElement('div');
    c.setAttribute('data-keep-class', 'mfa-comment');
    while (el.firstChild) c.appendChild(el.firstChild);
    el.replaceWith(c);
  });
  // Buttons are app chrome once their icons are gone; keep ones that carry real text content.
  // A button wrapping an image (click-to-zoom) is unwrapped so the image stays.
  clone.querySelectorAll('button, [role=button]').forEach(el => {
    const text = (el.textContent || '').trim();
    if (el.querySelector('img, [data-keep-class]')) {
      if (text.length < 40) el.replaceWith(...el.childNodes);
    } else if (text.length < 40) {
      el.remove();
    }
  });

  clone.querySelectorAll('a[href]').forEach(a => {
    const u = abs(a.getAttribute('href'));
    if (!u) return;
    a.setAttribute('href', u);
    let host = '';
    try { host = new URL(u).hostname; } catch (e) {}
    if (VIDEO_HOSTS.test(host) && !/youtube\.com\/(@|channel\/|c\/|user\/)|twitch\.tv\/[^/]+\/?$/.test(u)) {
      addVideo(u, a.textContent, 'link');
    }
  });

  for (const el of clone.querySelectorAll('*')) {
    if (el.closest('svg')) continue;
    const keep = el.getAttribute('data-keep-class');
    for (const a of [...el.attributes]) {
      const n = a.name;
      if (n === 'href' || n === 'src' || n === 'alt' || n === 'colspan' || n === 'rowspan' || n === 'start') continue;
      el.removeAttribute(n);
    }
    if (keep) el.setAttribute('class', keep);
  }
  // Collapse wrappers that ended up empty.
  for (let pass = 0; pass < 4; pass++) {
    clone.querySelectorAll('div, span, section, p, li, ul, ol, a, header, footer, aside').forEach(el => {
      if (!el.children.length && !(el.textContent || '').trim()) el.remove();
    });
  }
  // The editor emits <p><div>…</div></p>; browsers auto-close the <p>, which breaks spacing. Use a div.
  clone.querySelectorAll('p').forEach(p => {
    if (!p.querySelector('div, ul, ol, table, blockquote, pre, h1, h2, h3, h4')) return;
    const d = document.createElement('div');
    while (p.firstChild) d.appendChild(p.firstChild);
    p.replaceWith(d);
  });
  // Unwrap chains of single-child divs (the real page nests a dozen deep).
  for (let pass = 0; pass < 20; pass++) {
    let changed = false;
    clone.querySelectorAll('div').forEach(d => {
      if (d.getAttribute('data-keep-class') || d.children.length !== 1 || d.children[0].tagName !== 'DIV') return;
      if ([...d.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) return;
      if (d.children[0].getAttribute('data-keep-class')) return;
      d.replaceWith(d.children[0]); changed = true;
    });
    if (!changed) break;
  }

  // Section title: the heading in the section's own header first, then any h1/h2 in the content.
  // (A bare `h1` anywhere on the page can be UI chrome, e.g. a "REMOVE" label on a card.)
  const heading = root.querySelector('header h1, header h2') || root.querySelector('h1') || root.querySelector('h2');
  const og = document.querySelector('meta[property="og:title"]');

  // The guide's own name: a link back to the guide root, preferably one inside a heading.
  let guideTitle = '';
  if (basePath) {
    const links = [...document.querySelectorAll('a[href]')].filter(a => {
      try { return new URL(a.href).pathname.replace(/\/$/, '') === basePath; } catch (e) { return false; }
    });
    const pick = links.find(a => a.closest('h1, h2, h3') && a.innerText.trim());
    if (pick) guideTitle = pick.innerText.trim().split('\n')[0];
  }

  // The coach: Metafy profiles live at /@handle. Prefer a link whose text is a name rather than "Guides".
  let author = '', handle = '';
  for (const a of document.querySelectorAll('a[href]')) {
    let m;
    try { m = new URL(a.href).pathname.match(/^\/@([\w.-]+)(\/|$)/); } catch (e) { continue; }
    if (!m) continue;
    handle = handle || '@' + m[1];
    const t = (a.innerText || '').trim().split('\n')[0];
    if (t && !/^(guides?|sessions?|coaching|profile|view profile)$/i.test(t) && !author) author = t;
  }
  if (author && handle && author.toLowerCase() !== handle.toLowerCase()) author = author + ' (' + handle + ')';
  author = author || handle;

  return {
    guideTitle,
    author,
    title: (heading && heading.innerText.trim().split('\n')[0]) || '',
    docTitle: document.title || '',
    ogTitle: og ? og.getAttribute('content') || '' : '',
    html: clone.innerHTML,
    text: (clone.textContent || '').replace(/\s+/g, ' ').trim(),
    images, videos, ignore,
  };
}
