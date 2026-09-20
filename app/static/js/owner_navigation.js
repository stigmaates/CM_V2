(() => {
    const navigation = document.getElementById('ownerNavigation');
    const trigger = document.querySelector('[data-owner-menu-open]');
    const backdrop = document.querySelector('[data-owner-menu-close]');
    if (!navigation || !trigger) return;

    const desktopQuery = window.matchMedia('(min-width: 901px)');

    const setOpen = (open) => {
        const desktop = desktopQuery.matches;
        document.body.classList.toggle('owner-navigation-visible', open);
        document.body.classList.toggle('owner-navigation-open', !desktop && open);
        navigation.classList.toggle('is-open', open);
        navigation.setAttribute('aria-hidden', open ? 'false' : 'true');
        trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
        trigger.setAttribute('aria-label', open ? 'Свернуть боковую панель' : 'Открыть боковую панель');

        if (!desktop && window.ownerLenis) {
            if (open) window.ownerLenis.stop();
            else window.ownerLenis.start();
        }
    };

    setOpen(desktopQuery.matches);

    trigger.addEventListener('click', () => setOpen(!navigation.classList.contains('is-open')));
    if (backdrop) backdrop.addEventListener('click', () => setOpen(false));
    navigation.querySelectorAll('a').forEach((link) => link.addEventListener('click', () => {
        if (!desktopQuery.matches) setOpen(false);
    }));

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

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && navigation.classList.contains('is-open')) setOpen(false);
    });

    desktopQuery.addEventListener('change', (event) => setOpen(event.matches));
})();
