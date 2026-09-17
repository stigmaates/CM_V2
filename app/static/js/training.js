(function () {
    function activatePlayer(button) {
        const embedUrl = button.dataset.embedUrl;
        if (!embedUrl) return;
        const iframe = document.createElement("iframe");
        iframe.src = embedUrl;
        iframe.title = button.getAttribute("aria-label") || "Видео YouTube";
        iframe.allow = "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share";
        iframe.allowFullscreen = true;
        iframe.referrerPolicy = "strict-origin-when-cross-origin";
        iframe.setAttribute("loading", "lazy");
        button.replaceWith(iframe);
    }

    document.querySelectorAll("[data-training-player]").forEach((button) => {
        button.addEventListener("click", () => activatePlayer(button), { once: true });
    });
}());
