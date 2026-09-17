(function () {
    const page = document.querySelector("[data-drive-page]");
    if (!page) return;

    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
    const folderDialog = page.querySelector("[data-drive-folder-dialog]");
    const renameDialog = page.querySelector("[data-drive-rename-dialog]");
    const previewDialog = page.querySelector("[data-drive-preview-dialog]");
    const fileInput = page.querySelector("[data-drive-file-input]");
    const uploadForm = page.querySelector("[data-drive-upload-form]");
    const dropzone = page.querySelector("[data-drive-dropzone]");
    const uploadProgress = page.querySelector("[data-drive-upload-progress]");
    const uploadBar = page.querySelector("[data-drive-upload-bar]");
    const uploadPercent = page.querySelector("[data-drive-upload-percent]");
    const uploadLabel = page.querySelector("[data-drive-upload-label]");
    const uploadStatus = page.querySelector("[data-drive-upload-status]");

    function openDialog(dialog) {
        if (!dialog) return;
        document.body.classList.add("drive-dialog-open");
        if (typeof dialog.showModal === "function") dialog.showModal();
        else dialog.setAttribute("open", "");
    }

    function closeDialog(dialog) {
        if (!dialog) return;
        if (dialog === previewDialog) {
            previewDialog.querySelector("[data-drive-preview-frame]").src = "about:blank";
        }
        if (typeof dialog.close === "function" && dialog.open) dialog.close();
        else dialog.removeAttribute("open");
        if (!document.querySelector(".drive-dialog[open], .drive-preview[open]")) {
            document.body.classList.remove("drive-dialog-open");
        }
    }

    page.querySelector("[data-drive-new-folder]")?.addEventListener("click", () => {
        openDialog(folderDialog);
        folderDialog.querySelector("[data-drive-folder-name]").focus();
    });

    page.querySelectorAll("[data-drive-rename]").forEach((button) => {
        button.addEventListener("click", () => {
            const form = renameDialog.querySelector("[data-drive-rename-form]");
            const input = renameDialog.querySelector("[data-drive-rename-input]");
            form.action = button.dataset.action;
            input.value = button.dataset.name || "";
            renameDialog.querySelector("[data-drive-rename-title]").textContent = `Переименовать: ${button.dataset.kind || "Объект"}`;
            button.closest("details")?.removeAttribute("open");
            openDialog(renameDialog);
            input.focus();
            input.select();
        });
    });

    page.querySelectorAll("[data-drive-preview]").forEach((button) => {
        button.addEventListener("click", () => {
            previewDialog.querySelector("[data-drive-preview-title]").textContent = button.dataset.name || "Предпросмотр";
            previewDialog.querySelector("[data-drive-preview-frame]").src = button.dataset.previewUrl;
            openDialog(previewDialog);
        });
    });

    page.querySelectorAll(".drive-dialog, .drive-preview").forEach((dialog) => {
        dialog.querySelectorAll("[data-drive-dialog-close]").forEach((button) => {
            button.addEventListener("click", () => closeDialog(dialog));
        });
        dialog.addEventListener("click", (event) => {
            if (event.target === dialog) closeDialog(dialog);
        });
        dialog.addEventListener("cancel", (event) => {
            event.preventDefault();
            closeDialog(dialog);
        });
        dialog.addEventListener("close", () => {
            if (dialog === previewDialog) previewDialog.querySelector("[data-drive-preview-frame]").src = "about:blank";
            if (!document.querySelector(".drive-dialog[open], .drive-preview[open]")) {
                document.body.classList.remove("drive-dialog-open");
            }
        });
    });

    function showUploadStatus(message, isError) {
        uploadStatus.textContent = message;
        uploadStatus.classList.toggle("is-error", Boolean(isError));
    }

    function validateFiles(files) {
        if (!files.length) return "Выберите хотя бы один файл";
        if (files.length > 20) return "За один раз можно загрузить не больше 20 файлов";
        const maxFileBytes = Number(page.dataset.maxFileMb || 100) * 1024 * 1024;
        const maxRequestBytes = Number(page.dataset.requestMaxMb || 250) * 1024 * 1024;
        const oversized = files.find((file) => file.size > maxFileBytes);
        if (oversized) return `Файл «${oversized.name}» больше ${page.dataset.maxFileMb} МБ`;
        const total = files.reduce((sum, file) => sum + file.size, 0);
        if (total > maxRequestBytes) return `Общий размер загрузки больше ${page.dataset.requestMaxMb} МБ`;
        return "";
    }

    function uploadFiles(fileList) {
        const files = Array.from(fileList || []);
        const error = validateFiles(files);
        if (error) {
            showUploadStatus(error, true);
            return;
        }

        const formData = new FormData();
        files.forEach((file) => formData.append("files", file));
        const folderId = uploadForm.querySelector('input[name="folder_id"]')?.value;
        if (folderId) formData.append("folder_id", folderId);

        uploadProgress.hidden = false;
        uploadBar.value = 0;
        uploadPercent.textContent = "0%";
        uploadLabel.textContent = files.length === 1 ? files[0].name : `Файлов: ${files.length}`;
        showUploadStatus("", false);
        dropzone.setAttribute("aria-disabled", "true");

        const xhr = new XMLHttpRequest();
        xhr.open("POST", uploadForm.action);
        xhr.setRequestHeader("Accept", "application/json");
        if (csrfToken) xhr.setRequestHeader("X-CSRFToken", csrfToken);
        xhr.upload.addEventListener("progress", (event) => {
            if (!event.lengthComputable) return;
            const percent = Math.min(100, Math.round((event.loaded / event.total) * 100));
            uploadBar.value = percent;
            uploadPercent.textContent = `${percent}%`;
        });
        xhr.addEventListener("load", () => {
            let payload = {};
            try {
                payload = JSON.parse(xhr.responseText || "{}");
            } catch (_error) {
                payload = {};
            }
            if (xhr.status >= 200 && xhr.status < 300 && payload.uploaded) {
                const failed = Array.isArray(payload.errors) ? payload.errors.length : 0;
                showUploadStatus(failed ? `Загружено: ${payload.uploaded}. Ошибок: ${failed}` : `Загружено: ${payload.uploaded}`, failed > 0);
                window.setTimeout(() => window.location.reload(), failed ? 1600 : 350);
                return;
            }
            uploadProgress.hidden = true;
            showUploadStatus(payload.error || (payload.errors || []).join("; ") || "Не удалось загрузить файлы", true);
            dropzone.removeAttribute("aria-disabled");
        });
        xhr.addEventListener("error", () => {
            uploadProgress.hidden = true;
            showUploadStatus("Соединение прервалось во время загрузки", true);
            dropzone.removeAttribute("aria-disabled");
        });
        xhr.send(formData);
    }

    page.querySelector("[data-drive-pick-files]")?.addEventListener("click", () => fileInput.click());
    dropzone?.addEventListener("click", () => fileInput.click());
    dropzone?.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            fileInput.click();
        }
    });
    fileInput?.addEventListener("change", () => uploadFiles(fileInput.files));

    ["dragenter", "dragover"].forEach((name) => {
        dropzone?.addEventListener(name, (event) => {
            event.preventDefault();
            dropzone.classList.add("is-dragover");
        });
    });
    ["dragleave", "drop"].forEach((name) => {
        dropzone?.addEventListener(name, (event) => {
            event.preventDefault();
            dropzone.classList.remove("is-dragover");
        });
    });
    dropzone?.addEventListener("drop", (event) => uploadFiles(event.dataTransfer.files));

    document.addEventListener("click", (event) => {
        page.querySelectorAll(".drive-actions[open]").forEach((details) => {
            if (!details.contains(event.target)) details.removeAttribute("open");
        });
    });
}());
