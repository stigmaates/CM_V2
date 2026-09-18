(() => {
    const navigation = document.getElementById('ownerNavigation');
    const trigger = document.querySelector('[data-owner-menu-open]');
    const closeControls = document.querySelectorAll('[data-owner-menu-close]');
    if (!navigation || !trigger) return;

    let lastFocused = null;

    const setOpen = (open) => {
        document.body.classList.toggle('owner-navigation-open', open);
        navigation.classList.toggle('is-open', open);
        navigation.setAttribute('aria-hidden', open ? 'false' : 'true');
        trigger.setAttribute('aria-expanded', open ? 'true' : 'false');

        if (window.ownerLenis) {
            if (open) window.ownerLenis.stop();
            else window.ownerLenis.start();
        }

        if (open) {
            lastFocused = document.activeElement;
            requestAnimationFrame(() => navigation.querySelector('[data-owner-menu-close]')?.focus());
        } else if (lastFocused instanceof HTMLElement) {
            lastFocused.focus();
        }
    };

    trigger.addEventListener('click', () => setOpen(true));
    closeControls.forEach((control) => control.addEventListener('click', () => setOpen(false)));
    navigation.querySelectorAll('a').forEach((link) => link.addEventListener('click', () => setOpen(false)));

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
})();
