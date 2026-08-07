(function () {
    const SHOW_DELAY_MS = 140;
    const MIN_VISIBLE_MS = 280;
    let overlay;
    let showTimer;
    let shownAt = 0;

    function getOverlay() {
        if (!overlay) {
            overlay = document.querySelector("[data-page-loading]");
        }
        return overlay;
    }

    function showLoading(label) {
        clearTimeout(showTimer);
        showTimer = window.setTimeout(() => {
            const node = getOverlay();
            if (!node) {
                return;
            }
            shownAt = Date.now();
            node.classList.add("is-visible");
            node.setAttribute("aria-hidden", "false");
            document.documentElement.classList.add("is-page-loading");
        }, SHOW_DELAY_MS);
    }

    function hideLoading() {
        clearTimeout(showTimer);
        const node = getOverlay();
        if (!node) {
            return;
        }

        const elapsed = Date.now() - shownAt;
        const delay = shownAt && elapsed < MIN_VISIBLE_MS ? MIN_VISIBLE_MS - elapsed : 0;
        window.setTimeout(() => {
            node.classList.remove("is-visible");
            node.setAttribute("aria-hidden", "true");
            document.documentElement.classList.remove("is-page-loading");
            shownAt = 0;
        }, delay);
    }

    function shouldIgnoreLink(link, event) {
        if (!link || event.defaultPrevented) {
            return true;
        }
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) {
            return true;
        }
        if (link.target && link.target !== "_self") {
            return true;
        }
        if (link.hasAttribute("download")) {
            return true;
        }
        if (link.dataset.noLoading !== undefined) {
            return true;
        }

        const href = link.getAttribute("href");
        if (!href || href.startsWith("#") || href.startsWith("javascript:")) {
            return true;
        }

        let url;
        try {
            url = new URL(href, window.location.href);
        } catch (_error) {
            return true;
        }
        if (url.origin !== window.location.origin) {
            return true;
        }
        return url.pathname === window.location.pathname && url.search === window.location.search && url.hash;
    }

    document.addEventListener("click", (event) => {
        const link = event.target.closest("a[href]");
        if (shouldIgnoreLink(link, event)) {
            return;
        }
        showLoading("Открываем страницу");
    });

    document.addEventListener("submit", (event) => {
        const form = event.target;
        if (!form || form.dataset.noLoading !== undefined || event.defaultPrevented) {
            return;
        }
        showLoading("Сохраняем изменения");
    }, true);

    window.addEventListener("pageshow", hideLoading);
    window.addEventListener("pagehide", () => clearTimeout(showTimer));

    window.CyberBonusPageLoading = {
        show: showLoading,
        hide: hideLoading,
    };
})();
