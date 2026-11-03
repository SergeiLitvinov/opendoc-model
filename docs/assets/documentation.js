/* Controls for the independent OpenDoc Model documentation theme. */
window.addEventListener('DOMContentLoaded', () => {
    const root = document.documentElement;
    const themeButton = document.querySelector('.docs-theme-button');
    const updateThemeLabel = () => {
        const next = root.dataset.theme === 'dark' ? 'Включить светлую тему' : 'Включить тёмную тему';
        themeButton.setAttribute('aria-label', next);
        themeButton.title = next;
    };
    updateThemeLabel();
    themeButton.addEventListener('click', () => {
        root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
        try { localStorage.setItem('opendoc.docs.theme', root.dataset.theme); } catch (_) {}
        updateThemeLabel();
    });
    const menu = document.querySelector('.docs-menu-button');
    const sidebar = document.getElementById('docs-navigation');
    const closeMenu = () => { sidebar.classList.remove('is-open'); menu.setAttribute('aria-expanded', 'false'); };
    menu.addEventListener('click', () => {
        const open = menu.getAttribute('aria-expanded') !== 'true';
        sidebar.classList.toggle('is-open', open);
        menu.setAttribute('aria-expanded', String(open));
    });
    document.addEventListener('click', event => {
        if (!sidebar.contains(event.target) && !menu.contains(event.target)) closeMenu();
    });
    const dialog = document.getElementById('docs-search');
    const input = document.getElementById('mkdocs-search-query');
    const openSearch = () => { closeMenu(); if (!dialog.open) dialog.showModal(); input.focus(); };
    document.querySelector('[data-open-search]').addEventListener('click', openSearch);
    document.querySelector('[data-close-search]').addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
    document.addEventListener('keydown', event => {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); openSearch(); }
        if (event.key === 'Escape') {
            closeMenu();
            if (dialog.open) { event.preventDefault(); dialog.close(); }
        }
    });
    input.addEventListener('input', () => {
        if (typeof doSearch === 'function' && typeof min_search_length === 'number') doSearch();
    });
    // A query typed before the local index finishes loading must be replayed.
    if (typeof searchWorker !== 'undefined') searchWorker.addEventListener('message', event => {
        if (event.data.allowSearch && input.value.trim()) doSearch();
    });
});
