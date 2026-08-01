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

let crmFunnelPeriod = "all";

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
    const periodLabel = analysis.funnel_period_label || "за всё время";
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
        `).join("")}</div><div class="crm-funnel-caption">Воронка строится по выбранной когорте, ${periodLabel}. Под визитами — средний интервал до следующего визита.</div>`
        : `<div class="empty-state">По выбранной когорте пока нет визитов.</div>`;

    crmAnalysisMetricsEl.innerHTML = (analysis.metrics || []).map((item) => `
        <article class="crm-analysis-metric">
            <span>${item.label}</span>
            <strong>${item.value}</strong>
            <small>${item.hint || ""}</small>
        </article>
    `).join("");
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

if (crmAnalysisRulesContainer) {
    crmAddRule({});
    crmSetFunnelPeriod("all");
    crmRenderAnalysis(window.CRM_INITIAL_ANALYSIS || {});
}

if (addCrmAnalysisRuleBtn) addCrmAnalysisRuleBtn.addEventListener("click", () => crmAddRule({}));
if (applyCrmAnalysisBtn) applyCrmAnalysisBtn.addEventListener("click", crmApplyAnalysis);
if (saveCrmCohortBtn) saveCrmCohortBtn.addEventListener("click", crmSaveCohort);

document.querySelectorAll(".crm-cohort-chip").forEach((button) => {
    button.addEventListener("click", () => {
        crmApplySavedRules(JSON.parse(button.dataset.rules || "{}"));
    });
});

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
