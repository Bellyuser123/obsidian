function getOrCreateCursor() {
  let cursor = document.getElementById('cursor') || document.getElementById('custom-cursor');
  if (!cursor) {
    cursor = document.createElement('div');
    cursor.id = 'cursor';
    cursor.className = 'cursor';
    document.body.appendChild(cursor);
  }
  if (cursor.parentElement === document.body && document.body.lastElementChild !== cursor) {
    document.body.appendChild(cursor);
  }
  return cursor;
}

window.addEventListener('mousemove', (e) => {
  const cursor = getOrCreateCursor();
  if (cursor) {
    cursor.style.left = `${e.clientX - 8}px`;
    cursor.style.top = `${e.clientY - 8}px`;
  }
}, { passive: true });

document.addEventListener('mouseover', (e) => {
  const cursor = getOrCreateCursor();
  if (cursor) {
    const isInteractive = e.target.closest('button, a, input, select, textarea, [role="button"], .interactive');
    if (isInteractive) {
      cursor.style.transform = 'scale(1.5)';
    } else {
      cursor.style.transform = 'scale(1.0)';
    }
  }
}, { passive: true });