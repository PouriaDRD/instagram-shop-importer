(() => {
  'use strict';
  const search = document.getElementById('sessionSearch');
  const filter = document.getElementById('sessionStatusFilter');
  const count = document.getElementById('sessionsVisibleCount');
  const empty = document.getElementById('sessionNoMatches');
  const reset = document.getElementById('resetSessionFilters');
  const rows = [...document.querySelectorAll('[data-session-row]')];
  if (!search || !filter || !count || !empty) return;
  const normalize = (s) => String(s).toLocaleLowerCase('fa').normalize('NFKC').trim();
  const update = () => {
    const keyword = normalize(search.value);
    const state = filter.value;
    let visible = 0;
    for (const row of rows) {
      const matches = (state === 'all' || row.dataset.state === state) && normalize(row.dataset.search).includes(keyword);
      row.hidden = !matches;
      if (matches) visible++;
    }
    count.textContent = `${visible.toLocaleString('fa-IR')} نشست از ${rows.length.toLocaleString('fa-IR')}`;
    empty.hidden = visible !== 0;
  };
  search.addEventListener('input', update);
  filter.addEventListener('change', update);
  reset?.addEventListener('click', () => {
    search.value = '';
    filter.value = 'all';
    window.SeloraCustomSelect?.refreshAll();
    update();
    search.focus();
  });
  update();
})();
