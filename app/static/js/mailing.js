const fieldsMeta = window.MAILING_FIELDS || [];
const rulesContainer = document.getElementById("rulesContainer");
const audienceCountEl = document.getElementById("audienceCount");
const giveawayAudienceCountEl = document.getElementById("giveawayAudienceCount");
const giveawayRulesContainer = document.getElementById("giveawayRulesContainer");
const addGiveawayRuleBtn = document.getElementById("addGiveawayRuleBtn");
const previewGiveawayBtn = document.getElementById("previewGiveawayBtn");
const copyMailingRulesToGiveawayBtn = document.getElementById("copyMailingRulesToGiveawayBtn");
const giveawayBonusAmountEl = document.getElementById("giveawayBonusAmount");
const giveawayMessageTextEl = document.getElementById("giveawayMessageText");
const sendBonusGiveawayBtn = document.getElementById("sendBonusGiveawayBtn");
const filesListEl = document.getElementById("filesList");
const messageTextEl = document.getElementById("messageText");
const modalEl = document.getElementById("mailingConfirmModal");
const modalRecipientsCountEl = document.getElementById("modalRecipientsCount");
const modalFilesCountEl = document.getElementById("modalFilesCount");
const modalMessagePreviewEl = document.getElementById("modalMessagePreview");
const modalConfirmSendBtn = document.getElementById("modalConfirmSendBtn");

let uploadedFiles = [];
let currentSegmentId = null;

function createOption(value, label) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    return option;
}

const OPERATOR_LABELS = {
    "=": "Равно",
    "!=": "Не равно",
    ">": "Больше чем",
    ">=": "Не меньше чем",
    "<": "Меньше чем",
    "<=": "Не больше чем",
    "between": "В диапазоне",
    "in": "Один из вариантов",
    "not_in": "Не входит в варианты",
    "is_null": "Не заполнено",
    "is_not_null": "Заполнено",
};

function getOperatorLabel(op) {
    return OPERATOR_LABELS[op] || op;
}

function getFieldMeta(fieldKey) {
    return fieldsMeta.find((item) => item.key === fieldKey);
}

function getRules(container = rulesContainer) {
    if (!container) return [];
    const rows = Array.from(container.querySelectorAll(".rule-row"));
    return rows.map((row) => {
        const field = row.querySelector(".rule-field").value;
        const op = row.querySelector(".rule-op").value;
        const valueEl = row.querySelector(".rule-value");
        let value = valueEl.value;

        if (valueEl.multiple) {
            value = Array.from(valueEl.selectedOptions).map((option) => option.value);
        }

        const valueTo = row.querySelector(".rule-value-to").value;
        return { field, op, value, value_to: valueTo };
    }).filter((rule) => rule.field && rule.op);
}

function buildOpOptions(fieldType) {
    if (fieldType === "number") return ["=", "!=", ">", ">=", "<", "<=", "between"];
    if (fieldType === "date") return ["=", "!=", ">", ">=", "<", "<=", "between", "is_null", "is_not_null"];
    if (fieldType === "enum") return ["=", "!=", "in", "not_in"];
    if (fieldType === "bool") return ["="];
    if (fieldType === "phone_list") return ["="];
    return ["="];
}

function renderValueInputs(row, meta) {
    const valueInput = row.querySelector(".rule-value");
    const valueToInput = row.querySelector(".rule-value-to");
    const opSelect = row.querySelector(".rule-op");

    valueInput.innerHTML = "";
    valueToInput.style.display = opSelect.value === "between" ? "" : "none";

    if (meta.type === "enum") {
        const select = document.createElement("select");
        select.className = "rule-value";
        if (opSelect.value === "in" || opSelect.value === "not_in") {
            select.multiple = true;
        }
        (meta.options || []).forEach((item) => {
            select.appendChild(createOption(item.value, item.label));
        });
        row.replaceChild(select, row.querySelector(".rule-value"));
    } else if (meta.type === "bool") {
        const select = document.createElement("select");
        select.className = "rule-value";
        select.appendChild(createOption("1", "Да"));
        select.appendChild(createOption("0", "Нет"));
        row.replaceChild(select, row.querySelector(".rule-value"));
    } else {
        const input = document.createElement("input");
        input.className = "rule-value";
        input.type = meta.type === "date" ? "date" : "text";
        if (meta.type === "phone_list") {
            input.placeholder = "Например: +79991234567; 89997654321";
        }
        row.replaceChild(input, row.querySelector(".rule-value"));
    }

    const currentValueTo = row.querySelector(".rule-value-to");
    if (currentValueTo.tagName !== "INPUT") {
        const inputTo = document.createElement("input");
        inputTo.className = "rule-value-to";
        inputTo.type = meta.type === "date" ? "date" : "text";
        row.replaceChild(inputTo, currentValueTo);
    }
    row.querySelector(".rule-value-to").style.display = opSelect.value === "between" ? "" : "none";
}

function addRule(rule = {}, targetContainer = rulesContainer) {
    const row = document.createElement("div");
    row.className = "rule-row";

    const fieldSelect = document.createElement("select");
    fieldSelect.className = "rule-field";
    fieldSelect.appendChild(createOption("", "Поле"));
    fieldsMeta.forEach((field) => {
        fieldSelect.appendChild(createOption(field.key, field.label));
    });

    const opSelect = document.createElement("select");
    opSelect.className = "rule-op";
    opSelect.appendChild(createOption("", "Оператор"));

    const valueInput = document.createElement("input");
    valueInput.className = "rule-value";
    valueInput.placeholder = "Значение";

    const valueToInput = document.createElement("input");
    valueToInput.className = "rule-value-to";
    valueToInput.placeholder = "До";
    valueToInput.style.display = "none";

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "btn btn-danger-soft";
    removeBtn.textContent = "X";
    removeBtn.title = "Удалить фильтр";

    removeBtn.addEventListener("click", () => row.remove());

    fieldSelect.addEventListener("change", () => {
        const meta = getFieldMeta(fieldSelect.value);
        opSelect.innerHTML = "";
        opSelect.appendChild(createOption("", "Оператор"));
        if (!meta) return;
        buildOpOptions(meta.type).forEach((op) => {
            opSelect.appendChild(createOption(op, getOperatorLabel(op)));
        });
        renderValueInputs(row, meta);
    });

    opSelect.addEventListener("change", () => {
        const meta = getFieldMeta(fieldSelect.value);
        if (!meta) return;
        renderValueInputs(row, meta);
    });

    row.appendChild(fieldSelect);
    row.appendChild(opSelect);
    row.appendChild(valueInput);
    row.appendChild(valueToInput);
    row.appendChild(removeBtn);

    targetContainer.appendChild(row);

    if (rule.field) {
        fieldSelect.value = rule.field;
        fieldSelect.dispatchEvent(new Event("change"));
    }
    if (rule.op) {
        opSelect.value = rule.op;
        opSelect.dispatchEvent(new Event("change"));
    }

    const currentValueEl = row.querySelector(".rule-value");
    if (currentValueEl) {
        if (currentValueEl.multiple && Array.isArray(rule.value)) {
            Array.from(currentValueEl.options).forEach((opt) => {
                opt.selected = rule.value.includes(opt.value) || rule.value.includes(Number(opt.value));
            });
        } else if (rule.value !== undefined) {
            currentValueEl.value = rule.value;
        }
    }

    if (rule.value_to !== undefined) {
        row.querySelector(".rule-value-to").value = rule.value_to;
    }
}

async function previewSegment() {
    const response = await fetch("/owner/api/segments/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rules: getRules(rulesContainer) }),
    });
    const data = await response.json();
    if (!data.ok) {
        alert(data.error || "Не удалось посчитать аудиторию");
        return;
    }
    audienceCountEl.textContent = data.count;
}

async function saveSegment() {
    const name = document.getElementById("segmentName").value.trim();
    if (!name) {
        alert("Укажи название сегмента");
        return;
    }

    const response = await fetch("/owner/api/segments/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            name,
            rules: getRules(rulesContainer),
        }),
    });
    const data = await response.json();
    if (!data.ok) {
        alert(data.error || "Не удалось сохранить сегмент");
        return;
    }
    window.location.reload();
}

async function deleteSegment(segmentId) {
    const response = await fetch(`/owner/api/segments/${segmentId}`, { method: "DELETE" });
    const data = await response.json();
    if (!data.ok) {
        alert(data.error || "Не удалось удалить сегмент");
        return;
    }
    window.location.reload();
}

async function uploadFiles(files) {
    const formData = new FormData();
    Array.from(files).forEach((file) => formData.append("files", file));

    const response = await fetch("/owner/api/mailings/upload", {
        method: "POST",
        body: formData,
    });
    const data = await response.json();
    if (!data.ok) {
        alert(data.error || "Не удалось загрузить файлы");
        return;
    }

    uploadedFiles = uploadedFiles.concat(data.files);
    renderUploadedFiles();
}

function renderUploadedFiles() {
    filesListEl.innerHTML = "";
    uploadedFiles.forEach((file, index) => {
        const row = document.createElement("div");
        row.className = "file-item";
        row.innerHTML = `
            <div>${file.original_name} <small>(${file.file_type})</small></div>
            <button type="button" class="btn btn-danger-soft">Удалить</button>
        `;
        row.querySelector("button").addEventListener("click", () => {
            uploadedFiles.splice(index, 1);
            renderUploadedFiles();
        });
        filesListEl.appendChild(row);
    });
}

async function getRecipientsPreviewCount(rules = getRules(rulesContainer), targetEl = audienceCountEl) {
    const response = await fetch("/owner/api/segments/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rules }),
    });
    const data = await response.json();
    if (!data.ok) {
        throw new Error(data.error || "Не удалось посчитать аудиторию");
    }
    if (targetEl) {
        targetEl.textContent = data.count;
    }
    return data.count;
}

async function previewGiveawayAudience() {
    return getRecipientsPreviewCount(getRules(giveawayRulesContainer), giveawayAudienceCountEl);
}


function escapeHtml(value) {
    return value
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function openMailingModal(recipientsCount, messageText) {
    modalRecipientsCountEl.textContent = recipientsCount;
    modalFilesCountEl.textContent = uploadedFiles.length;
    modalMessagePreviewEl.innerHTML = escapeHtml(messageText).replaceAll("\n", "<br>");
    modalEl.classList.add("is-open");
    modalEl.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    requestAnimationFrame(function () {
        void modalEl.offsetWidth;
    });
}

function closeMailingModal() {
    modalEl.classList.remove("is-open");
    modalEl.setAttribute("aria-hidden", "true");
    const hm = document.getElementById("mailingHistoryModal");
    const hint = document.getElementById("mailingAudienceHintModal");
    if ((!hm || !hm.classList.contains("is-open")) && (!hint || !hint.classList.contains("is-open"))) {
        document.body.style.overflow = "";
    }
}

async function openMailingConfirm() {
    const messageText = messageTextEl.value.trim();
    if (!messageText) {
        alert("Введи текст сообщения");
        return;
    }

    try {
        const recipientsCount = await getRecipientsPreviewCount(getRules(rulesContainer), audienceCountEl);
        openMailingModal(recipientsCount, messageText);
    } catch (error) {
        alert(error.message || "Не удалось подготовить предпросмотр");
    }
}

async function createMailing() {
    const messageText = messageTextEl.value.trim();
    if (!messageText) {
        alert("Введи текст сообщения");
        return;
    }

    modalConfirmSendBtn.disabled = true;
    modalConfirmSendBtn.textContent = "Отправляю...";

    try {
        const response = await fetch("/owner/api/mailings/create", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                segment_id: currentSegmentId,
                rules: getRules(rulesContainer),
                message_text: messageText,
                attachments: uploadedFiles,
                start_now: true,
            }),
        });
        const data = await response.json();
        if (!data.ok) {
            alert(data.error || "Не удалось создать рассылку");
            return;
        }

        alert(`Рассылка запущена. Получателей: ${data.recipients_count}`);
        window.location.reload();
    } finally {
        modalConfirmSendBtn.disabled = false;
        modalConfirmSendBtn.textContent = "Отправить";
    }
}


async function createBonusGiveaway() {
    if (!giveawayBonusAmountEl || !giveawayMessageTextEl || !sendBonusGiveawayBtn) {
        return;
    }

    const bonusAmount = Number(giveawayBonusAmountEl.value || 0);
    const messageText = giveawayMessageTextEl.value.trim();

    if (!Number.isFinite(bonusAmount) || bonusAmount <= 0) {
        alert("Укажи количество бонусов больше 0");
        return;
    }

    if (!messageText) {
        alert("Введи текст сообщения для гостей");
        return;
    }

    let recipientsCount = 0;
    try {
        recipientsCount = await previewGiveawayAudience();
    } catch (error) {
        alert(error.message || "Не удалось посчитать аудиторию");
        return;
    }

    if (recipientsCount <= 0) {
        alert("По текущим фильтрам нет гостей с Telegram");
        return;
    }

    const confirmed = confirm(`Начислить ${bonusAmount} бонусов ${recipientsCount} гостям и отправить им сообщение?`);
    if (!confirmed) {
        return;
    }

    sendBonusGiveawayBtn.disabled = true;
    sendBonusGiveawayBtn.textContent = "Запускаю...";

    try {
        const response = await fetch("/owner/api/bonus-giveaways/create", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                rules: getRules(giveawayRulesContainer),
                bonus_amount: bonusAmount,
                message_text: messageText,
                start_now: true,
            }),
        });
        const data = await response.json();
        if (!data.ok) {
            alert(data.error || "Не удалось запустить раздачу");
            return;
        }

        alert(`Раздача запущена. Получателей: ${data.recipients_count}. Начислено: ${data.awarded_count}.`);
        window.location.reload();
    } catch (error) {
        alert(error.message || "Не удалось запустить раздачу");
    } finally {
        sendBonusGiveawayBtn.disabled = false;
        sendBonusGiveawayBtn.textContent = "Отправить раздачу";
    }
}

function applySegmentRules(rulesJson, segmentId = null) {
    currentSegmentId = segmentId;
    rulesContainer.innerHTML = "";
    const rules = (rulesJson && rulesJson.rules) || [];
    rules.forEach((rule) => addRule(rule, rulesContainer));

    if (!rules.length) {
        addRule({}, rulesContainer);
    }
}

function clearActiveCrmSegmentCards() {
    document.querySelectorAll(".crm-segment-card").forEach((card) => {
        card.classList.remove("is-active");
    });
}

async function applyCrmSegment(card) {
    clearActiveCrmSegmentCards();
    card.classList.add("is-active");

    const rules = JSON.parse(card.dataset.rules);
    applySegmentRules(rules, null);

    try {
        await previewSegment();
    } catch (error) {
        console.error(error);
    }
}

function wrapSelection(tag) {
    const textarea = messageTextEl;
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const selected = textarea.value.substring(start, end);
    const wrapped = `<${tag}>${selected}</${tag}>`;
    textarea.setRangeText(wrapped, start, end, "end");
    textarea.focus();
}

function insertLink() {
    const url = prompt("Вставь ссылку");
    if (!url) return;
    const text = prompt("Текст ссылки", "ссылка") || "ссылка";

    const textarea = messageTextEl;
    const start = textarea.selectionStart;
    textarea.setRangeText(`<a href="${url}">${text}</a>`, start, textarea.selectionEnd, "end");
    textarea.focus();
}

document.getElementById("addRuleBtn").addEventListener("click", () => addRule({}, rulesContainer));
document.getElementById("previewBtn").addEventListener("click", previewSegment);
document.getElementById("saveSegmentBtn").addEventListener("click", saveSegment);
document.getElementById("sendMailingBtn").addEventListener("click", openMailingConfirm);
if (sendBonusGiveawayBtn) {
    sendBonusGiveawayBtn.addEventListener("click", createBonusGiveaway);
}
if (addGiveawayRuleBtn && giveawayRulesContainer) {
    addGiveawayRuleBtn.addEventListener("click", () => addRule({}, giveawayRulesContainer));
}
if (previewGiveawayBtn) {
    previewGiveawayBtn.addEventListener("click", () => {
        previewGiveawayAudience().catch((error) => alert(error.message || "Не удалось посчитать получателей раздачи"));
    });
}
if (copyMailingRulesToGiveawayBtn && giveawayRulesContainer) {
    copyMailingRulesToGiveawayBtn.addEventListener("click", async () => {
        giveawayRulesContainer.innerHTML = "";
        const rules = getRules(rulesContainer);
        rules.forEach((rule) => addRule(rule, giveawayRulesContainer));
        if (!rules.length) {
            addRule({}, giveawayRulesContainer);
        }
        try {
            await previewGiveawayAudience();
        } catch (error) {
            console.error(error);
        }
    });
}
document.getElementById("filesInput").addEventListener("change", (e) => uploadFiles(e.target.files));

document.querySelectorAll(".segment-chip__delete").forEach((btn) => {
    btn.addEventListener("click", () => deleteSegment(btn.dataset.id));
});

document.querySelectorAll(".segment-chip__use").forEach((btn) => {
    btn.addEventListener("click", () => {
        clearActiveCrmSegmentCards();
        const parent = btn.closest(".segment-chip");
        const rules = JSON.parse(parent.dataset.rules);
        applySegmentRules(rules, parent.dataset.id);
        previewSegment();
    });
});

document.querySelectorAll(".crm-segment-card").forEach((card) => {
    card.addEventListener("click", () => applyCrmSegment(card));
});

document.querySelectorAll(".editor-toolbar button[data-tag]").forEach((btn) => {
    btn.addEventListener("click", () => wrapSelection(btn.dataset.tag));
});

document.getElementById("insertLinkBtn").addEventListener("click", insertLink);
document.getElementById("modalConfirmSendBtn").addEventListener("click", createMailing);
document.getElementById("modalEditBtn").addEventListener("click", closeMailingModal);
document.getElementById("mailingModalClose").addEventListener("click", closeMailingModal);
document.getElementById("mailingModalOverlay").addEventListener("click", closeMailingModal);

const historyModalEl = document.getElementById("mailingHistoryModal");
const openHistoryBtn = document.getElementById("openMailingHistoryBtn");
const closeHistoryBtn = document.getElementById("closeMailingHistoryBtn");
const historyBackdrop = document.getElementById("mailingHistoryBackdrop");

function openMailingHistoryModal() {
    if (!historyModalEl) return;
    historyModalEl.classList.add("is-open");
    historyModalEl.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    requestAnimationFrame(function () {
        void historyModalEl.offsetWidth;
    });
}

function closeMailingHistoryModal() {
    if (!historyModalEl) return;
    historyModalEl.classList.remove("is-open");
    historyModalEl.setAttribute("aria-hidden", "true");
    const hint = document.getElementById("mailingAudienceHintModal");
    if ((!modalEl || !modalEl.classList.contains("is-open")) && (!hint || !hint.classList.contains("is-open"))) {
        document.body.style.overflow = "";
    }
}

const mailingAudienceHintModal = document.getElementById("mailingAudienceHintModal");
const mailingAudienceHelpBtn = document.getElementById("mailingAudienceHelpBtn");
const mailingAudienceHintClose = document.getElementById("mailingAudienceHintClose");
const mailingAudienceHintOk = document.getElementById("mailingAudienceHintOk");

function openMailingAudienceHintModal() {
    if (!mailingAudienceHintModal) return;
    mailingAudienceHintModal.classList.add("is-open");
    mailingAudienceHintModal.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
}

function closeMailingAudienceHintModal() {
    if (!mailingAudienceHintModal) return;
    mailingAudienceHintModal.classList.remove("is-open");
    mailingAudienceHintModal.setAttribute("aria-hidden", "true");
    if ((!modalEl || !modalEl.classList.contains("is-open")) && (!historyModalEl || !historyModalEl.classList.contains("is-open"))) {
        document.body.style.overflow = "";
    }
}

if (mailingAudienceHelpBtn) {
    mailingAudienceHelpBtn.addEventListener("click", openMailingAudienceHintModal);
}
if (mailingAudienceHintClose) {
    mailingAudienceHintClose.addEventListener("click", closeMailingAudienceHintModal);
}
if (mailingAudienceHintOk) {
    mailingAudienceHintOk.addEventListener("click", closeMailingAudienceHintModal);
}
if (mailingAudienceHintModal) {
    mailingAudienceHintModal.addEventListener("click", function (event) {
        if (event.target === mailingAudienceHintModal) {
            closeMailingAudienceHintModal();
        }
    });
}

if (openHistoryBtn) {
    openHistoryBtn.addEventListener("click", openMailingHistoryModal);
}
if (closeHistoryBtn) {
    closeHistoryBtn.addEventListener("click", closeMailingHistoryModal);
}
if (historyBackdrop) {
    historyBackdrop.addEventListener("click", closeMailingHistoryModal);
}

document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    if (mailingAudienceHintModal && mailingAudienceHintModal.classList.contains("is-open")) {
        closeMailingAudienceHintModal();
        return;
    }
    if (historyModalEl && historyModalEl.classList.contains("is-open")) {
        closeMailingHistoryModal();
    }
    if (modalEl && modalEl.classList.contains("is-open")) {
        closeMailingModal();
    }
});

// стартовая пустая строка
if (!document.querySelector(".rule-row")) {
    addRule();
}
// Вкладки: ручная рассылка / авторассылки
const mailingTabs = document.querySelectorAll(".mailing-tab");
const mailingTabPanels = document.querySelectorAll(".mailing-tab-panel");

mailingTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
        const tabName = tab.dataset.tab;
        mailingTabs.forEach((item) => item.classList.remove("is-active"));
        mailingTabPanels.forEach((panel) => panel.classList.remove("is-active"));
        tab.classList.add("is-active");
        const targetPanel = document.querySelector(`[data-tab-panel="${tabName}"]`);
        if (targetPanel) targetPanel.classList.add("is-active");
    });
});

// Настройки авторассылок
function getAutoMailingPayload(card) {
    const toggle = card.querySelector(".auto-mailing-toggle");
    const daysInput = card.querySelector(".auto-mailing-days");
    const bonusInput = card.querySelector(".auto-mailing-bonus");

    const code = card.dataset.autoMailingCode || "";
    return {
        is_enabled: Boolean(toggle && toggle.checked),
        days_inactive: Number(daysInput ? daysInput.value : (code === "first_visit_survey" ? 1 : 14)),
        bonus_amount: Number(bonusInput ? bonusInput.value : 200),
    };
}

function setAutoMailingStatus(card, text, isError = false) {
    const status = card.querySelector(".auto-mailing-save-status");
    if (!status) return;
    status.textContent = text || "";
    status.classList.toggle("is-error", Boolean(isError));

    if (text && !isError) {
        window.setTimeout(() => {
            if (status.textContent === text) {
                status.textContent = "";
            }
        }, 2200);
    }
}

async function saveAutoMailing(card, options = {}) {
    const code = card.dataset.autoMailingCode || (card.querySelector(".auto-mailing-toggle") || {}).dataset.code;
    const toggle = card.querySelector(".auto-mailing-toggle");
    const saveBtn = card.querySelector(".auto-mailing-save");
    const daysInput = card.querySelector(".auto-mailing-days");
    const bonusInput = card.querySelector(".auto-mailing-bonus");
    const messageBox = card.querySelector(".auto-mailing-card__message");
    const previousChecked = toggle ? !toggle.checked : false;

    if (!code) return;

    const payload = getAutoMailingPayload(card);
    if (code !== "first_visit_survey" && (!Number.isFinite(payload.days_inactive) || payload.days_inactive < 1)) {
        setAutoMailingStatus(card, "Укажи дни неактива больше 0", true);
        if (toggle && options.fromToggle) toggle.checked = previousChecked;
        return;
    }
    if (!Number.isFinite(payload.bonus_amount) || payload.bonus_amount < 1) {
        setAutoMailingStatus(card, "Укажи бонусы больше 0", true);
        if (toggle && options.fromToggle) toggle.checked = previousChecked;
        return;
    }

    [toggle, saveBtn, daysInput, bonusInput].forEach((el) => {
        if (el) el.disabled = true;
    });
    setAutoMailingStatus(card, "Сохраняем...");

    try {
        const response = await fetch(`/owner/api/auto-mailings/${code}/toggle`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await response.json();
        if (!data.ok) {
            if (toggle && options.fromToggle) toggle.checked = previousChecked;
            setAutoMailingStatus(card, data.error || "Не удалось сохранить", true);
            return;
        }

        if (data.auto_mailing) {
            if (toggle) toggle.checked = Boolean(Number(data.auto_mailing.is_enabled));
            if (daysInput) daysInput.value = data.auto_mailing.days_inactive || payload.days_inactive;
            if (bonusInput) bonusInput.value = data.auto_mailing.bonus_amount || payload.bonus_amount;
            if (messageBox && data.auto_mailing.message_text) {
                messageBox.textContent = data.auto_mailing.message_text;
            }
        }
        setAutoMailingStatus(card, "Сохранено");
    } catch (error) {
        if (toggle && options.fromToggle) toggle.checked = previousChecked;
        setAutoMailingStatus(card, "Не удалось сохранить", true);
    } finally {
        [toggle, saveBtn, daysInput, bonusInput].forEach((el) => {
            if (el) el.disabled = false;
        });
    }
}

document.querySelectorAll(".auto-mailing-toggle").forEach((input) => {
    input.addEventListener("change", () => {
        const card = input.closest(".auto-mailing-card");
        if (card) saveAutoMailing(card, { fromToggle: true });
    });
});

document.querySelectorAll(".auto-mailing-save").forEach((button) => {
    button.addEventListener("click", () => {
        const card = button.closest(".auto-mailing-card");
        if (card) saveAutoMailing(card);
    });
});


if (giveawayRulesContainer && !giveawayRulesContainer.querySelector(".rule-row")) {
    addRule({}, giveawayRulesContainer);
}
