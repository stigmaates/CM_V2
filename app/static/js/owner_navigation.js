(() => {
    const navigation = document.getElementById('ownerNavigation');
    if (!navigation) return;

    const groups = Array.from(navigation.querySelectorAll('[data-owner-nav-group]'));
    const setGroupOpen = (group, open) => {
        const toggle = group.querySelector('.owner-navigation__group-toggle');
        const links = group.querySelector('.owner-navigation__links-shell');
        group.classList.toggle('is-open', open);
        if (toggle) toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
        if (links) links.setAttribute('aria-hidden', open ? 'false' : 'true');
    };

    groups.forEach((group) => {
        const toggle = group.querySelector('.owner-navigation__group-toggle');
        if (!toggle) return;
        toggle.addEventListener('click', () => {
            const willOpen = !group.classList.contains('is-open');
            groups.forEach((other) => {
                if (other !== group) setGroupOpen(other, false);
            });
            setGroupOpen(group, willOpen);
        });
    });

})();
