"use strict";

export function installDefinitionPopovers() {
  const popup = document.createElement('div');
  popup.id = 'variable-definition';
  popup.className = 'definition-popup';
  popup.setAttribute('role','tooltip');
  popup.hidden = true;
  const title = document.createElement('strong');
  const text = document.createElement('p');
  const formula = document.createElement('code');
  popup.append(title,text,formula);
  document.body.append(popup);
  let active = null, pinned = false, timer, anchorBounds;

  function close() {
    clearTimeout(timer);
    active?.removeAttribute('aria-describedby');
    active = null;
    pinned = false;
    popup.hidden = true;
  }
  function position() {
    if (!active?.isConnected) return close();
    const anchor = active.getBoundingClientRect(), gap = 8, edge = 12;
    anchorBounds = anchor;
    const box = popup.getBoundingClientRect();
    const left = Math.max(edge, Math.min(anchor.left, innerWidth-box.width-edge));
    let top = anchor.bottom+gap;
    if (top+box.height > innerHeight-edge) top = anchor.top-gap-box.height;
    top = Math.max(edge, Math.min(top, innerHeight-box.height-edge));
    popup.style.left = left+'px';
    popup.style.top = top+'px';
  }
  function show(button) {
    clearTimeout(timer);
    if (active !== button) close();
    active = button;
    title.textContent = button.dataset.definitionTitle;
    text.textContent = button.dataset.definitionText;
    formula.textContent = button.dataset.definitionFormula || '';
    formula.hidden = !formula.textContent;
    popup.hidden = false;
    active.setAttribute('aria-describedby',popup.id);
    position();
  }
  function scheduleClose() {
    clearTimeout(timer);
    if (!pinned) timer = setTimeout(close,160);
  }
  document.addEventListener('pointerover', event => {
    if (event.pointerType === 'touch') return;
    const button = event.target.closest('.definition-button');
    if (button) show(button);
    else if (popup.contains(event.target)) clearTimeout(timer);
  });
  document.addEventListener('pointerout', event => {
    if (!active || event.pointerType === 'touch') return;
    if (active.contains(event.relatedTarget) || popup.contains(event.relatedTarget)) return;
    if (active.contains(event.target) || popup.contains(event.target)) scheduleClose();
  });
  document.addEventListener('focusin', event => {
    const button = event.target.closest('.definition-button');
    if (button) show(button);
    else if (!popup.contains(event.target)) close();
  });
  document.addEventListener('focusout', event => {
    if (event.target === active) scheduleClose();
  });
  document.addEventListener('click', event => {
    const button = event.target.closest('.definition-button');
    if (button) {
      if (button === active && pinned) close();
      else { show(button); pinned = true; }
    } else if (!popup.contains(event.target)) close();
  });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') close(); });
  window.addEventListener('resize',close);
  document.addEventListener('scroll', event => {
    if (!active || event.target === popup) return;
    // Focus/scrollIntoView can deliver a delayed event after the anchor has settled.
    const now = active.getBoundingClientRect();
    if (Math.abs(now.left-anchorBounds.left)>.5 || Math.abs(now.top-anchorBounds.top)>.5) close();
  },true);
  return {close};
}
