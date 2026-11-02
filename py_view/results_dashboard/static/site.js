/* Shared navigation only. Catalog pages do not fetch analysis datasets. */
(() => {
  const legacy = {overview:'/',tianmaqu:'/modules/materials/',member:'/modules/member/',cyclic:'/modules/cyclic/',forces:'/modules/forces/',resources:'/modules/resources/'};
  const migrateBookmark = () => {
    if (!['/', '/index.html'].includes(location.pathname)) return;
    const destination = legacy[location.hash.slice(1)];
    if (destination && location.hash) location.replace(destination);
  };
  migrateBookmark(); window.addEventListener('hashchange', migrateBookmark);
  const sidebar = document.getElementById('siteSidebar');
  const button = document.getElementById('menuButton');
  const backdrop = document.getElementById('menuBackdrop');
  const toggle = open => {
    sidebar.classList.toggle('open',open);backdrop.hidden=!open;
    button.setAttribute('aria-expanded',String(open));
    button.setAttribute('aria-label',open?'关闭导航':'打开导航');
  };
  button.addEventListener('click',()=>toggle(button.getAttribute('aria-expanded')!=='true'));
  backdrop.addEventListener('click',()=>toggle(false));
  document.addEventListener('keydown',e=>{if(e.key==='Escape'){toggle(false);button.focus();}});
  document.querySelectorAll('.nav-link').forEach(a=>a.addEventListener('click',()=>toggle(false)));
  document.getElementById('servicePort').textContent=`PORT ${location.port||'default'}`;
})();
