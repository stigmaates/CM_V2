(() => {
    const navigation = document.getElementById('ownerNavigation');
    const trigger = document.querySelector('[data-owner-menu-open]');
    const closeControls = document.querySelectorAll('[data-owner-menu-close]');
    if (!navigation || !trigger) return;

    const desktopQuery = window.matchMedia('(min-width: 901px)');
    let lastFocused = null;

    const setOpen = (open, { focus = false } = {}) => {
        const desktop = desktopQuery.matches;
        document.body.classList.toggle('owner-navigation-collapsed', desktop && !open);
        document.body.classList.toggle('owner-navigation-open', !desktop && open);
        navigation.classList.toggle('is-open', open);
        navigation.setAttribute('aria-hidden', open ? 'false' : 'true');
        trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
        trigger.setAttribute('aria-label', open ? 'Свернуть меню' : 'Открыть меню');

        closeControls.forEach((control) => {
            control.setAttribute('aria-label', desktop ? 'Свернуть меню' : 'Закрыть меню');
        });

        if (!desktop && window.ownerLenis) {
            if (open) window.ownerLenis.stop();
            else window.ownerLenis.start();
        }

        if (open && focus && !desktop) {
            lastFocused = document.activeElement;
            requestAnimationFrame(() => navigation.querySelector('[data-owner-menu-close]')?.focus());
        } else if (!open && focus && !desktop && lastFocused instanceof HTMLElement) {
            lastFocused.focus();
        }
    };

    setOpen(desktopQuery.matches);

    trigger.addEventListener('click', () => setOpen(!navigation.classList.contains('is-open'), { focus: true }));
    closeControls.forEach((control) => control.addEventListener('click', () => setOpen(false, { focus: true })));
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
        if (event.key === 'Escape' && navigation.classList.contains('is-open')) setOpen(false, { focus: true });
    });

    desktopQuery.addEventListener('change', (event) => setOpen(event.matches));
})();
