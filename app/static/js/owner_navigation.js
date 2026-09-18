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

    navigation.querySelectorAll('.owner-navigation__group').forEach((group) => {
        group.addEventListener('toggle', () => {
            if (!group.open) return;
            navigation.querySelectorAll('.owner-navigation__group[open]').forEach((other) => {
                if (other !== group) other.open = false;
            });
        });
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && navigation.classList.contains('is-open')) setOpen(false);
    });

    desktopQuery.addEventListener('change', (event) => setOpen(event.matches));
})();
