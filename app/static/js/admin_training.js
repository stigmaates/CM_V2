(function () {
    const VIDEO_ID_RE = /^[A-Za-z0-9_-]{11}$/;

    function extractVideoId(value) {
        const raw = String(value || "").trim();
        if (VIDEO_ID_RE.test(raw)) return raw;
        try {
            const url = new URL(raw.includes("://") ? raw : `https://${raw}`);
            const host = url.hostname.toLowerCase().replace(/\.$/, "");
            if (host === "youtu.be" || host.endsWith(".youtu.be")) {
                return url.pathname.split("/").filter(Boolean)[0] || "";
            }
            if (host === "youtube.com" || host.endsWith(".youtube.com")) {
                if (url.pathname.replace(/\/$/, "") === "/watch") return url.searchParams.get("v") || "";
                const parts = url.pathname.split("/").filter(Boolean);
                if (["embed", "shorts", "live"].includes(parts[0])) return parts[1] || "";
            }
        } catch (_error) {
            return "";
        }
        return "";
    }

    const urlInput = document.querySelector("[data-youtube-url-input]");
    const preview = document.querySelector("[data-youtube-preview]");
    if (urlInput && preview) {
        const image = preview.querySelector("img");
        const refreshPreview = () => {
            const videoId = extractVideoId(urlInput.value);
            const valid = VIDEO_ID_RE.test(videoId);
            preview.hidden = !valid;
            if (valid) image.src = `https://i.ytimg.com/vi/${videoId}/hqdefault.jpg`;
        };
        urlInput.addEventListener("input", refreshPreview);
        urlInput.addEventListener("change", refreshPreview);
    }

    document.querySelectorAll("[data-training-edit-toggle]").forEach((button) => {
        button.addEventListener("click", () => {
            const editor = button.closest("[data-training-card]").querySelector("[data-training-editor]");
            const opening = editor.hidden;
            editor.hidden = !opening;
            button.setAttribute("aria-expanded", String(opening));
            button.textContent = opening ? "Свернуть" : "Редактировать";
        });
    });

    const sortable = document.querySelector("[data-training-sortable]");
    if (!sortable) return;
    const status = document.querySelector("[data-training-sort-status]");
    let dragged = null;
    let dragArmed = false;

    function setStatus(text, isError) {
        if (!status) return;
        status.textContent = text;
        status.classList.toggle("is-error", Boolean(isError));
    }

    async function saveOrder() {
        const ids = Array.from(sortable.querySelectorAll("[data-video-id]"), (card) => Number(card.dataset.videoId));
        setStatus("Сохраняем порядок…", false);
        try {
            const response = await fetch(sortable.dataset.reorderUrl, {
                method: "POST",
                headers: { "Content-Type": "application/json", "Accept": "application/json" },
                body: JSON.stringify({ ids })
            });
            const payload = await response.json();
            if (!response.ok || !payload.ok) throw new Error(payload.error || "Не удалось сохранить порядок");
            setStatus("Порядок сохранён", false);
        } catch (error) {
            setStatus(error.message || "Не удалось сохранить порядок", true);
        }
    }

    sortable.querySelectorAll("[data-training-card]").forEach((card) => {
        const handle = card.querySelector(".training-drag-handle");
        handle.addEventListener("pointerdown", () => {
            dragArmed = true;
            card.draggable = true;
        });
        document.addEventListener("pointerup", () => {
            dragArmed = false;
            if (card !== dragged) card.draggable = false;
        });
        card.addEventListener("dragstart", (event) => {
            if (!dragArmed) {
                event.preventDefault();
                return;
            }
            dragged = card;
            card.classList.add("is-dragging");
            event.dataTransfer.effectAllowed = "move";
            event.dataTransfer.setData("text/plain", card.dataset.videoId);
        });
        card.addEventListener("dragend", () => {
            card.classList.remove("is-dragging");
            card.draggable = false;
            dragArmed = false;
            dragged = null;
            saveOrder();
        });
    });

    sortable.addEventListener("dragover", (event) => {
        if (!dragged) return;
        event.preventDefault();
        const target = event.target.closest("[data-training-card]");
        if (!target || target === dragged) return;
        const box = target.getBoundingClientRect();
        const insertAfter = event.clientY > box.top + box.height / 2;
        sortable.insertBefore(dragged, insertAfter ? target.nextSibling : target);
    });
}());
