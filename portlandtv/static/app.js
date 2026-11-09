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
  const times = v => /^\s*\d+\s*$/.test(v) && +v >= 1 ? +v : NaN;  // as config.length_repeat
  const total = lengths.reduce((sum, el, i) => sum + secs(el.value) * times(repeats[i].value), 0);
  const left = document.getElementById('left');
  left.textContent = 'Still to assign: ' + (isNaN(total) ? '?' : hm(86400 - total));
  left.className = total === 86400 ? 'ok' : 'bad';
});
// Buttons post in the background and the new page is swapped in where you were, not at the top.
document.addEventListener('submit', async e => {
  e.preventDefault();
  const form = e.target, y = scrollY;
  // getAttribute: form.action is shadowed by the buttons named "action"
  const r = await fetch(form.getAttribute('action'), {method: 'POST', body: new FormData(form, e.submitter)});
  document.body.replaceWith(new DOMParser().parseFromString(await r.text(), 'text/html').body);
  scrollTo(0, y);
});
// "All" ticks or clears every box beside it.
document.addEventListener('change', e => {
  if (!e.target.matches('[data-check-all]')) return;
  for (const box of e.target.closest('fieldset').querySelectorAll('input[type=checkbox]')) box.checked = e.target.checked;
});
// Browse… picks a Library folder on the laptop, as the service sees it.
let browseTarget;
async function browse(path) {
  const f = await (await fetch('/folders?path=' + encodeURIComponent(path))).json();
  const d = document.getElementById('folders'), list = d.querySelector('ul');
  d.dataset.path = f.path;
  d.querySelector('h3').textContent = f.path;
  d.querySelector('.bad').textContent = f.error || '';
  list.replaceChildren(...[...(f.parent ? [{name: '↑ up', path: f.parent}] : []), ...f.dirs].map(dir => {
    const li = document.createElement('li'), b = document.createElement('button');
    b.type = 'button';
    b.textContent = dir.name;
    b.onclick = () => browse(dir.path);
    li.append(b);
    return li;
  }));
  if (!d.open) d.showModal();
}
document.addEventListener('click', e => {
  const t = e.target;
  if (t.matches('[data-browse]')) {
    browseTarget = document.querySelector(`[name="${t.dataset.browse}"]`);
    browse(browseTarget.value || '/media');
  } else if (t.matches('[data-pick]')) {
    browseTarget.value = document.getElementById('folders').dataset.path;
    t.closest('dialog').close();
  } else if (t.matches('[data-close]')) {
    t.closest('dialog').close();
  }
});
