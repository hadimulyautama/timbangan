/* Tema dan menu mengikuti portal; perubahan tampilan tidak mengirim formulir. */
(() => {
  const body = document.body;
  const menu = document.getElementById('menu-timbang');
  const open = document.querySelector('.pd-menu');
  const close = document.querySelector('.pd-close');
  const backdrop = document.querySelector('.pd-backdrop');
  const theme = document.querySelector('.pd-theme');
  const mobile = matchMedia('(max-width:899px)');
  const main = document.querySelector('.bingkai');
  document.querySelectorAll('.bawah__isi>a.aktif').forEach(a => a.setAttribute('aria-current', 'page'));
  function setDrawer(value, restore = true) {
    const active = value && mobile.matches;
    body.classList.toggle('pd-drawer-open', active);
    if (open) open.setAttribute('aria-expanded', String(active));
    if (backdrop) backdrop.hidden = !active;
    if (main) main.inert = active;
    if (menu) {
      menu.inert = mobile.matches && !active;
      if (active) { menu.setAttribute('role', 'dialog'); menu.setAttribute('aria-modal', 'true'); }
      else { menu.removeAttribute('role'); menu.removeAttribute('aria-modal'); }
    }
    if (active && close) close.focus();
    else if (restore && open && mobile.matches) open.focus();
  }
  if (open) open.addEventListener('click', () => setDrawer(true));
  if (close) close.addEventListener('click', () => setDrawer(false));
  if (backdrop) backdrop.addEventListener('click', () => setDrawer(false));
  document.addEventListener('keydown', e => {
    if (!body.classList.contains('pd-drawer-open')) return;
    if (e.key === 'Escape') { e.preventDefault(); setDrawer(false); }
    if (e.key === 'Tab' && menu) {
      const items = [...menu.querySelectorAll('a[href],button:not([disabled])')].filter(e => e.getClientRects().length);
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });
  mobile.addEventListener('change', () => setDrawer(false, false));
  setDrawer(false, false);
  function updateTheme() {
    if (!theme) return;
    const light = body.classList.contains('terik');
    theme.textContent = light ? '☾' : '☀';
    theme.setAttribute('aria-label', light ? 'Aktifkan mode gelap' : 'Aktifkan mode terang');
    document.documentElement.style.colorScheme = light ? 'light' : 'dark';
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = light ? '#f5f5ef' : '#111914';
  }
  if (theme) theme.addEventListener('click', () => {
    body.classList.toggle('terik');
    try { localStorage.setItem('pd.tema.timbang', body.classList.contains('terik') ? 'light' : 'dark'); } catch (_) {}
    updateTheme();
  });
  updateTheme();
})();
