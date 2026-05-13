/* global Telegram */
const tg = window.Telegram?.WebApp;
let initData = "";
let currentUser = null;
let advertisers = [];
let promos = [];
let exchangeRate = 92;

// ── Init ──

document.addEventListener("DOMContentLoaded", async () => {
    if (tg) {
        tg.ready();
        tg.expand();
        initData = tg.initData || "";
        tg.setHeaderColor(
            getComputedStyle(document.documentElement)
                .getPropertyValue("--tg-theme-bg-color")
                .trim() || "#1a1a2e"
        );
    }
    await auth();
    showPage("dashboard");
});

// ── API ──

async function api(path, options = {}) {
    const headers = {
        "Content-Type": "application/json",
        "X-Telegram-Init-Data": initData || JSON.stringify({ id: 1, first_name: "Dev", username: "dev" }),
    };
    const resp = await fetch(path, { ...options, headers });
    if (!resp.ok) {
        const err = await resp.text();
        console.error("API error:", resp.status, err);
        throw new Error(err);
    }
    return resp.json();
}

async function auth() {
    try {
        currentUser = await api("/api/auth", { method: "POST" });
    } catch (e) {
        console.error("Auth failed:", e);
    }
}

// ── Navigation ──

function showPage(page) {
    document.querySelectorAll(".page").forEach((p) => p.classList.remove("active"));
    document.querySelectorAll(".nav-btn").forEach((b) => b.classList.remove("active"));
    document.getElementById("page-" + page)?.classList.add("active");
    document.querySelector(`.nav-btn[data-page="${page}"]`)?.classList.add("active");

    switch (page) {
        case "dashboard": loadDashboard(); break;
        case "advertisers": loadAdvertisers(); break;
        case "promos": loadPromosPage(); break;
        case "converter": loadConverter(); break;
        case "profile": loadProfile(); break;
    }
}

// ── Dashboard ──

async function loadDashboard() {
    try {
        const profile = await api("/api/profile");
        document.getElementById("statAdvertisers").textContent = profile.advertisers_count;
        document.getElementById("statPromos").textContent = profile.promos_count;
        document.getElementById("statDone").textContent = profile.done_count;
        document.getElementById("statPending").textContent = profile.promos_count - profile.done_count;
    } catch (e) {
        console.error(e);
    }

    try {
        const allPromos = await api("/api/promos");
        const now = new Date();
        const upcoming = allPromos
            .filter((p) => p.deadline && p.status !== "done")
            .sort((a, b) => new Date(a.deadline) - new Date(b.deadline))
            .slice(0, 5);

        const container = document.getElementById("upcomingDeadlines");
        if (upcoming.length === 0) {
            container.innerHTML = '<div class="empty-state"><div class="empty-icon">📅</div><div class="empty-text">Нет активных дедлайнов</div></div>';
        } else {
            container.innerHTML = upcoming.map((p) => {
                const dl = new Date(p.deadline);
                const diff = dl - now;
                const hours = Math.floor(diff / 3600000);
                let deadlineClass = "";
                if (diff < 0) deadlineClass = "overdue";
                else if (hours < 24) deadlineClass = "soon";
                return `
                    <div class="card" onclick="showPromoDetail(${p.id})">
                        <div class="card-header">
                            <span class="card-title">${esc(p.name)}</span>
                            <span class="status status-${p.status}">${statusLabel(p.status)}</span>
                        </div>
                        <div class="card-meta">
                            <span>👤 ${esc(p.advertiser_name || "—")}</span>
                            <span class="deadline ${deadlineClass}">📅 ${formatDate(p.deadline)}</span>
                            ${p.price_usdt ? `<span class="price-usdt">$${p.price_usdt}</span>` : ""}
                        </div>
                    </div>`;
            }).join("");
        }
    } catch (e) {
        console.error(e);
    }

    try {
        const reminders = await api("/api/reminders");
        const container = document.getElementById("remindersList");
        if (reminders.length === 0) {
            container.innerHTML = '<div class="empty-state"><div class="empty-icon">🔔</div><div class="empty-text">Нет напоминаний</div></div>';
        } else {
            container.innerHTML = reminders.map((r) => `
                <div class="card">
                    <div class="card-header">
                        <span class="card-title">🔔 ${esc(r.message || r.promo_name || "Напоминание")}</span>
                        <button class="btn-icon btn-sm" onclick="event.stopPropagation(); deleteReminder(${r.id})" style="background:var(--danger);width:24px;height:24px;font-size:12px;">✕</button>
                    </div>
                    <div class="card-meta">
                        <span>⏰ ${formatDate(r.remind_at)}</span>
                        ${r.promo_name ? `<span>📋 ${esc(r.promo_name)}</span>` : ""}
                    </div>
                </div>`).join("");
        }
    } catch (e) {
        console.error(e);
    }
}

// ── Advertisers ──

async function loadAdvertisers() {
    try {
        advertisers = await api("/api/advertisers");
        const container = document.getElementById("advertisersList");
        if (advertisers.length === 0) {
            container.innerHTML = '<div class="empty-state"><div class="empty-icon">👤</div><div class="empty-text">Нет рекламодателей.<br>Нажмите + Добавить</div></div>';
        } else {
            container.innerHTML = advertisers.map((a) => `
                <div class="card" onclick="showAdvertiserDetail(${a.id})">
                    <div class="card-header">
                        <span class="card-title">${esc(a.name)}</span>
                    </div>
                    ${a.username ? `<div class="card-subtitle">@${esc(a.username)}</div>` : ""}
                    ${a.link ? `<div class="card-meta"><span>🔗 ${esc(a.link)}</span></div>` : ""}
                    ${a.notes ? `<div class="card-meta"><span>📝 ${esc(a.notes.substring(0, 60))}${a.notes.length > 60 ? "..." : ""}</span></div>` : ""}
                </div>`).join("");
        }
    } catch (e) {
        console.error(e);
    }
}

function showAddAdvertiser(existing = null) {
    const isEdit = !!existing;
    openModal(`
        <div class="modal-title">${isEdit ? "✏️ Редактировать" : "➕ Новый рекламодатель"}</div>
        <div class="input-group">
            <label>Имя / Название</label>
            <input type="text" id="advName" value="${esc(existing?.name || "")}" placeholder="Название компании или имя">
        </div>
        <div class="input-group">
            <label>Username (Telegram)</label>
            <input type="text" id="advUsername" value="${esc(existing?.username || "")}" placeholder="@username">
        </div>
        <div class="input-group">
            <label>Ссылка</label>
            <input type="url" id="advLink" value="${esc(existing?.link || "")}" placeholder="https://...">
        </div>
        <div class="input-group">
            <label>Заметки</label>
            <textarea id="advNotes" placeholder="Дополнительная информация...">${esc(existing?.notes || "")}</textarea>
        </div>
        <div class="modal-actions">
            <button class="btn-secondary" onclick="closeModal()">Отмена</button>
            ${isEdit ? `<button class="btn-danger" onclick="deleteAdvertiser(${existing.id})">Удалить</button>` : ""}
            <button class="btn-primary" onclick="saveAdvertiser(${existing?.id || "null"})">${isEdit ? "Сохранить" : "Добавить"}</button>
        </div>
    `);
}

async function saveAdvertiser(id) {
    const data = {
        name: document.getElementById("advName").value.trim(),
        username: document.getElementById("advUsername").value.trim().replace(/^@/, ""),
        link: document.getElementById("advLink").value.trim(),
        notes: document.getElementById("advNotes").value.trim(),
    };
    if (!data.name) {
        tg?.showAlert?.("Введите имя рекламодателя") || alert("Введите имя рекламодателя");
        return;
    }
    try {
        if (id) {
            await api(`/api/advertisers/${id}`, { method: "PUT", body: JSON.stringify(data) });
        } else {
            await api("/api/advertisers", { method: "POST", body: JSON.stringify(data) });
        }
        closeModal();
        loadAdvertisers();
        if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
    } catch (e) {
        tg?.showAlert?.("Ошибка сохранения") || alert("Ошибка");
    }
}

async function deleteAdvertiser(id) {
    if (!confirm("Удалить рекламодателя и все его промо?")) return;
    try {
        await api(`/api/advertisers/${id}`, { method: "DELETE" });
        closeModal();
        loadAdvertisers();
    } catch (e) {
        console.error(e);
    }
}

async function showAdvertiserDetail(id) {
    const adv = advertisers.find((a) => a.id === id);
    if (adv) showAddAdvertiser(adv);
}

// ── Promos ──

async function loadPromosPage() {
    try {
        advertisers = await api("/api/advertisers");
        const select = document.getElementById("promoFilterAdvertiser");
        const currentVal = select.value;
        select.innerHTML = '<option value="">Все рекламодатели</option>' +
            advertisers.map((a) => `<option value="${a.id}">${esc(a.name)}</option>`).join("");
        select.value = currentVal;
    } catch (e) {
        console.error(e);
    }
    await loadPromos();
}

async function loadPromos() {
    const advFilter = document.getElementById("promoFilterAdvertiser")?.value;
    try {
        let url = "/api/promos";
        if (advFilter) url += `?advertiser_id=${advFilter}`;
        promos = await api(url);
        renderPromos();
    } catch (e) {
        console.error(e);
    }
}

function filterPromos() {
    renderPromos();
}

function renderPromos() {
    const statusFilter = document.getElementById("promoFilterStatus")?.value;
    let filtered = promos;
    if (statusFilter) filtered = promos.filter((p) => p.status === statusFilter);

    const container = document.getElementById("promosList");
    if (filtered.length === 0) {
        container.innerHTML = '<div class="empty-state"><div class="empty-icon">🔗</div><div class="empty-text">Нет промо-ссылок.<br>Нажмите + Добавить</div></div>';
        return;
    }

    const now = new Date();
    container.innerHTML = filtered.map((p) => {
        let deadlineHtml = "";
        if (p.deadline) {
            const dl = new Date(p.deadline);
            const diff = dl - now;
            let cls = "";
            if (diff < 0) cls = "overdue";
            else if (diff < 86400000) cls = "soon";
            deadlineHtml = `<span class="deadline ${cls}">📅 ${formatDate(p.deadline)}</span>`;
        }
        return `
            <div class="card" onclick="showPromoDetail(${p.id})">
                <div class="card-header">
                    <span class="card-title">${esc(p.name)}</span>
                    <select class="status-select ${p.status}" onchange="event.stopPropagation(); changePromoStatus(${p.id}, this.value)" onclick="event.stopPropagation()">
                        <option value="not_ready" ${p.status === "not_ready" ? "selected" : ""}>❌ Не готово</option>
                        <option value="in_progress" ${p.status === "in_progress" ? "selected" : ""}>⏳ В процессе</option>
                        <option value="done" ${p.status === "done" ? "selected" : ""}>✅ Готово</option>
                    </select>
                </div>
                <div class="card-subtitle">👤 ${esc(p.advertiser_name || "—")}</div>
                <div class="card-meta">
                    ${p.link ? `<span>🔗 Ссылка</span>` : ""}
                    ${deadlineHtml}
                    ${p.price_usdt ? `<span class="price-usdt">$${p.price_usdt} USDT</span>` : ""}
                </div>
                ${p.notes ? `<div class="card-meta"><span>📝 ${esc(p.notes.substring(0, 80))}${p.notes.length > 80 ? "..." : ""}</span></div>` : ""}
            </div>`;
    }).join("");
}

function showAddPromo(existing = null) {
    const isEdit = !!existing;
    openModal(`
        <div class="modal-title">${isEdit ? "✏️ Редактировать промо" : "➕ Новое промо"}</div>
        <div class="input-group">
            <label>Рекламодатель</label>
            <select id="promoAdvId">
                <option value="">Выберите...</option>
                ${advertisers.map((a) => `<option value="${a.id}" ${existing?.advertiser_id === a.id ? "selected" : ""}>${esc(a.name)}</option>`).join("")}
            </select>
        </div>
        <div class="input-group">
            <label>Название промо</label>
            <input type="text" id="promoName" value="${esc(existing?.name || "")}" placeholder="Название кампании">
        </div>
        <div class="input-group">
            <label>Ссылка</label>
            <input type="url" id="promoLink" value="${esc(existing?.link || "")}" placeholder="https://...">
        </div>
        <div class="input-group">
            <label>Цена (USDT)</label>
            <input type="number" id="promoPrice" value="${existing?.price_usdt || ""}" placeholder="0.00" step="0.01" oninput="updatePromoRubPrice()">
            <div style="font-size:12px;color:var(--text-secondary);margin-top:4px;" id="promoRubEquiv"></div>
        </div>
        <div class="input-group">
            <label>Дедлайн</label>
            <input type="datetime-local" id="promoDeadline" value="${existing?.deadline ? existing.deadline.replace(" ", "T").substring(0, 16) : ""}">
        </div>
        <div class="input-group">
            <label>Статус</label>
            <select id="promoStatus">
                <option value="not_ready" ${existing?.status === "not_ready" ? "selected" : ""}>❌ Не готово</option>
                <option value="in_progress" ${existing?.status === "in_progress" ? "selected" : ""}>⏳ В процессе</option>
                <option value="done" ${existing?.status === "done" ? "selected" : ""}>✅ Готово</option>
            </select>
        </div>
        <div class="input-group">
            <label>Заметки</label>
            <textarea id="promoNotes" placeholder="Дополнительная информация...">${esc(existing?.notes || "")}</textarea>
        </div>
        <div class="modal-actions">
            <button class="btn-secondary" onclick="closeModal()">Отмена</button>
            ${isEdit ? `<button class="btn-danger" onclick="deletePromo(${existing.id})">Удалить</button>` : ""}
            <button class="btn-primary" onclick="savePromo(${existing?.id || "null"})">${isEdit ? "Сохранить" : "Добавить"}</button>
        </div>
    `);
    updatePromoRubPrice();
}

async function updatePromoRubPrice() {
    const priceInput = document.getElementById("promoPrice");
    const equiv = document.getElementById("promoRubEquiv");
    if (!priceInput || !equiv) return;
    const val = parseFloat(priceInput.value);
    if (val && val > 0) {
        try {
            const data = await api(`/api/convert?amount=${val}&direction=usdt_to_rub`);
            equiv.textContent = `≈ ${data.result} RUB (курс: ${data.rate})`;
            exchangeRate = data.rate;
        } catch (e) {
            equiv.textContent = `≈ ${(val * exchangeRate).toFixed(2)} RUB`;
        }
    } else {
        equiv.textContent = "";
    }
}

async function savePromo(id) {
    const data = {
        advertiser_id: parseInt(document.getElementById("promoAdvId").value),
        name: document.getElementById("promoName").value.trim(),
        link: document.getElementById("promoLink").value.trim(),
        price_usdt: parseFloat(document.getElementById("promoPrice").value) || null,
        deadline: document.getElementById("promoDeadline").value?.replace("T", " ") || null,
        status: document.getElementById("promoStatus").value,
        notes: document.getElementById("promoNotes").value.trim(),
    };
    if (!data.advertiser_id) {
        tg?.showAlert?.("Выберите рекламодателя") || alert("Выберите рекламодателя");
        return;
    }
    if (!data.name) {
        tg?.showAlert?.("Введите название промо") || alert("Введите название промо");
        return;
    }
    try {
        if (id) {
            await api(`/api/promos/${id}`, { method: "PUT", body: JSON.stringify(data) });
        } else {
            await api("/api/promos", { method: "POST", body: JSON.stringify(data) });
        }
        closeModal();
        loadPromos();
        if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
    } catch (e) {
        tg?.showAlert?.("Ошибка сохранения") || alert("Ошибка");
    }
}

async function showPromoDetail(id) {
    const promo = promos.find((p) => p.id === id);
    if (!promo) return;

    let notesHtml = "";
    try {
        const notes = await api(`/api/notes?promo_id=${id}`);
        notesHtml = notes.map((n) => `
            <div class="note-item">
                ${esc(n.content)}
                <div class="note-date">${formatDate(n.created_at)}</div>
                <button class="note-delete" onclick="deleteNote(${n.id}, ${id})">✕</button>
            </div>`).join("");
    } catch (e) {
        console.error(e);
    }

    openModal(`
        <div class="modal-title">📋 ${esc(promo.name)}</div>
        <div style="margin-bottom:16px;">
            <div class="card-meta" style="margin-bottom:8px;">
                <span>👤 ${esc(promo.advertiser_name || "—")}</span>
                <span class="status status-${promo.status}">${statusLabel(promo.status)}</span>
            </div>
            ${promo.link ? `<div class="card-meta" style="margin-bottom:8px;"><a href="${esc(promo.link)}" target="_blank" style="color:var(--link)">🔗 ${esc(promo.link)}</a></div>` : ""}
            ${promo.deadline ? `<div class="card-meta" style="margin-bottom:8px;"><span>📅 Дедлайн: ${formatDate(promo.deadline)}</span></div>` : ""}
            ${promo.price_usdt ? `<div class="card-meta"><span class="price-usdt">💰 $${promo.price_usdt} USDT</span><span class="price-rub">≈ ${(promo.price_usdt * exchangeRate).toFixed(2)} RUB</span></div>` : ""}
        </div>
        
        <div class="section">
            <div class="section-header">
                <h2>📝 Заметки</h2>
            </div>
            <div id="promoNotesContainer">${notesHtml || '<div class="empty-state"><div class="empty-text">Нет заметок</div></div>'}</div>
            <div style="display:flex;gap:8px;margin-top:10px;">
                <input type="text" id="newNoteInput" placeholder="Добавить заметку..." style="flex:1;background:var(--bg);color:var(--text);border:1px solid var(--border);padding:10px;border-radius:var(--radius-sm);font-size:14px;">
                <button class="btn-primary btn-sm" onclick="addNoteToPromo(${id})">+</button>
            </div>
        </div>

        <div class="modal-actions">
            <button class="btn-secondary" onclick="closeModal()">Закрыть</button>
            <button class="btn-primary" onclick="closeModal(); showAddPromo(${JSON.stringify(promo).replace(/"/g, '&quot;')})">✏️ Редактировать</button>
        </div>
    `);
}

async function addNoteToPromo(promoId) {
    const input = document.getElementById("newNoteInput");
    if (!input?.value.trim()) return;
    try {
        await api("/api/notes", {
            method: "POST",
            body: JSON.stringify({ promo_id: promoId, content: input.value.trim() }),
        });
        showPromoDetail(promoId);
    } catch (e) {
        console.error(e);
    }
}

async function deleteNote(noteId, promoId) {
    try {
        await api(`/api/notes/${noteId}`, { method: "DELETE" });
        if (promoId) showPromoDetail(promoId);
        else loadProfile();
    } catch (e) {
        console.error(e);
    }
}

async function changePromoStatus(id, status) {
    try {
        await api(`/api/promos/${id}/status`, { method: "PATCH", body: JSON.stringify({ status }) });
        if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred("light");
        await loadPromos();
    } catch (e) {
        console.error(e);
    }
}

async function deletePromo(id) {
    if (!confirm("Удалить промо?")) return;
    try {
        await api(`/api/promos/${id}`, { method: "DELETE" });
        closeModal();
        loadPromos();
    } catch (e) {
        console.error(e);
    }
}

// ── Converter ──

async function loadConverter() {
    try {
        const data = await api("/api/exchange-rate");
        exchangeRate = data.usdt_rub;
        document.getElementById("currentRate").textContent = exchangeRate.toFixed(2);
    } catch (e) {
        document.getElementById("currentRate").textContent = exchangeRate.toFixed(2);
    }
}

function convertCurrency(from) {
    if (from === "usdt") {
        const val = parseFloat(document.getElementById("usdtInput").value) || 0;
        document.getElementById("rubInput").value = val ? (val * exchangeRate).toFixed(2) : "";
    } else {
        const val = parseFloat(document.getElementById("rubInput").value) || 0;
        document.getElementById("usdtInput").value = val ? (val / exchangeRate).toFixed(4) : "";
    }
}

function swapCurrency() {
    const usdt = document.getElementById("usdtInput").value;
    const rub = document.getElementById("rubInput").value;
    document.getElementById("usdtInput").value = rub;
    document.getElementById("rubInput").value = usdt;
}

// ── Reminders ──

function showAddReminder() {
    openModal(`
        <div class="modal-title">🔔 Новое напоминание</div>
        <div class="input-group">
            <label>Дата и время</label>
            <input type="datetime-local" id="reminderDate">
        </div>
        <div class="input-group">
            <label>Сообщение</label>
            <input type="text" id="reminderMessage" placeholder="О чем напомнить?">
        </div>
        <div class="input-group">
            <label>Привязать к промо (необязательно)</label>
            <select id="reminderPromo">
                <option value="">Без привязки</option>
                ${promos.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("")}
            </select>
        </div>
        <div class="modal-actions">
            <button class="btn-secondary" onclick="closeModal()">Отмена</button>
            <button class="btn-primary" onclick="saveReminder()">Сохранить</button>
        </div>
    `);
}

async function saveReminder() {
    const data = {
        remind_at: document.getElementById("reminderDate").value?.replace("T", " "),
        message: document.getElementById("reminderMessage").value.trim(),
        promo_id: parseInt(document.getElementById("reminderPromo").value) || null,
    };
    if (!data.remind_at) {
        tg?.showAlert?.("Укажите дату и время") || alert("Укажите дату и время");
        return;
    }
    try {
        await api("/api/reminders", { method: "POST", body: JSON.stringify(data) });
        closeModal();
        loadDashboard();
        if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
    } catch (e) {
        console.error(e);
    }
}

async function deleteReminder(id) {
    try {
        await api(`/api/reminders/${id}`, { method: "DELETE" });
        loadDashboard();
    } catch (e) {
        console.error(e);
    }
}

// ── Profile ──

async function loadProfile() {
    try {
        const profile = await api("/api/profile");
        document.getElementById("profileName").textContent = [profile.first_name, profile.last_name].filter(Boolean).join(" ") || "—";
        document.getElementById("profileUsername").textContent = profile.username ? `@${profile.username}` : "—";
        document.getElementById("profileAdvCount").textContent = profile.advertisers_count;
        document.getElementById("profilePromoCount").textContent = profile.promos_count;
        document.getElementById("profileDoneCount").textContent = profile.done_count;
    } catch (e) {
        console.error(e);
    }

    try {
        const notes = await api("/api/notes");
        const container = document.getElementById("allNotesList");
        if (notes.length === 0) {
            container.innerHTML = '<div class="empty-state"><div class="empty-icon">📝</div><div class="empty-text">Нет заметок</div></div>';
        } else {
            container.innerHTML = notes.map((n) => `
                <div class="note-item">
                    ${esc(n.content)}
                    <div class="note-date">${formatDate(n.created_at)}</div>
                    <button class="note-delete" onclick="deleteNote(${n.id})">✕</button>
                </div>`).join("");
        }
    } catch (e) {
        console.error(e);
    }
}

// ── Modal ──

function openModal(html) {
    document.getElementById("modalContent").innerHTML = html;
    document.getElementById("modal").classList.add("active");
}

function closeModal() {
    document.getElementById("modal").classList.remove("active");
}

// ── Helpers ──

function esc(str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

function statusLabel(status) {
    switch (status) {
        case "done": return "✅ Готово";
        case "in_progress": return "⏳ В процессе";
        default: return "❌ Не готово";
    }
}

function formatDate(dateStr) {
    if (!dateStr) return "—";
    const d = new Date(dateStr.replace(" ", "T"));
    if (isNaN(d.getTime())) return dateStr;
    const now = new Date();
    const diff = d - now;
    const pad = (n) => String(n).padStart(2, "0");

    let relative = "";
    if (diff < 0) {
        relative = " (просрочено)";
    } else if (diff < 3600000) {
        relative = ` (через ${Math.floor(diff / 60000)} мин)`;
    } else if (diff < 86400000) {
        relative = ` (через ${Math.floor(diff / 3600000)} ч)`;
    }

    return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}${relative}`;
}
