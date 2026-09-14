(() => {
    "use strict";

    const $ = (id) => document.getElementById(id);
    const number = new Intl.NumberFormat("ru-RU");
    const stateText = {
        HTTP_403: "API-ключ не имеет доступа к сотрудникам или сменам.",
        langame_club_mapping_required: "Нужно сопоставить клуб с Langame.",
        invalid_shift_dates: "Langame вернул некорректные даты смен.",
    };
    let report = null;
    let today = null;
    let controller = null;
    let calendarView = null;
    let calendarFrom = null;
    let calendarTo = null;
    const tableSort = {
        registrations: { key: "club_registrations", direction: "desc" },
        funnel: { key: "conversion12", direction: "desc" },
    };

    function escape(value) {
        return String(value ?? "").replace(
            /[&<>"']/g,
            (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char],
        );
    }

    function num(value) {
        return number.format(value || 0);
    }

    function percent(value) {
        return value === null ? "—" : `${number.format(value)}%`;
    }

    function formattedTimestamp(value) {
        if (!value) return "Смены ещё не загружены";
        const [rawDate, rawTime = ""] = value.split("T");
        const [year, month, day] = rawDate.split("-");
        return `Данные обновлены: ${day}.${month}.${year} ${rawTime.slice(0, 5)}`;
    }

    function isWorking(admin) {
        return admin.admin_id !== null && admin.has_recent_shift && admin.is_working !== false;
    }

    function initials(name) {
        return String(name || "?")
            .split(/\s+/)
            .filter(Boolean)
            .slice(0, 2)
            .map((part) => part[0])
            .join("")
            .toUpperCase();
    }

    function identity(admin) {
        const schedule = { day: "Дневные смены", night: "Ночные смены" }[admin.work_schedule];
        const meta = admin.admin_id === null
            ? "Нет единственной смены"
            : `ID ${escape(admin.admin_id)}${schedule ? ` · ${escape(schedule)}` : ""}`;
        return `<span class="team-person"><span class="team-avatar">${escape(initials(admin.name))}</span><span><strong>${escape(admin.name)}</strong><small>${meta}</small></span></span>`;
    }

    function visibleAdmins() {
        return report ? report.admins.filter(isWorking) : [];
    }

    function totals(admins) {
        const total = {
            club_registrations: 0,
            club_to_module: 0,
            module_registrations: 0,
            module_estimated: 0,
            shift_count: 0,
            cohort: 0,
            visit1: 0,
            visit2: 0,
            visit3: 0,
        };
        admins.forEach((admin) => {
            Object.keys(total).forEach((key) => { total[key] += admin[key] || 0; });
        });
        total.conversion12 = total.cohort ? Math.round((total.visit2 / total.cohort) * 1000) / 10 : null;
        total.conversion23 = total.visit2 ? Math.round((total.visit3 / total.visit2) * 1000) / 10 : null;
        return total;
    }

    function rank(index) {
        return `<span class="team-rank${index === 0 ? " is-top" : ""}">${index + 1}</span>`;
    }

    function conversion(value) {
        const strong = value !== null && value >= 50 ? " is-strong" : "";
        return `<span class="team-conversion${strong}">${percent(value)}</span>`;
    }

    function renderKpis(total) {
        $("kpiClub").textContent = num(total.club_registrations);
        $("kpiModule").textContent = num(total.module_registrations);
        $("kpiModuleNote").textContent = "впервые подключились к Кибер Бонус";
        $("kpiConversion12").textContent = percent(total.conversion12);
        $("kpiConversion23").textContent = percent(total.conversion23);
    }

    function sortAdmins(admins, table) {
        const { key, direction } = tableSort[table];
        return [...admins].sort((a, b) => {
            if ((a.admin_id === null) !== (b.admin_id === null)) return a.admin_id === null ? 1 : -1;
            const aValue = a[key];
            const bValue = b[key];
            const aMissing = aValue === null || aValue === undefined;
            const bMissing = bValue === null || bValue === undefined;
            if (aMissing !== bMissing) return aMissing ? 1 : -1;
            let comparison;
            if (key === "name") {
                comparison = String(aValue || "").localeCompare(String(bValue || ""), "ru");
            } else {
                comparison = Number(aValue) - Number(bValue);
            }
            if (comparison && direction === "desc") comparison *= -1;
            return comparison || a.name.localeCompare(b.name, "ru");
        });
    }

    function updateSortHeaders(table) {
        document.querySelectorAll(`[data-sort-table="${table}"]`).forEach((button) => {
            const active = button.dataset.sortKey === tableSort[table].key;
            button.classList.toggle("is-active", active);
            button.dataset.direction = active ? tableSort[table].direction : "";
            button.closest("th").setAttribute(
                "aria-sort",
                active ? (tableSort[table].direction === "asc" ? "ascending" : "descending") : "none",
            );
        });
    }

    function renderRegistrations(admins) {
        const ordered = sortAdmins(admins, "registrations");
        updateSortHeaders("registrations");
        if (!ordered.length) {
            $("teamRegistrations").innerHTML = '<tr><td class="team-empty" colspan="7">Нет данных по выбранному составу</td></tr>';
            return;
        }
        $("teamRegistrations").innerHTML = ordered.map((admin, index) => {
            return `<tr class="${admin.admin_id === null ? "team-unknown" : ""}">
                <td>${rank(index)}</td>
                <td>${identity(admin)}</td>
                <td><span class="team-number">${num(admin.club_registrations)}</span></td>
                <td><span class="team-number">${num(admin.club_to_module)}</span></td>
                <td><span class="team-number">${num(admin.module_registrations)}</span></td>
                <td><span class="team-number">${num(admin.shift_count)}</span></td>
                <td><span class="team-module-conversion"><strong>${percent(admin.module_conversion)}</strong><small>${num(admin.club_to_module)} из ${num(admin.club_registrations)}</small></span></td>
            </tr>`;
        }).join("");
    }

    function renderFunnel(admins) {
        const ordered = sortAdmins(admins, "funnel");
        updateSortHeaders("funnel");
        if (!ordered.length) {
            $("teamFunnel").innerHTML = '<tr><td class="team-empty" colspan="7">Нет данных по выбранному составу</td></tr>';
            return;
        }
        $("teamFunnel").innerHTML = ordered.map((admin, index) => `<tr class="${admin.admin_id === null ? "team-unknown" : ""}">
            <td>${rank(index)}</td>
            <td>${identity(admin)}</td>
            <td><span class="team-number">${num(admin.cohort)}</span></td>
            <td><span class="team-number">${num(admin.visit2)}</span></td>
            <td><span class="team-number">${num(admin.visit3)}</span></td>
            <td>${conversion(admin.conversion12)}</td>
            <td>${conversion(admin.conversion23)}</td>
        </tr>`).join("");
    }

    function renderView() {
        const admins = visibleAdmins();
        const total = totals(admins);
        renderKpis(total);
        renderRegistrations(admins);
        renderFunnel(admins);
    }

    function updateToggleAllButton() {
        const inputs = [...$("teamAdminSettingsList").querySelectorAll("[data-admin-id]")];
        const allSelected = inputs.length > 0 && inputs.every((input) => input.checked);
        $("teamAdminSettingsToggleAll").textContent = allSelected ? "Снять выбор" : "Выбрать всех";
        $("teamAdminSettingsToggleAll").disabled = inputs.length === 0;
    }

    function openAdminSettings() {
        if (!report) return;
        const admins = report.admins
            .filter((admin) => admin.admin_id !== null && admin.has_recent_shift)
            .sort((a, b) => a.name.localeCompare(b.name, "ru"));
        $("teamAdminSettingsList").innerHTML = admins.length ? admins.map((admin) => `
            <div class="team-admin-setting">
                <span class="team-avatar">${escape(initials(admin.name))}</span>
                <span><strong>${escape(admin.name)}</strong><small>ID ${escape(admin.admin_id)}</small></span>
                <label class="team-switch">
                    <span>Работает</span>
                    <input type="checkbox" data-admin-id="${escape(admin.admin_id)}"${isWorking(admin) ? " checked" : ""}>
                    <span class="team-switch__track" aria-hidden="true"></span>
                </label>
            </div>
        `).join("") : '<p class="team-empty">Список администраторов ещё не загружен</p>';
        updateToggleAllButton();
        $("teamAdminSettingsStatus").textContent = "";
        $("teamAdminSettingsModal").showModal();
        document.body.classList.add("team-modal-open");
        ($("teamAdminSettingsList").querySelector("input") || $("teamAdminSettingsSave")).focus();
    }

    function closeAdminSettings() {
        if ($("teamAdminSettingsModal").open) $("teamAdminSettingsModal").close();
        document.body.classList.remove("team-modal-open");
        $("teamAdminSettingsOpen").focus();
    }

    async function saveAdminSettings() {
        const inputs = [...$("teamAdminSettingsList").querySelectorAll("[data-admin-id]")];
        const admins = inputs.map((input) => ({
            admin_id: input.dataset.adminId,
            is_working: input.checked,
        }));
        $("teamAdminSettingsSave").disabled = true;
        $("teamAdminSettingsStatus").textContent = "Сохраняем…";
        try {
            const response = await fetch("/owner/api/team/admins", {
                method: "POST",
                headers: { Accept: "application/json", "Content-Type": "application/json" },
                body: JSON.stringify({ admins }),
            });
            const data = await response.json();
            if (!response.ok || !data.ok) throw new Error(data.error || "Не удалось сохранить состав");
            const saved = new Map(admins.map((admin) => [String(admin.admin_id), admin.is_working]));
            report.admins.forEach((admin) => {
                if (saved.has(String(admin.admin_id))) admin.is_working = saved.get(String(admin.admin_id));
            });
            renderView();
            closeAdminSettings();
        } catch (error) {
            $("teamAdminSettingsStatus").textContent = error.message || "Не удалось сохранить состав";
        } finally {
            $("teamAdminSettingsSave").disabled = false;
        }
    }

    function parseDate(value) {
        return value ? new Date(`${value}T12:00:00Z`) : null;
    }

    function isoDate(value) {
        return value.toISOString().slice(0, 10);
    }

    function monthStart(value) {
        return new Date(Date.UTC(value.getUTCFullYear(), value.getUTCMonth(), 1, 12));
    }

    function addMonths(value, amount) {
        return new Date(Date.UTC(value.getUTCFullYear(), value.getUTCMonth() + amount, 1, 12));
    }

    function formatDate(value) {
        if (!value) return "—";
        const [year, month, day] = value.split("-");
        return `${day}.${month}.${year}`;
    }

    function presetStart(preset) {
        const date = parseDate(today);
        if (preset === "month") date.setUTCDate(1);
        else date.setUTCDate(date.getUTCDate() - ((date.getUTCDay() + 6) % 7));
        return isoDate(date);
    }

    function setActivePreset() {
        if (!today || !$("sharedFrom").value || !$("sharedTo").value) return;
        const from = $("sharedFrom").value;
        const preset = $("sharedTo").value === today
            ? (["week", "month"].find((name) => from === presetStart(name)) || null)
            : null;
        document.querySelectorAll("[data-preset]").forEach((button) => {
            const active = button.dataset.preset === preset;
            button.classList.toggle("is-active", active);
            button.setAttribute("aria-pressed", String(active));
        });
        $("teamCalendarTrigger").classList.toggle("is-active", !preset);
        $("teamPeriodSummary").textContent = `${formatDate(from)} — ${formatDate($("sharedTo").value)}`;
    }

    function monthMarkup(firstDay) {
        const monthNames = [
            "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
            "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
        ];
        const year = firstDay.getUTCFullYear();
        const month = firstDay.getUTCMonth();
        const offset = (firstDay.getUTCDay() + 6) % 7;
        const dayCount = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
        const cells = Array.from({ length: offset }, () => '<span class="team-calendar-day is-empty"></span>');
        for (let day = 1; day <= dayCount; day += 1) {
            const value = isoDate(new Date(Date.UTC(year, month, day, 12)));
            const classes = ["team-calendar-day"];
            if (value === today) classes.push("is-today");
            if (value === calendarFrom) classes.push("is-start");
            if (value === calendarTo) classes.push("is-end");
            if (calendarFrom && calendarTo && value > calendarFrom && value < calendarTo) classes.push("is-range");
            cells.push(`<button class="${classes.join(" ")}" type="button" data-calendar-date="${value}"${value > today ? " disabled" : ""}>${day}</button>`);
        }
        return `<section class="team-calendar-month">
            <h3>${monthNames[month]} ${year}</h3>
            <div class="team-calendar-weekdays"><span>Пн</span><span>Вт</span><span>Ср</span><span>Чт</span><span>Пт</span><span>Сб</span><span>Вс</span></div>
            <div class="team-calendar-days">${cells.join("")}</div>
        </section>`;
    }

    function renderCalendars() {
        $("teamCalendars").innerHTML = monthMarkup(calendarView) + monthMarkup(addMonths(calendarView, 1));
        $("teamCalendarFrom").textContent = formatDate(calendarFrom);
        $("teamCalendarTo").textContent = formatDate(calendarTo);
        $("teamCalendarApply").disabled = !(calendarFrom && calendarTo);
        const currentMonth = monthStart(parseDate(today));
        $("teamCalendarNext").disabled = addMonths(calendarView, 1) >= currentMonth;
    }

    function openCalendar() {
        calendarFrom = $("sharedFrom").value || null;
        calendarTo = $("sharedTo").value || null;
        const anchor = monthStart(parseDate(calendarTo || today));
        calendarView = addMonths(anchor, -1);
        renderCalendars();
        $("teamCalendarPopover").hidden = false;
        $("teamCalendarTrigger").setAttribute("aria-expanded", "true");
    }

    function closeCalendar() {
        $("teamCalendarPopover").hidden = true;
        $("teamCalendarTrigger").setAttribute("aria-expanded", "false");
    }

    function selectCalendarDate(value) {
        if (!calendarFrom || calendarTo) {
            calendarFrom = value;
            calendarTo = null;
        } else if (value < calendarFrom) {
            calendarFrom = value;
        } else {
            calendarTo = value;
        }
        renderCalendars();
    }

    function render(data) {
        report = data;
        today = data.today;
        $("sharedFrom").value = data.registration_range[0];
        $("sharedTo").value = data.registration_range[1];
        $("teamUpdated").textContent = formattedTimestamp(data.updated_at);
        $("teamTimezone").textContent = data.timezone;
        $("teamStatus").textContent = data.error
            ? stateText[data.error] || "Ошибка обновления смен. Показаны сохранённые данные."
            : data.stale ? "Данные смен требуют обновления." : "";
        setActivePreset();
        renderView();
        $("teamCoverage").textContent = "«Из них в КБ» — новые гости администратора, которые уже подключились к Кибер Бонус. «Зарегистрировано в КБ» — все подключения во время его смен. Смены считаются по уникальным рабочим дням. Конверсия = «Из них в КБ» / «Новые в Langame».";
    }

    async function load() {
        controller?.abort();
        controller = new AbortController();
        const own = controller;
        const params = new URLSearchParams();
        if ($("sharedFrom").value) {
            params.set("registration_from", $("sharedFrom").value);
            params.set("cohort_from", $("sharedFrom").value);
        }
        if ($("sharedTo").value) {
            params.set("registration_to", $("sharedTo").value);
            params.set("cohort_to", $("sharedTo").value);
        }
        $("teamError").hidden = true;
        $("teamStatus").textContent = "Обновляем отчёт…";
        document.querySelectorAll(".team button").forEach((button) => { button.disabled = true; });
        try {
            const response = await fetch(`/owner/api/team?${params}`, {
                signal: own.signal,
                headers: { Accept: "application/json" },
            });
            const data = await response.json();
            if (!response.ok || !data.ok) throw new Error(data.error || "Не удалось загрузить отчёт");
            if (controller === own) render(data);
        } catch (error) {
            if (error.name !== "AbortError") {
                $("teamError").textContent = error.message || "Не удалось загрузить отчёт";
                $("teamError").hidden = false;
                $("teamStatus").textContent = "Отчёт не обновлён. Показаны предыдущие данные.";
            }
        } finally {
            if (controller === own) {
                document.querySelectorAll(".team button").forEach((button) => { button.disabled = false; });
            }
        }
    }

    document.querySelectorAll("[data-sort-table][data-sort-key]").forEach((button) => {
        button.addEventListener("click", () => {
            const sorting = tableSort[button.dataset.sortTable];
            if (sorting.key === button.dataset.sortKey) sorting.direction = sorting.direction === "desc" ? "asc" : "desc";
            else {
                sorting.key = button.dataset.sortKey;
                sorting.direction = button.dataset.sortKey === "name" ? "asc" : "desc";
            }
            renderView();
        });
    });
    $("teamRefresh").addEventListener("click", load);
    $("teamAdminSettingsOpen").addEventListener("click", openAdminSettings);
    $("teamAdminSettingsSave").addEventListener("click", saveAdminSettings);
    $("teamAdminSettingsToggleAll").addEventListener("click", () => {
        const inputs = [...$("teamAdminSettingsList").querySelectorAll("[data-admin-id]")];
        const selectAll = !inputs.every((input) => input.checked);
        inputs.forEach((input) => { input.checked = selectAll; });
        updateToggleAllButton();
    });
    $("teamAdminSettingsList").addEventListener("change", (event) => {
        if (event.target.matches("[data-admin-id]")) updateToggleAllButton();
    });
    document.querySelectorAll("[data-admin-settings-close]").forEach((button) => {
        button.addEventListener("click", closeAdminSettings);
    });
    $("teamAdminSettingsModal").addEventListener("cancel", (event) => {
        event.preventDefault();
        closeAdminSettings();
    });
    $("teamAdminSettingsModal").addEventListener("click", (event) => {
        if (event.target === $("teamAdminSettingsModal")) closeAdminSettings();
    });
    document.querySelectorAll("[data-preset]").forEach((button) => button.addEventListener("click", () => {
        if (!today) return;
        $("sharedFrom").value = presetStart(button.dataset.preset);
        $("sharedTo").value = today;
        closeCalendar();
        setActivePreset();
        load();
    }));
    $("teamCalendarTrigger").addEventListener("click", () => {
        if ($("teamCalendarPopover").hidden) openCalendar();
        else closeCalendar();
    });
    $("teamCalendarPrev").addEventListener("click", () => {
        calendarView = addMonths(calendarView, -1);
        renderCalendars();
    });
    $("teamCalendarNext").addEventListener("click", () => {
        calendarView = addMonths(calendarView, 1);
        renderCalendars();
    });
    $("teamCalendars").addEventListener("click", (event) => {
        const button = event.target.closest("[data-calendar-date]");
        if (button && !button.disabled) selectCalendarDate(button.dataset.calendarDate);
    });
    $("teamCalendarApply").addEventListener("click", () => {
        if (!calendarFrom || !calendarTo) return;
        $("sharedFrom").value = calendarFrom;
        $("sharedTo").value = calendarTo;
        closeCalendar();
        setActivePreset();
        load();
    });
    document.addEventListener("click", (event) => {
        const clickedInsidePeriod = event.composedPath().some(
            (element) => element instanceof Element && element.classList.contains("team-period"),
        );
        if (!clickedInsidePeriod) closeCalendar();
    });
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !$("teamCalendarPopover").hidden) closeCalendar();
    });
    load();
})();
