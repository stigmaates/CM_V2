(() => {
    "use strict";

    const originalFetch = window.fetch.bind(window);
    const toast = document.createElement("div");
    toast.className = "demo-toast";
    toast.setAttribute("role", "status");
    document.addEventListener("DOMContentLoaded", () => document.body.append(toast), { once: true });
    let toastTimer = null;

    function showToast(message = "Изменение сохранено только в демо-режиме") {
        toast.textContent = message;
        toast.classList.add("is-visible");
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => toast.classList.remove("is-visible"), 2400);
    }

    function demoUrl(input) {
        const raw = typeof input === "string" ? input : input.url;
        const url = new URL(raw, window.location.origin);
        if (url.origin !== window.location.origin) return raw;
        if (url.pathname.startsWith("/owner/api/")) {
            url.pathname = `/demo/api/owner/${url.pathname.slice("/owner/api/".length)}`;
        } else if (url.pathname.startsWith("/guest/api/")) {
            url.pathname = `/demo/api/guest/${url.pathname.slice("/guest/api/".length)}`;
        }
        return `${url.pathname}${url.search}${url.hash}`;
    }

    window.fetch = (input, options) => originalFetch(demoUrl(input), options);
    window.demoToast = showToast;

    document.addEventListener("submit", (event) => {
        const form = event.target.closest("form");
        if (!form) return;
        const action = new URL(form.action || window.location.href, window.location.origin);
        if (action.origin !== window.location.origin || !action.pathname.startsWith("/demo/action/")) return;
        event.preventDefault();
        showToast();
    }, true);

    document.addEventListener("click", (event) => {
        const link = event.target.closest("a[href]");
        if (!link) return;
        const url = new URL(link.href, window.location.origin);
        if (url.origin === window.location.origin && (url.pathname.startsWith("/owner/") || url.pathname.startsWith("/guest/"))) {
            event.preventDefault();
            showToast("В демо-режиме этот переход не меняет боевые данные");
        }
    }, true);
})();
