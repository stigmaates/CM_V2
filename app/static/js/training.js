(function () {
    const modal = document.querySelector("[data-training-modal]");
    if (!modal) return;

    const frame = modal.querySelector("[data-training-modal-frame]");
    const title = modal.querySelector("[data-training-modal-title]");
    const description = modal.querySelector("[data-training-modal-description]");
    const youtubeLink = modal.querySelector("[data-training-modal-youtube]");
    const items = Array.from(modal.querySelectorAll("[data-training-modal-item]"));
    const emptyPlaylist = modal.querySelector("[data-training-modal-playlist-empty]");
    let opener = null;

    function selectVideo(videoId) {
        const selected = items.find((item) => item.dataset.videoId === String(videoId));
        if (!selected) return;

        title.textContent = selected.dataset.videoTitle || "Видео обучения";
        description.textContent = selected.dataset.videoDescription || "Описание пока не добавлено.";
        youtubeLink.href = selected.dataset.youtubeUrl || "#";
        frame.title = selected.dataset.videoTitle || "Видео обучения";
        frame.src = selected.dataset.embedUrl || "about:blank";

        let visibleItems = 0;
        items.forEach((item) => {
            const isCurrent = item === selected;
            item.hidden = isCurrent;
            item.classList.toggle("is-current", isCurrent);
            if (!isCurrent) visibleItems += 1;
        });
        if (emptyPlaylist) emptyPlaylist.hidden = visibleItems > 0;
    }

    function openModal(button) {
        opener = button;
        selectVideo(button.dataset.videoId);
        document.body.classList.add("training-modal-open");
        if (typeof modal.showModal === "function") {
            modal.showModal();
        } else {
            modal.setAttribute("open", "");
        }
        modal.querySelector("[data-training-modal-close]").focus();
    }

    function closeModal() {
        frame.src = "about:blank";
        document.body.classList.remove("training-modal-open");
        if (typeof modal.close === "function" && modal.open) {
            modal.close();
        } else {
            modal.removeAttribute("open");
        }
        if (opener) opener.focus();
    }

    document.querySelectorAll("[data-training-player]").forEach((button) => {
        button.addEventListener("click", () => openModal(button));
    });

    items.forEach((item) => {
        item.addEventListener("click", () => selectVideo(item.dataset.videoId));
    });

    modal.querySelectorAll("[data-training-modal-close]").forEach((button) => {
        button.addEventListener("click", closeModal);
    });

    modal.addEventListener("click", (event) => {
        if (event.target === modal) closeModal();
    });

    modal.addEventListener("cancel", (event) => {
        event.preventDefault();
        closeModal();
    });

    modal.addEventListener("close", () => {
        frame.src = "about:blank";
        document.body.classList.remove("training-modal-open");
    });
}());
