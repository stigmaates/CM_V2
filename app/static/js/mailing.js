const fieldsMeta = window.MAILING_FIELDS || [];
const messageVariablesMeta = window.MAILING_VARIABLES || [];
const rulesContainer = document.getElementById("rulesContainer");
const audienceCountEl = document.getElementById("audienceCount");
const giveawayAudienceCountEl = audienceCountEl;
const giveawayRulesContainer = rulesContainer;
const addGiveawayRuleBtn = null;
const previewGiveawayBtn = null;
const copyMailingRulesToGiveawayBtn = null;
const giveawayBonusEnabledEl = document.getElementById("giveawayBonusEnabled");
const giveawayTokenEnabledEl = document.getElementById("giveawayTokenEnabled");
const giveawayBonusAmountEl = document.getElementById("giveawayBonusAmount");
const giveawayTokenAmountEl = document.getElementById("giveawayTokenAmount");
const giveawayExpiringBonusEl = document.getElementById("giveawayExpiringBonus");
const giveawayExpirationControlsEl = document.getElementById("giveawayExpirationControls");
const giveawayExpiresValueEl = document.getElementById("giveawayExpiresValue");
const giveawayExpiresUnitEl = document.getElementById("giveawayExpiresUnit");
const giveawayMessageTextEl = document.getElementById("messageText");
const sendBonusGiveawayBtn = null;
const filesListEl = document.getElementById("filesList");
const messageTextEl = document.getElementById("messageText");
const messageVariableSelect = document.getElementById("messageVariableSelect");
const insertMessageVariableBtn = document.getElementById("insertMessageVariableBtn");
const giveawayVariableSelect = document.getElementById("giveawayVariableSelect");
const insertGiveawayVariableBtn = document.getElementById("insertGiveawayVariableBtn");
const modalEl = document.getElementById("mailingConfirmModal");
const modalRecipientsCountEl = document.getElementById("modalRecipientsCount");
const modalFilesCountEl = document.getElementById("modalFilesCount");
const modalMessagePreviewEl = document.getElementById("modalMessagePreview");
const modalConfirmSendBtn = document.getElementById("modalConfirmSendBtn");
const messageCharacterCountEl = document.getElementById("messageCharacterCount");
const campaignMessagePreviewEl = document.getElementById("campaignMessagePreview");
const summaryAudienceCountEl = document.getElementById("summaryAudienceCount");
const summaryRewardsEl = document.getElementById("summaryRewards");
const summaryExpirationEl = document.getElementById("summaryExpiration");
const summaryCharactersEl = document.getElementById("summaryCharacters");
const summaryFilesEl = document.getElementById("summaryFiles");

let uploadedFiles = [];
let currentSegmentId = null;

function createOption(value, label) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    return option;
}

function populateVariableSelect(selectEl) {
    if (!selectEl) return;
    selectEl.innerHTML = "";
    messageVariablesMeta.forEach((item) => {
        const label = item.description ? `${item.label} · ${item.token}` : `${item.label}`;
        selectEl.appendChild(createOption(item.token, label));
    });
}

function insertAtCursor(textarea, value) {
    if (!textarea || !value) return;
    const start = textarea.selectionStart ?? textarea.value.length;
    const end = textarea.selectionEnd ?? textarea.value.length;
    textarea.setRangeText(value, start, end, "end");
    textarea.focus();
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
}

function insertSelectedVariable(selectEl, textarea) {
    if (!selectEl || !textarea) return;
    insertAtCursor(textarea, selectEl.value);
}

async function readApiResponse(response, fallbackMessage) {
    const body = await response.text();
    if (body) {
        try {
            return JSON.parse(body);
        } catch (_error) {
            // Nginx and Flask can return an HTML error page. Do not expose its markup in the UI.
        }
    }
    return {
        ok: false,
        error: response.status === 413
            ? "Файл слишком большой для загрузки"
            : (fallbackMessage || `Ошибка сервера (${response.status})`),
    };
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
    if (summaryAudienceCountEl) summaryAudienceCountEl.textContent = data.count;
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
    updateCampaignSummary();
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
    if (summaryAudienceCountEl) summaryAudienceCountEl.textContent = data.count;
    return data.count;
}

async function previewGiveawayAudience() {
    return getRecipientsPreviewCount(getRules(giveawayRulesContainer), giveawayAudienceCountEl);
}


function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function openMailingModal(recipientsCount, messageText) {
    modalRecipientsCountEl.textContent = recipientsCount;
    modalFilesCountEl.textContent = uploadedFiles.length;
    renderTelegramMessagePreview(modalMessagePreviewEl, messageText);
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
    const hm = document.getElementById("crmInteractionModal");
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
        if (recipientsCount <= 0) {
            alert("По текущим фильтрам нет гостей с Telegram");
            return;
        }
        getCampaignRewardPayload(true);
        openMailingModal(recipientsCount, messageText);
    } catch (error) {
        alert(error.message || "Не удалось подготовить предпросмотр");
    }
}

function getCampaignRewardPayload(validate = false) {
    const bonusEnabled = Boolean(giveawayBonusEnabledEl && giveawayBonusEnabledEl.checked);
    const tokenEnabled = Boolean(giveawayTokenEnabledEl && giveawayTokenEnabledEl.checked);
    const bonusAmount = bonusEnabled ? Number(giveawayBonusAmountEl.value || 0) : 0;
    const tokenAmount = tokenEnabled ? Number(giveawayTokenAmountEl.value || 0) : 0;
    const isExpiring = Boolean((bonusEnabled || tokenEnabled) && giveawayExpiringBonusEl && giveawayExpiringBonusEl.checked);
    const expiresValue = Number(giveawayExpiresValueEl ? giveawayExpiresValueEl.value || 0 : 0);
    const expiresUnit = giveawayExpiresUnitEl ? giveawayExpiresUnitEl.value : "days";

    if (validate && bonusEnabled && (!Number.isFinite(bonusAmount) || bonusAmount <= 0)) {
        throw new Error("Укажи количество КБ больше 0");
    }
    if (validate && tokenEnabled && (!Number.isFinite(tokenAmount) || tokenAmount <= 0)) {
        throw new Error("Укажи количество жетонов больше 0");
    }
    if (validate && isExpiring && (!Number.isFinite(expiresValue) || expiresValue < 1)) {
        throw new Error("Укажи срок сгорания больше 0");
    }

    return {
        hasRewards: bonusAmount > 0 || tokenAmount > 0,
        bonusAmount,
        tokenAmount,
        isExpiring,
        expiresValue,
        expiresUnit,
    };
}

function sampleMessageText(value) {
    const samples = {
        "{name}": "Алексей",
        "{first_name}": "Алексей",
        "{fio}": "Алексей Смирнов",
        "{club_name}": "Ваш клуб",
        "{cm_bonus_balance}": "250",
        "{kb_balance}": "250",
        "{token_balance}": "3",
        "{tokens_balance}": "3",
    };
    let result = String(value || "");
    Object.entries(samples).forEach(([token, sample]) => {
        result = result.replaceAll(token, sample);
    });
    return result || "Здесь появится текст сообщения";
}

function normalizeLinkUrl(value, addMissingScheme = true) {
    let candidate = String(value || "").trim();
    if (!candidate) return null;
    if (addMissingScheme && !/^[a-z][a-z0-9+.-]*:\/\//i.test(candidate)) {
        candidate = `https://${candidate}`;
    }
    try {
        const parsed = new URL(candidate);
        return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : null;
    } catch (_error) {
        return null;
    }
}

function escapeTelegramHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
}

function appendTelegramPreviewNode(source, target) {
    if (source.nodeType === Node.TEXT_NODE) {
        target.appendChild(document.createTextNode(source.textContent || ""));
        return;
    }
    if (source.nodeType !== Node.ELEMENT_NODE) return;

    const tag = source.tagName.toLowerCase();
    if (tag === "br") {
        target.appendChild(document.createElement("br"));
        return;
    }

    const allowed = new Set(["b", "strong", "i", "em", "u", "a"]);
    if (!allowed.has(tag)) {
        Array.from(source.childNodes).forEach((child) => appendTelegramPreviewNode(child, target));
        return;
    }

    const previewTag = tag === "strong" ? "b" : tag === "em" ? "i" : tag;
    const element = document.createElement(previewTag);
    if (previewTag === "a") {
        const href = normalizeLinkUrl(source.getAttribute("href"), false);
        if (!href) {
            Array.from(source.childNodes).forEach((child) => appendTelegramPreviewNode(child, target));
            return;
        }
        element.href = href;
        element.target = "_blank";
        element.rel = "noopener noreferrer";
    }
    Array.from(source.childNodes).forEach((child) => appendTelegramPreviewNode(child, element));
    target.appendChild(element);
}

function renderTelegramMessagePreview(target, value) {
    if (!target) return;
    const parsed = new DOMParser().parseFromString(sampleMessageText(value), "text/html");
    const fragment = document.createDocumentFragment();
    Array.from(parsed.body.childNodes).forEach((node) => appendTelegramPreviewNode(node, fragment));
    target.replaceChildren(fragment);
}

function updateCampaignSummary() {
    const message = messageTextEl ? messageTextEl.value : "";
    const rewards = getCampaignRewardPayload(false);
    const rewardParts = [];
    if (rewards.bonusAmount > 0) rewardParts.push(`${rewards.bonusAmount} КБ`);
    if (rewards.tokenAmount > 0) rewardParts.push(`${rewards.tokenAmount} жет.`);

    if (messageCharacterCountEl) messageCharacterCountEl.textContent = message.length;
    if (summaryCharactersEl) summaryCharactersEl.textContent = message.length;
    if (summaryFilesEl) summaryFilesEl.textContent = uploadedFiles.length;
    if (summaryRewardsEl) summaryRewardsEl.textContent = rewardParts.length ? rewardParts.join(" · ") : "Без начислений";
    if (summaryExpirationEl) {
        const unitLabel = giveawayExpiresUnitEl && giveawayExpiresUnitEl.options[giveawayExpiresUnitEl.selectedIndex]
            ? giveawayExpiresUnitEl.options[giveawayExpiresUnitEl.selectedIndex].text
            : "дней";
        summaryExpirationEl.textContent = rewards.isExpiring ? `Через ${rewards.expiresValue} ${unitLabel}` : "Бессрочно";
    }
    renderTelegramMessagePreview(campaignMessagePreviewEl, message);
}

function syncRewardControls() {
    const bonusEnabled = Boolean(giveawayBonusEnabledEl && giveawayBonusEnabledEl.checked);
    const tokenEnabled = Boolean(giveawayTokenEnabledEl && giveawayTokenEnabledEl.checked);
    const hasRewards = bonusEnabled || tokenEnabled;

    if (giveawayBonusAmountEl) {
        giveawayBonusAmountEl.disabled = !bonusEnabled;
        if (bonusEnabled && Number(giveawayBonusAmountEl.value || 0) <= 0) giveawayBonusAmountEl.value = "200";
        if (!bonusEnabled) giveawayBonusAmountEl.value = "0";
    }
    if (giveawayTokenAmountEl) {
        giveawayTokenAmountEl.disabled = !tokenEnabled;
        if (tokenEnabled && Number(giveawayTokenAmountEl.value || 0) <= 0) giveawayTokenAmountEl.value = "1";
        if (!tokenEnabled) giveawayTokenAmountEl.value = "0";
    }
    if (giveawayExpiringBonusEl) {
        giveawayExpiringBonusEl.disabled = !hasRewards;
        if (!hasRewards) giveawayExpiringBonusEl.checked = false;
    }
    if (giveawayExpirationControlsEl) {
        giveawayExpirationControlsEl.classList.toggle("is-hidden", !hasRewards || !giveawayExpiringBonusEl.checked);
    }
    updateCampaignSummary();
}

async function createCampaign() {
    const messageText = messageTextEl.value.trim();
    if (!messageText) {
        alert("Введи текст сообщения");
        return;
    }

    let rewards;
    try {
        rewards = getCampaignRewardPayload(true);
    } catch (error) {
        alert(error.message);
        return;
    }

    modalConfirmSendBtn.disabled = true;
    modalConfirmSendBtn.textContent = "Отправляю...";

    try {
        const endpoint = rewards.hasRewards ? "/owner/api/bonus-giveaways/create" : "/owner/api/mailings/create";
        const payload = {
            segment_id: currentSegmentId,
            rules: getRules(rulesContainer),
            message_text: messageText,
            attachments: uploadedFiles,
            start_now: true,
        };
        if (rewards.hasRewards) {
            Object.assign(payload, {
                bonus_amount: rewards.bonusAmount,
                token_amount: rewards.tokenAmount,
                is_expiring: rewards.isExpiring,
                expires_value: rewards.expiresValue,
                expires_unit: rewards.expiresUnit,
            });
        }

        const response = await fetch(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await readApiResponse(response, "Не удалось создать рассылку");
        if (!data.ok) {
            alert(data.error || "Не удалось создать рассылку");
            return;
        }

        alert(`Рассылка запущена. Получателей: ${data.recipients_count}`);
        window.location.reload();
    } catch (error) {
        alert(error.message || "Не удалось запустить рассылку");
    } finally {
        modalConfirmSendBtn.disabled = false;
        modalConfirmSendBtn.textContent = "Отправить";
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
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
}

function insertLink() {
    const textarea = messageTextEl;
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const selectedText = textarea.value.substring(start, end);
    const rawUrl = prompt("Адрес ссылки (например, https://cyber-bonus.ru)");
    if (!rawUrl) return;
    const url = normalizeLinkUrl(rawUrl);
    if (!url) {
        alert("Укажи корректную ссылку с адресом сайта");
        return;
    }
    const linkText = selectedText || prompt("Текст ссылки", "Открыть");
    if (!linkText) return;

    textarea.setRangeText(
        `<a href="${escapeTelegramHtml(url)}">${escapeTelegramHtml(linkText)}</a>`,
        start,
        end,
        "end"
    );
    textarea.focus();
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
}

document.getElementById("addRuleBtn").addEventListener("click", () => addRule({}, rulesContainer));
document.getElementById("previewBtn").addEventListener("click", previewSegment);
document.getElementById("saveSegmentBtn").addEventListener("click", saveSegment);
document.getElementById("sendMailingBtn").addEventListener("click", openMailingConfirm);
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
populateVariableSelect(messageVariableSelect);
populateVariableSelect(giveawayVariableSelect);
document.querySelectorAll(".auto-mailing-variable-select").forEach(populateVariableSelect);
if (insertMessageVariableBtn) {
    insertMessageVariableBtn.addEventListener("click", () => insertSelectedVariable(messageVariableSelect, messageTextEl));
}
if (insertGiveawayVariableBtn) {
    insertGiveawayVariableBtn.addEventListener("click", () => insertSelectedVariable(giveawayVariableSelect, giveawayMessageTextEl));
}
document.querySelectorAll(".auto-mailing-variable-insert").forEach((button) => {
    button.addEventListener("click", () => {
        const field = button.closest(".auto-mailing-message-field");
        if (!field) return;
        insertSelectedVariable(
            field.querySelector(".auto-mailing-variable-select"),
            field.querySelector(".auto-mailing-message-text")
        );
    });
});
document.getElementById("modalConfirmSendBtn").addEventListener("click", createCampaign);
document.getElementById("modalEditBtn").addEventListener("click", closeMailingModal);
document.getElementById("mailingModalClose").addEventListener("click", closeMailingModal);
document.getElementById("mailingModalOverlay").addEventListener("click", closeMailingModal);

const crmInteractionModal = document.getElementById("crmInteractionModal");
const closeCrmInteractionBtn = document.getElementById("closeCrmInteractionBtn");
const crmInteractionBackdrop = document.getElementById("crmInteractionBackdrop");
const crmInteractionBody = document.getElementById("crmInteractionBody");
const crmInteractionTitle = document.getElementById("crmInteractionTitle");
const crmInteractionType = document.getElementById("crmInteractionType");

function openCrmInteractionModal() {
    if (!crmInteractionModal) return;
    crmInteractionModal.classList.add("is-open");
    crmInteractionModal.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    requestAnimationFrame(function () {
        void crmInteractionModal.offsetWidth;
    });
}

function closeCrmInteractionModal() {
    if (!crmInteractionModal) return;
    crmInteractionModal.classList.remove("is-open");
    crmInteractionModal.setAttribute("aria-hidden", "true");
    const hint = document.getElementById("mailingAudienceHintModal");
    if ((!modalEl || !modalEl.classList.contains("is-open")) && (!hint || !hint.classList.contains("is-open"))) {
        document.body.style.overflow = "";
    }
}

function formatValue(value, fallback = "—") {
    if (value === null || value === undefined || value === "") return fallback;
    return value;
}

function formatDateTime(value) {
    if (!value) return "";
    const match = String(value).match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
    if (!match) return value;
    return `${match[3]}.${match[2]}.${match[1]} ${match[4]}:${match[5]}`;
}

function formatDeliveryStatus(status) {
    const labels = {
        sent: "Доставлено",
        failed: "Ошибка",
        pending: "В очереди",
        queued: "В очереди",
        in_progress: "В работе",
        completed: "Завершено",
    };
    return labels[status] || status || "—";
}

function renderVisitCell(dateTime, duration) {
    if (!dateTime) {
        return `<span class="interaction-muted">Не было</span>`;
    }
    return `
        <span class="interaction-date">${escapeHtml(formatDateTime(dateTime))}</span>
        ${duration ? `<span class="interaction-duration">${escapeHtml(duration)}</span>` : ""}
    `;
}

function renderFailureReasons(reasons) {
    if (!reasons || !reasons.length) {
        return `<div class="empty-hint">Ошибок доставки нет.</div>`;
    }
    return reasons.map((item) => `
        <div class="interaction-reason-row">
            <span>${escapeHtml(item.reason)}</span>
            <strong>${escapeHtml(item.count)}</strong>
        </div>
    `).join("");
}

function renderInteractionRecipients(recipients) {
    if (!recipients || !recipients.length) {
        return `<div class="empty-hint">Получателей нет.</div>`;
    }
    return recipients.map((row) => {
        const name = row.fio || row.phone || `Гость #${row.guest_id}`;
        const previousVisit = renderVisitCell(row.previous_visit_at, row.previous_visit_duration_display);
        const nextVisit = renderVisitCell(row.next_visit_at, row.next_visit_duration_display);
        const deliveryClass = row.delivery_status === "sent" ? "is-ok" : (row.delivery_status === "failed" ? "is-bad" : "is-wait");
        const rewardParts = [];
        if (Number(row.recipient_bonus_amount || 0) > 0) rewardParts.push(`+${row.recipient_bonus_amount} КБ`);
        if (Number(row.recipient_token_amount || 0) > 0) rewardParts.push(`+${row.recipient_token_amount} жет.`);
        const deliveryDetail = row.error_text
            ? `<span>${escapeHtml(row.error_text)}</span>`
            : (rewardParts.length ? `<span>${escapeHtml(rewardParts.join(" · "))}</span>` : "");
        return `
            <div class="interaction-guest-row">
                <div>
                    <strong>${escapeHtml(name)}</strong>
                    <span>${escapeHtml(row.phone || `ID ${row.guest_id}`)}</span>
                </div>
                <div>
                    <span class="interaction-status ${deliveryClass}">${escapeHtml(formatDeliveryStatus(row.delivery_status))}</span>
                    ${deliveryDetail}
                </div>
                <div>${previousVisit}</div>
                <div>${nextVisit}</div>
                <div>${escapeHtml(row.avg_session_display || "—")}</div>
                <div>${escapeHtml(formatValue(row.total_visits))}</div>
                <div>${escapeHtml(formatValue(row.visits_30d_before_message))}</div>
            </div>
        `;
    }).join("");
}

function renderCrmInteractionDetail(data) {
    const interaction = data.interaction || {};
    const summary = data.summary || {};
    const typeLabel = interaction.interaction_type === "giveaway"
        ? "Рассылка с начислением"
        : (interaction.interaction_type === "auto_mailing" ? "Авторассылка" : "Рассылка");
    const createdAt = formatDateTime(interaction.created_at);
    const title = `${typeLabel} №${interaction.interaction_id}${createdAt ? ` (${createdAt})` : ""}`;
    crmInteractionTitle.textContent = title;
    crmInteractionType.textContent = formatDeliveryStatus(interaction.status) || "CRM-взаимодействие";

    const bonusBlock = Number(interaction.bonus_amount || 0) > 0
        ? `<div class="interaction-kpi"><span>КБ</span><strong>+${escapeHtml(interaction.bonus_amount)}</strong></div>`
        : "";
    const tokenBlock = Number(interaction.token_amount || 0) > 0
        ? `<div class="interaction-kpi"><span>Жетоны</span><strong>+${escapeHtml(interaction.token_amount)}</strong></div>`
        : "";

    crmInteractionBody.innerHTML = `
        <div class="interaction-summary-grid">
            <div class="interaction-kpi"><span>Получателей</span><strong>${escapeHtml(summary.recipients_count || 0)}</strong></div>
            <div class="interaction-kpi"><span>Дошло</span><strong>${escapeHtml(summary.sent_count || 0)}</strong></div>
            <div class="interaction-kpi"><span>Не дошло</span><strong>${escapeHtml(summary.failed_count || 0)}</strong></div>
            <div class="interaction-kpi"><span>Вернулись</span><strong>${escapeHtml(summary.returned_count || 0)} · ${escapeHtml(summary.return_rate || 0)}%</strong></div>
            ${bonusBlock}
            ${tokenBlock}
        </div>

        <section class="interaction-section interaction-guest-table">
            <h3>Гости после взаимодействия</h3>
            <div class="interaction-guest-head">
                <div>Гость</div>
                <div>Доставка</div>
                <div>Последний визит</div>
                <div>Следующий визит</div>
                <div>Средний визит</div>
                <div>Всего визитов</div>
                <div>30 дней до</div>
            </div>
            <div class="interaction-guests">${renderInteractionRecipients(data.recipients || [])}</div>
        </section>

        <section class="interaction-section">
            <h3>Сообщение</h3>
            <div class="interaction-message">${escapeHtml(interaction.message_text || "").replaceAll("\n", "<br>")}</div>
        </section>

        <section class="interaction-section">
            <h3>Причины недоставки</h3>
            <div class="interaction-reasons">${renderFailureReasons(summary.failure_reasons || [])}</div>
        </section>
    `;
}

async function openCrmInteractionDetail(type, id) {
    if (!type || !id || !crmInteractionBody) return;
    crmInteractionBody.innerHTML = `<div class="empty-hint">Загрузка...</div>`;
    if (crmInteractionTitle) crmInteractionTitle.textContent = "История взаимодействия";
    if (crmInteractionType) crmInteractionType.textContent = "CRM-взаимодействие";
    openCrmInteractionModal();
    try {
        const response = await fetch(`/owner/api/crm-interactions/${type}/${id}`);
        const data = await response.json();
        if (!data.ok) {
            crmInteractionBody.innerHTML = `<div class="empty-hint">${escapeHtml(data.error || "Не удалось загрузить взаимодействие")}</div>`;
            return;
        }
        renderCrmInteractionDetail(data);
    } catch (error) {
        crmInteractionBody.innerHTML = `<div class="empty-hint">Не удалось загрузить взаимодействие.</div>`;
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
    if ((!modalEl || !modalEl.classList.contains("is-open")) && (!crmInteractionModal || !crmInteractionModal.classList.contains("is-open"))) {
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

const crmInteractionRows = Array.from(document.querySelectorAll(".interaction-row"));
const crmInteractionTypeFilter = document.getElementById("crmInteractionTypeFilter");
const hideAutoMailingsFilter = document.getElementById("hideAutoMailingsFilter");
const crmInteractionsFilterEmpty = document.getElementById("crmInteractionsFilterEmpty");

function applyCrmInteractionFilters() {
    const selectedType = crmInteractionTypeFilter ? crmInteractionTypeFilter.value : "all";
    const hideAuto = Boolean(hideAutoMailingsFilter && hideAutoMailingsFilter.checked);
    let visibleCount = 0;

    crmInteractionRows.forEach((row) => {
        const rowType = row.dataset.interactionType || "";
        const matchesType = selectedType === "all"
            || rowType === selectedType
            || (selectedType === "campaign" && (rowType === "mailing" || rowType === "giveaway"));
        const matchesAutoFilter = !(hideAuto && rowType === "auto_mailing");
        const isVisible = matchesType && matchesAutoFilter;
        row.classList.toggle("is-filter-hidden", !isVisible);
        if (isVisible) visibleCount += 1;
    });

    if (crmInteractionsFilterEmpty) {
        crmInteractionsFilterEmpty.classList.toggle("is-filter-hidden", visibleCount > 0 || crmInteractionRows.length === 0);
    }
}

if (crmInteractionTypeFilter) {
    crmInteractionTypeFilter.addEventListener("change", applyCrmInteractionFilters);
}
if (hideAutoMailingsFilter) {
    hideAutoMailingsFilter.addEventListener("change", applyCrmInteractionFilters);
}
applyCrmInteractionFilters();

crmInteractionRows.forEach((row) => {
    row.addEventListener("click", () => {
        openCrmInteractionDetail(row.dataset.interactionType, row.dataset.interactionId);
    });
});
if (closeCrmInteractionBtn) {
    closeCrmInteractionBtn.addEventListener("click", closeCrmInteractionModal);
}
if (crmInteractionBackdrop) {
    crmInteractionBackdrop.addEventListener("click", closeCrmInteractionModal);
}
if (crmInteractionModal) {
    ["wheel", "touchmove"].forEach((eventName) => {
        crmInteractionModal.addEventListener(eventName, function (event) {
            if (crmInteractionBody && crmInteractionBody.contains(event.target)) {
                event.stopPropagation();
                return;
            }
            event.preventDefault();
        }, { passive: false });
    });
}

document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    if (mailingAudienceHintModal && mailingAudienceHintModal.classList.contains("is-open")) {
        closeMailingAudienceHintModal();
        return;
    }
    if (crmInteractionModal && crmInteractionModal.classList.contains("is-open")) {
        closeCrmInteractionModal();
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
    const delayInput = card.querySelector(".auto-mailing-delay");
    const titleInput = card.querySelector(".auto-mailing-title-input");
    const descriptionInput = card.querySelector(".auto-mailing-description-input");
    const messageInput = card.querySelector(".auto-mailing-message-text");
    const sendStartInput = card.querySelector(".auto-mailing-send-start");
    const sendEndInput = card.querySelector(".auto-mailing-send-end");

    const code = card.dataset.autoMailingCode || "";
    const payload = {
        is_enabled: Boolean(toggle && toggle.checked),
        days_inactive: Number(daysInput ? daysInput.value : ((code === "first_visit_survey" || code === "streak_expiring_reminder") ? 1 : 14)),
        bonus_amount: Number(bonusInput ? bonusInput.value : (code === "streak_expiring_reminder" ? 1 : 200)),
        title: titleInput ? titleInput.value.trim() : "",
        description: descriptionInput ? descriptionInput.value.trim() : "",
        message_text: messageInput ? messageInput.value.trim() : "",
        send_start_time: sendStartInput ? sendStartInput.value : "10:00",
        send_end_time: sendEndInput ? sendEndInput.value : "22:30",
    };
    if (delayInput) {
        payload.delay_minutes = Number(delayInput.value);
    }
    return payload;
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
    const delayInput = card.querySelector(".auto-mailing-delay");
    const titleInput = card.querySelector(".auto-mailing-title-input");
    const descriptionInput = card.querySelector(".auto-mailing-description-input");
    const messageInput = card.querySelector(".auto-mailing-message-text");
    const sendStartInput = card.querySelector(".auto-mailing-send-start");
    const sendEndInput = card.querySelector(".auto-mailing-send-end");
    const previousChecked = toggle ? !toggle.checked : false;

    if (!code) return;

    const payload = getAutoMailingPayload(card);
    if (code !== "first_visit_survey" && code !== "streak_expiring_reminder" && (!Number.isFinite(payload.days_inactive) || payload.days_inactive < 1)) {
        setAutoMailingStatus(card, "Укажи дни неактива больше 0", true);
        if (toggle && options.fromToggle) toggle.checked = previousChecked;
        return;
    }
    if (!Number.isFinite(payload.bonus_amount) || payload.bonus_amount < 1) {
        setAutoMailingStatus(card, "Укажи бонусы больше 0", true);
        if (toggle && options.fromToggle) toggle.checked = previousChecked;
        return;
    }
    if (code === "first_visit_survey" && (!Number.isFinite(payload.delay_minutes) || payload.delay_minutes < 1)) {
        setAutoMailingStatus(card, "Укажи задержку отправки больше 0", true);
        if (toggle && options.fromToggle) toggle.checked = previousChecked;
        return;
    }
    if (!payload.title) {
        setAutoMailingStatus(card, "Укажи название", true);
        if (toggle && options.fromToggle) toggle.checked = previousChecked;
        return;
    }
    if (!payload.message_text) {
        setAutoMailingStatus(card, "Сообщение пустое", true);
        if (toggle && options.fromToggle) toggle.checked = previousChecked;
        return;
    }
    if (!payload.send_start_time || !payload.send_end_time) {
        setAutoMailingStatus(card, "Укажи начало и конец окна отправки", true);
        if (toggle && options.fromToggle) toggle.checked = previousChecked;
        return;
    }
    if (payload.send_start_time === payload.send_end_time) {
        setAutoMailingStatus(card, "Начало и конец окна должны отличаться", true);
        if (toggle && options.fromToggle) toggle.checked = previousChecked;
        return;
    }

    [toggle, saveBtn, daysInput, bonusInput, delayInput, titleInput, descriptionInput, messageInput, sendStartInput, sendEndInput].forEach((el) => {
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
            if (delayInput) delayInput.value = data.auto_mailing.delay_minutes || payload.delay_minutes;
            if (titleInput) titleInput.value = data.auto_mailing.title || payload.title;
            if (descriptionInput) descriptionInput.value = data.auto_mailing.description || payload.description;
            if (messageInput) messageInput.value = data.auto_mailing.message_text || payload.message_text;
            if (sendStartInput) sendStartInput.value = data.auto_mailing.send_start_time || payload.send_start_time;
            if (sendEndInput) sendEndInput.value = data.auto_mailing.send_end_time || payload.send_end_time;
        }
        setAutoMailingStatus(card, "Сохранено");
    } catch (error) {
        if (toggle && options.fromToggle) toggle.checked = previousChecked;
        setAutoMailingStatus(card, "Не удалось сохранить", true);
    } finally {
        [toggle, saveBtn, daysInput, bonusInput, delayInput, titleInput, descriptionInput, messageInput, sendStartInput, sendEndInput].forEach((el) => {
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

[giveawayBonusEnabledEl, giveawayTokenEnabledEl, giveawayExpiringBonusEl].forEach((element) => {
    if (element) element.addEventListener("change", syncRewardControls);
});
[giveawayBonusAmountEl, giveawayTokenAmountEl, giveawayExpiresValueEl, giveawayExpiresUnitEl].forEach((element) => {
    if (element) element.addEventListener("input", updateCampaignSummary);
    if (element) element.addEventListener("change", updateCampaignSummary);
});
if (messageTextEl) messageTextEl.addEventListener("input", updateCampaignSummary);

syncRewardControls();
updateCampaignSummary();
previewSegment().catch(() => {
    if (audienceCountEl) audienceCountEl.textContent = "—";
    if (summaryAudienceCountEl) summaryAudienceCountEl.textContent = "—";
});
