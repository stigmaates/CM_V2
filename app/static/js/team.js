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

    function adminKey(admin) {
        return admin.admin_id === null ? "unknown" : String(admin.admin_id);
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

    function filteredAdmins() {
        if (!report) return [];
        const selected = $("teamAdminFilter").value;
        return selected === "all"
            ? report.admins
            : report.admins.filter((admin) => adminKey(admin) === selected);
    }

    function totals(admins) {
        const total = {
            club_registrations: 0,
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
        total.conversion12 = total.visit1 ? Math.round((total.visit2 / total.visit1) * 1000) / 10 : null;
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

    function renderKpis(admins, total) {
        const known = admins.filter((admin) => admin.admin_id !== null);
        const active = known.filter((admin) => (admin.shift_count || 0) > 0).length;
        $("kpiClub").textContent = num(total.club_registrations);
        $("kpiModule").textContent = num(total.module_registrations);
        $("kpiModuleNote").textContent = total.module_estimated
            ? `≈ ${num(total.module_estimated)} с восстановленной датой`
            : "точные регистрации за период";
        $("kpiAdmins").textContent = num(active);
        $("kpiAdminsNote").textContent = `из ${num(known.length)} в текущем фильтре`;
        $("kpiShifts").textContent = num(total.shift_count);
        $("kpiConversion12").textContent = percent(total.conversion12);
        $("kpiConversion23").textContent = percent(total.conversion23);
    }

    function renderRegistrations(admins, total) {
        const sort = $("teamRegistrationSort").value;
        const key = { club: "club_registrations", module: "module_registrations", shifts: "shift_count" }[sort];
        const ordered = [...admins].sort((a, b) => (
            Number(a.admin_id === null) - Number(b.admin_id === null)
            || (b[key] || 0) - (a[key] || 0)
            || a.name.localeCompare(b.name, "ru")
        ));
        if (!ordered.length) {
            $("teamRegistrations").innerHTML = '<tr><td class="team-empty" colspan="6">Нет данных по выбранному администратору</td></tr>';
            return;
        }
        $("teamRegistrations").innerHTML = ordered.map((admin, index) => {
            const share = total.club_registrations
                ? Math.round((admin.club_registrations / total.club_registrations) * 1000) / 10
                : 0;
            const estimated = admin.module_estimated
                ? `<small>≈ ${num(admin.module_estimated)} восстановлено</small>`
                : "";
            return `<tr class="${admin.admin_id === null ? "team-unknown" : ""}">
                <td>${rank(index)}</td>
                <td>${identity(admin)}</td>
                <td><span class="team-number">${num(admin.club_registrations)}</span></td>
                <td><span class="team-number">${num(admin.module_registrations)}${estimated}</span></td>
                <td><span class="team-number">${num(admin.shift_count)}</span></td>
                <td><span class="team-share"><span>${percent(share)}</span><span class="team-share__bar"><i style="width:${Math.min(100, share)}%"></i></span></span></td>
            </tr>`;
        }).join("");
    }

    function renderFunnel(admins) {
        const sort = $("teamFunnelSort").value;
        const ordered = [...admins].sort((a, b) => {
            const first = sort === "cohort" ? (b.cohort || 0) - (a.cohort || 0) : (b.conversion12 ?? -1) - (a.conversion12 ?? -1);
            return Number(a.admin_id === null) - Number(b.admin_id === null) || first || a.name.localeCompare(b.name, "ru");
        });
        if (!ordered.length) {
            $("teamFunnel").innerHTML = '<tr><td class="team-empty" colspan="8">Нет данных по выбранному администратору</td></tr>';
            return;
        }
        $("teamFunnel").innerHTML = ordered.map((admin, index) => `<tr class="${admin.admin_id === null ? "team-unknown" : ""}">
            <td>${rank(index)}</td>
            <td>${identity(admin)}</td>
            <td><span class="team-number">${num(admin.cohort)}</span></td>
            <td><span class="team-number">${num(admin.visit1)}</span></td>
            <td><span class="team-number">${num(admin.visit2)}</span></td>
            <td><span class="team-number">${num(admin.visit3)}</span></td>
            <td>${conversion(admin.conversion12)}</td>
            <td>${conversion(admin.conversion23)}</td>
        </tr>`).join("");
    }

    function renderView() {
        const admins = filteredAdmins();
        const total = totals(admins);
        const selectedOption = $("teamAdminFilter").selectedOptions[0];
        $("teamAdminFilterLabel").textContent = selectedOption?.textContent || "Все администраторы";
        renderKpis(admins, total);
        renderRegistrations(admins, total);
        renderFunnel(admins);
    }

    function populateAdminFilter(admins) {
        const select = $("teamAdminFilter");
        const selected = select.value;
        select.innerHTML = '<option value="all">Все администраторы</option>' + admins.map((admin) => (
            `<option value="${escape(adminKey(admin))}">${escape(admin.name)}</option>`
        )).join("");
        if ([...select.options].some((option) => option.value === selected)) select.value = selected;
    }

    function setActivePreset() {
        document.querySelectorAll("[data-preset]").forEach((button) => button.classList.remove("is-active"));
        if (!today || !$("sharedFrom").value) return;
        const selected = $("sharedFrom").value;
        const date = new Date(`${today}T12:00:00Z`);
        const month = new Date(date); month.setUTCDate(1);
        const week = new Date(date); week.setUTCDate(week.getUTCDate() - ((week.getUTCDay() + 6) % 7));
        const preset = selected === month.toISOString().slice(0, 10) ? "month"
            : selected === week.toISOString().slice(0, 10) ? "week" : null;
        if (preset) document.querySelector(`[data-preset="${preset}"]`).classList.add("is-active");
    }

    function render(data) {
        report = data;
        today = data.today;
        $("sharedFrom").value = data.registration_range[0];
        $("sharedTo").value = data.registration_range[1];
        $("sharedFrom").max = today;
        $("sharedTo").max = today;
        $("teamUpdated").textContent = formattedTimestamp(data.updated_at);
        $("teamTimezone").textContent = data.timezone;
        $("teamStatus").textContent = data.error
            ? stateText[data.error] || "Ошибка обновления смен. Показаны сохранённые данные."
            : data.stale ? "Данные смен требуют обновления." : "";
        populateAdminFilter(data.admins);
        setActivePreset();
        renderView();
        $("teamCoverage").textContent = `≈ — дата регистрации в модуле восстановлена приблизительно. Без известной даты: в клубе ${num(data.unknown_club_dates)}, в модуле ${num(data.unknown_module_dates)}.`;
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

    $("teamAdminFilter").addEventListener("change", renderView);
    $("teamRegistrationSort").addEventListener("change", renderView);
    $("teamFunnelSort").addEventListener("change", renderView);
    $("teamRefresh").addEventListener("click", load);
    $("sharedFrom").addEventListener("change", setActivePreset);
    $("sharedTo").addEventListener("change", setActivePreset);
    document.querySelector("[data-apply]").addEventListener("click", load);
    document.querySelectorAll("[data-preset]").forEach((button) => button.addEventListener("click", () => {
        if (!today) return;
        const date = new Date(`${today}T12:00:00Z`);
        if (button.dataset.preset === "month") date.setUTCDate(1);
        else date.setUTCDate(date.getUTCDate() - ((date.getUTCDay() + 6) % 7));
        $("sharedFrom").value = date.toISOString().slice(0, 10);
        $("sharedTo").value = today;
        load();
    }));
    document.querySelectorAll("[data-scroll-to]").forEach((button) => button.addEventListener("click", () => {
        document.querySelectorAll("[data-scroll-to]").forEach((item) => item.classList.remove("is-active"));
        button.classList.add("is-active");
        document.getElementById(button.dataset.scrollTo).scrollIntoView({ behavior: "smooth", block: "start" });
    }));

    load();
})();
