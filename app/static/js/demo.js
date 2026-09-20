(() => {
    const toastBox = document.querySelector('[data-demo-toast-box]');
    let toastTimer;
    const showToast = (message) => {
        if (!toastBox) return;
        toastBox.textContent = message;
        toastBox.classList.add('is-visible');
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => toastBox.classList.remove('is-visible'), 2600);
    };

    const sidebar = document.querySelector('[data-demo-sidebar]');
    document.querySelector('[data-demo-menu]')?.addEventListener('click', () => sidebar?.classList.toggle('is-open'));
    document.querySelectorAll('[data-demo-nav-toggle]').forEach((button) => {
        button.addEventListener('click', () => {
            const group = button.closest('[data-demo-nav-group]');
            document.querySelectorAll('[data-demo-nav-group]').forEach((other) => {
                if (other !== group) other.classList.remove('is-open');
            });
            group?.classList.toggle('is-open');
        });
    });

    document.querySelectorAll('.demo-segment').forEach((segment) => {
        segment.querySelectorAll('button').forEach((button) => {
            button.addEventListener('click', () => {
                segment.querySelectorAll('button').forEach((item) => item.classList.remove('is-active'));
                button.classList.add('is-active');
            });
        });
    });

    const randomizeVisibleData = () => {
        document.querySelectorAll('[data-demo-chart] i').forEach((bar) => {
            const value = 28 + Math.floor(Math.random() * 70);
            bar.style.setProperty('--value', `${value}%`);
            const label = bar.querySelector('span');
            if (label) label.textContent = value;
        });
        document.querySelectorAll('[data-random-number]').forEach((node, index) => {
            const values = [
                320 + Math.floor(Math.random() * 330),
                900 + Math.floor(Math.random() * 1100),
                `${480 + Math.floor(Math.random() * 430)} ₽`,
                `${54 + Math.floor(Math.random() * 30)}%`,
            ];
            node.textContent = typeof values[index] === 'number' ? values[index].toLocaleString('ru-RU') : values[index];
        });
        showToast('Демонстрационные данные обновлены');
    };
    document.querySelectorAll('[data-demo-refresh]').forEach((button) => button.addEventListener('click', randomizeVisibleData));
    document.querySelectorAll('[data-demo-filter]').forEach((input) => input.addEventListener('change', () => showToast('Фильтр применён к демо-данным')));

    const search = document.querySelector('[data-demo-search]');
    search?.addEventListener('input', () => {
        const query = search.value.trim().toLowerCase();
        document.querySelectorAll('[data-demo-row]').forEach((row) => {
            row.hidden = Boolean(query) && !row.textContent.toLowerCase().includes(query);
        });
    });

    const statusFilter = document.querySelector('[data-demo-status-filter]');
    statusFilter?.querySelectorAll('button').forEach((button) => {
        button.addEventListener('click', () => {
            const selected = button.dataset.status;
            document.querySelectorAll('.demo-mission[data-status]').forEach((card) => {
                card.hidden = selected !== 'all' && card.dataset.status !== selected;
            });
        });
    });

    document.querySelectorAll('.demo-switch').forEach((toggle) => {
        toggle.addEventListener('click', () => {
            toggle.classList.toggle('is-on');
            toggle.setAttribute('aria-pressed', toggle.classList.contains('is-on') ? 'true' : 'false');
        });
    });

    const openModal = (modal) => {
        if (!modal) return;
        modal.classList.add('is-open');
        modal.setAttribute('aria-hidden', 'false');
        document.documentElement.style.overflow = 'hidden';
    };
    const closeModal = (modal) => {
        if (!modal) return;
        modal.classList.remove('is-open');
        modal.setAttribute('aria-hidden', 'true');
        document.documentElement.style.overflow = '';
    };
    document.querySelectorAll('[data-demo-modal-open]').forEach((button) => {
        button.addEventListener('click', () => openModal(document.getElementById(button.dataset.demoModalOpen)));
    });
    document.querySelectorAll('.demo-modal').forEach((modal) => {
        modal.addEventListener('click', (event) => { if (event.target === modal) closeModal(modal); });
        modal.querySelectorAll('.demo-modal-close, .demo-modal-close-action').forEach((button) => button.addEventListener('click', () => closeModal(modal)));
    });
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') document.querySelectorAll('.demo-modal.is-open').forEach(closeModal);
    });
    document.querySelectorAll('.demo-save').forEach((button) => {
        button.addEventListener('click', () => {
            closeModal(button.closest('.demo-modal'));
            showToast('Изменения сохранены только в демо');
        });
    });
    document.querySelectorAll('[data-demo-toast]').forEach((button) => button.addEventListener('click', () => showToast(button.dataset.demoToast)));

    const caseModal = document.getElementById('demoCaseModal');
    if (!caseModal) return;

    let selectedCaseId = null;
    let caseBusy = false;
    const title = caseModal.querySelector('[data-demo-case-title]');
    const itemsBox = caseModal.querySelector('[data-demo-case-items]');
    const reel = caseModal.querySelector('[data-demo-reel]');
    const previewView = caseModal.querySelector('[data-demo-case-preview-view]');
    const resultView = caseModal.querySelector('[data-demo-case-result]');
    const openButton = caseModal.querySelector('[data-demo-open-case]');
    const balanceNode = document.querySelector('[data-demo-balance]');
    const historyNode = document.querySelector('[data-demo-history]');

    const readCaseItems = (caseId) => {
        const template = document.getElementById(`demo-case-${caseId}`);
        if (!template?.content) return [];
        return Array.from(template.content.querySelectorAll('div')).map((node) => ({
            name: node.dataset.name,
            symbol: node.dataset.symbol,
            description: node.dataset.description,
        }));
    };

    const renderReel = (items, winner = null) => {
        if (!reel) return;
        const sequence = Array.from({ length: 15 }, (_, index) => {
            if (winner && index === 11) return winner;
            return items[Math.floor(Math.random() * items.length)];
        });
        reel.innerHTML = sequence.map((item) => `<article title="${item.name}"><span>${item.symbol}</span></article>`).join('');
    };

    const previewCase = (caseId) => {
        const template = document.getElementById(`demo-case-${caseId}`);
        if (!template) return;
        selectedCaseId = caseId;
        const items = readCaseItems(caseId);
        title.textContent = template.dataset.caseName;
        itemsBox.innerHTML = items.map((item) => `<article><span>${item.symbol}</span><b>${item.name}</b></article>`).join('');
        renderReel(items);
        previewView.hidden = false;
        resultView.hidden = true;
        openButton.disabled = false;
        openButton.textContent = `Открыть за ${template.dataset.casePrice} жет.`;
        caseModal.querySelector('.demo-case-reel')?.classList.remove('is-spinning');
        openModal(caseModal);
    };
    document.querySelectorAll('[data-demo-case-preview]').forEach((button) => button.addEventListener('click', () => previewCase(Number(button.dataset.demoCasePreview))));

    const renderHistory = (history) => {
        if (!historyNode) return;
        if (!history.length) {
            historyNode.innerHTML = '<p class="demo-empty">Открой первый кейс — выигрыш появится здесь.</p>';
            return;
        }
        historyNode.innerHTML = history.map((item) => `<article><span>${item.symbol}</span><div><b>${item.name}</b><small>${item.case} · сегодня ${item.time}</small></div></article>`).join('');
    };

    openButton?.addEventListener('click', async () => {
        if (caseBusy || !selectedCaseId) return;
        caseBusy = true;
        openButton.disabled = true;
        openButton.textContent = 'Открываем…';
        try {
            const endpoint = String(window.demoCaseOpenUrl || '').replace(/\/0\/open$/, `/${selectedCaseId}/open`);
            const response = await fetch(endpoint, { method: 'POST', headers: { Accept: 'application/json' } });
            const data = await response.json();
            if (!response.ok) {
                if (data.error === 'no_tokens') showToast('Жетонов не хватает. Сбросьте демо-баланс.');
                else showToast('Не удалось открыть кейс');
                return;
            }
            const items = readCaseItems(selectedCaseId);
            renderReel(items, data.prize);
            const reelBox = caseModal.querySelector('.demo-case-reel');
            reelBox.classList.remove('is-spinning');
            void reelBox.offsetWidth;
            reelBox.classList.add('is-spinning');
            await new Promise((resolve) => setTimeout(resolve, 2700));
            if (balanceNode) balanceNode.textContent = data.tokens;
            renderHistory(data.history || []);
            caseModal.querySelector('[data-demo-win-symbol]').textContent = data.prize.symbol;
            caseModal.querySelector('[data-demo-win-name]').textContent = data.prize.name;
            caseModal.querySelector('[data-demo-win-description]').textContent = data.prize.description;
            previewView.hidden = true;
            resultView.hidden = false;
        } catch (error) {
            showToast('Соединение с демо временно недоступно');
        } finally {
            caseBusy = false;
            openButton.disabled = false;
        }
    });

    document.querySelector('[data-demo-reset]')?.addEventListener('click', async () => {
        try {
            const response = await fetch('/demo/guest/reset', { method: 'POST', headers: { Accept: 'application/json' } });
            const data = await response.json();
            if (balanceNode) balanceNode.textContent = data.tokens;
            renderHistory([]);
            showToast('Демо-баланс восстановлен');
        } catch (error) {
            showToast('Не удалось сбросить демо');
        }
    });
})();
