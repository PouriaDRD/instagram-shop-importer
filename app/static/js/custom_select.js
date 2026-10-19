/* Accessible progressive enhancement: real <select> stays the source of truth. */
(() => {
  'use strict';
  const instances = [];
  let serial = 0;

  const close = (instance, restoreFocus = false) => {
    if (!instance.open) return;
    instance.open = false;
    instance.root.classList.remove('is-open');
    instance.button.setAttribute('aria-expanded', 'false');
    instance.list.hidden = true;
    if (restoreFocus) instance.button.focus();
  };
  const closeOthers = (except) => {
    for (const instance of instances) if (instance !== except) close(instance);
  };
  const selectable = (instance) => [...instance.select.options].map((option, index) => ({option, index})).filter(item => !item.option.disabled && !item.option.hidden);

  const setActive = (instance, index) => {
    const items = selectable(instance);
    if (!items.length) return;
    const match = items.find(item => item.index === index) || items[0];
    instance.active = match.index;
    for (const child of instance.list.children) {
      const isActive = Number(child.dataset.index) === instance.active;
      child.classList.toggle('is-active', isActive);
    }
    const active = instance.list.querySelector(`[data-index="${instance.active}"]`);
    instance.button.setAttribute('aria-activedescendant', active?.id || '');
    active?.scrollIntoView({block: 'nearest'});
  };
  const refresh = (instance) => {
    const {select, button, list} = instance;
    button.disabled = select.disabled;
    button.classList.toggle('is-disabled', select.disabled);
    button.querySelector('.selora-select__label').textContent = select.selectedOptions[0]?.textContent?.trim() || select.dataset.placeholder || 'انتخاب کنید';
    list.replaceChildren();
    for (const [index, option] of [...select.options].entries()) {
      if (option.hidden) continue;
      const item = document.createElement('li');
      item.id = `${instance.id}-option-${index}`;
      item.dataset.index = String(index);
      item.className = 'selora-select__option';
      item.setAttribute('role', 'option');
      item.setAttribute('aria-selected', String(select.selectedIndex === index));
      item.setAttribute('aria-disabled', String(option.disabled));
      if (option.disabled) item.classList.add('is-disabled');
      if (select.selectedIndex === index) item.classList.add('is-selected');
      const caption = document.createElement('span');
      caption.textContent = option.textContent.trim();
      const check = document.createElement('span');
      check.className = 'selora-select__check';
      check.setAttribute('aria-hidden', 'true');
      check.textContent = '✓';
      item.append(caption, check);
      item.addEventListener('click', () => selectIndex(instance, index));
      list.append(item);
    }
    if (select.disabled) close(instance);
    instance.active = select.selectedIndex;
    // No expensive scrolling while a list is closed.
    button.removeAttribute('aria-activedescendant');
  };
  const selectIndex = (instance, index) => {
    const option = instance.select.options[index];
    if (!option || option.disabled || option.hidden) return;
    const changed = instance.select.selectedIndex !== index;
    instance.select.selectedIndex = index;
    refresh(instance);
    close(instance, true);
    if (changed) instance.select.dispatchEvent(new Event('change', {bubbles: true}));
  };
  const open = (instance) => {
    if (instance.select.disabled) return;
    closeOthers(instance);
    instance.open = true;
    instance.root.classList.add('is-open');
    instance.button.setAttribute('aria-expanded', 'true');
    instance.list.hidden = false;
    setActive(instance, instance.select.selectedIndex);
  };
  const init = (select) => {
    if (select.dataset.enhanced === 'true') return;
    select.dataset.enhanced = 'true';
    const id = `selora-select-${++serial}`;
    const root = document.createElement('div');
    root.className = 'selora-select';
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'selora-select__trigger';
    button.setAttribute('role', 'combobox');
    button.setAttribute('aria-haspopup', 'listbox');
    button.setAttribute('aria-expanded', 'false');
    button.setAttribute('aria-controls', `${id}-list`);
    const label = document.querySelector(`label[for="${CSS.escape(select.id)}"]`);
    button.setAttribute('aria-label', label?.textContent?.trim() || select.dataset.placeholder || 'انتخاب گزینه');
    const caption = document.createElement('span');
    caption.className = 'selora-select__label';
    const arrow = document.createElement('span');
    arrow.className = 'selora-select__arrow';
    arrow.setAttribute('aria-hidden', 'true');
    arrow.textContent = '⌄';
    button.append(caption, arrow);
    const list = document.createElement('ul');
    list.id = `${id}-list`;
    list.className = 'selora-select__options';
    list.setAttribute('role', 'listbox');
    list.hidden = true;
    select.parentNode.insertBefore(root, select);
    root.append(select, button, list);
    select.classList.add('selora-select__native');
    select.tabIndex = -1;
    select.setAttribute('aria-hidden', 'true');
    const instance = {id, select, root, button, list, active: select.selectedIndex, open: false};
    instances.push(instance);
    refresh(instance);
    button.addEventListener('click', () => instance.open ? close(instance) : open(instance));
    button.addEventListener('keydown', (event) => {
      const key = event.key;
      if (key === 'Escape') {if (instance.open) {event.preventDefault(); close(instance, true);} return;}
      if (key === 'Tab') {close(instance); return;}
      if (!['ArrowDown', 'ArrowUp', 'Home', 'End', 'Enter', ' '].includes(key)) return;
      event.preventDefault();
      if (!instance.open) {
        open(instance);
        return;
      }
      if (key === 'Enter' || key === ' ') {selectIndex(instance, instance.active); return;}
      const indices = selectable(instance).map(item => item.index);
      if (!indices.length) return;
      let pos = Math.max(0, indices.indexOf(instance.active));
      if (key === 'Home') pos = 0;
      else if (key === 'End') pos = indices.length - 1;
      else pos = (pos + (key === 'ArrowDown' ? 1 : -1) + indices.length) % indices.length;
      setActive(instance, indices[pos]);
    });
    select.addEventListener('change', () => refresh(instance));
  };
  document.addEventListener('pointerdown', event => {
    for (const instance of instances) if (!instance.root.contains(event.target)) close(instance);
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') closeOthers(null);
  });
  const initialize = () => document.querySelectorAll('select[data-custom-select]').forEach(init);
  window.SeloraCustomSelect = {
    refreshAll: () => instances.forEach(refresh),
    initialize,
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize);
  else initialize();
})();
