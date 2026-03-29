const cursor = document.getElementById('cursor');
document.addEventListener('mousemove', e => {
  cursor.style.left = e.clientX - 8 + 'px';
  cursor.style.top = e.clientY - 8 + 'px';
});