/**
 * JioNews Data & Analytics Dashboard - Frontend Logic
 */

// ── State ──────────────────────────────────────────────────────────

let activeModule = "onboarding";
const sessions = {
    onboarding: generateSessionId(),
    analytics: generateSessionId(),
};
const loading = { onboarding: false, analytics: false };

// Track current feed type for downloads
let currentDataFeedType = "headlines";

// ── Init ───────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
    checkHealth();
    loadFeedStats();

    // Configure marked.js
    if (typeof marked !== "undefined") {
        marked.setOptions({
            breaks: true,
            gfm: true,
            headerIds: false,
            mangle: false,
        });
    }

    document.getElementById("inputOnboarding").focus();
});

// ── Helpers ────────────────────────────────────────────────────────

function generateSessionId() {
    return "sess-" + Math.random().toString(36).substring(2, 10) + "-" + Date.now().toString(36);
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

function renderMarkdown(text) {
    if (typeof marked !== "undefined" && typeof DOMPurify !== "undefined") {
        const raw = marked.parse(text);
        return DOMPurify.sanitize(raw);
    }
    return escapeHtml(text).replace(/\n/g, "<br>");
}

// ── Module Switching ──────────────────────────────────────────────

function switchModule(module) {
    activeModule = module;

    // Update tabs
    document.getElementById("tabOnboarding").classList.toggle("active", module === "onboarding");
    document.getElementById("tabAnalytics").classList.toggle("active", module === "analytics");

    // Update module containers
    document.getElementById("moduleOnboarding").classList.toggle("active", module === "onboarding");
    document.getElementById("moduleAnalytics").classList.toggle("active", module === "analytics");

    // Update sidebar sections
    document.getElementById("sidebarOnboarding").classList.toggle("active", module === "onboarding");
    document.getElementById("sidebarAnalytics").classList.toggle("active", module === "analytics");

    // Focus input
    const inputId = module === "onboarding" ? "inputOnboarding" : "inputAnalytics";
    document.getElementById(inputId).focus();
}

// ── Health Check ───────────────────────────────────────────────────

async function checkHealth() {
    const indicator = document.getElementById("statusIndicator");
    const dot = indicator.querySelector(".status-dot");
    const text = indicator.querySelector(".status-text");

    try {
        const resp = await fetch("/api/health");
        const data = await resp.json();

        if (data.status === "healthy" && data.api_key_configured) {
            dot.className = "status-dot connected";
            text.textContent = "Connected to Claude";

            // Update DB status
            const dbStatus = document.getElementById("dbStatus");
            if (data.mongodb_connected) {
                dbStatus.textContent = "MongoDB connected (ingestion-data)";
            } else {
                dbStatus.textContent = "MongoDB not connected. Check MONGODB_URI.";
            }
        } else if (data.status === "healthy") {
            dot.className = "status-dot error";
            text.textContent = "API key not configured";
        } else {
            dot.className = "status-dot error";
            text.textContent = "Service error";
        }
    } catch {
        dot.className = "status-dot error";
        text.textContent = "Server unreachable";
    }
}

// ── Feed Stats ────────────────────────────────────────────────────

async function loadFeedStats() {
    try {
        const resp = await fetch("/api/feeds/stats");
        const data = await resp.json();

        const h = data.headlines || {};
        const v = data.videos || {};
        const s = data.summaries || {};

        document.getElementById("statHeadlines").textContent = h.total_feeds || 0;
        document.getElementById("statVideos").textContent = v.total_feeds || 0;
        document.getElementById("statSummaries").textContent = s.total_feeds || 0;
        document.getElementById("statTotal").textContent =
            (h.total_feeds || 0) + (v.total_feeds || 0) + (s.total_feeds || 0);
    } catch {
        // Stats not critical, silently fail
    }
}

// ── Send Message ───────────────────────────────────────────────────

async function sendMessage(module) {
    module = module || activeModule;
    const inputId = module === "onboarding" ? "inputOnboarding" : "inputAnalytics";
    const input = document.getElementById(inputId);
    const message = input.value.trim();

    if (!message || loading[module]) return;

    // Hide welcome screen
    const welcomeId = module === "onboarding" ? "welcomeOnboarding" : "welcomeAnalytics";
    const welcome = document.getElementById(welcomeId);
    if (welcome) welcome.remove();

    // Add user message
    addMessage(module, "user", message);

    // Clear input
    input.value = "";
    input.style.height = "auto";
    setLoading(module, true);
    showTypingIndicator(module);

    // Determine API endpoint
    const endpoint = module === "onboarding" ? "/api/onboarding/chat" : "/api/analytics/chat";

    try {
        const resp = await fetch(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                message: message,
                session_id: sessions[module],
            }),
        });

        removeTypingIndicator(module);

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.error || "Server error (" + resp.status + ")");
        }

        const data = await resp.json();
        sessions[module] = data.session_id;
        addMessage(module, "assistant", data.response);

    } catch (error) {
        removeTypingIndicator(module);
        showError(error.message || "Failed to get response.");
        addMessage(module, "assistant", "**Error:** " + (error.message || "Something went wrong."));
    } finally {
        setLoading(module, false);
        input.focus();
    }
}

function sendQuickAction(text, module) {
    module = module || activeModule;
    const inputId = module === "onboarding" ? "inputOnboarding" : "inputAnalytics";
    document.getElementById(inputId).value = text;
    sendMessage(module);
}

// ── UI Helpers ─────────────────────────────────────────────────────

function addMessage(module, role, content) {
    const containerId = module === "onboarding" ? "messagesOnboarding" : "messagesAnalytics";
    const container = document.getElementById(containerId);

    const messageDiv = document.createElement("div");
    messageDiv.className = "message " + (role === "user" ? "user-message" : "assistant-message");

    const avatarLabel = role === "user" ? "U" : (module === "onboarding" ? "PO" : "SA");
    const senderLabel = role === "user" ? "You" : (module === "onboarding" ? "Publisher Onboarding" : "Smart Analytics");

    messageDiv.innerHTML =
        '<div class="message-avatar ' + role + '">' + avatarLabel + '</div>' +
        '<div class="message-content">' +
            '<div class="message-sender">' + senderLabel + '</div>' +
            '<div class="message-body">' +
                (role === "user" ? escapeHtml(content) : renderMarkdown(content)) +
            '</div>' +
        '</div>';

    container.appendChild(messageDiv);
    scrollToBottom(containerId);
}

function showTypingIndicator(module) {
    const containerId = module === "onboarding" ? "messagesOnboarding" : "messagesAnalytics";
    const container = document.getElementById(containerId);

    const typingDiv = document.createElement("div");
    typingDiv.className = "typing-indicator";
    typingDiv.id = "typing-" + module;

    const avatar = module === "onboarding" ? "PO" : "SA";
    const label = module === "onboarding" ? "Analyzing feed..." : "Querying database...";

    typingDiv.innerHTML =
        '<div class="message-avatar assistant">' + avatar + '</div>' +
        '<div class="message-content">' +
            '<div class="typing-dots"><span></span><span></span><span></span></div>' +
            '<div class="typing-label">' + label + '</div>' +
        '</div>';

    container.appendChild(typingDiv);
    scrollToBottom(containerId);
}

function removeTypingIndicator(module) {
    const el = document.getElementById("typing-" + module);
    if (el) el.remove();
}

function setLoading(module, isLoading) {
    loading[module] = isLoading;
    const btnId = module === "onboarding" ? "sendBtnOnboarding" : "sendBtnAnalytics";
    document.getElementById(btnId).disabled = isLoading;
}

function scrollToBottom(containerId) {
    const container = document.getElementById(containerId);
    requestAnimationFrame(() => {
        container.scrollTop = container.scrollHeight;
    });
}

function showError(message) {
    const toast = document.createElement("div");
    toast.className = "error-toast";
    toast.textContent = message;
    document.body.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transition = "opacity 0.3s";
        setTimeout(() => toast.remove(), 300);
    }, 5000);
}

// ── Data Panel ────────────────────────────────────────────────────

function showDataPanel(title, data, feedType) {
    currentDataFeedType = feedType || "headlines";
    const panel = document.getElementById("dataPanelOnboarding");
    const titleEl = document.getElementById("dataPanelTitle");
    const body = document.getElementById("dataPanelBody");

    titleEl.textContent = title || "Feed Data";

    if (!data || !data.length) {
        body.innerHTML = '<p style="padding:16px;color:var(--gray-500);">No data to display.</p>';
        panel.classList.add("visible");
        return;
    }

    // Build table
    const headers = Object.keys(data[0]);
    let html = '<table class="data-table"><thead><tr>';
    headers.forEach(h => { html += '<th>' + escapeHtml(h) + '</th>'; });
    html += '</tr></thead><tbody>';

    data.forEach(row => {
        html += '<tr>';
        headers.forEach(h => {
            const val = row[h] !== null && row[h] !== undefined ? String(row[h]) : '';
            html += '<td title="' + escapeHtml(val) + '">' + escapeHtml(val) + '</td>';
        });
        html += '</tr>';
    });
    html += '</tbody></table>';

    body.innerHTML = html;
    panel.classList.add("visible");
}

function closeDataPanel() {
    document.getElementById("dataPanelOnboarding").classList.remove("visible");
}

function downloadData(format) {
    const url = "/api/feeds/download?feed_type=" + encodeURIComponent(currentDataFeedType) + "&format=" + encodeURIComponent(format);
    window.open(url, "_blank");
}

// ── Input Handlers ─────────────────────────────────────────────────

function handleKeyDown(event, module) {
    if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendMessage(module);
    }
}

function autoResize(textarea) {
    textarea.style.height = "auto";
    textarea.style.height = Math.min(textarea.scrollHeight, 120) + "px";
}

// ── Sidebar Toggle ─────────────────────────────────────────────────

function toggleSidebar() {
    const sidebar = document.getElementById("sidebar");
    sidebar.classList.toggle("open");

    let overlay = document.querySelector(".sidebar-overlay");
    if (!overlay) {
        overlay = document.createElement("div");
        overlay.className = "sidebar-overlay";
        overlay.onclick = () => {
            sidebar.classList.remove("open");
            overlay.classList.remove("visible");
        };
        document.body.appendChild(overlay);
    }
    overlay.classList.toggle("visible");
}

// ── Reset Chat ─────────────────────────────────────────────────────

async function resetChat() {
    const module = activeModule;
    const endpoint = module === "onboarding" ? "/api/onboarding/reset" : "/api/analytics/reset";

    // Reset server-side
    try {
        await fetch(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_id: sessions[module] }),
        });
    } catch { /* Continue */ }

    // New session
    sessions[module] = generateSessionId();

    // Clear messages
    const containerId = module === "onboarding" ? "messagesOnboarding" : "messagesAnalytics";
    const container = document.getElementById(containerId);
    container.innerHTML = "";

    // Re-add welcome
    if (module === "onboarding") {
        container.innerHTML = getOnboardingWelcome();
    } else {
        container.innerHTML = getAnalyticsWelcome();
    }

    // Close data panel
    closeDataPanel();

    // Close sidebar on mobile
    const sidebar = document.getElementById("sidebar");
    sidebar.classList.remove("open");
    const overlay = document.querySelector(".sidebar-overlay");
    if (overlay) overlay.classList.remove("visible");

    const inputId = module === "onboarding" ? "inputOnboarding" : "inputAnalytics";
    document.getElementById(inputId).focus();

    // Reload stats
    loadFeedStats();
}

// ── Welcome HTML Templates ────────────────────────────────────────

function getOnboardingWelcome() {
    return '<div class="welcome-screen" id="welcomeOnboarding">' +
        '<div class="welcome-icon">' +
            '<svg width="48" height="48" viewBox="0 0 48 48" fill="none">' +
                '<rect width="48" height="48" rx="12" fill="url(#w-grad1b)"/>' +
                '<path d="M14 18h20M14 24h16M14 30h18" stroke="white" stroke-width="2.5" stroke-linecap="round"/>' +
                '<circle cx="36" cy="36" r="8" fill="#10B981"/>' +
                '<path d="M33 36l2 2 4-4" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>' +
                '<defs><linearGradient id="w-grad1b" x1="0" y1="0" x2="48" y2="48"><stop stop-color="#059669"/><stop offset="1" stop-color="#0D9488"/></linearGradient></defs>' +
            '</svg>' +
        '</div>' +
        '<h2>Publisher Onboarding</h2>' +
        '<p>Validate, evaluate, and onboard publisher RSS/JSON/MRSS feeds into JioNews pipelines.</p>' +
        '<div class="quick-actions">' +
            '<button class="quick-action-card" onclick="sendQuickAction(\'I want to validate a headline RSS feed for onboarding.\', \'onboarding\')">' +
                '<div class="qa-icon"><svg width="22" height="22" viewBox="0 0 24 24" fill="none"><rect x="3" y="3" width="18" height="18" rx="3" stroke="#059669" stroke-width="2"/><path d="M7 8h10M7 12h8M7 16h6" stroke="#059669" stroke-width="2" stroke-linecap="round"/></svg></div>' +
                '<div class="qa-text"><strong>Validate Headlines</strong><span>Check RSS/JSON feed for articles</span></div>' +
            '</button>' +
            '<button class="quick-action-card" onclick="sendQuickAction(\'I want to validate a native video MRSS feed.\', \'onboarding\')">' +
                '<div class="qa-icon"><svg width="22" height="22" viewBox="0 0 24 24" fill="none"><rect x="3" y="5" width="18" height="14" rx="3" stroke="#0D9488" stroke-width="2"/><path d="M10 9l5 3-5 3V9z" fill="#0D9488"/></svg></div>' +
                '<div class="qa-text"><strong>Validate Videos</strong><span>Check MRSS with MP4 validation</span></div>' +
            '</button>' +
            '<button class="quick-action-card" onclick="sendQuickAction(\'I want to validate a summaries feed.\', \'onboarding\')">' +
                '<div class="qa-icon"><svg width="22" height="22" viewBox="0 0 24 24" fill="none"><rect x="3" y="3" width="18" height="18" rx="3" stroke="#3B82F6" stroke-width="2"/><path d="M7 8h10M7 12h10M7 16h10" stroke="#3B82F6" stroke-width="1.5" stroke-linecap="round"/></svg></div>' +
                '<div class="qa-text"><strong>Validate Summaries</strong><span>Check feed with hygiene scoring</span></div>' +
            '</button>' +
            '<button class="quick-action-card" onclick="sendQuickAction(\'Show me all existing feeds and their stats.\', \'onboarding\')">' +
                '<div class="qa-icon"><svg width="22" height="22" viewBox="0 0 24 24" fill="none"><path d="M3 12h4l3-9 4 18 3-9h4" stroke="#F59E0B" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></div>' +
                '<div class="qa-text"><strong>Feed Analytics</strong><span>Query existing feed configs</span></div>' +
            '</button>' +
        '</div>' +
    '</div>';
}

function getAnalyticsWelcome() {
    return '<div class="welcome-screen" id="welcomeAnalytics">' +
        '<div class="welcome-icon">' +
            '<svg width="48" height="48" viewBox="0 0 48 48" fill="none">' +
                '<rect width="48" height="48" rx="12" fill="url(#w-grad2b)"/>' +
                '<path d="M14 34V22M22 34V14M30 34V26M38 34V18" stroke="white" stroke-width="3" stroke-linecap="round"/>' +
                '<defs><linearGradient id="w-grad2b" x1="0" y1="0" x2="48" y2="48"><stop stop-color="#0D9488"/><stop offset="1" stop-color="#059669"/></linearGradient></defs>' +
            '</svg>' +
        '</div>' +
        '<h2>Smart Analytics Engine</h2>' +
        '<p>Query and analyze JioNews MongoDB data using natural language.</p>' +
        '<div class="quick-actions">' +
            '<button class="quick-action-card" onclick="sendQuickAction(\'What collections are available in the database?\', \'analytics\')">' +
                '<div class="qa-icon"><svg width="22" height="22" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9" stroke="#0D9488" stroke-width="2"/><path d="M12 8v4M12 16h.01" stroke="#0D9488" stroke-width="2" stroke-linecap="round"/></svg></div>' +
                '<div class="qa-text"><strong>Explore Collections</strong><span>See available data sources</span></div>' +
            '</button>' +
            '<button class="quick-action-card" onclick="sendQuickAction(\'How many documents are in the raw_headlines collection? Show breakdown by language.\', \'analytics\')">' +
                '<div class="qa-icon"><svg width="22" height="22" viewBox="0 0 24 24" fill="none"><path d="M3 12h4l3-9 4 18 3-9h4" stroke="#059669" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></div>' +
                '<div class="qa-text"><strong>Headlines Analytics</strong><span>Count and breakdown by language</span></div>' +
            '</button>' +
            '<button class="quick-action-card" onclick="sendQuickAction(\'Show me the latest 10 summaries that failed hygiene checks.\', \'analytics\')">' +
                '<div class="qa-icon"><svg width="22" height="22" viewBox="0 0 24 24" fill="none"><path d="M12 9v4M12 17h.01" stroke="#EF4444" stroke-width="2" stroke-linecap="round"/><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" stroke="#EF4444" stroke-width="2"/></svg></div>' +
                '<div class="qa-text"><strong>Failed Hygiene</strong><span>Find content that failed checks</span></div>' +
            '</button>' +
            '<button class="quick-action-card" onclick="sendQuickAction(\'Compare summaries test results across different models.\', \'analytics\')">' +
                '<div class="qa-icon"><svg width="22" height="22" viewBox="0 0 24 24" fill="none"><rect x="3" y="3" width="7" height="7" rx="1" stroke="#8B5CF6" stroke-width="2"/><rect x="14" y="3" width="7" height="7" rx="1" stroke="#8B5CF6" stroke-width="2"/><rect x="3" y="14" width="7" height="7" rx="1" stroke="#8B5CF6" stroke-width="2"/><rect x="14" y="14" width="7" height="7" rx="1" stroke="#8B5CF6" stroke-width="2"/></svg></div>' +
                '<div class="qa-text"><strong>Model Comparison</strong><span>Compare test results across models</span></div>' +
            '</button>' +
        '</div>' +
    '</div>';
}
