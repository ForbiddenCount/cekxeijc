/* global Telegram */
const tg = window.Telegram?.WebApp;
let initData = "";
let currentUser = null;
let advertisers = [];
let promos = [];
let exchangeRate = 92;

// ── Particles ──

function initParticles() {
    const canvas = document.getElementById("particleCanvas");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    let w, h, particles;

    function resize() {
        w = canvas.width = window.innerWidth;
        h = canvas.height = window.innerHeight;
    }

    function createParticles() {
        particles = [];
        const count = Math.floor((w * h) / 6000);
        for (let i = 0; i < count; i++) {
            particles.push({
                x: Math.random() * w,
                y: Math.random() * h,
                r: Math.random() * 5 + 1.2,
                dx: (Math.random() - 0.5) * 0.3,
                dy: (Math.random() - 0.5) * 0.3,
                alpha: Math.random() * 0.6 + 0.25,
                pulse: Math.random() * Math.PI * 2,
                glow: Math.random() * 14 + 6,
            });
        }
    }

    function draw() {
        ctx.clearRect(0, 0, w, h);
        for (const p of particles) {
            p.x += p.dx;
            p.y += p.dy;
            p.pulse += 0.012;
            if (p.x < 0) p.x = w;
            if (p.x > w) p.x = 0;
            if (p.y < 0) p.y = h;
            if (p.y > h) p.y = 0;
            const a = p.alpha + Math.sin(p.pulse) * 0.2;
            const al = Math.max(0, a);

            ctx.save();
            ctx.shadowBlur = p.glow;
            ctx.shadowColor = `rgba(139, 92, 246, ${al * 0.8})`;
            ctx.beginPath();
            ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
            ctx.fillStyle = `rgba(160, 120, 255, ${al})`;
            ctx.fill();
            ctx.restore();
        }
        requestAnimationFrame(draw);
    }

    resize();
    createParticles();
    draw();
    window.addEventListener("resize", () => { resize(); createParticles(); });
}

// ── Init ──

document.addEventListener("DOMContentLoaded", async () => {
    initParticles();
    if (tg) {
        tg.ready();
        tg.expand();
        initData = tg.initData || "";
        tg.setHeaderColor(
            getComputedStyle(document.documentElement)
                .getPropertyValue("--tg-theme-bg-color")
                .trim() || "#000000"
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
        if (currentUser && currentUser.is_admin) {
            const adminSection = document.getElementById("adminSection");
            if (adminSection) adminSection.style.display = "";
        }
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
        case "yokoso": loadCategoryPromos("yokoso"); break;
        case "sako": loadCategoryPromos("sako"); break;
        case "converter": loadConverter(); break;
        case "more": loadMore(); break;
    }
}

async function loadMore() {
    loadProfile();
    loadAdvertisers();
    if (currentUser?.is_admin) loadAdminPanel();
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
            container.innerHTML = '<div class="empty-state"><svg class="empty-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg><div class="empty-text">Нет активных дедлайнов</div></div>';
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
                            <span>${esc(p.advertiser_name || "—")}</span>
                            <span class="deadline ${deadlineClass}">${formatDate(p.deadline)}</span>
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
            container.innerHTML = '<div class="empty-state"><svg class="empty-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></svg><div class="empty-text">Нет напоминаний</div></div>';
        } else {
            container.innerHTML = reminders.map((r) => `
                <div class="card">
                    <div class="card-header">
                        <span class="card-title">${esc(r.message || r.promo_name || "Напоминание")}</span>
                        <button class="btn-icon btn-sm" onclick="event.stopPropagation(); deleteReminder(${r.id})" style="width:24px;height:24px;font-size:12px;">✕</button>
                    </div>
                    <div class="card-meta">
                        <span>${formatDate(r.remind_at)}</span>
                        ${r.promo_name ? `<span>${esc(r.promo_name)}</span>` : ""}
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
            container.innerHTML = '<div class="empty-state"><svg class="empty-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="8" r="4"/><path d="M4 21v-1a6 6 0 0112 0v1"/></svg><div class="empty-text">Нет рекламодателей.<br>Нажмите + Добавить</div></div>';
        } else {
            container.innerHTML = advertisers.map((a) => `
                <div class="card" onclick="showAdvertiserDetail(${a.id})">
                    <div class="card-header">
                        <span class="card-title">${esc(a.name)}</span>
                    </div>
                    ${a.username ? `<div class="card-subtitle">@${esc(a.username)}</div>` : ""}
                    ${a.link ? `<div class="card-meta"><span>${esc(a.link)}</span></div>` : ""}
                    ${a.notes ? `<div class="card-meta"><span>${esc(a.notes.substring(0, 60))}${a.notes.length > 60 ? "..." : ""}</span></div>` : ""}
                </div>`).join("");
        }
    } catch (e) {
        console.error(e);
    }
}

function showAddAdvertiser(existing = null) {
    const isEdit = !!existing;
    openModal(`
        <div class="modal-title">${isEdit ? "Редактировать" : "Новый рекламодатель"}</div>
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

let currentCategory = "yokoso";
let categoryPromos = { yokoso: [], sako: [] };

async function loadCategoryPromos(category) {
    currentCategory = category;
    try {
        advertisers = await api("/api/advertisers");
    } catch (e) {
        console.error(e);
    }
    try {
        categoryPromos[category] = await api(`/api/promos?category=${category}`);
        renderCategoryPromos(category);
    } catch (e) {
        console.error(e);
    }
}

function filterCategoryPromos(category) {
    renderCategoryPromos(category);
}

function renderCategoryPromos(category) {
    const statusFilter = document.getElementById(`${category}FilterStatus`)?.value;
    let filtered = categoryPromos[category] || [];
    if (statusFilter) filtered = filtered.filter((p) => p.status === statusFilter);
    promos = categoryPromos[category] || [];

    const container = document.getElementById(`${category}List`);
    if (filtered.length === 0) {
        container.innerHTML = '<div class="empty-state"><svg class="empty-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71"/></svg><div class="empty-text">Нет промо.<br>Нажмите + Добавить</div></div>';
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
            deadlineHtml = `<span class="deadline ${cls}">${formatDate(p.deadline)}</span>`;
        }
        return `
            <div class="card" onclick="showPromoDetail(${p.id})">
                <div class="card-header">
                    <span class="card-title">${esc(p.name)}</span>
                    <select class="status-select ${p.status}" onchange="event.stopPropagation(); changePromoStatus(${p.id}, this.value)" onclick="event.stopPropagation()">
                        <option value="not_ready" ${p.status === "not_ready" ? "selected" : ""}>Не готово</option>
                        <option value="in_progress" ${p.status === "in_progress" ? "selected" : ""}>В процессе</option>
                        <option value="done" ${p.status === "done" ? "selected" : ""}>Готово</option>
                    </select>
                </div>
                <div class="card-subtitle">${esc(p.advertiser_name || "—")}</div>
                <div class="card-meta">
                    ${p.link ? `<span>Ссылка</span>` : ""}
                    ${deadlineHtml}
                    ${p.price_usdt ? `<span class="price-usdt">$${p.price_usdt} USDT</span>` : ""}
                </div>
                ${p.notes ? `<div class="card-meta"><span>${esc(p.notes.substring(0, 80))}${p.notes.length > 80 ? "..." : ""}</span></div>` : ""}
            </div>`;
    }).join("");
}

function showAddPromo(categoryOrExisting = null) {
    let existing = null;
    let category = currentCategory;
    if (typeof categoryOrExisting === "string") {
        category = categoryOrExisting;
    } else if (categoryOrExisting && typeof categoryOrExisting === "object") {
        existing = categoryOrExisting;
        category = existing.category || currentCategory;
    }
    const isEdit = !!existing;
    openModal(`
        <div class="modal-title">${isEdit ? "Редактировать промо" : "Новое промо"}</div>
        <input type="hidden" id="promoCategory" value="${category}">
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
                <option value="not_ready" ${existing?.status === "not_ready" ? "selected" : ""}>Не готово</option>
                <option value="in_progress" ${existing?.status === "in_progress" ? "selected" : ""}>В процессе</option>
                <option value="done" ${existing?.status === "done" ? "selected" : ""}>Готово</option>
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
        category: document.getElementById("promoCategory")?.value || currentCategory,
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
        loadCategoryPromos(currentCategory);
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
                <div class="note-content" id="note-text-${n.id}">${esc(n.content)}</div>
                <div class="note-date" id="note-date-${n.id}" data-raw="${esc(n.created_at || '')}">${formatDate(n.created_at)}</div>
                <div class="note-actions">
                    <button class="note-action-btn" onclick="editNote(${n.id}, ${id})"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg></button>
                    <button class="note-action-btn" onclick="deleteNote(${n.id}, ${id})">✕</button>
                </div>
            </div>`).join("");
    } catch (e) {
        console.error(e);
    }

    openModal(`
        <div class="modal-title">${esc(promo.name)}</div>
        <div style="margin-bottom:16px;">
            <div class="card-meta" style="margin-bottom:8px;">
                <span>${esc(promo.advertiser_name || "—")}</span>
                <span class="status status-${promo.status}">${statusLabel(promo.status)}</span>
            </div>
            ${promo.link ? `<div class="card-meta" style="margin-bottom:8px;"><a href="${esc(promo.link)}" target="_blank" style="color:var(--link)">${esc(promo.link)}</a></div>` : ""}
            ${promo.deadline ? `<div class="card-meta" style="margin-bottom:8px;"><span>Дедлайн: ${formatDate(promo.deadline)}</span></div>` : ""}
            ${promo.price_usdt ? `<div class="card-meta"><span class="price-usdt">$${promo.price_usdt} USDT</span><span class="price-rub">≈ ${(promo.price_usdt * exchangeRate).toFixed(2)} RUB</span></div>` : ""}
        </div>
        
        <div class="section">
            <div class="section-header">
                <h2>Заметки</h2>
            </div>
            <div id="promoNotesContainer">${notesHtml || '<div class="empty-state"><div class="empty-text">Нет заметок</div></div>'}</div>
            <div style="display:flex;gap:8px;margin-top:10px;">
                <input type="text" id="newNoteInput" placeholder="Добавить заметку..." style="flex:1;background:var(--bg);color:var(--text);border:1px solid var(--border);padding:10px;border-radius:var(--radius-sm);font-size:14px;">
                <button class="btn-primary btn-sm" onclick="addNoteToPromo(${id})">+</button>
            </div>
        </div>

        <div class="modal-actions">
            <button class="btn-secondary" onclick="closeModal()">Закрыть</button>
            <button class="btn-primary" onclick="closeModal(); showAddPromo(${JSON.stringify(promo).replace(/"/g, '&quot;')})">Редактировать</button>
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

async function editNote(noteId, promoId) {
    const el = document.getElementById(`note-text-${noteId}`);
    const dateEl = document.getElementById(`note-date-${noteId}`);
    if (!el) return;
    const oldContent = el.textContent.trim();
    const rawDate = dateEl?.dataset?.raw || "";
    const dateVal = rawDate ? rawDate.replace(" ", "T").substring(0, 16) : "";
    const noteItem = el.closest(".note-item");
    if (!noteItem) return;
    noteItem.innerHTML = `
        <div style="display:flex;flex-direction:column;gap:8px;">
            <input type="text" id="edit-note-${noteId}" value="${esc(oldContent)}" style="background:var(--bg);color:var(--text);border:1px solid var(--accent);padding:8px;border-radius:var(--radius-sm);font-size:13px;">
            <div style="display:flex;gap:6px;align-items:center;">
                <input type="datetime-local" id="edit-note-date-${noteId}" value="${dateVal}" style="flex:1;background:var(--bg);color:var(--text);border:1px solid var(--border);padding:8px;border-radius:var(--radius-sm);font-size:12px;">
                <button class="btn-primary btn-sm" onclick="saveNote(${noteId}, ${promoId})">OK</button>
            </div>
        </div>`;
    document.getElementById(`edit-note-${noteId}`)?.focus();
}

async function saveNote(noteId, promoId) {
    const input = document.getElementById(`edit-note-${noteId}`);
    const dateInput = document.getElementById(`edit-note-date-${noteId}`);
    if (!input?.value.trim()) return;
    const body = { content: input.value.trim() };
    if (dateInput?.value) body.created_at = dateInput.value.replace("T", " ");
    try {
        await api(`/api/notes/${noteId}`, { method: "PUT", body: JSON.stringify(body) });
        if (promoId) showPromoDetail(promoId);
        else loadProfile();
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
        await loadCategoryPromos(currentCategory);
    } catch (e) {
        console.error(e);
    }
}

async function deletePromo(id) {
    if (!confirm("Удалить промо?")) return;
    try {
        await api(`/api/promos/${id}`, { method: "DELETE" });
        closeModal();
        loadCategoryPromos(currentCategory);
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
        <div class="modal-title">Новое напоминание</div>
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
            container.innerHTML = '<div class="empty-state"><svg class="empty-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg><div class="empty-text">Нет заметок</div></div>';
        } else {
            container.innerHTML = notes.map((n) => `
                <div class="note-item">
                    <div class="note-content" id="note-text-${n.id}">${esc(n.content)}</div>
                    <div class="note-date" id="note-date-${n.id}" data-raw="${esc(n.created_at || '')}">${formatDate(n.created_at)}</div>
                    <div class="note-actions">
                        <button class="note-action-btn" onclick="editNote(${n.id})"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg></button>
                        <button class="note-action-btn" onclick="deleteNote(${n.id})">✕</button>
                    </div>
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
        case "done": return "Готово";
        case "in_progress": return "В процессе";
        default: return "Не готово";
    }
}

// ── Admin Panel ──

async function loadAdminPanel() {
    if (!currentUser || !currentUser.is_admin) return;
    try {
        const stats = await api("/api/admin/stats");
        document.getElementById("adminStatUsers").textContent = stats.total_users;
        document.getElementById("adminStatAdvertisers").textContent = stats.total_advertisers;
        document.getElementById("adminStatPromos").textContent = stats.total_promos;
        document.getElementById("adminStatDone").textContent = stats.done_promos;
    } catch (e) {
        console.error(e);
    }
    try {
        const users = await api("/api/admin/users");
        const container = document.getElementById("adminUsersList");
        if (!users.length) {
            container.innerHTML = '<div class="empty-state"><svg class="empty-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/></svg><div class="empty-text">Нет пользователей</div></div>';
            return;
        }
        container.innerHTML = users.map(u => `
            <div class="card">
                <div class="card-header">
                    <div class="card-title">${esc(u.first_name || "")} ${esc(u.last_name || "")}</div>
                    <div class="card-actions">
                        <button class="btn-icon" onclick="adminViewUser(${u.telegram_id})"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg></button>
                        <button class="btn-icon danger" onclick="adminDeleteUser(${u.telegram_id})">✕</button>
                    </div>
                </div>
                <div class="card-body">
                    <span class="card-meta">ID: ${u.telegram_id}</span>
                    ${u.username ? `<span class="card-meta">@${esc(u.username)}</span>` : ""}
                    <span class="card-meta">Рекл: ${u.advertisers_count} · Промо: ${u.promos_count} · Готово: ${u.done_count}</span>
                </div>
            </div>
        `).join("");
    } catch (e) {
        console.error(e);
    }
}

async function adminViewUser(telegramId) {
    try {
        const [advs, prms] = await Promise.all([
            api(`/api/admin/users/${telegramId}/advertisers`),
            api(`/api/admin/users/${telegramId}/promos`),
        ]);
        let html = `<div class="modal-header"><h3>Данные пользователя ${telegramId}</h3></div>`;
        html += `<div class="section"><h4 style="margin-bottom:8px">Рекламодатели (${advs.length})</h4>`;
        if (advs.length) {
            html += advs.map(a => `<div class="card"><div class="card-header"><div class="card-title">${esc(a.name)}</div></div><div class="card-body">${a.username ? `<span class="card-meta">@${esc(a.username)}</span>` : ""}${a.link ? `<span class="card-meta">${esc(a.link)}</span>` : ""}</div></div>`).join("");
        } else {
            html += '<div class="empty-state"><div class="empty-text">Нет рекламодателей</div></div>';
        }
        html += `</div><div class="section"><h4 style="margin-bottom:8px">Промо (${prms.length})</h4>`;
        if (prms.length) {
            html += prms.map(p => `<div class="card"><div class="card-header"><div class="card-title">${esc(p.name)}</div><span class="badge badge-${p.status}">${statusLabel(p.status)}</span></div><div class="card-body">${p.advertiser_name ? `<span class="card-meta">${esc(p.advertiser_name)}</span>` : ""}${p.price_usdt ? `<span class="card-meta">${p.price_usdt} USDT</span>` : ""}${p.deadline ? `<span class="card-meta">${formatDate(p.deadline)}</span>` : ""}</div></div>`).join("");
        } else {
            html += '<div class="empty-state"><div class="empty-text">Нет промо</div></div>';
        }
        html += `</div><button class="btn-secondary" onclick="closeModal()" style="width:100%;margin-top:12px">Закрыть</button>`;
        openModal(html);
    } catch (e) {
        console.error(e);
    }
}

async function adminDeleteUser(telegramId) {
    if (!confirm(`Удалить пользователя ${telegramId} и все его данные?`)) return;
    try {
        await api(`/api/admin/users/${telegramId}`, { method: "DELETE" });
        loadAdminPanel();
    } catch (e) {
        console.error(e);
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
