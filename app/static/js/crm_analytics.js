const crmFieldsMeta = window.CRM_ANALYSIS_FIELDS || [];
const crmAnalysisRulesContainer = document.getElementById("crmAnalysisRulesContainer");
const addCrmAnalysisRuleBtn = document.getElementById("addCrmAnalysisRuleBtn");
const applyCrmAnalysisBtn = document.getElementById("applyCrmAnalysisBtn");
const saveCrmCohortBtn = document.getElementById("saveCrmCohortBtn");
const crmCohortNameEl = document.getElementById("crmCohortName");
const crmAnalysisAudienceEl = document.getElementById("crmAnalysisAudience");
const crmAnalysisFunnelEl = document.getElementById("crmAnalysisFunnel");
const crmAnalysisMetricsEl = document.getElementById("crmAnalysisMetrics");
const crmFunnelPeriodBtns = Array.from(document.querySelectorAll(".crm-funnel-period"));
const crmFunnelCustomPeriodEl = document.getElementById("crmFunnelCustomPeriod");
const crmFunnelDateFromEl = document.getElementById("crmFunnelDateFrom");
const crmFunnelDateToEl = document.getElementById("crmFunnelDateTo");
const crmCampaignModal = document.getElementById("crmCampaignModal");
const crmCampaignBackdrop = document.getElementById("crmCampaignBackdrop");
const crmCampaignClose = document.getElementById("crmCampaignClose");
const crmCampaignBody = document.getElementById("crmCampaignBody");
const crmCampaignTitle = document.getElementById("crmCampaignTitle");
const crmCampaignStatus = document.getElementById("crmCampaignStatus");
const crmCampaignsShowAllBtn = document.getElementById("crmCampaignsShowAll");
const crmPulseGroups = window.CRM_PULSE_GROUPS || [];
const crmMessageVariables = window.CRM_MESSAGE_VARIABLES || [];
const crmPulseModal = document.getElementById("crmPulseModal");
const crmPulseBackdrop = document.getElementById("crmPulseBackdrop");
const crmPulseClose = document.getElementById("crmPulseClose");
const crmPulseBody = document.getElementById("crmPulseBody");
const crmPulseTitle = document.getElementById("crmPulseTitle");
const crmPulseSubtitle = document.getElementById("crmPulseSubtitle");
const crmPulseRecipientSummary = document.getElementById("crmPulseRecipientSummary");
const crmPulseRecipientList = document.getElementById("crmPulseRecipientList");
const crmPulseMessage = document.getElementById("crmPulseMessage");
const crmPulseVariableSelect = document.getElementById("crmPulseVariableSelect");
const crmPulseInsertVariable = document.getElementById("crmPulseInsertVariable");
const crmPulseBonusAmount = document.getElementById("crmPulseBonusAmount");
const crmPulseTokenAmount = document.getElementById("crmPulseTokenAmount");
const crmPulseExpiringBonus = document.getElementById("crmPulseExpiringBonus");
const crmPulseExpiration = document.getElementById("crmPulseExpiration");
const crmPulseExpiresValue = document.getElementById("crmPulseExpiresValue");
const crmPulseExpiresUnit = document.getElementById("crmPulseExpiresUnit");
const crmPulseSubmit = document.getElementById("crmPulseSubmit");
const crmPulseStatus = document.getElementById("crmPulseStatus");

let crmFunnelPeriod = "all";
let crmCampaignScrollY = 0;
let crmPulseScrollY = 0;
let crmActivePulseGroup = null;

const CRM_OPERATOR_LABELS = {
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

function crmEscapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function crmFormatValue(value, fallback = "—") {
    if (value === null || value === undefined || value === "") return fallback;
    return value;
}

function crmFormatDateTime(value) {
    if (!value) return "—";
    const match = String(value).match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
    if (!match) return value;
    return `${match[3]}.${match[2]}.${match[1]} ${match[4]}:${match[5]}`;
}

function crmFormatStatus(status) {
    const labels = {
        sent: "Доставлено",
        failed: "Ошибка",
        pending: "В очереди",
        queued: "В очереди",
        in_progress: "В работе",
        completed: "Завершено",
        processing: "В работе",
        created: "Создано",
        awarded: "Начислено",
        skipped: "Пропущено",
    };
    return labels[status] || status || "—";
}

function crmFormatMoney(value) {
    const number = Number(value || 0);
    return `${Math.round(number).toLocaleString("ru-RU")} ₽`;
}

function crmFormatBonus(value) {
    const number = Number(value || 0);
    return number ? `${Math.round(number).toLocaleString("ru-RU")} КБ` : "0 КБ";
}

function crmFormatRubPerBonus(value) {
    const number = Number(value || 0);
    const formatted = number.toLocaleString("ru-RU", {maximumFractionDigits: 2});
    return `${formatted} ₽ / КБ`;
}

function crmCreateOption(value, label) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    return option;
}

function crmGetFieldMeta(fieldKey) {
    return crmFieldsMeta.find((item) => item.key === fieldKey);
}

function crmAllowedOps(type) {
    if (type === "number") return ["=", "!=", ">", ">=", "<", "<=", "between"];
    if (type === "date") return ["=", "!=", ">", ">=", "<", "<=", "between", "is_null", "is_not_null"];
    if (type === "enum") return ["=", "!=", "in", "not_in"];
    if (type === "bool") return ["="];
    if (type === "phone_list") return ["in"];
    return ["="];
}

function crmRenderValueInputs(row, meta) {
    const valueWrap = row.querySelector(".crm-rule-value-wrap");
    const valueToWrap = row.querySelector(".crm-rule-value-to-wrap");
    const opSelect = row.querySelector(".rule-op");
    valueWrap.innerHTML = "";
    valueToWrap.innerHTML = "";

    const op = opSelect.value;
    row.classList.toggle("has-range", op === "between");
    if (op === "is_null" || op === "is_not_null") {
        valueWrap.appendChild(document.createElement("span"));
        valueToWrap.appendChild(document.createElement("span"));
        return;
    }

    let input;
    if (meta.type === "enum") {
        input = document.createElement("select");
        if (op === "in" || op === "not_in") input.multiple = true;
        (meta.options || []).forEach((item) => input.appendChild(crmCreateOption(item.value, item.label)));
    } else if (meta.type === "bool") {
        input = document.createElement("select");
        input.appendChild(crmCreateOption("1", "Да"));
        input.appendChild(crmCreateOption("0", "Нет"));
    } else if (meta.type === "date") {
        input = document.createElement("input");
        input.type = "date";
    } else if (meta.type === "phone_list") {
        input = document.createElement("input");
        input.type = "text";
        input.placeholder = "Телефоны через запятую";
    } else {
        input = document.createElement("input");
        input.type = "number";
        input.step = "any";
        input.placeholder = "число";
    }
    input.className = "rule-value";
    valueWrap.appendChild(input);

    if (op === "between") {
        const inputTo = document.createElement("input");
        inputTo.className = "rule-value-to";
        inputTo.type = meta.type === "date" ? "date" : "number";
        inputTo.step = "any";
        valueToWrap.appendChild(inputTo);
    }
}

function crmAddRule(rule = {}) {
    if (!crmAnalysisRulesContainer) return;
    const row = document.createElement("div");
    row.className = "rule-row crm-analysis-rule-row";

    const fieldSelect = document.createElement("select");
    fieldSelect.className = "rule-field";
    crmFieldsMeta.forEach((field) => fieldSelect.appendChild(crmCreateOption(field.key, field.label)));

    const opSelect = document.createElement("select");
    opSelect.className = "rule-op";
    const valueWrap = document.createElement("div");
    valueWrap.className = "crm-rule-value-wrap";
    const valueToWrap = document.createElement("div");
    valueToWrap.className = "crm-rule-value-to-wrap";

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "crm-rule-remove";
    removeBtn.textContent = "×";
    removeBtn.addEventListener("click", () => row.remove());

    function syncOps() {
        const meta = crmGetFieldMeta(fieldSelect.value);
        opSelect.innerHTML = "";
        crmAllowedOps(meta.type).forEach((op) => opSelect.appendChild(crmCreateOption(op, CRM_OPERATOR_LABELS[op] || op)));
        crmRenderValueInputs(row, meta);
    }

    fieldSelect.addEventListener("change", syncOps);
    opSelect.addEventListener("change", () => {
        const meta = crmGetFieldMeta(fieldSelect.value);
        crmRenderValueInputs(row, meta);
    });

    row.appendChild(fieldSelect);
    row.appendChild(opSelect);
    row.appendChild(valueWrap);
    row.appendChild(valueToWrap);
    row.appendChild(removeBtn);
    crmAnalysisRulesContainer.appendChild(row);

    if (rule.field) fieldSelect.value = rule.field;
    syncOps();
    if (rule.op) {
        opSelect.value = rule.op;
        crmRenderValueInputs(row, crmGetFieldMeta(fieldSelect.value));
    }
    const valueEl = row.querySelector(".rule-value");
    if (valueEl && rule.value !== undefined) {
        if (valueEl.multiple && Array.isArray(rule.value)) {
            Array.from(valueEl.options).forEach((option) => {
                option.selected = rule.value.includes(option.value) || rule.value.includes(Number(option.value));
            });
        } else {
            valueEl.value = rule.value;
        }
    }
    const valueToEl = row.querySelector(".rule-value-to");
    if (valueToEl && rule.value_to !== undefined) valueToEl.value = rule.value_to;
}

function crmGetRules() {
    return Array.from(crmAnalysisRulesContainer.querySelectorAll(".rule-row")).map((row) => {
        const field = row.querySelector(".rule-field").value;
        const op = row.querySelector(".rule-op").value;
        const valueEl = row.querySelector(".rule-value");
        const valueToEl = row.querySelector(".rule-value-to");
        let value = valueEl ? valueEl.value : null;
        if (valueEl && valueEl.multiple) {
            value = Array.from(valueEl.selectedOptions).map((option) => option.value);
        }
        if (!["is_null", "is_not_null"].includes(op)) {
            const hasValue = Array.isArray(value) ? value.length > 0 : String(value || "").trim() !== "";
            const hasValueTo = valueToEl ? String(valueToEl.value || "").trim() !== "" : true;
            if (!hasValue || (op === "between" && !hasValueTo)) return null;
        }
        return {
            field,
            op,
            value,
            value_to: valueToEl ? valueToEl.value : null,
        };
    }).filter(Boolean);
}

function crmGetFunnelPeriodPayload() {
    return {
        funnel_period: crmFunnelPeriod,
        funnel_date_from: crmFunnelDateFromEl ? crmFunnelDateFromEl.value : null,
        funnel_date_to: crmFunnelDateToEl ? crmFunnelDateToEl.value : null,
    };
}

function crmSetFunnelPeriod(period) {
    crmFunnelPeriod = period || "all";
    crmFunnelPeriodBtns.forEach((button) => {
        button.classList.toggle("active", button.dataset.period === crmFunnelPeriod);
    });
    if (crmFunnelCustomPeriodEl) {
        crmFunnelCustomPeriodEl.hidden = crmFunnelPeriod !== "custom";
    }
}

function crmRenderAnalysis(analysis) {
    const audience = analysis.audience || {};
    crmAnalysisAudienceEl.innerHTML = `
        <span>Гостей</span>
        <strong>${audience.total || 0}</strong>
        <small>${audience.telegram || 0} с Telegram · ${audience.telegram_percent || 0}%</small>
    `;

    const funnel = analysis.funnel || [];
    crmAnalysisFunnelEl.innerHTML = funnel.length
        ? `<div class="crm-funnel-bars">${funnel.map((item, index) => `
            <div class="crm-funnel-step" style="--bar-height:${item.height}%">
                <div class="crm-funnel-bar-wrap">
                    <div class="crm-funnel-count">${item.count}</div>
                    <div class="crm-funnel-bar"></div>
                </div>
                <strong>${item.step}</strong>
                <small>визит</small>
                ${index < funnel.length - 1 ? `<em>${item.gap_to_next === null ? "—" : item.gap_to_next + " дн."}</em>` : ""}
            </div>
        `).join("")}</div>`
        : `<div class="empty-state">По выбранной когорте пока нет визитов.</div>`;

    crmAnalysisMetricsEl.innerHTML = (analysis.metrics || []).map((item) => `
        <article class="crm-analysis-metric">
            <span>${item.label}</span>
            <strong>${item.value}</strong>
            <small>${item.hint || ""}</small>
        </article>
    `).join("");
}

function crmOpenCampaignModal() {
    if (!crmCampaignModal) return;
    crmCampaignScrollY = window.scrollY || document.documentElement.scrollTop || 0;
    crmCampaignModal.classList.add("is-open");
    crmCampaignModal.setAttribute("aria-hidden", "false");
    document.documentElement.classList.add("crm-modal-lock");
    document.body.classList.add("crm-modal-lock");
    document.body.style.top = `-${crmCampaignScrollY}px`;
}

function crmCloseCampaignModal() {
    if (!crmCampaignModal) return;
    crmCampaignModal.classList.remove("is-open");
    crmCampaignModal.setAttribute("aria-hidden", "true");
    document.documentElement.classList.remove("crm-modal-lock");
    document.body.classList.remove("crm-modal-lock");
    document.body.style.top = "";
    window.scrollTo(0, crmCampaignScrollY);
}

function crmOpenPulseModal() {
    if (!crmPulseModal) return;
    crmPulseScrollY = window.scrollY || document.documentElement.scrollTop || 0;
    crmPulseModal.classList.add("is-open");
    crmPulseModal.setAttribute("aria-hidden", "false");
    document.documentElement.classList.add("crm-modal-lock");
    document.body.classList.add("crm-modal-lock");
    document.body.style.top = `-${crmPulseScrollY}px`;
}

function crmClosePulseModal() {
    if (!crmPulseModal) return;
    crmPulseModal.classList.remove("is-open");
    crmPulseModal.setAttribute("aria-hidden", "true");
    document.documentElement.classList.remove("crm-modal-lock");
    document.body.classList.remove("crm-modal-lock");
    document.body.style.top = "";
    window.scrollTo(0, crmPulseScrollY);
}

function crmRouteCampaignModalWheel(event) {
    if (!crmCampaignModal || !crmCampaignModal.classList.contains("is-open") || !crmCampaignBody) return;
    event.preventDefault();
    crmCampaignBody.scrollTop += event.deltaY;
}

function crmRoutePulseModalWheel(event) {
    if (!crmPulseModal || !crmPulseModal.classList.contains("is-open") || !crmPulseBody) return;
    event.preventDefault();
    crmPulseBody.scrollTop += event.deltaY;
}

function crmRenderCampaignBar(items, className = "") {
    if (!items || !items.length) {
        return `<div class="empty-state">Данных пока нет.</div>`;
    }
    return `
        <div class="crm-campaign-funnel ${className}">
            ${items.map((item) => `
                <div class="crm-campaign-funnel__step" style="--bar-height:${item.height || 8}%">
                    <div class="crm-campaign-funnel__bar-wrap">
                        <strong>${crmEscapeHtml(item.count || 0)}</strong>
                        <div class="crm-campaign-funnel__bar"></div>
                    </div>
                    <span>${crmEscapeHtml(item.label)}</span>
                </div>
            `).join("")}
        </div>
    `;
}

function crmRenderCampaignRecipients(recipients) {
    if (!recipients || !recipients.length) {
        return `<div class="empty-state">Получателей нет.</div>`;
    }
    return recipients.map((row) => {
        const name = row.fio || row.phone || `Гость #${row.guest_id}`;
        const didVisit = row.next_visit_at ? "Да" : "Нет";
        const didTopup = Number(row.topup_amount_after || 0) > 0 ? "Да" : "Нет";
        const deliveryClass = row.delivery_status === "sent" ? "is-ok" : (row.delivery_status === "failed" ? "is-bad" : "is-wait");
        return `
            <div class="crm-campaign-recipient-row">
                <div>
                    <strong>${crmEscapeHtml(name)}</strong>
                    <span>${crmEscapeHtml(row.phone || `ID ${row.guest_id}`)}</span>
                </div>
                <div><span class="crm-campaign-status ${deliveryClass}">${crmEscapeHtml(crmFormatStatus(row.delivery_status))}</span></div>
                <div>
                    <strong>${didVisit}</strong>
                    <span>${crmEscapeHtml(crmFormatDateTime(row.next_visit_at))}</span>
                </div>
                <div>
                    <strong>${didTopup}</strong>
                    <span>${crmEscapeHtml(crmFormatMoney(row.topup_amount_after))}</span>
                </div>
                <div>${crmEscapeHtml(crmFormatBonus(row.used_bonus_after))}</div>
            </div>
        `;
    }).join("");
}

function crmRenderCampaignPassport(passport) {
    const campaign = passport.campaign || {};
    const summary = passport.summary || {};
    const typeLabel = campaign.campaign_type === "giveaway" ? "раздачи" : "рассылки";
    const titleLabel = campaign.campaign_type === "giveaway" ? "Паспорт раздачи" : "Паспорт рассылки";
    crmCampaignTitle.textContent = `${titleLabel} #${campaign.campaign_id}${campaign.created_at ? ` (${crmFormatDateTime(campaign.created_at)})` : ""}`;
    crmCampaignStatus.textContent = crmFormatStatus(campaign.status);

    const rewardParts = [];
    if (Number(campaign.bonus_amount || 0) > 0) rewardParts.push(`+${campaign.bonus_amount} КБ`);
    if (Number(campaign.token_amount || 0) > 0) rewardParts.push(`+${campaign.token_amount} жет.`);

    crmCampaignBody.innerHTML = `
        <section class="crm-campaign-passport-block">
            <h3>Основная информация</h3>
            <div class="crm-campaign-kpis">
                <article><span>Получателей</span><strong>${crmEscapeHtml(summary.recipients_count || 0)}</strong></article>
                <article><span>Доставлено</span><strong>${crmEscapeHtml(summary.delivered_count || 0)}</strong></article>
                <article><span>Визитов после</span><strong>${crmEscapeHtml(summary.visited_count || 0)} · ${crmEscapeHtml(summary.visit_conversion || 0)}%</strong></article>
                <article><span>Пополнили после</span><strong>${crmEscapeHtml(summary.topped_up_count || 0)} · ${crmEscapeHtml(summary.topup_conversion || 0)}%</strong></article>
                <article><span>Начислено КБ</span><strong>${crmEscapeHtml(crmFormatBonus(summary.bonus_spent))}</strong></article>
                <article><span>Награда</span><strong>${crmEscapeHtml(rewardParts.join(" · ") || "—")}</strong></article>
            </div>
        </section>

        <section class="crm-campaign-passport-block">
            <h3>Воронка ${crmEscapeHtml(typeLabel)}</h3>
            ${crmRenderCampaignBar(passport.delivery_funnel || [])}
        </section>

        <section class="crm-campaign-passport-block">
            <h3>Сколько дней до возврата</h3>
            ${crmRenderCampaignBar(passport.return_funnel || [], "crm-campaign-funnel--days")}
        </section>

        <section class="crm-campaign-passport-block">
            <h3>Экономика за ${crmEscapeHtml(summary.window_days || 30)} дней после кампании</h3>
            <div class="crm-campaign-kpis crm-campaign-kpis--economy">
                <article><span>Использовано бонусов</span><strong>${crmEscapeHtml(crmFormatBonus(summary.used_bonus))}</strong></article>
                <article><span>Пополнено</span><strong>${crmEscapeHtml(crmFormatMoney(summary.topup_amount))}</strong></article>
                <article><span>Среднее пополнение</span><strong>${crmEscapeHtml(crmFormatMoney(summary.avg_topup))}</strong></article>
                <article><span>Пополнение / КБ</span><strong>${crmEscapeHtml(crmFormatRubPerBonus(summary.topup_per_bonus))}</strong></article>
            </div>
        </section>

        <section class="crm-campaign-passport-block">
            <h3>Получатели</h3>
            <div class="crm-campaign-recipient-head">
                <div>Получатель</div>
                <div>Доставка</div>
                <div>Визит</div>
                <div>Пополнение</div>
                <div>Бонусы списаны</div>
            </div>
            <div class="crm-campaign-recipients">
                ${crmRenderCampaignRecipients(passport.recipients || [])}
            </div>
        </section>

        <section class="crm-campaign-passport-block">
            <h3>Сообщение</h3>
            <div class="crm-campaign-message">${crmEscapeHtml(passport.message_text || "").replaceAll("\n", "<br>")}</div>
        </section>
    `;
}

async function crmOpenCampaignPassport(type, id) {
    if (!type || !id || !crmCampaignBody) return;
    crmCampaignTitle.textContent = "Паспорт кампании";
    crmCampaignStatus.textContent = "Загрузка";
    crmCampaignBody.innerHTML = `<div class="empty-state">Загрузка...</div>`;
    crmOpenCampaignModal();
    try {
        const response = await fetch(`/owner/api/crm-campaigns/${type}/${id}`);
        const data = await response.json();
        if (!data.ok) {
            crmCampaignBody.innerHTML = `<div class="empty-state">${crmEscapeHtml(data.error || "Не удалось загрузить кампанию")}</div>`;
            return;
        }
        crmRenderCampaignPassport(data.passport || {});
    } catch (error) {
        crmCampaignBody.innerHTML = `<div class="empty-state">Не удалось загрузить кампанию.</div>`;
    }
}

function crmGetPulseGroup(key) {
    return crmPulseGroups.find((group) => group.key === key);
}

function crmRenderPulseRecipients(group) {
    const guests = group.guests || [];
    const telegramGuests = guests.filter((guest) => guest.has_telegram);
    crmPulseRecipientSummary.innerHTML = `
        <article><span>Всего</span><strong>${group.total_count || guests.length}</strong></article>
        <article><span>С Telegram</span><strong>${group.telegram_count || telegramGuests.length}</strong></article>
        <article><span>После авторассылки</span><strong>${group.recent_auto_count || 0}</strong></article>
    `;
    crmPulseRecipientList.innerHTML = guests.map((guest) => {
        const warning = guest.recent_auto_mailing_title
            ? `<i title="Недавно была авторассылка &quot;${crmEscapeHtml(guest.recent_auto_mailing_title)}&quot;">!</i>`
            : "";
        const telegramLabel = guest.has_telegram ? "Telegram есть" : "без Telegram";
        return `
            <div class="crm-pulse-recipient-row ${guest.has_telegram ? "" : "is-muted"}">
                <div>
                    <strong>${crmEscapeHtml(guest.fio || `Гость #${guest.guest_id}`)}</strong>
                    <span>${crmEscapeHtml(guest.phone || `ID ${guest.guest_id}`)}</span>
                </div>
                <div>${crmEscapeHtml(telegramLabel)}</div>
                <div>${crmEscapeHtml(guest.visits_30d || 0)} визитов за 30 дней</div>
                <div>${warning}</div>
            </div>
        `;
    }).join("");
}

function crmFillPulseVariables() {
    if (!crmPulseVariableSelect) return;
    crmPulseVariableSelect.innerHTML = "";
    crmMessageVariables.forEach((item) => {
        crmPulseVariableSelect.appendChild(crmCreateOption(item.token, item.label));
    });
}

function crmOpenPulseInteraction(key) {
    const group = crmGetPulseGroup(key);
    if (!group) return;
    crmActivePulseGroup = group;
    crmPulseTitle.textContent = `${group.old_label} → ${group.new_label}`;
    crmPulseSubtitle.textContent = "Пульс базы";
    crmPulseMessage.value = "";
    crmPulseBonusAmount.value = "0";
    crmPulseTokenAmount.value = "0";
    crmPulseExpiringBonus.checked = false;
    crmPulseExpiration.hidden = true;
    crmPulseStatus.textContent = "";
    crmRenderPulseRecipients(group);
    crmFillPulseVariables();
    crmOpenPulseModal();
}

function crmInsertPulseVariable() {
    if (!crmPulseMessage || !crmPulseVariableSelect) return;
    const token = crmPulseVariableSelect.value || "";
    const start = crmPulseMessage.selectionStart || crmPulseMessage.value.length;
    const end = crmPulseMessage.selectionEnd || start;
    crmPulseMessage.value = `${crmPulseMessage.value.slice(0, start)}${token}${crmPulseMessage.value.slice(end)}`;
    crmPulseMessage.focus();
    const nextPosition = start + token.length;
    crmPulseMessage.setSelectionRange(nextPosition, nextPosition);
}

async function crmSubmitPulseInteraction() {
    if (!crmActivePulseGroup || !crmPulseSubmit) return;
    crmPulseSubmit.disabled = true;
    crmPulseStatus.textContent = "Отправляем...";
    try {
        const response = await fetch("/owner/api/crm-pulse/interact", {
            method: "POST",
            headers: {"Content-Type": "application/json", "Accept": "application/json"},
            body: JSON.stringify({
                guest_ids: crmActivePulseGroup.guest_ids || [],
                transition: {
                    old_status: crmActivePulseGroup.old_status,
                    new_status: crmActivePulseGroup.new_status,
                    old_label: crmActivePulseGroup.old_label,
                    new_label: crmActivePulseGroup.new_label,
                },
                message_text: crmPulseMessage.value,
                bonus_amount: crmPulseBonusAmount.value,
                token_amount: crmPulseTokenAmount.value,
                is_expiring: crmPulseExpiringBonus.checked,
                expires_value: crmPulseExpiresValue.value,
                expires_unit: crmPulseExpiresUnit.value,
            }),
        });
        const data = await response.json();
        if (!data.ok) {
            crmPulseStatus.textContent = data.error || "Не удалось отправить";
            return;
        }
        crmPulseStatus.textContent = `Поставлено в очередь: ${data.recipients_count || 0} получателей`;
        setTimeout(() => crmClosePulseModal(), 900);
    } catch (error) {
        crmPulseStatus.textContent = "Не удалось отправить";
    } finally {
        crmPulseSubmit.disabled = false;
    }
}

async function crmApplyAnalysis() {
    applyCrmAnalysisBtn.disabled = true;
    try {
        const response = await fetch("/owner/api/crm-analysis/preview", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({rules: crmGetRules(), ...crmGetFunnelPeriodPayload()}),
        });
        const data = await response.json();
        if (!data.ok) {
            alert(data.error || "Не удалось посчитать анализ");
            return;
        }
        crmRenderAnalysis(data.analysis);
    } finally {
        applyCrmAnalysisBtn.disabled = false;
    }
}

async function crmSaveCohort() {
    const name = (crmCohortNameEl.value || "").trim();
    if (!name) {
        alert("Укажи название когорты");
        return;
    }
    const response = await fetch("/owner/api/crm-cohorts/save", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({name, rules: crmGetRules()}),
    });
    const data = await response.json();
    if (!data.ok) {
        alert(data.error || "Не удалось сохранить когорту");
        return;
    }
    window.location.reload();
}

function crmApplySavedRules(rulesJson) {
    crmAnalysisRulesContainer.innerHTML = "";
    const rules = (rulesJson && rulesJson.rules) || [];
    rules.forEach((rule) => crmAddRule(rule));
    if (!rules.length) crmAddRule({});
    crmApplyAnalysis();
}

async function crmDeleteCohort(button) {
    const cohortId = button.dataset.cohortId;
    if (!cohortId) return;
    if (!window.confirm("Удалить сохраненную когорту?")) return;

    button.disabled = true;
    const response = await fetch(`/owner/api/crm-cohorts/${cohortId}`, {method: "DELETE"});
    const data = await response.json();
    if (!data.ok) {
        button.disabled = false;
        alert(data.error || "Не удалось удалить когорту");
        return;
    }
    button.closest(".crm-cohort-chip")?.remove();
}

if (crmAnalysisRulesContainer) {
    crmAddRule({});
    crmSetFunnelPeriod("all");
    crmRenderAnalysis(window.CRM_INITIAL_ANALYSIS || {});
}

if (addCrmAnalysisRuleBtn) addCrmAnalysisRuleBtn.addEventListener("click", () => crmAddRule({}));
if (applyCrmAnalysisBtn) applyCrmAnalysisBtn.addEventListener("click", crmApplyAnalysis);
if (saveCrmCohortBtn) saveCrmCohortBtn.addEventListener("click", crmSaveCohort);

document.querySelectorAll(".crm-cohort-apply").forEach((button) => {
    button.addEventListener("click", () => {
        crmApplySavedRules(JSON.parse(button.dataset.rules || "{}"));
    });
});

document.querySelectorAll(".crm-cohort-delete").forEach((button) => {
    button.addEventListener("click", () => crmDeleteCohort(button));
});

document.querySelectorAll(".crm-campaign-row").forEach((row) => {
    row.addEventListener("click", () => {
        crmOpenCampaignPassport(row.dataset.campaignType, row.dataset.campaignId);
    });
});

document.querySelectorAll(".crm-pulse-action").forEach((button) => {
    button.addEventListener("click", () => {
        crmOpenPulseInteraction(button.dataset.pulseKey);
    });
});

if (crmCampaignsShowAllBtn) {
    crmCampaignsShowAllBtn.addEventListener("click", () => {
        document.querySelectorAll(".crm-campaign-row.is-campaign-hidden").forEach((row) => {
            row.classList.remove("is-campaign-hidden");
        });
        crmCampaignsShowAllBtn.remove();
    });
}

if (crmCampaignBackdrop) crmCampaignBackdrop.addEventListener("click", crmCloseCampaignModal);
if (crmCampaignClose) crmCampaignClose.addEventListener("click", crmCloseCampaignModal);
if (crmCampaignModal) crmCampaignModal.addEventListener("wheel", crmRouteCampaignModalWheel, {passive: false});
if (crmPulseBackdrop) crmPulseBackdrop.addEventListener("click", crmClosePulseModal);
if (crmPulseClose) crmPulseClose.addEventListener("click", crmClosePulseModal);
if (crmPulseModal) crmPulseModal.addEventListener("wheel", crmRoutePulseModalWheel, {passive: false});
if (crmPulseInsertVariable) crmPulseInsertVariable.addEventListener("click", crmInsertPulseVariable);
if (crmPulseSubmit) crmPulseSubmit.addEventListener("click", crmSubmitPulseInteraction);
if (crmPulseExpiringBonus) {
    crmPulseExpiringBonus.addEventListener("change", () => {
        crmPulseExpiration.hidden = !crmPulseExpiringBonus.checked;
    });
}

crmFunnelPeriodBtns.forEach((button) => {
    button.addEventListener("click", () => {
        crmSetFunnelPeriod(button.dataset.period);
        crmApplyAnalysis();
    });
});

[crmFunnelDateFromEl, crmFunnelDateToEl].forEach((input) => {
    if (!input) return;
    input.addEventListener("change", () => {
        if (crmFunnelPeriod === "custom") crmApplyAnalysis();
    });
});

document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && crmCampaignModal && crmCampaignModal.classList.contains("is-open")) {
        crmCloseCampaignModal();
    }
    if (event.key === "Escape" && crmPulseModal && crmPulseModal.classList.contains("is-open")) {
        crmClosePulseModal();
    }
});
