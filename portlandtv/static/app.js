// Buttons with data-confirm (e.g. distributed -> fixed drops six days) ask first.
document.addEventListener('click', e => {
  const b = e.target.closest('[data-confirm]');
  if (b && !confirm(b.dataset.confirm)) e.preventDefault();
});
// Live "Still to assign" while typing Block lengths and repeats; the server re-checks on save.
const secs = t => { const m = /^\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*$/.exec(t); return m && (m[1] || m[2]) ? (+m[1] || 0) * 3600 + (+m[2] || 0) * 60 : NaN; };
const hm = s => (s < 0 ? '−' : '') + Math.floor(Math.abs(s) / 3600) + 'h' + String(Math.floor(Math.abs(s) % 3600 / 60)).padStart(2, '0');
document.addEventListener('input', () => {
  const lengths = [...document.querySelectorAll('[data-length]')], repeats = [...document.querySelectorAll('[data-repeat]')];
  const total = lengths.reduce((sum, el, i) => sum + secs(el.value) * (parseInt(repeats[i].value, 10) || 0), 0);
  const left = document.getElementById('left');
  left.textContent = 'Still to assign: ' + (isNaN(total) ? '?' : hm(86400 - total));
  left.className = total === 86400 ? 'ok' : 'bad';
});
