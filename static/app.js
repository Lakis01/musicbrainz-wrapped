document.addEventListener("DOMContentLoaded", () => {
    const state = {
        metric: "minutes",
        timeframe: "all",
        start_ts: null,
        end_ts: null,
        min_ts: null,
        max_ts: null,
        limit: 31,
        layout: "tiered",
        showCaptions: true,
        showFlags: false,
        yearsMode: "active",
        selectedYear: null,
        mapRankBy: "metric",
        countryTopX: 5,
        showCountryPie: false,
        stats: null,
        topArtists: [],
        topAlbums: [],
        topTracks: [],
        releaseYearsData: null,
        countryStats: [],
        habits: null,
        worldCountriesGeo: null,
        config: null,
        artistFilter: "",
        albumFilter: "",
        songFilter: "",
        artistSort: { col: "minutes", dir: "desc" },
        albumSort: { col: "minutes", dir: "desc" },
        songSort: { col: "minutes", dir: "desc" },
    };

    // DOM References
    const activeUsernameEl = document.getElementById("active-username");
    const activeFolderEl = document.getElementById("active-folder-label");
    const syncStatusEl = document.getElementById("sync-status");
    const onboardingCallout = document.getElementById("onboarding-callout");

    const statTotalMinutes = document.getElementById("stat-total-minutes");
    const heroStatLabel = document.getElementById("hero-stat-label");
    const heroStatUnit = document.getElementById("hero-stat-unit");
    const statHoursBreakdown = document.getElementById("stat-hours-breakdown");
    const statTotalListens = document.getElementById("stat-total-listens");
    const statDailyAvg = document.getElementById("stat-daily-avg");
    const statUniqueArtists = document.getElementById("stat-unique-artists");
    const statUniqueAlbums = document.getElementById("stat-unique-albums");
    const statUniqueTracks = document.getElementById("stat-unique-tracks");
    const statListenRange = document.getElementById("stat-listen-range");

    const btnMetricMinutes = document.getElementById("btn-metric-minutes");
    const btnMetricPlays = document.getElementById("btn-metric-plays");
    const limitSelect = document.getElementById("limit-select");
    const chkIncludeFlags = document.getElementById("chk-include-flags");
    const btnDataSource = document.getElementById("btn-data-source");
    const btnOpenImportOnboarding = document.getElementById("btn-open-import-onboarding");
    const btnSyncData = document.getElementById("btn-sync-data");

    const yearPillGroup = document.getElementById("year-pill-group");
    const monthQuickSelect = document.getElementById("month-quick-select");
    const sliderStartInput = document.getElementById("slider-start-input");
    const sliderEndInput = document.getElementById("slider-end-input");
    const sliderFillHighlight = document.getElementById("slider-fill-highlight");
    const sliderStartBadge = document.getElementById("slider-start-badge");
    const sliderEndBadge = document.getElementById("slider-end-badge");
    const sliderMinDateLabel = document.getElementById("slider-min-date-label");
    const sliderMaxDateLabel = document.getElementById("slider-max-date-label");
    const sliderActiveSpanLabel = document.getElementById("slider-active-span-label");
    const btnResetSlider = document.getElementById("btn-reset-slider");

    const collageContainer = document.getElementById("collage-container");
    const artistsPodium = document.getElementById("artists-podium");
    const artistsContainer = document.getElementById("artists-list-container");
    const albumsContainer = document.getElementById("albums-list-container");
    const songsPodium = document.getElementById("songs-podium");
    const songsContainer = document.getElementById("songs-list-container");
    const yearsContainer = document.getElementById("years-chart-container");
    const yearSpotlight = document.getElementById("year-spotlight");
    const yearsLedgerTbody = document.getElementById("years-ledger-tbody");

    const worldMapContainer = document.getElementById("world-map-svg-container");
    const countryTableTbody = document.getElementById("country-table-tbody");
    const countryTableHeading = document.getElementById("country-table-heading");
    const countryInsightsGrid = document.getElementById("country-insights-grid");
    const countryPieCard = document.getElementById("country-pie-card");
    const countryPieContainer = document.getElementById("country-pie-container");
    const mapTooltip = document.getElementById("map-tooltip");

    const btnLayoutTiered = document.getElementById("btn-layout-tiered");
    const btnLayoutUniform = document.getElementById("btn-layout-uniform");
    const btnToggleCaptions = document.getElementById("btn-toggle-captions");
    const btnDownloadCollage = document.getElementById("btn-download-collage");
    const btnExportArtists = document.getElementById("btn-export-artists");
    const btnExportSongs = document.getElementById("btn-export-songs");
    const btnExportYears = document.getElementById("btn-export-years");
    const btnExportMap = document.getElementById("btn-export-map");
    const btnExportAll = document.getElementById("btn-export-all");
    const exportFormatGroup = document.getElementById("export-format-group");
    const exportResultLinks = document.getElementById("export-result-links");
    const chkJxlWrap = document.getElementById("chk-jxl-wrap");

    const btnYearsActiveOnly = document.getElementById("btn-years-active-only");
    const btnYearsContinuous = document.getElementById("btn-years-continuous");
    const btnMapModeMetric = document.getElementById("btn-map-mode-metric");
    const btnMapModeArtists = document.getElementById("btn-map-mode-artists");
    const countryTopXSelect = document.getElementById("country-top-x-select");
    const chkCountryPie = document.getElementById("chk-country-pie");

    const filterArtistsInput = document.getElementById("filter-artists-input");
    const filterAlbumsInput = document.getElementById("filter-albums-input");
    const filterSongsInput = document.getElementById("filter-songs-input");

    const drilldownModal = document.getElementById("drilldown-modal");
    const modalCloseBtn = document.getElementById("modal-close-btn");
    const modalHeader = document.getElementById("modal-header");
    const modalNav = document.getElementById("modal-nav");
    const modalBody = document.getElementById("modal-body");

    const dataSourceModal = document.getElementById("data-source-modal");
    const dataModalCloseBtn = document.getElementById("data-modal-close-btn");
    const discoveredSourcesList = document.getElementById("discovered-sources-list");
    const customDataDirInput = document.getElementById("custom-data-dir-input");
    const btnApplyCustomPath = document.getElementById("btn-apply-custom-path");
    const exportFileInput = document.getElementById("export-file-input");
    const uploadDropzone = document.getElementById("upload-dropzone");
    const uploadDropzoneText = document.getElementById("upload-dropzone-text");
    const dataSourceFeedback = document.getElementById("data-source-feedback");
    const lbTokenInput = document.getElementById("lb-token-input");
    const btnToggleLbToken = document.getElementById("btn-toggle-lb-token");
    const btnSaveLbToken = document.getElementById("btn-save-lb-token");
    const btnClearLbToken = document.getElementById("btn-clear-lb-token");
    const chkRememberLbToken = document.getElementById("chk-remember-lb-token");
    const lbTokenStatusBadge = document.getElementById("lb-token-status-badge");
    const btnAutoLbExport = document.getElementById("btn-auto-lb-export");
    const lbExportProgressText = document.getElementById("lb-export-progress-text");
    let lbPollTimer = null;

    const tabBtns = document.querySelectorAll(".tab-btn");
    const tabContents = document.querySelectorAll(".tab-content");

    const PIE_COLORS = [
        "#3b82f6", "#f59e0b", "#10b981", "#ec4899", "#06b6d4",
        "#a855f7", "#f43f5e", "#84cc16", "#fb923c", "#6366f1",
        "#14b8a6", "#eab308", "#e879f9", "#38bdf8", "#f97316",
    ];

    function escapeHtml(str) {
        if (str === null || str === undefined) return "";
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function normalizeFlagCode(code) {
        if (!code) return "";
        const c = String(code).trim().toUpperCase();
        if (c === "UK") return "gb";
        if (c === "CN-TW") return "tw";
        if (c === "XX" || c.length !== 2) return "";
        return c.toLowerCase();
    }

    function flagHtml(countryCode, countryName = "", large = false) {
        if (!state.showFlags) return "";
        const norm = normalizeFlagCode(countryCode);
        if (!norm) return "";
        const cls = large ? "inline-flag inline-flag-lg" : "inline-flag";
        const label = escapeHtml(countryName || countryCode || "");
        return `<img class="${cls}" src="/flags/${norm}.svg" alt="${label}" title="${label}">`;
    }

    function getFallbackAvatar(name) {
        const initials = name
            ? name.split(" ").slice(0, 2).map(w => w[0] || "").join("").toUpperCase()
            : "?";
        const svg = `<svg xmlns='http://www.w3.org/2000/svg' width='100' height='100' viewBox='0 0 100 100'><rect width='100' height='100' fill='%231e293b'/><text x='50' y='58' font-family='sans-serif' font-size='34' font-weight='bold' fill='%2394a3b8' text-anchor='middle'>${escapeHtml(initials || "?")}</text></svg>`;
        return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
    }

    function debounce(fn, delay = 70) {
        let timer = null;
        return function (...args) {
            clearTimeout(timer);
            timer = setTimeout(() => fn.apply(this, args), delay);
        };
    }

    const debouncedLoadAllData = debounce(() => loadAllData(), 70);

    function formatDateBadge(ts) {
        if (!ts) return "--";
        const d = new Date(ts * 1000);
        return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
    }

    function formatMonthName(monthStr) {
        if (!monthStr || !monthStr.includes("-")) return monthStr;
        const [y, m] = monthStr.split("-");
        const date = new Date(parseInt(y, 10), parseInt(m, 10) - 1, 1);
        return date.toLocaleDateString("en-US", { month: "long", year: "numeric" });
    }

    function timeQuery() {
        if (state.start_ts && state.end_ts) {
            return `&start_ts=${state.start_ts}&end_ts=${state.end_ts}`;
        }
        if (state.timeframe && state.timeframe !== "all") {
            return `&timeframe=${encodeURIComponent(state.timeframe)}`;
        }
        return "";
    }

    function getSelectedFormats() {
        const checked = Array.from(exportFormatGroup.querySelectorAll('input[type="checkbox"]:checked:not(:disabled)'))
            .map(el => el.value);
        if (checked.length === 0) {
            const webpBox = exportFormatGroup.querySelector('input[value="webp"]');
            if (webpBox) webpBox.checked = true;
            return ["webp"];
        }
        return checked;
    }

    function positionTooltip(clientX, clientY) {
        const pad = 16;
        const rect = mapTooltip.getBoundingClientRect();
        const w = rect.width || 280;
        const h = rect.height || 160;
        let x = clientX + pad;
        let y = clientY + pad;
        if (x + w + 10 > window.innerWidth) {
            x = Math.max(10, clientX - w - pad);
        }
        if (y + h + 10 > window.innerHeight) {
            y = Math.max(10, window.innerHeight - h - 10);
        }
        mapTooltip.style.left = `${x}px`;
        mapTooltip.style.top = `${y}px`;
    }

    const TIERED_PRESETS = [
        { v: 11, label: "Top 11 (Gapless)" },
        { v: 16, label: "Top 16 (Gapless)" },
        { v: 21, label: "Top 21 (Gapless)" },
        { v: 31, label: "Top 31 (Gapless)" },
        { v: 41, label: "Top 41 (Gapless)" },
        { v: 51, label: "Top 51 (Gapless)" },
        { v: 76, label: "Top 76 (Gapless)" },
        { v: 101, label: "Top 101 (Gapless)" },
    ];

    const UNIFORM_PRESETS = [
        { v: 9, label: "Top 9 (3×3)", cols: 3 },
        { v: 16, label: "Top 16 (4×4)", cols: 4 },
        { v: 20, label: "Top 20 (5×4)", cols: 5 },
        { v: 25, label: "Top 25 (5×5)", cols: 5 },
        { v: 30, label: "Top 30 (5×6)", cols: 5 },
        { v: 50, label: "Top 50 (5×10)", cols: 5 },
        { v: 100, label: "Top 100 (5×20)", cols: 5 },
    ];

    function syncLimitDropdown() {
        const presets = state.layout === "tiered" ? TIERED_PRESETS : UNIFORM_PRESETS;
        // Snap current state.limit to nearest available preset
        let closest = presets[0].v;
        let minDiff = Infinity;
        for (const p of presets) {
            const diff = Math.abs(p.v - state.limit);
            if (diff < minDiff) {
                minDiff = diff;
                closest = p.v;
            }
        }
        state.limit = closest;
        limitSelect.innerHTML = presets.map(p => `<option value="${p.v}" ${p.v === closest ? "selected" : ""}>${p.label}</option>`).join("");
    }

    function calculateTieredLimit(targetLimit) {
        const t = parseInt(targetLimit, 10);
        if (t <= 3) return 3;
        if (t <= 7) return 7;
        if (t <= 11) return 11;
        const rem = (t - 11) % 5;
        return rem === 0 ? t : t + (5 - rem);
    }

    // Boot Sequence
    initTabs();
    initControls();
    initModalEvents();
    initDataSourceModal();
    initTableSorting();
    loadWorldGeoJSON();
    loadConfig();
    initTimeRangeAndLoad();

    function initTabs() {
        tabBtns.forEach(btn => {
            btn.addEventListener("click", () => {
                const targetTab = btn.getAttribute("data-tab");
                tabBtns.forEach(b => b.classList.remove("active"));
                tabContents.forEach(c => c.classList.remove("active"));
                btn.classList.add("active");
                const targetEl = document.getElementById(targetTab);
                if (targetEl) targetEl.classList.add("active");
                mapTooltip.style.display = "none";
                exportResultLinks.innerHTML = "";
            });
        });
    }

    async function loadConfig() {
        try {
            const res = await fetch("/api/config");
            const cfg = await res.json();
            state.config = cfg;

            const rawUser = (cfg.username || "").trim();
            const displayUser = rawUser || "Listener";
            activeUsernameEl.textContent = displayUser;
            if (rawUser && !["listener", "unknown"].includes(rawUser.toLowerCase())) {
                activeUsernameEl.href = `https://listenbrainz.org/user/${encodeURIComponent(rawUser)}`;
                activeUsernameEl.title = `Open ${rawUser}'s ListenBrainz profile`;
                activeUsernameEl.classList.remove("disabled-link");
            } else {
                activeUsernameEl.removeAttribute("href");
                activeUsernameEl.removeAttribute("title");
                activeUsernameEl.classList.add("disabled-link");
            }
            if (cfg.data_dir) {
                const folderName = cfg.data_dir.split(/[\\/]/).filter(Boolean).pop() || cfg.data_dir;
                activeFolderEl.textContent = folderName;
                activeFolderEl.title = cfg.data_dir;
            } else {
                activeFolderEl.textContent = "No export folder selected";
            }

            onboardingCallout.classList.toggle("hidden", (cfg.total_listens || 0) > 0);

            if (chkJxlWrap) {
                const jxlInput = chkJxlWrap.querySelector("input");
                if (!cfg.cjxl_available) {
                    jxlInput.disabled = true;
                    jxlInput.checked = false;
                    chkJxlWrap.classList.add("disabled");
                    chkJxlWrap.title = "Install libjxl (cjxl) on your system to export JPEG XL";
                }
            }
            renderDiscoveredSources(cfg);
            renderLbTokenStatus(cfg.listenbrainz_token);
        } catch (err) {
            console.error("Failed loading config:", err);
        }
    }

    function renderLbTokenStatus(tokStatus) {
        if (!lbTokenStatusBadge) return;
        if (!tokStatus || !tokStatus.has_token) {
            lbTokenStatusBadge.textContent = "Token: Not set";
            lbTokenStatusBadge.classList.remove("active");
            if (btnClearLbToken) btnClearLbToken.classList.add("hidden");
            return;
        }
        const srcLabel = tokStatus.source === "env"
            ? "Env var"
            : (tokStatus.source === "config" ? "Saved (0600)" : "Session");
        lbTokenStatusBadge.textContent = `${srcLabel} ${tokStatus.masked || ""}`.trim();
        lbTokenStatusBadge.classList.add("active");
        if (btnClearLbToken) {
            btnClearLbToken.classList.toggle("hidden", tokStatus.source === "env");
        }
    }

    function renderDiscoveredSources(cfg) {
        if (!discoveredSourcesList) return;
        const list = (cfg && cfg.discovered) || [];
        if (list.length === 0) {
            discoveredSourcesList.innerHTML = `<div class="import-hint">No ListenBrainz export folders detected in <code>imports/</code>, <code>~/Documents/Music Library/</code>, or <code>~/Downloads/</code>. Upload a .zip or enter a path below.</div>`;
            return;
        }
        discoveredSourcesList.innerHTML = list.map(src => `
            <div class="source-item ${src.active ? "active" : ""}">
                <div class="source-meta">
                    <div class="source-title">
                        <span>${escapeHtml(src.name)}</span>
                        <span class="source-badge ${src.active ? "active" : ""}">${src.active ? "Active" : (src.kind === "archive" ? "Archive" : `${src.file_count} files`)}</span>
                        <span class="tag-badge">User: ${escapeHtml(src.username)}</span>
                    </div>
                    <div class="source-path">${escapeHtml(src.path)}</div>
                </div>
                <button class="btn-primary btn-select-source" type="button" data-path="${encodeURIComponent(src.path)}">
                    ${src.active ? "Re-Sync" : (src.kind === "archive" ? "Extract & Load" : "Use & Sync")}
                </button>
            </div>
        `).join("");

        discoveredSourcesList.querySelectorAll(".btn-select-source").forEach(btn => {
            btn.addEventListener("click", async () => {
                const p = decodeURIComponent(btn.getAttribute("data-path"));
                await switchDataSource(p);
            });
        });
    }

    async function switchDataSource(dirPath) {
        showDataFeedback("Loading and syncing ListenBrainz export...", false);
        try {
            const res = await fetch("/api/config", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ data_dir: dirPath }),
            });
            const data = await res.json();
            if (!res.ok || !data.success) {
                throw new Error(data.error || "Failed to load export folder");
            }
            showDataFeedback(
                `Loaded ${data.sync.username}'s export (${data.sync.total_listens.toLocaleString()} listens, ${data.sync.new_scrobbles} new) in ${data.sync.elapsed_ms} ms.`,
                false
            );
            await loadConfig();
            await initTimeRangeAndLoad();
        } catch (err) {
            showDataFeedback(err.message, true);
        }
    }

    function showDataFeedback(msg, isError) {
        dataSourceFeedback.textContent = msg;
        dataSourceFeedback.classList.remove("hidden", "error");
        if (isError) dataSourceFeedback.classList.add("error");
    }

    function initDataSourceModal() {
        const openModal = () => {
            loadConfig();
            dataSourceFeedback.classList.add("hidden");
            dataSourceModal.classList.add("open");
        };
        const closeDataModal = () => dataSourceModal.classList.remove("open");

        if (btnDataSource) btnDataSource.addEventListener("click", openModal);
        if (btnOpenImportOnboarding) btnOpenImportOnboarding.addEventListener("click", openModal);
        if (dataModalCloseBtn) dataModalCloseBtn.addEventListener("click", closeDataModal);
        dataSourceModal.addEventListener("click", e => {
            if (e.target === dataSourceModal) closeDataModal();
        });

        btnApplyCustomPath.addEventListener("click", async () => {
            const val = customDataDirInput.value.trim();
            if (!val) {
                showDataFeedback("Please enter a folder or archive path first.", true);
                return;
            }
            await switchDataSource(val);
        });

        async function uploadArchiveFile(file) {
            if (!file) return;
            uploadDropzoneText.textContent = `Uploading & extracting ${file.name}...`;
            showDataFeedback(`Uploading ${file.name}...`, false);
            try {
                const res = await fetch(`/api/upload-export?filename=${encodeURIComponent(file.name)}`, {
                    method: "POST",
                    body: file,
                });
                const data = await res.json();
                if (!res.ok || !data.success) {
                    throw new Error(data.error || "Upload failed");
                }
                showDataFeedback(
                    `Imported ${file.name} (${data.sync.total_listens.toLocaleString()} listens) in ${data.sync.elapsed_ms} ms.`,
                    false
                );
                await loadConfig();
                await initTimeRangeAndLoad();
            } catch (err) {
                showDataFeedback(err.message, true);
            } finally {
                uploadDropzoneText.textContent = "Click to choose or drop a ListenBrainz .zip / .tar.gz file";
            }
        }

        exportFileInput.addEventListener("change", e => {
            if (e.target.files && e.target.files[0]) {
                uploadArchiveFile(e.target.files[0]);
            }
        });

        uploadDropzone.addEventListener("dragover", e => {
            e.preventDefault();
            uploadDropzone.classList.add("dragover");
        });
        uploadDropzone.addEventListener("dragleave", () => uploadDropzone.classList.remove("dragover"));
        uploadDropzone.addEventListener("drop", e => {
            e.preventDefault();
            uploadDropzone.classList.remove("dragover");
            if (e.dataTransfer.files && e.dataTransfer.files[0]) {
                uploadArchiveFile(e.dataTransfer.files[0]);
            }
        });

        if (btnToggleLbToken && lbTokenInput) {
            btnToggleLbToken.addEventListener("click", () => {
                const hidden = lbTokenInput.type === "password";
                lbTokenInput.type = hidden ? "text" : "password";
                btnToggleLbToken.textContent = hidden ? "Hide" : "Show";
            });
        }

        if (btnSaveLbToken && lbTokenInput) {
            btnSaveLbToken.addEventListener("click", async () => {
                const tok = lbTokenInput.value.trim();
                if (!tok) {
                    showDataFeedback("Please paste your ListenBrainz User Token first.", true);
                    return;
                }
                try {
                    const res = await fetch("/api/listenbrainz-token", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ token: tok, remember: Boolean(chkRememberLbToken && chkRememberLbToken.checked) }),
                    });
                    const data = await res.json();
                    if (!res.ok || !data.success) throw new Error(data.error || "Failed saving token");
                    lbTokenInput.value = "";
                    lbTokenInput.type = "password";
                    if (btnToggleLbToken) btnToggleLbToken.textContent = "Show";
                    renderLbTokenStatus(data.listenbrainz_token);
                    showDataFeedback("ListenBrainz User Token stored safely.", false);
                } catch (err) {
                    showDataFeedback(err.message, true);
                }
            });
        }

        if (btnClearLbToken) {
            btnClearLbToken.addEventListener("click", async () => {
                try {
                    const res = await fetch("/api/listenbrainz-token", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ clear: true }),
                    });
                    const data = await res.json();
                    if (!res.ok || !data.success) throw new Error(data.error || "Failed clearing token");
                    renderLbTokenStatus(data.listenbrainz_token);
                    showDataFeedback("Saved ListenBrainz token removed.", false);
                } catch (err) {
                    showDataFeedback(err.message, true);
                }
            });
        }

        async function pollAutoExportStatus() {
            try {
                const res = await fetch("/api/listenbrainz-export/status");
                const data = await res.json();
                const job = data && data.job;
                if (!job) return;
                if (lbExportProgressText) {
                    lbExportProgressText.textContent = job.progress || job.state;
                }
                if (job.state === "completed") {
                    clearInterval(lbPollTimer);
                    lbPollTimer = null;
                    if (btnAutoLbExport) btnAutoLbExport.disabled = false;
                    showDataFeedback(job.progress || "ListenBrainz export imported successfully!", false);
                    await loadConfig();
                    await initTimeRangeAndLoad();
                } else if (job.state === "failed") {
                    clearInterval(lbPollTimer);
                    lbPollTimer = null;
                    if (btnAutoLbExport) btnAutoLbExport.disabled = false;
                    showDataFeedback(job.error || "Automatic ListenBrainz export failed.", true);
                }
            } catch (err) {
                console.error("Failed polling export status:", err);
            }
        }

        if (btnAutoLbExport) {
            btnAutoLbExport.addEventListener("click", async () => {
                const tok = lbTokenInput ? lbTokenInput.value.trim() : "";
                const remember = Boolean(chkRememberLbToken && chkRememberLbToken.checked);
                btnAutoLbExport.disabled = true;
                if (lbExportProgressText) lbExportProgressText.textContent = "Starting ListenBrainz export...";
                showDataFeedback("Connecting to ListenBrainz Export API...", false);
                try {
                    const payload = tok ? { token: tok, remember } : {};
                    const res = await fetch("/api/listenbrainz-export/start", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(payload),
                    });
                    const data = await res.json();
                    if (!res.ok || !data.success) {
                        throw new Error(data.error || "Failed starting ListenBrainz export");
                    }
                    if (tok && lbTokenInput) {
                        lbTokenInput.value = "";
                        lbTokenInput.type = "password";
                        if (btnToggleLbToken) btnToggleLbToken.textContent = "Show";
                    }
                    renderLbTokenStatus(data.listenbrainz_token);
                    if (lbExportProgressText && data.job) {
                        lbExportProgressText.textContent = data.job.progress || "Queued...";
                    }
                    if (lbPollTimer) clearInterval(lbPollTimer);
                    lbPollTimer = setInterval(pollAutoExportStatus, 2000);
                } catch (err) {
                    btnAutoLbExport.disabled = false;
                    if (lbExportProgressText) lbExportProgressText.textContent = "";
                    showDataFeedback(err.message, true);
                }
            });
        }
    }

    async function initTimeRangeAndLoad() {
        try {
            const res = await fetch("/api/time-range");
            const data = await res.json();
            state.min_ts = data.min_timestamp;
            state.max_ts = data.max_timestamp;
            state.start_ts = state.min_ts;
            state.end_ts = state.max_ts;

            sliderStartInput.min = state.min_ts;
            sliderStartInput.max = state.max_ts;
            sliderStartInput.value = state.start_ts;

            sliderEndInput.min = state.min_ts;
            sliderEndInput.max = state.max_ts;
            sliderEndInput.value = state.end_ts;

            sliderMinDateLabel.textContent = formatDateBadge(state.min_ts);
            sliderMaxDateLabel.textContent = formatDateBadge(state.max_ts);

            populateTimePresets(data);
            updateSliderDisplay();
        } catch (e) {
            console.error("Failed to load time range:", e);
        }
        await loadAllData();
    }

    function populateTimePresets(data) {
        yearPillGroup.innerHTML = `<button class="pill-mini-btn active" data-year="all" type="button">All Time</button>`;
        if (data.years && data.years.length > 0) {
            data.years.forEach(year => {
                const btn = document.createElement("button");
                btn.type = "button";
                btn.className = "pill-mini-btn";
                btn.setAttribute("data-year", year);
                btn.textContent = year;
                yearPillGroup.appendChild(btn);
            });
        }

        yearPillGroup.querySelectorAll(".pill-mini-btn").forEach(btn => {
            btn.addEventListener("click", () => {
                yearPillGroup.querySelectorAll(".pill-mini-btn").forEach(b => b.classList.remove("active"));
                btn.classList.add("active");
                monthQuickSelect.value = "all";

                const yr = btn.getAttribute("data-year");
                if (yr === "all") {
                    state.start_ts = state.min_ts;
                    state.end_ts = state.max_ts;
                    state.timeframe = "all";
                } else {
                    const yearNum = parseInt(yr, 10);
                    const startOfYear = Math.floor(new Date(yearNum, 0, 1, 0, 0, 0).getTime() / 1000);
                    const endOfYear = Math.floor(new Date(yearNum, 11, 31, 23, 59, 59).getTime() / 1000);
                    state.start_ts = Math.max(state.min_ts, startOfYear);
                    state.end_ts = Math.min(state.max_ts, endOfYear);
                    state.timeframe = yr;
                }

                sliderStartInput.value = state.start_ts;
                sliderEndInput.value = state.end_ts;
                updateSliderDisplay();
                loadAllData();
            });
        });

        monthQuickSelect.innerHTML = `<option value="all">All Months</option>`;
        if (data.months && data.months.length > 0) {
            data.months.forEach(mStr => {
                const opt = document.createElement("option");
                opt.value = mStr;
                opt.textContent = formatMonthName(mStr);
                monthQuickSelect.appendChild(opt);
            });
        }

        monthQuickSelect.onchange = e => {
            const val = e.target.value;
            yearPillGroup.querySelectorAll(".pill-mini-btn").forEach(b => b.classList.remove("active"));
            if (val === "all") {
                const allBtn = yearPillGroup.querySelector('.pill-mini-btn[data-year="all"]');
                if (allBtn) allBtn.classList.add("active");
                state.start_ts = state.min_ts;
                state.end_ts = state.max_ts;
                state.timeframe = "all";
            } else {
                const [y, m] = val.split("-");
                const yrNum = parseInt(y, 10);
                const moNum = parseInt(m, 10);
                const startOfMonth = Math.floor(new Date(yrNum, moNum - 1, 1, 0, 0, 0).getTime() / 1000);
                const endOfMonth = Math.floor(new Date(yrNum, moNum, 0, 23, 59, 59).getTime() / 1000);
                state.start_ts = Math.max(state.min_ts, startOfMonth);
                state.end_ts = Math.min(state.max_ts, endOfMonth);
                state.timeframe = `${yrNum}-${moNum}`;
            }

            sliderStartInput.value = state.start_ts;
            sliderEndInput.value = state.end_ts;
            updateSliderDisplay();
            loadAllData();
        };

        sliderStartInput.oninput = () => {
            let startVal = parseInt(sliderStartInput.value, 10);
            const endVal = parseInt(sliderEndInput.value, 10);
            if (startVal > endVal) {
                sliderStartInput.value = endVal;
                startVal = endVal;
            }
            state.start_ts = startVal;
            state.end_ts = endVal;
            state.timeframe = "custom";
            clearPresetActiveHighlights();
            updateSliderDisplay();
            debouncedLoadAllData();
        };

        sliderEndInput.oninput = () => {
            const startVal = parseInt(sliderStartInput.value, 10);
            let endVal = parseInt(sliderEndInput.value, 10);
            if (endVal < startVal) {
                sliderEndInput.value = startVal;
                endVal = startVal;
            }
            state.start_ts = startVal;
            state.end_ts = endVal;
            state.timeframe = "custom";
            clearPresetActiveHighlights();
            updateSliderDisplay();
            debouncedLoadAllData();
        };

        btnResetSlider.onclick = () => {
            state.start_ts = state.min_ts;
            state.end_ts = state.max_ts;
            state.timeframe = "all";
            sliderStartInput.value = state.min_ts;
            sliderEndInput.value = state.max_ts;
            monthQuickSelect.value = "all";
            yearPillGroup.querySelectorAll(".pill-mini-btn").forEach(b => b.classList.remove("active"));
            const allBtn = yearPillGroup.querySelector('.pill-mini-btn[data-year="all"]');
            if (allBtn) allBtn.classList.add("active");
            updateSliderDisplay();
            loadAllData();
        };
    }

    function clearPresetActiveHighlights() {
        yearPillGroup.querySelectorAll(".pill-mini-btn").forEach(b => b.classList.remove("active"));
        monthQuickSelect.value = "all";
    }

    function updateSliderDisplay() {
        if (!state.min_ts || !state.max_ts) return;
        const min = state.min_ts;
        const max = state.max_ts;
        const range = max - min || 1;
        const leftPct = ((state.start_ts - min) / range) * 100;
        const rightPct = ((max - state.end_ts) / range) * 100;
        const widthPct = Math.max(0, 100 - leftPct - rightPct);

        sliderFillHighlight.style.left = `${leftPct}%`;
        sliderFillHighlight.style.width = `${widthPct}%`;

        sliderStartBadge.textContent = formatDateBadge(state.start_ts);
        sliderEndBadge.textContent = formatDateBadge(state.end_ts);

        const days = Math.max(1, Math.round((state.end_ts - state.start_ts) / 86400));
        if (state.start_ts === state.min_ts && state.end_ts === state.max_ts) {
            sliderActiveSpanLabel.textContent = `Full Range (${days} days)`;
        } else {
            sliderActiveSpanLabel.textContent = `${days} days selected`;
        }
    }

    function updateExportButtonText() {
        const targetLimit = state.layout === "tiered" ? calculateTieredLimit(state.limit) : state.limit;
        btnDownloadCollage.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
            Export Top ${targetLimit}
        `;
    }

    async function runImageExport(btn, urlBuilder, sectionLabel = "") {
        const formats = getSelectedFormats();
        const origHtml = btn.innerHTML;
        btn.textContent = `Exporting (${formats.join(", ").toUpperCase()})...`;
        btn.disabled = true;
        exportResultLinks.innerHTML = "";
        try {
            const url = urlBuilder(formats);
            const res = await fetch(url);
            const data = await res.json();
            if (!res.ok || !data.success) {
                throw new Error(data.error || "Export failed");
            }
            const files = data.files || (data.url ? [{ format: formats[0], url: data.url, filename: data.url.split("/").pop() }] : []);
            exportResultLinks.innerHTML = files.map(f => {
                const chipLabel = f.format === "zip"
                    ? `${sectionLabel || "All Graphics"} (ZIP)`
                    : (sectionLabel ? `${sectionLabel} · ${f.format.toUpperCase()}` : `Download ${f.format.toUpperCase()}`);
                return `<a class="export-file-chip" href="${escapeHtml(f.url)}" download="${escapeHtml(f.filename)}">${escapeHtml(chipLabel)}</a>`;
            }).join("");

            // Trigger download for generated file(s) automatically; show chips for all generated formats
            files.forEach((f, idx) => {
                setTimeout(() => {
                    const link = document.createElement("a");
                    link.href = f.url;
                    link.download = f.filename;
                    document.body.appendChild(link);
                    link.click();
                    document.body.removeChild(link);
                }, idx * 250);
            });
        } catch (err) {
            console.error("Image export failed:", err);
            exportResultLinks.innerHTML = `<span style="color:#fda4af;font-size:12px;">Export error: ${escapeHtml(err.message)}</span>`;
        } finally {
            btn.innerHTML = origHtml;
            btn.disabled = false;
        }
    }

    function initControls() {
        btnMetricMinutes.addEventListener("click", () => {
            if (state.metric !== "minutes") {
                state.metric = "minutes";
                btnMetricMinutes.classList.add("active");
                btnMetricPlays.classList.remove("active");
                state.artistSort = { col: "minutes", dir: "desc" };
                state.albumSort = { col: "minutes", dir: "desc" };
                state.songSort = { col: "minutes", dir: "desc" };
                updateMetricHeaders();
                loadAllData();
            }
        });

        btnMetricPlays.addEventListener("click", () => {
            if (state.metric !== "plays") {
                state.metric = "plays";
                btnMetricPlays.classList.add("active");
                btnMetricMinutes.classList.remove("active");
                state.artistSort = { col: "plays", dir: "desc" };
                state.albumSort = { col: "plays", dir: "desc" };
                state.songSort = { col: "plays", dir: "desc" };
                updateMetricHeaders();
                loadAllData();
            }
        });

        limitSelect.addEventListener("change", e => {
            state.limit = parseInt(e.target.value, 10);
            syncLimitDropdown();
        updateExportButtonText();
            loadRankings();
        });

        chkIncludeFlags.addEventListener("change", e => {
            state.showFlags = e.target.checked;
            renderCollage(state.topAlbums);
            renderArtists();
            renderAlbumsList();
            renderSongsList();
            renderCountryTable(state.countryStats);
            if (state.showCountryPie) renderCountryPieChart(state.countryStats);
        });

        btnLayoutTiered.addEventListener("click", () => {
            state.layout = "tiered";
            btnLayoutTiered.classList.add("active");
            btnLayoutUniform.classList.remove("active");
            syncLimitDropdown();
            syncLimitDropdown();
        updateExportButtonText();
            loadRankings();
        });

        btnLayoutUniform.addEventListener("click", () => {
            state.layout = "uniform";
            btnLayoutUniform.classList.add("active");
            btnLayoutTiered.classList.remove("active");
            syncLimitDropdown();
            syncLimitDropdown();
        updateExportButtonText();
            loadRankings();
        });

        btnToggleCaptions.addEventListener("click", () => {
            state.showCaptions = !state.showCaptions;
            btnToggleCaptions.classList.toggle("active", state.showCaptions);
            btnToggleCaptions.innerHTML = `
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 7V4h16v3M9 20h6M12 4v16"></path></svg>
                ${state.showCaptions ? "Titles On" : "Titles Off"}
            `;
            document.querySelectorAll(".collage-item").forEach(item => {
                item.classList.toggle("hide-captions", !state.showCaptions);
            });
        });

        state.showFlags = Boolean(chkIncludeFlags && chkIncludeFlags.checked);
        state.showCountryPie = Boolean(chkCountryPie && chkCountryPie.checked);
        if (countryPieCard) countryPieCard.classList.toggle("hidden", !state.showCountryPie);
        if (countryInsightsGrid) countryInsightsGrid.classList.toggle("with-pie", state.showCountryPie);

        syncLimitDropdown();
        updateExportButtonText();

        if (btnExportAll) {
            btnExportAll.addEventListener("click", () => {
                const targetLimit = state.layout === "tiered" ? calculateTieredLimit(state.limit) : state.limit;
                runImageExport(
                    btnExportAll,
                    formats =>
                        `/api/generate-all?layout=${state.layout}&limit=${targetLimit}&metric=${state.metric}&formats=${formats.join(",")}&captions=${state.showCaptions ? 1 : 0}&flags=${state.showFlags ? 1 : 0}&years_mode=${state.yearsMode}&rank_by=${state.mapRankBy}&top_x=${state.countryTopX}&pie=${state.showCountryPie ? 1 : 0}${timeQuery()}`,
                    "All Graphics"
                );
            });
        }

        btnDownloadCollage.addEventListener("click", () => {
            const targetLimit = state.layout === "tiered" ? calculateTieredLimit(state.limit) : state.limit;
            runImageExport(btnDownloadCollage, formats =>
                `/api/generate-collage?layout=${state.layout}&limit=${targetLimit}&metric=${state.metric}&formats=${formats.join(",")}&captions=${state.showCaptions ? 1 : 0}&flags=${state.showFlags ? 1 : 0}${timeQuery()}`,
                "Album Collage"
            );
        });

        btnExportArtists.addEventListener("click", () => {
            runImageExport(btnExportArtists, formats =>
                `/api/generate-table?type=artists&limit=50&metric=${state.metric}&formats=${formats.join(",")}&flags=${state.showFlags ? 1 : 0}${timeQuery()}`,
                "Top Artists"
            );
        });

        btnExportSongs.addEventListener("click", () => {
            runImageExport(btnExportSongs, formats =>
                `/api/generate-table?type=songs&limit=50&metric=${state.metric}&formats=${formats.join(",")}&flags=${state.showFlags ? 1 : 0}${timeQuery()}`,
                "Top Songs"
            );
        });

        if (btnExportYears) {
            btnExportYears.addEventListener("click", () => {
                runImageExport(btnExportYears, formats =>
                    `/api/generate-years?metric=${state.metric}&mode=${state.yearsMode}&formats=${formats.join(",")}${timeQuery()}`,
                    "Release Years"
                );
            });
        }

        if (btnExportMap) {
            btnExportMap.addEventListener("click", () => {
                runImageExport(btnExportMap, formats =>
                    `/api/generate-map?metric=${state.metric}&rank_by=${state.mapRankBy}&top_x=${state.countryTopX}&pie=${state.showCountryPie ? 1 : 0}&flags=${state.showFlags ? 1 : 0}&formats=${formats.join(",")}${timeQuery()}`,
                    "World Map"
                );
            });
        }

        btnYearsActiveOnly.addEventListener("click", () => {
            state.yearsMode = "active";
            btnYearsActiveOnly.classList.add("active");
            btnYearsContinuous.classList.remove("active");
            renderReleaseYears(state.releaseYearsData);
        });

        btnYearsContinuous.addEventListener("click", () => {
            state.yearsMode = "continuous";
            btnYearsContinuous.classList.add("active");
            btnYearsActiveOnly.classList.remove("active");
            renderReleaseYears(state.releaseYearsData);
        });

        btnMapModeMetric.addEventListener("click", () => {
            state.mapRankBy = "metric";
            btnMapModeMetric.classList.add("active");
            btnMapModeArtists.classList.remove("active");
            renderWorldMap(state.countryStats);
            if (state.showCountryPie) renderCountryPieChart(state.countryStats);
        });

        btnMapModeArtists.addEventListener("click", () => {
            state.mapRankBy = "artists";
            btnMapModeArtists.classList.add("active");
            btnMapModeMetric.classList.remove("active");
            renderWorldMap(state.countryStats);
            if (state.showCountryPie) renderCountryPieChart(state.countryStats);
        });

        countryTopXSelect.addEventListener("change", e => {
            state.countryTopX = parseInt(e.target.value, 10);
            renderCountryTable(state.countryStats);
            if (state.showCountryPie) renderCountryPieChart(state.countryStats);
        });

        chkCountryPie.addEventListener("change", e => {
            state.showCountryPie = e.target.checked;
            countryPieCard.classList.toggle("hidden", !state.showCountryPie);
            countryInsightsGrid.classList.toggle("with-pie", state.showCountryPie);
            if (state.showCountryPie) {
                renderCountryPieChart(state.countryStats);
                countryPieCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
            }
        });

        btnSyncData.addEventListener("click", async () => {
            btnSyncData.classList.add("syncing");
            syncStatusEl.textContent = "Syncing...";
            try {
                const res = await fetch("/api/sync");
                const data = await res.json();
                syncStatusEl.textContent = `Synced (${data.new_scrobbles || 0} new, ${data.elapsed_ms || 0} ms)`;
                await loadConfig();
                await initTimeRangeAndLoad();
            } catch (e) {
                console.error("Sync error:", e);
                syncStatusEl.textContent = "Sync failed";
            } finally {
                btnSyncData.classList.remove("syncing");
            }
        });

        filterArtistsInput.addEventListener("input", e => {
            state.artistFilter = e.target.value.toLowerCase();
            renderArtists();
        });
        filterAlbumsInput.addEventListener("input", e => {
            state.albumFilter = e.target.value.toLowerCase();
            renderAlbumsList();
        });
        filterSongsInput.addEventListener("input", e => {
            state.songFilter = e.target.value.toLowerCase();
            renderSongsList();
        });
    }

    function initModalEvents() {
        const closeModal = () => drilldownModal.classList.remove("open");
        modalCloseBtn.addEventListener("click", closeModal);
        drilldownModal.addEventListener("click", e => {
            if (e.target === drilldownModal) closeModal();
        });
        document.addEventListener("keydown", e => {
            if (e.key === "Escape") {
                drilldownModal.classList.remove("open");
                dataSourceModal.classList.remove("open");
                mapTooltip.style.display = "none";
            }
        });
    }

    async function openArtistDrilldown(artistName) {
        modalHeader.innerHTML = `<div class="modal-title-group"><div class="modal-title">Loading ${escapeHtml(artistName)}...</div></div>`;
        modalNav.innerHTML = "";
        modalBody.innerHTML = `<div style="padding:36px;text-align:center;color:#94a3b8;">Fetching albums and track breakdown...</div>`;
        drilldownModal.classList.add("open");

        try {
            const res = await fetch(`/api/artist-drilldown?artist=${encodeURIComponent(artistName)}&metric=${state.metric}${timeQuery()}`);
            const data = await res.json();
            renderArtistDrilldownContent(data);
        } catch (err) {
            modalBody.innerHTML = `<div style="padding:36px;text-align:center;color:#fda4af;">Failed to load artist breakdown.</div>`;
        }
    }

    function renderArtistDrilldownContent(data) {
        const avatarSrc = data.image_local_path || getFallbackAvatar(data.artist_name);
        const flag = flagHtml(data.country_code, data.country_name || "", true);

        modalHeader.innerHTML = `
            <div class="modal-avatar-wrapper">
                <img src="${escapeHtml(avatarSrc)}" alt="${escapeHtml(data.artist_name)}" onerror="this.src='${getFallbackAvatar(data.artist_name)}'">
            </div>
            <div class="modal-title-group">
                <div class="modal-title">
                    <span>${escapeHtml(data.artist_name)}</span>
                    ${flag}
                </div>
                <div class="modal-subtitle">
                    <span>${escapeHtml(data.country_name || "Unknown Origin")}</span>
                    <span>•</span>
                    <span>${data.album_count} Releases</span>
                    <span>•</span>
                    <span>${data.song_count} Unique Tracks</span>
                </div>
                <div class="modal-stats-strip">
                    <div class="modal-stat-pill">Listen Time: <span>${Number(data.total_minutes).toLocaleString()} mins</span> (${data.total_hours}h)</div>
                    <div class="modal-stat-pill">Total Listens: <span>${Number(data.play_count).toLocaleString()}</span></div>
                </div>
            </div>
        `;

        modalNav.innerHTML = `
            <button class="modal-tab-btn active" id="modal-tab-albums" type="button">Albums (${data.albums.length})</button>
            <button class="modal-tab-btn" id="modal-tab-songs" type="button">Tracks (${data.songs.length})</button>
        `;

        function showAlbumsTab() {
            modalNav.querySelector("#modal-tab-albums").classList.add("active");
            modalNav.querySelector("#modal-tab-songs").classList.remove("active");
            if (!data.albums || data.albums.length === 0) {
                modalBody.innerHTML = `<div style="padding:28px;color:#94a3b8;text-align:center;">No album records found.</div>`;
                return;
            }
            let html = `<div class="responsive-table-wrap"><table class="drilldown-table"><thead><tr>
                <th class="drilldown-th">Album</th>
                <th class="drilldown-th">Year</th>
                <th class="drilldown-th text-right">Tracks</th>
                <th class="drilldown-th text-right">Listens</th>
                <th class="drilldown-th text-right">Time</th>
                <th class="drilldown-th text-right">Share</th>
            </tr></thead><tbody>`;
            data.albums.forEach(alb => {
                const coverSrc = alb.cover_local_path || getFallbackAvatar(alb.release_name);
                const yr = alb.original_release_year ? `<span class="tag-badge">${alb.original_release_year}</span>` : "—";
                html += `<tr class="drilldown-row clickable-row" data-album="${encodeURIComponent(alb.release_name)}">
                    <td class="drilldown-td"><div style="display:flex;align-items:center;">
                        <img src="${escapeHtml(coverSrc)}" class="drilldown-cover" alt="" onerror="this.src='${getFallbackAvatar(alb.release_name)}'">
                        <div><div class="drilldown-title">${escapeHtml(alb.release_name)}</div></div>
                    </div></td>
                    <td class="drilldown-td">${yr}</td>
                    <td class="drilldown-td text-right num">${alb.track_count}</td>
                    <td class="drilldown-td text-right num">${alb.play_count}</td>
                    <td class="drilldown-td text-right drilldown-stat num">${Number(alb.minutes_listened).toLocaleString()}m</td>
                    <td class="drilldown-td text-right drilldown-stat num">${alb.percentage}%</td>
                </tr>`;
            });
            html += `</tbody></table></div>`;
            modalBody.innerHTML = html;
            modalBody.querySelectorAll("tr[data-album]").forEach(tr => {
                tr.addEventListener("click", () => openAlbumDrilldown(data.artist_name, decodeURIComponent(tr.getAttribute("data-album"))));
            });
        }

        function showSongsTab() {
            modalNav.querySelector("#modal-tab-songs").classList.add("active");
            modalNav.querySelector("#modal-tab-albums").classList.remove("active");
            if (!data.songs || data.songs.length === 0) {
                modalBody.innerHTML = `<div style="padding:28px;color:#94a3b8;text-align:center;">No track records found.</div>`;
                return;
            }
            let html = `<div class="responsive-table-wrap"><table class="drilldown-table"><thead><tr>
                <th class="drilldown-th">#</th>
                <th class="drilldown-th">Track</th>
                <th class="drilldown-th">Album</th>
                <th class="drilldown-th text-right">Length</th>
                <th class="drilldown-th text-right">Listens</th>
                <th class="drilldown-th text-right">Time</th>
                <th class="drilldown-th text-right">Share</th>
            </tr></thead><tbody>`;
            data.songs.forEach(song => {
                html += `<tr class="drilldown-row">
                    <td class="drilldown-td num" style="color:#94a3b8;">#${song.rank}</td>
                    <td class="drilldown-td"><div class="drilldown-title">${escapeHtml(song.track_name)}</div></td>
                    <td class="drilldown-td" style="color:#cbd5e1;">${escapeHtml(song.release_name)}</td>
                    <td class="drilldown-td text-right num">${escapeHtml(song.duration_formatted)}</td>
                    <td class="drilldown-td text-right num">${song.play_count}</td>
                    <td class="drilldown-td text-right drilldown-stat num">${Number(song.minutes_listened).toLocaleString()}m</td>
                    <td class="drilldown-td text-right drilldown-stat num">${song.percentage}%</td>
                </tr>`;
            });
            html += `</tbody></table></div>`;
            modalBody.innerHTML = html;
        }

        modalNav.querySelector("#modal-tab-albums").addEventListener("click", showAlbumsTab);
        modalNav.querySelector("#modal-tab-songs").addEventListener("click", showSongsTab);
        showAlbumsTab();
    }

    async function openAlbumDrilldown(artistName, releaseName) {
        modalHeader.innerHTML = `<div class="modal-title-group"><div class="modal-title">Loading ${escapeHtml(releaseName)}...</div></div>`;
        modalNav.innerHTML = "";
        modalBody.innerHTML = `<div style="padding:36px;text-align:center;color:#94a3b8;">Fetching album tracklist...</div>`;
        drilldownModal.classList.add("open");

        try {
            const res = await fetch(`/api/album-drilldown?artist=${encodeURIComponent(artistName)}&release=${encodeURIComponent(releaseName)}&metric=${state.metric}${timeQuery()}`);
            const data = await res.json();
            renderAlbumDrilldownContent(data);
        } catch (err) {
            modalBody.innerHTML = `<div style="padding:36px;text-align:center;color:#fda4af;">Failed to load album breakdown.</div>`;
        }
    }

    function renderAlbumDrilldownContent(data) {
        const coverSrc = data.cover_local_path || getFallbackAvatar(data.release_name);
        const yr = data.original_release_year ? ` (${data.original_release_year})` : "";
        const flag = flagHtml(data.country_code, data.country_name || "", false);

        modalHeader.innerHTML = `
            <div class="modal-avatar-wrapper square">
                <img src="${escapeHtml(coverSrc)}" alt="${escapeHtml(data.release_name)}" onerror="this.src='${getFallbackAvatar(data.release_name)}'">
            </div>
            <div class="modal-title-group">
                <div class="modal-title">${escapeHtml(data.release_name)}${yr}</div>
                <div class="modal-subtitle">
                    <strong style="color:#fff;cursor:pointer;text-decoration:underline;" id="drilldown-artist-link">${escapeHtml(data.artist_name)}</strong>
                    ${flag}
                    <span>•</span>
                    <span>${data.song_count} Tracks</span>
                </div>
                <div class="modal-stats-strip">
                    <div class="modal-stat-pill">Listen Time: <span>${Number(data.total_minutes).toLocaleString()} mins</span> (${data.total_hours}h)</div>
                    <div class="modal-stat-pill">Total Listens: <span>${Number(data.play_count).toLocaleString()}</span></div>
                </div>
            </div>
        `;
        const artLink = document.getElementById("drilldown-artist-link");
        if (artLink) artLink.addEventListener("click", () => openArtistDrilldown(data.artist_name));

        modalNav.innerHTML = "";
        if (!data.songs || data.songs.length === 0) {
            modalBody.innerHTML = `<div style="padding:28px;color:#94a3b8;text-align:center;">No track data found.</div>`;
            return;
        }
        let html = `<div class="responsive-table-wrap"><table class="drilldown-table"><thead><tr>
            <th class="drilldown-th">#</th>
            <th class="drilldown-th">Track</th>
            <th class="drilldown-th text-right">Length</th>
            <th class="drilldown-th text-right">Listens</th>
            <th class="drilldown-th text-right">Time</th>
            <th class="drilldown-th text-right">Share</th>
        </tr></thead><tbody>`;
        data.songs.forEach(song => {
            html += `<tr class="drilldown-row">
                <td class="drilldown-td num" style="color:#94a3b8;">#${song.rank}</td>
                <td class="drilldown-td"><div class="drilldown-title">${escapeHtml(song.track_name)}</div></td>
                <td class="drilldown-td text-right num">${escapeHtml(song.duration_formatted)}</td>
                <td class="drilldown-td text-right num">${song.play_count}</td>
                <td class="drilldown-td text-right drilldown-stat num">${Number(song.minutes_listened).toLocaleString()}m</td>
                <td class="drilldown-td text-right drilldown-stat num">${song.percentage}%</td>
            </tr>`;
        });
        html += `</tbody></table></div>`;
        modalBody.innerHTML = html;
    }

    async function loadWorldGeoJSON() {
        try {
            const [resMain, resExtra] = await Promise.all([
                fetch("/world_countries.json"),
                fetch("/countries_svg.json").catch(() => null),
            ]);
            const mainGeo = await resMain.json();
            if (mainGeo["CN-TW"] && !mainGeo["TW"]) {
                mainGeo["TW"] = mainGeo["CN-TW"];
                delete mainGeo["CN-TW"];
            }
            if (resExtra && resExtra.ok) {
                const extraGeo = await resExtra.json();
                for (const [code, entry] of Object.entries(extraGeo)) {
                    if (!mainGeo[code] || code === "FR" || code === "NO" || code === "XK") {
                        mainGeo[code] = entry;
                    }
                }
            }
            state.worldCountriesGeo = mainGeo;
            if (state.countryStats.length > 0) {
                renderWorldMap(state.countryStats);
            }
        } catch (e) {
            console.error("Failed loading world countries GeoJSON:", e);
        }
    }

    function initTableSorting() {
        const bindSort = (tabId, key, renderFn) => {
            document.querySelectorAll(`#${tabId} .sortable`).forEach(th => {
                th.addEventListener("click", () => {
                    const col = th.getAttribute("data-sort");
                    if (state[key].col === col) {
                        state[key].dir = state[key].dir === "desc" ? "asc" : "desc";
                    } else {
                        state[key].col = col;
                        state[key].dir = col === "rank" ? "asc" : "desc";
                    }
                    updateSortHeaderIcons(tabId, state[key]);
                    renderFn();
                });
            });
        };
        bindSort("tab-artists", "artistSort", renderArtists);
        bindSort("tab-albums", "albumSort", renderAlbumsList);
        bindSort("tab-songs", "songSort", renderSongsList);
    }

    function updateSortHeaderIcons(tabId, sortState) {
        document.querySelectorAll(`#${tabId} .sortable`).forEach(th => {
            th.classList.remove("active");
            const icon = th.querySelector(".sort-icon");
            if (icon) icon.textContent = "";
        });
        const activeTh = document.querySelector(`#${tabId} .sortable[data-sort="${sortState.col}"]`);
        if (activeTh) {
            activeTh.classList.add("active");
            const icon = activeTh.querySelector(".sort-icon");
            if (icon) icon.textContent = sortState.dir === "desc" ? "▼" : "▲";
        }
    }

    function updateMetricHeaders() {
        const isMin = state.metric === "minutes";
        const label = isMin ? "Listen Time" : "No. of Listens";
        document.getElementById("artist-header-stat").innerHTML = `${label} <span class="sort-icon">▼</span>`;
        document.getElementById("album-header-stat").innerHTML = `${label} <span class="sort-icon">▼</span>`;
        document.getElementById("song-header-stat").innerHTML = `${label} <span class="sort-icon">▼</span>`;
        document.getElementById("country-metric-tag").textContent = label;
        document.getElementById("monthly-metric-tag").textContent = label;
    }

    async function loadAllData() {
        await Promise.all([
            loadStats(),
            loadRankings(),
            loadYears(),
            loadCountryStats(),
            loadHabits(),
        ]);
    }

    async function loadStats() {
        try {
            const res = await fetch(`/api/stats?_t=1${timeQuery()}`);
            state.stats = await res.json();
            renderStats(state.stats);
        } catch (err) {
            console.error("Failed loading stats:", err);
        }
    }

    async function loadRankings() {
        try {
            const isTiered = state.layout === "tiered";
            const tq = timeQuery();
            const [artistsRes, albumsRes, tracksRes] = await Promise.all([
                fetch(`/api/top-artists?limit=${state.limit}&metric=${state.metric}${tq}`),
                fetch(`/api/top-albums?limit=${state.limit}&plus_one=${isTiered ? 1 : 0}&metric=${state.metric}${tq}`),
                fetch(`/api/top-tracks?limit=${state.limit}&metric=${state.metric}${tq}`),
            ]);
            state.topArtists = await artistsRes.json();
            state.topAlbums = await albumsRes.json();
            state.topTracks = await tracksRes.json();

            renderCollage(state.topAlbums);
            renderArtists();
            renderAlbumsList();
            renderSongsList();
        } catch (err) {
            console.error("Failed loading rankings:", err);
        }
    }

    async function loadYears() {
        try {
            const res = await fetch(`/api/release-years?metric=${state.metric}${timeQuery()}`);
            state.releaseYearsData = await res.json();
            renderReleaseYears(state.releaseYearsData);
        } catch (err) {
            console.error("Failed loading release years:", err);
        }
    }

    async function loadCountryStats() {
        try {
            const res = await fetch(`/api/countries?metric=${state.metric}${timeQuery()}`);
            state.countryStats = await res.json();
            if (state.worldCountriesGeo) renderWorldMap(state.countryStats);
            renderCountryTable(state.countryStats);
            if (state.showCountryPie) renderCountryPieChart(state.countryStats);
        } catch (err) {
            console.error("Failed loading country stats:", err);
        }
    }

    async function loadHabits() {
        try {
            const res = await fetch(`/api/habits?_t=1${timeQuery()}`);
            state.habits = await res.json();
            renderHabits(state.habits);
        } catch (err) {
            console.error("Failed loading habits:", err);
        }
    }

    function renderStats(stats) {
        if (!stats) return;
        const isMin = state.metric === "minutes";
        if (isMin) {
            heroStatLabel.textContent = "Total Listening Time";
            statTotalMinutes.textContent = Number(stats.total_minutes).toLocaleString();
            heroStatUnit.textContent = "mins";
            statHoursBreakdown.textContent = `${Number(stats.total_hours).toLocaleString()} hours (${stats.total_days} days)`;
        } else {
            heroStatLabel.textContent = "Total Listens";
            statTotalMinutes.textContent = Number(stats.total_listens).toLocaleString();
            heroStatUnit.textContent = "plays";
            statHoursBreakdown.textContent = `${Number(stats.total_minutes).toLocaleString()} mins (${stats.total_hours} hrs)`;
        }
        statTotalListens.textContent = Number(stats.total_listens).toLocaleString();
        const avgPlays = stats.days_span ? (stats.total_listens / stats.days_span).toFixed(1) : stats.total_listens;
        statDailyAvg.textContent = isMin ? `${stats.avg_daily_minutes} mins/day avg` : `${avgPlays} plays/day avg`;
        statUniqueArtists.textContent = Number(stats.unique_artists).toLocaleString();
        statUniqueAlbums.textContent = Number(stats.unique_albums).toLocaleString();
        statUniqueTracks.textContent = Number(stats.unique_tracks).toLocaleString();
        if (stats.first_listen && stats.last_listen) {
            statListenRange.textContent = `${stats.first_listen.split(" ")[0]} → ${stats.last_listen.split(" ")[0]}`;
        }
    }

    function renderCollage(albums) {
        collageContainer.innerHTML = "";
        if (!albums || albums.length === 0) {
            collageContainer.innerHTML = `<div style="padding:36px;text-align:center;color:#94a3b8;">No album data available for this timeframe.</div>`;
            return;
        }
        if (state.layout === "tiered") {
            collageContainer.className = "collage-grid tiered";
            const t1 = albums.slice(0, 3);
            if (t1.length) {
                const r1 = document.createElement("div");
                r1.className = "collage-tier-row tier-hero";
                t1.forEach(a => r1.appendChild(createCollageItemElement(a, "hero")));
                collageContainer.appendChild(r1);
            }
            const t2 = albums.slice(3, 11);
            if (t2.length) {
                const r2 = document.createElement("div");
                r2.className = "collage-tier-row tier-medium";
                t2.forEach(a => r2.appendChild(createCollageItemElement(a, "medium")));
                collageContainer.appendChild(r2);
            }
            const t3 = albums.slice(11);
            if (t3.length) {
                const r3 = document.createElement("div");
                r3.className = "collage-tier-row tier-compact";
                t3.forEach(a => r3.appendChild(createCollageItemElement(a, "compact")));
                collageContainer.appendChild(r3);
            }
        } else {
            const preset = UNIFORM_PRESETS.find(p => p.v === state.limit);
            const cols = preset ? preset.cols : 5;
            collageContainer.className = "collage-grid uniform";
            collageContainer.style.setProperty("--uniform-cols", String(cols));
            albums.slice(0, state.limit).forEach(a => collageContainer.appendChild(createCollageItemElement(a, "uniform")));
        }
    }

    function createCollageItemElement(album, tierClass) {
        const item = document.createElement("div");
        item.className = `collage-item ${tierClass} ${state.showCaptions ? "" : "hide-captions"}`;
        const imgSrc = album.cover_local_path || album.cover_url || getFallbackAvatar(album.release_name);
        const statLabel = state.metric === "minutes"
            ? `${Number(album.minutes_listened).toLocaleString()} mins (${album.hours_listened}h)`
            : `${album.play_count} listens • ${Math.round(album.minutes_listened)}m`;
        const yearBadge = album.original_release_year ? ` (${album.original_release_year})` : "";
        const flag = flagHtml(album.country_code, album.country_name || "");

        item.innerHTML = `
            <div class="album-rank-badge">#${album.rank}</div>
            <img class="collage-cover-img" src="${escapeHtml(imgSrc)}" alt="${escapeHtml(album.release_name)}" loading="lazy" onerror="this.src='${getFallbackAvatar(album.release_name)}'">
            <div class="collage-caption">
                <div class="album-title-text" title="${escapeHtml(album.release_name)}">${escapeHtml(album.release_name)}${yearBadge}</div>
                <div class="album-artist-row">
                    <span class="album-artist-text" title="${escapeHtml(album.artist_name)}">${escapeHtml(album.artist_name)}</span>
                    ${flag}
                </div>
                <div class="album-stat-text">${statLabel}</div>
            </div>
        `;
        item.addEventListener("click", () => openAlbumDrilldown(album.artist_name, album.release_name));
        return item;
    }

    function sortData(list, sortConfig) {
        return [...list].sort((a, b) => {
            let valA, valB;
            if (sortConfig.col === "rank") { valA = a.rank; valB = b.rank; }
            else if (sortConfig.col === "name") { valA = (a.artist_name || "").toLowerCase(); valB = (b.artist_name || "").toLowerCase(); }
            else if (sortConfig.col === "title") { valA = (a.track_name || a.release_name || "").toLowerCase(); valB = (b.track_name || b.release_name || "").toLowerCase(); }
            else if (sortConfig.col === "artist") { valA = (a.artist_name || "").toLowerCase(); valB = (b.artist_name || "").toLowerCase(); }
            else if (sortConfig.col === "country") { valA = (a.country_name || "").toLowerCase(); valB = (b.country_name || "").toLowerCase(); }
            else if (sortConfig.col === "year") { valA = a.original_release_year || 0; valB = b.original_release_year || 0; }
            else if (sortConfig.col === "duration") { valA = a.duration_seconds || 0; valB = b.duration_seconds || 0; }
            else if (sortConfig.col === "plays") { valA = a.play_count; valB = b.play_count; }
            else if (sortConfig.col === "hours") { valA = a.hours_listened; valB = b.hours_listened; }
            else { valA = a.minutes_listened; valB = b.minutes_listened; }

            if (valA < valB) return sortConfig.dir === "asc" ? -1 : 1;
            if (valA > valB) return sortConfig.dir === "asc" ? 1 : -1;
            return 0;
        });
    }

    function renderArtists() {
        artistsPodium.innerHTML = "";
        artistsContainer.innerHTML = "";
        let list = state.topArtists.filter(a =>
            a.artist_name.toLowerCase().includes(state.artistFilter) ||
            (a.country_name && a.country_name.toLowerCase().includes(state.artistFilter))
        );
        list = sortData(list, state.artistSort);
        if (list.length === 0) {
            artistsContainer.innerHTML = `<div style="padding:20px;text-align:center;color:#94a3b8;">No matching artists found.</div>`;
            return;
        }
        const isMin = state.metric === "minutes";
        const maxStat = Math.max(...state.topArtists.map(a => isMin ? a.minutes_listened : a.play_count), 1);

        const podiumSlice = list.length >= 3 ? list.slice(0, 3) : [];
        const restSlice = list.length >= 3 ? list.slice(3) : list;

        podiumSlice.forEach((artist, idx) => {
            const pos = idx + 1;
            const cur = isMin ? artist.minutes_listened : artist.play_count;
            const pct = Math.max(4, Math.round((cur / maxStat) * 100));
            const avatarSrc = artist.image_local_path || artist.image_url || getFallbackAvatar(artist.artist_name);
            const flag = flagHtml(artist.country_code, artist.country_name || "");
            const primaryTxt = isMin
                ? `${artist.hours_listened} hrs (${Number(artist.minutes_listened).toLocaleString()}m)`
                : `${artist.play_count.toLocaleString()} listens`;
            const subTxt = isMin
                ? `${artist.play_count.toLocaleString()} listens • ${pct}% of #1`
                : `${artist.hours_listened} hrs (${Number(artist.minutes_listened).toLocaleString()}m) • ${pct}% of #1`;

            const card = document.createElement("div");
            card.className = `podium-card podium-${pos}`;
            card.innerHTML = `
                <div class="podium-rank-badge">#${artist.rank}</div>
                <div class="podium-media round">
                    <img src="${escapeHtml(avatarSrc)}" alt="${escapeHtml(artist.artist_name)}" onerror="this.src='${getFallbackAvatar(artist.artist_name)}'">
                </div>
                <div class="podium-title-row">
                    <span class="podium-title-text">${escapeHtml(artist.artist_name)}</span>
                    ${flag}
                </div>
                <div class="podium-subtitle-row">${escapeHtml(artist.country_name || "Unknown Origin")}</div>
                <div class="podium-metric-val">${primaryTxt}</div>
                <div class="podium-metric-sub">${subTxt}</div>
                <div class="podium-bar-track"><div class="podium-bar-fill" style="width:${pct}%"></div></div>
            `;
            card.addEventListener("click", () => openArtistDrilldown(artist.artist_name));
            artistsPodium.appendChild(card);
        });

        restSlice.forEach(artist => {
            const row = document.createElement("div");
            row.className = "wrapped-bar-row";
            const avatarSrc = artist.image_local_path || artist.image_url || getFallbackAvatar(artist.artist_name);
            const cur = isMin ? artist.minutes_listened : artist.play_count;
            const pct = Math.max(2, Math.round((cur / maxStat) * 100));
            const flag = flagHtml(artist.country_code, artist.country_name || "");
            const statVal = isMin ? `${Number(artist.minutes_listened).toLocaleString()} min` : `${artist.play_count.toLocaleString()} listens`;
            const statSub = isMin ? `${artist.hours_listened}h · ${artist.play_count}p` : `${Number(artist.minutes_listened).toLocaleString()} min`;

            row.innerHTML = `
                <div class="row-rank">#${artist.rank}</div>
                <div class="artist-avatar-wrapper">
                    <img src="${escapeHtml(avatarSrc)}" alt="${escapeHtml(artist.artist_name)}" onerror="this.src='${getFallbackAvatar(artist.artist_name)}'">
                </div>
                <div class="row-main-cell">
                    <div class="item-primary-text">
                        <span class="truncate-name">${escapeHtml(artist.artist_name)}</span>
                        ${flag}
                    </div>
                    <div class="item-secondary-text">${escapeHtml(artist.country_name || "Unknown Origin")}</div>
                </div>
                <div class="wrapped-visual-bar-wrap">
                    <div class="wrapped-visual-track"><div class="wrapped-visual-fill" style="width:${pct}%"></div></div>
                    <span class="wrapped-visual-pct">${pct}%</span>
                </div>
                <div class="wrapped-stat-right">
                    <div class="row-stat-val">${statVal}</div>
                    <div class="row-stat-sub">${statSub}</div>
                </div>
            `;
            row.addEventListener("click", () => openArtistDrilldown(artist.artist_name));
            artistsContainer.appendChild(row);
        });
    }

    function renderAlbumsList() {
        albumsContainer.innerHTML = "";
        let list = state.topAlbums.filter(a =>
            a.release_name.toLowerCase().includes(state.albumFilter) ||
            a.artist_name.toLowerCase().includes(state.albumFilter) ||
            (a.original_release_year && a.original_release_year.toString().includes(state.albumFilter))
        );
        list = sortData(list, state.albumSort);
        if (list.length === 0) {
            albumsContainer.innerHTML = `<div style="padding:20px;text-align:center;color:#94a3b8;">No matching albums found.</div>`;
            return;
        }
        list.slice(0, state.limit).forEach(album => {
            const row = document.createElement("div");
            row.className = "leaderboard-row album-row";
            const rankClass = album.rank <= 3 ? `top-${album.rank}` : "";
            const coverSrc = album.cover_local_path || album.cover_url || getFallbackAvatar(album.release_name);
            const statVal = state.metric === "minutes" ? `${Number(album.minutes_listened).toLocaleString()} min` : `${album.play_count} listens`;
            const statSub = state.metric === "minutes" ? `${album.hours_listened} hrs` : `${Number(album.minutes_listened).toLocaleString()} min`;
            const yrText = album.original_release_year ? `<span class="tag-badge">${album.original_release_year}</span>` : `<span class="tag-badge" style="opacity:0.45;">—</span>`;
            const flag = flagHtml(album.country_code, album.country_name || "");

            row.innerHTML = `
                <div class="row-rank ${rankClass}">#${album.rank}</div>
                <div class="album-cover-thumb">
                    <img src="${escapeHtml(coverSrc)}" alt="${escapeHtml(album.release_name)}" onerror="this.src='${getFallbackAvatar(album.release_name)}'">
                </div>
                <div class="row-main-cell">
                    <div class="item-primary-text"><span class="truncate-name">${escapeHtml(album.release_name)}</span></div>
                    <div class="item-secondary-text row-mobile-only">
                        <span>${escapeHtml(album.artist_name)}</span>${flag}
                        ${album.original_release_year ? `<span class="tag-badge">${album.original_release_year}</span>` : ""}
                    </div>
                </div>
                <div class="row-mobile-hide">
                    <div class="item-primary-text" style="font-size:13.5px;font-weight:500;">
                        <span class="truncate-name">${escapeHtml(album.artist_name)}</span>${flag}
                    </div>
                </div>
                <div class="row-mobile-hide">${yrText}</div>
                <div class="row-stat-cell">
                    <div class="row-stat-val">${statVal}</div>
                    <div class="row-stat-sub">${statSub}</div>
                </div>
                <div class="row-plays row-mono-cell row-mobile-hide">${album.play_count}</div>
                <div class="row-hours row-mono-cell row-mobile-hide" style="color:#93c5fd;">${album.hours_listened}h</div>
            `;
            row.addEventListener("click", () => openAlbumDrilldown(album.artist_name, album.release_name));
            albumsContainer.appendChild(row);
        });
    }

    function renderSongsList() {
        songsPodium.innerHTML = "";
        songsContainer.innerHTML = "";
        let list = state.topTracks.filter(s =>
            s.track_name.toLowerCase().includes(state.songFilter) ||
            s.artist_name.toLowerCase().includes(state.songFilter) ||
            s.release_name.toLowerCase().includes(state.songFilter)
        );
        list = sortData(list, state.songSort);
        if (list.length === 0) {
            songsContainer.innerHTML = `<div style="padding:20px;text-align:center;color:#94a3b8;">No matching songs found.</div>`;
            return;
        }
        const isMin = state.metric === "minutes";
        const maxStat = Math.max(...state.topTracks.map(s => isMin ? s.minutes_listened : s.play_count), 1);

        const visible = list.slice(0, state.limit);
        const podiumSlice = visible.length >= 3 ? visible.slice(0, 3) : [];
        const restSlice = visible.length >= 3 ? visible.slice(3) : visible;

        podiumSlice.forEach((song, idx) => {
            const pos = idx + 1;
            const cur = isMin ? song.minutes_listened : song.play_count;
            const pct = Math.max(4, Math.round((cur / maxStat) * 100));
            const coverSrc = song.album_cover_local_path || song.artist_image_local_path || getFallbackAvatar(song.artist_name);
            const flag = flagHtml(song.country_code, song.country_name || "");
            const primaryTxt = isMin ? `${Number(song.minutes_listened).toLocaleString()} mins` : `${song.play_count.toLocaleString()} listens`;
            const subTxt = `${song.duration_formatted} × ${song.play_count} listens • ${pct}% of #1`;

            const card = document.createElement("div");
            card.className = `podium-card podium-${pos}`;
            card.innerHTML = `
                <div class="podium-rank-badge">#${song.rank}</div>
                <div class="podium-media square">
                    <img src="${escapeHtml(coverSrc)}" alt="${escapeHtml(song.track_name)}" onerror="this.src='${getFallbackAvatar(song.artist_name)}'">
                </div>
                <div class="podium-title-row">
                    <span class="podium-title-text" title="${escapeHtml(song.track_name)}">${escapeHtml(song.track_name)}</span>
                </div>
                <div class="podium-subtitle-row">
                    <span class="podium-title-text">${escapeHtml(song.artist_name)}</span>
                    ${flag}
                </div>
                <div class="podium-metric-val">${primaryTxt}</div>
                <div class="podium-metric-sub">${subTxt}</div>
                <div class="podium-bar-track"><div class="podium-bar-fill" style="width:${pct}%"></div></div>
            `;
            card.addEventListener("click", () => {
                if (song.release_name && song.release_name !== "Single / Unknown") {
                    openAlbumDrilldown(song.artist_name, song.release_name);
                } else {
                    openArtistDrilldown(song.artist_name);
                }
            });
            songsPodium.appendChild(card);
        });

        restSlice.forEach(song => {
            const row = document.createElement("div");
            row.className = "wrapped-bar-row";
            const coverSrc = song.album_cover_local_path || song.artist_image_local_path || getFallbackAvatar(song.artist_name);
            const cur = isMin ? song.minutes_listened : song.play_count;
            const pct = Math.max(2, Math.round((cur / maxStat) * 100));
            const flag = flagHtml(song.country_code, song.country_name || "");
            const statVal = isMin ? `${Number(song.minutes_listened).toLocaleString()} min` : `${song.play_count.toLocaleString()} listens`;
            const statSub = isMin ? `${song.duration_formatted} × ${song.play_count}p` : `${Number(song.minutes_listened).toLocaleString()}m (${song.duration_formatted})`;

            row.innerHTML = `
                <div class="row-rank">#${song.rank}</div>
                <div class="album-cover-thumb">
                    <img src="${escapeHtml(coverSrc)}" alt="${escapeHtml(song.track_name)}" onerror="this.src='${getFallbackAvatar(song.artist_name)}'">
                </div>
                <div class="row-main-cell">
                    <div class="item-primary-text"><span class="truncate-name">${escapeHtml(song.track_name)}</span></div>
                    <div class="item-secondary-text">
                        <strong style="color:#e2e8f0;">${escapeHtml(song.artist_name)}</strong>
                        ${flag}
                        <span class="tag-badge">${escapeHtml(song.release_name)}</span>
                    </div>
                </div>
                <div class="wrapped-visual-bar-wrap">
                    <div class="wrapped-visual-track"><div class="wrapped-visual-fill song-fill" style="width:${pct}%"></div></div>
                    <span class="wrapped-visual-pct">${pct}%</span>
                </div>
                <div class="wrapped-stat-right">
                    <div class="row-stat-val">${statVal}</div>
                    <div class="row-stat-sub">${statSub}</div>
                </div>
            `;
            row.addEventListener("click", () => {
                if (song.release_name && song.release_name !== "Single / Unknown") {
                    openAlbumDrilldown(song.artist_name, song.release_name);
                } else {
                    openArtistDrilldown(song.artist_name);
                }
            });
            songsContainer.appendChild(row);
        });
    }

    // =========================================================================
    // RELEASE YEARS (UNBINNED INDIVIDUAL YEARS)
    // =========================================================================
    function getEraColor(year) {
        if (year < 1970) return "var(--era-60s)";
        if (year < 1980) return "var(--era-70s)";
        if (year < 1990) return "var(--era-80s)";
        if (year < 2000) return "var(--era-90s)";
        if (year < 2010) return "var(--era-00s)";
        if (year < 2020) return "var(--era-10s)";
        return "var(--era-20s)";
    }

    function renderReleaseYears(payload) {
        yearsContainer.innerHTML = "";
        yearsLedgerTbody.innerHTML = "";
        if (!payload || !payload.years || payload.years.length === 0) {
            yearsContainer.innerHTML = `<div style="padding:36px;color:#94a3b8;">No release year data available.</div>`;
            return;
        }

        const summary = payload.summary || {};
        const isMin = state.metric === "minutes";

        document.getElementById("yr-kpi-peak").textContent = summary.peak_year
            ? `${summary.peak_year} (${isMin ? `${Math.round(summary.peak_minutes)}m` : `${summary.peak_plays}p`})`
            : "--";
        document.getElementById("yr-kpi-mean").textContent = summary.weighted_avg_year ? `${summary.weighted_avg_year}` : "--";
        const ageEl = document.getElementById("yr-kpi-age");
        const ageSubEl = document.getElementById("yr-kpi-age-sub");
        const ageCardEl = document.getElementById("yr-kpi-age-card");
        if (ageEl) {
            ageEl.textContent = summary.listening_age ? `${summary.listening_age} yrs` : "--";
        }
        if (ageSubEl) {
            ageSubEl.textContent = summary.weighted_avg_year
                ? `From avg. ${summary.weighted_avg_year}`
                : "No release year data";
        }
        if (ageCardEl && summary.weighted_avg_year) {
            ageCardEl.title = `Estimated from weighted average release year (${summary.weighted_avg_year}), assuming formative musical taste peaks around age ${summary.listening_age_anchor || 18}.`;
        }
        document.getElementById("yr-kpi-span").textContent = summary.earliest_year ? `${summary.earliest_year} – ${summary.latest_year}` : "--";
        document.getElementById("yr-kpi-count").textContent = summary.active_years_count ? `${summary.active_years_count} years` : "--";
        document.getElementById("yr-kpi-coverage").textContent = `${summary.coverage_pct || 0}%`;

        const activeYears = payload.years.filter(y => (isMin ? y.minutes_listened : y.play_count) > 0);
        const displayYears = state.yearsMode === "active" ? activeYears : payload.years;

        if (displayYears.length === 0) {
            yearsContainer.innerHTML = `<div style="padding:36px;color:#94a3b8;">No release year listens in this interval.</div>`;
            yearSpotlight.innerHTML = "";
            return;
        }

        const maxVal = Math.max(...displayYears.map(y => isMin ? y.minutes_listened : y.play_count), 1);

        if (!state.selectedYear || !activeYears.some(y => y.year === state.selectedYear)) {
            state.selectedYear = summary.peak_year || (activeYears[activeYears.length - 1] && activeYears[activeYears.length - 1].year);
        }

        displayYears.forEach(yr => {
            const col = document.createElement("div");
            const val = isMin ? yr.minutes_listened : yr.play_count;
            const pct = val > 0 ? Math.max(6, Math.round((val / maxVal) * 100)) : 0;
            const eraColor = getEraColor(yr.year);
            const displayVal = val > 0 ? (isMin ? `${Math.round(yr.minutes_listened)}m` : `${yr.play_count}`) : "";
            const isSelected = yr.year === state.selectedYear;

            col.className = `year-column ${isSelected ? "selected" : ""}`;
            const labelClass = state.yearsMode === "active" ? "year-label rotated" : "year-label";
            const labelText = state.yearsMode === "active"
                ? `${yr.year}`
                : (yr.year % 5 === 0 || yr.year === summary.earliest_year || yr.year === summary.latest_year ? yr.year : "•");

            col.innerHTML = `
                <div class="year-val">${displayVal}</div>
                <div class="year-bar-track">
                    <div class="year-bar" style="height:${pct}%;background:${val > 0 ? eraColor : "transparent"};"></div>
                </div>
                <div class="${labelClass}">${labelText}</div>
            `;

            if (val > 0) {
                col.addEventListener("click", () => {
                    state.selectedYear = yr.year;
                    yearsContainer.querySelectorAll(".year-column").forEach(c => c.classList.remove("selected"));
                    col.classList.add("selected");
                    renderYearSpotlight(yr);
                });

                col.addEventListener("mouseenter", () => {
                    const topAlbsHtml = (yr.top_albums || []).slice(0, 3).map(a => `
                        <div style="font-size:12px;display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:4px;">
                            <span style="color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:190px;">${escapeHtml(a.release_name)} — ${escapeHtml(a.artist_name)}</span>
                            <span style="color:#7dd3fc;font-family:var(--font-mono);font-weight:600;">${isMin ? `${Math.round(a.minutes)}m` : `${a.plays}p`}</span>
                        </div>
                    `).join("");
                    mapTooltip.innerHTML = `
                        <div style="font-size:15px;font-weight:700;color:${eraColor};">Release Year ${yr.year}</div>
                        <div style="margin-top:3px;color:#e2e8f0;font-weight:600;">${Number(yr.minutes_listened).toLocaleString()} mins (${yr.hours_listened}h) • ${yr.play_count} listens</div>
                        <div style="font-size:11.5px;color:#94a3b8;">${yr.share_pct}% share • ${yr.album_count} albums • ${yr.artist_count} artists</div>
                        ${topAlbsHtml ? `<div style="margin-top:8px;border-top:1px solid rgba(255,255,255,0.12);padding-top:6px;">${topAlbsHtml}</div>` : ""}
                    `;
                    mapTooltip.style.display = "block";
                });
                col.addEventListener("mousemove", e => positionTooltip(e.clientX, e.clientY));
                col.addEventListener("mouseleave", () => { mapTooltip.style.display = "none"; });
            }
            yearsContainer.appendChild(col);
        });

        const spotObj = activeYears.find(y => y.year === state.selectedYear) || activeYears[0];
        if (spotObj) renderYearSpotlight(spotObj);

        // Unbinned Individual Year Ledger Table (newest first or sorted by year descending)
        const ledgerRows = [...activeYears].sort((a, b) => b.year - a.year);
        yearsLedgerTbody.innerHTML = ledgerRows.map(yr => {
            const topChips = (yr.top_albums || []).slice(0, 3).map(a => `
                <span class="mini-release-tag" data-artist="${encodeURIComponent(a.artist_name)}" data-release="${encodeURIComponent(a.release_name)}" title="${escapeHtml(a.artist_name)} — ${escapeHtml(a.release_name)}">
                    ${a.cover_local_path ? `<img src="${escapeHtml(a.cover_local_path)}" alt="">` : ""}
                    <span>${escapeHtml(a.release_name)}</span>
                </span>
            `).join("");
            return `
                <tr>
                    <td><strong style="color:${getEraColor(yr.year)};font-family:var(--font-mono);">${yr.year}</strong></td>
                    <td class="text-right num">${Number(yr.minutes_listened).toLocaleString()}m <span style="color:var(--text-muted);font-size:11.5px;">(${yr.hours_listened}h)</span></td>
                    <td class="text-right num">${yr.play_count.toLocaleString()}</td>
                    <td class="text-right num">
                        <span class="inline-share-bar">
                            <span>${yr.share_pct}%</span>
                            <span class="inline-share-track"><span class="inline-share-fill" style="width:${Math.min(100, yr.share_pct * 3)}%;background:${getEraColor(yr.year)};"></span></span>
                        </span>
                    </td>
                    <td class="text-right num">${yr.album_count}</td>
                    <td><div class="mini-releases-strip">${topChips}</div></td>
                </tr>
            `;
        }).join("");

        yearsLedgerTbody.querySelectorAll(".mini-release-tag").forEach(tag => {
            tag.addEventListener("click", () => {
                openAlbumDrilldown(decodeURIComponent(tag.getAttribute("data-artist")), decodeURIComponent(tag.getAttribute("data-release")));
            });
        });
    }

    function renderYearSpotlight(yr) {
        if (!yr) {
            yearSpotlight.innerHTML = "";
            return;
        }
        const chips = (yr.top_albums || []).map(a => `
            <div class="spotlight-album-chip" data-artist="${encodeURIComponent(a.artist_name)}" data-release="${encodeURIComponent(a.release_name)}">
                <img src="${escapeHtml(a.cover_local_path || getFallbackAvatar(a.release_name))}" alt="">
                <div class="spotlight-album-info">
                    <strong>${escapeHtml(a.release_name)}</strong>
                    <span>${escapeHtml(a.artist_name)} • ${Math.round(a.minutes)}m (${a.plays}p)</span>
                </div>
            </div>
        `).join("");

        yearSpotlight.innerHTML = `
            <div class="year-spotlight-meta">
                <h4>Release Year ${yr.year}</h4>
                <p>${Number(yr.minutes_listened).toLocaleString()} mins (${yr.hours_listened} hrs) • ${yr.play_count} listens • ${yr.share_pct}% of year-tagged listening • ${yr.album_count} albums</p>
            </div>
            <div class="year-spotlight-albums">${chips}</div>
        `;
        yearSpotlight.querySelectorAll(".spotlight-album-chip").forEach(el => {
            el.addEventListener("click", () => {
                openAlbumDrilldown(decodeURIComponent(el.getAttribute("data-artist")), decodeURIComponent(el.getAttribute("data-release")));
            });
        });
    }

    // =========================================================================
    // WORLD MAP, TOP X COUNTRY TABLE & OPTIONAL PIE CHART
    // =========================================================================
    function getMapBrackets(countries) {
        if (state.mapRankBy === "artists") {
            return [
                { min: 50,  label: "50+ artists",   color: "#f59e0b" },
                { min: 20,  label: "20 – 49",       color: "#ec4899" },
                { min: 10,  label: "10 – 19",       color: "#a855f7" },
                { min: 5,   label: "5 – 9",         color: "#3b82f6" },
                { min: 2,   label: "2 – 4",         color: "#06b6d4" },
                { min: 1,   label: "1 artist",      color: "#10b981" },
            ];
        }
        const vals = (countries || []).map(c => state.metric === "minutes" ? c.minutes_listened : c.play_count);
        const maxVal = Math.max(...vals, 1);
        if (state.metric === "plays") {
            if (maxVal < 500) {
                return [
                    { min: Math.ceil(maxVal * 0.55), label: `${Math.ceil(maxVal * 0.55)}+ listens`, color: "#f59e0b" },
                    { min: Math.ceil(maxVal * 0.25), label: `${Math.ceil(maxVal * 0.25)}+`,         color: "#ec4899" },
                    { min: Math.ceil(maxVal * 0.10), label: `${Math.ceil(maxVal * 0.10)}+`,         color: "#a855f7" },
                    { min: 10,  label: "10+",       color: "#3b82f6" },
                    { min: 3,   label: "3 – 9",     color: "#06b6d4" },
                    { min: 1,   label: "1 – 2",     color: "#0f766e" },
                ];
            }
            return [
                { min: 1500, label: "1,500+ listens", color: "#f59e0b" },
                { min: 500,  label: "500 – 1,499",    color: "#ec4899" },
                { min: 150,  label: "150 – 499",      color: "#a855f7" },
                { min: 50,   label: "50 – 149",       color: "#3b82f6" },
                { min: 15,   label: "15 – 49",        color: "#06b6d4" },
                { min: 1,    label: "1 – 14 listens", color: "#0f766e" },
            ];
        }
        return [
            { min: 5000, label: "5,000+ mins (83h+)", color: "#f59e0b" },
            { min: 1500, label: "1,500 – 5,000m",     color: "#ec4899" },
            { min: 500,  label: "500 – 1,500m",       color: "#a855f7" },
            { min: 150,  label: "150 – 500m",         color: "#3b82f6" },
            { min: 30,   label: "30 – 150m",          color: "#06b6d4" },
            { min: 1,    label: "1 – 30m",            color: "#0f766e" },
        ];
    }

    function getChoroplethColor(value, brackets) {
        if (!value || value <= 0) {
            return { fill: "#1e293b", opacity: 0.55 };
        }
        for (const b of brackets) {
            if (value >= b.min) {
                return { fill: b.color, opacity: 0.92 };
            }
        }
        return { fill: "#0f766e", opacity: 0.85 };
    }

    function renderWorldMap(countries) {
        if (!state.worldCountriesGeo) return;
        const countryDataMap = {};
        countries.forEach(c => { countryDataMap[c.country_code] = c; });
        const brackets = getMapBrackets(countries);

        let svgHtml = `<svg viewBox="0 0 1000 500" class="world-svg-root" xmlns="http://www.w3.org/2000/svg">
            <rect width="1000" height="500" fill="#070b14" rx="10"/>
            <path d="M 0 125 L 1000 125 M 0 250 L 1000 250 M 0 375 L 1000 375" stroke="rgba(255,255,255,0.03)" stroke-width="1"/>
            <path d="M 250 0 L 250 500 M 500 0 L 500 500 M 750 0 L 750 500" stroke="rgba(255,255,255,0.03)" stroke-width="1"/>
        `;

        for (const [code, geo] of Object.entries(state.worldCountriesGeo)) {
            const data = countryDataMap[code];
            const val = data
                ? (state.mapRankBy === "artists" ? data.artist_count : (state.metric === "minutes" ? data.minutes_listened : data.play_count))
                : 0;
            const { fill, opacity } = getChoroplethColor(val, brackets);
            svgHtml += `<path d="${geo.path}" class="country-vector-path ${data ? "has-data" : ""}" data-code="${escapeHtml(code)}" data-name="${escapeHtml(geo.name || code)}" fill="${fill}" fill-opacity="${opacity}" stroke="rgba(255,255,255,0.14)" stroke-width="0.5"/>`;
        }
        svgHtml += `</svg>`;
        worldMapContainer.innerHTML = svgHtml;

        const legendEl = document.getElementById("map-legend-overlay");
        legendEl.innerHTML = [...brackets].reverse().map(b => `
            <div class="legend-scale-row">
                <span class="legend-color-box" style="background:${b.color}"></span>
                <span class="legend-scale-text">${escapeHtml(b.label)}</span>
            </div>
        `).join("") + `<div class="legend-scale-row"><span class="legend-color-box" style="background:#1e293b"></span><span class="legend-scale-text">No listens</span></div>`;

        document.querySelectorAll(".country-vector-path").forEach(pathEl => {
            const code = pathEl.getAttribute("data-code");
            const geoName = pathEl.getAttribute("data-name");
            const data = countryDataMap[code];

            const showTip = e => {
                const flag = flagHtml(code, (data && data.country_name) || geoName, true);
                if (!data) {
                    mapTooltip.innerHTML = `
                        <div style="font-size:14px;font-weight:700;display:flex;align-items:center;gap:7px;">
                            ${flag}<span>${escapeHtml(geoName)}</span>
                        </div>
                        <div style="color:#94a3b8;margin-top:2px;">0 listens recorded</div>
                    `;
                } else {
                    const artistsHtml = (data.top_artists || []).slice(0, 4).map(a => `
                        <div style="display:flex;align-items:center;justify-content:space-between;margin-top:5px;gap:8px;">
                            <div style="display:flex;align-items:center;gap:6px;min-width:0;">
                                <img src="${escapeHtml(a.image_local_path || getFallbackAvatar(a.artist_name))}" style="width:20px;height:20px;border-radius:50%;object-fit:cover;" alt="" onerror="this.src='${getFallbackAvatar(a.artist_name)}'">
                                <span style="color:#fff;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:145px;">${escapeHtml(a.artist_name)}</span>
                            </div>
                            <span style="color:#7dd3fc;font-family:var(--font-mono);font-size:11px;">${Math.round(a.minutes)}m (${a.plays}p)</span>
                        </div>
                    `).join("");
                    mapTooltip.innerHTML = `
                        <div style="font-size:15px;font-weight:700;display:flex;align-items:center;gap:8px;">
                            ${flag}
                            <span>#${data.rank} ${escapeHtml(data.country_name)}</span>
                        </div>
                        <div style="margin-top:4px;color:#e2e8f0;font-weight:600;">
                            ${Number(data.minutes_listened).toLocaleString()} mins (${data.hours_listened}h) • ${data.play_count.toLocaleString()} listens
                        </div>
                        <div style="font-size:11.5px;color:#94a3b8;">${data.share_pct}% share • ${data.artist_count} unique artists</div>
                        ${artistsHtml ? `<div style="margin-top:8px;border-top:1px solid rgba(255,255,255,0.12);padding-top:6px;">${artistsHtml}</div>` : ""}
                    `;
                }
                mapTooltip.style.display = "block";
                if (e && e.clientX !== undefined) positionTooltip(e.clientX, e.clientY);
            };

            pathEl.addEventListener("mouseenter", showTip);
            pathEl.addEventListener("mousemove", e => positionTooltip(e.clientX, e.clientY));
            pathEl.addEventListener("click", showTip);
            pathEl.addEventListener("mouseleave", () => { mapTooltip.style.display = "none"; });
        });
    }

    function renderCountryTable(countries) {
        if (!countries || countries.length === 0) {
            countryTableHeading.textContent = "Top Countries";
            countryTableTbody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:#94a3b8;padding:24px;">No country statistics available.</td></tr>`;
            return;
        }
        const topX = state.countryTopX >= 999 ? countries.length : Math.min(state.countryTopX, countries.length);
        countryTableHeading.textContent = state.countryTopX >= 999 ? `All Countries (${countries.length})` : `Top ${topX} Countries`;

        const slice = countries.slice(0, topX);
        countryTableTbody.innerHTML = slice.map((c, idx) => {
            const flag = flagHtml(c.country_code, c.country_name);
            const lead = (c.top_artists && c.top_artists[0]) ? c.top_artists[0].artist_name : "—";
            const color = PIE_COLORS[idx % PIE_COLORS.length];
            return `
                <tr class="clickable-row" data-code="${escapeHtml(c.country_code)}">
                    <td class="num"><strong>#${c.rank}</strong></td>
                    <td>
                        <div class="country-cell">
                            ${flag}
                            <span>${escapeHtml(c.country_name)}</span>
                        </div>
                    </td>
                    <td class="text-right num">${Number(c.minutes_listened).toLocaleString()}m <span style="color:var(--text-muted);font-size:11.5px;">(${c.hours_listened}h)</span></td>
                    <td class="text-right num">${c.play_count.toLocaleString()}</td>
                    <td class="text-right num">${c.artist_count}</td>
                    <td class="text-right num">
                        <span class="inline-share-bar">
                            <span>${c.share_pct}%</span>
                            <span class="inline-share-track"><span class="inline-share-fill" style="width:${Math.min(100, c.share_pct)}%;background:${color};"></span></span>
                        </span>
                    </td>
                    <td>${escapeHtml(lead)}</td>
                </tr>
            `;
        }).join("");

        countryTableTbody.querySelectorAll("tr[data-code]").forEach(row => {
            row.addEventListener("click", () => {
                const code = row.getAttribute("data-code");
                document.querySelectorAll(".country-vector-path.highlighted").forEach(p => p.classList.remove("highlighted"));
                const targetPath = document.querySelector(`.country-vector-path[data-code="${code}"]`);
                if (targetPath) {
                    targetPath.classList.add("highlighted");
                    targetPath.scrollIntoView({ behavior: "smooth", block: "center" });
                }
            });
        });
    }

    function renderCountryPieChart(countries) {
        if (!countries || countries.length === 0) {
            countryPieContainer.innerHTML = `<div style="color:#94a3b8;padding:24px;">No country data for pie chart.</div>`;
            return;
        }
        const isMin = state.metric === "minutes";
        const isArtistsPie = state.mapRankBy === "artists";
        const pieTagEl = document.getElementById("country-pie-tag");
        if (pieTagEl) {
            pieTagEl.textContent = isArtistsPie ? "Artist Count" : (isMin ? "Listen Time" : "No. of Listens");
        }
        const topX = state.countryTopX >= 999 ? Math.min(12, countries.length) : Math.min(state.countryTopX, countries.length);
        const topSlice = countries.slice(0, topX);
        const restSlice = countries.slice(topX);

        const getVal = c => (isArtistsPie ? c.artist_count : (isMin ? c.minutes_listened : c.play_count));
        const totalVal = countries.reduce((acc, c) => acc + getVal(c), 0) || 1;
        const segments = topSlice.map((c, idx) => {
            const val = getVal(c);
            return {
                label: c.country_name,
                code: c.country_code,
                val,
                pct: (val / totalVal) * 100,
                color: PIE_COLORS[idx % PIE_COLORS.length],
            };
        });

        const restVal = restSlice.reduce((acc, c) => acc + getVal(c), 0);
        if (restVal > 0) {
            segments.push({
                label: `Other (${restSlice.length} countries)`,
                code: "XX",
                val: restVal,
                pct: (restVal / totalVal) * 100,
                color: "#475569",
            });
        }

        const cx = 110, cy = 110, rOuter = 96, rInner = 52;
        let angle = -Math.PI / 2;
        const paths = segments.map((seg, idx) => {
            const frac = seg.val / totalVal;
            const sweep = frac * Math.PI * 2;
            const endAngle = angle + sweep;
            const largeArc = sweep > Math.PI ? 1 : 0;

            if (frac >= 0.999) {
                const circle = `<circle cx="${cx}" cy="${cy}" r="${rOuter}" fill="${seg.color}" class="pie-slice" data-idx="${idx}"/><circle cx="${cx}" cy="${cy}" r="${rInner}" fill="var(--bg-card)"/>`;
                angle = endAngle;
                return circle;
            }

            const x1 = cx + rOuter * Math.cos(angle);
            const y1 = cy + rOuter * Math.sin(angle);
            const x2 = cx + rOuter * Math.cos(endAngle);
            const y2 = cy + rOuter * Math.sin(endAngle);
            const x3 = cx + rInner * Math.cos(endAngle);
            const y3 = cy + rInner * Math.sin(endAngle);
            const x4 = cx + rInner * Math.cos(angle);
            const y4 = cy + rInner * Math.sin(angle);

            const d = [
                `M ${x1.toFixed(2)} ${y1.toFixed(2)}`,
                `A ${rOuter} ${rOuter} 0 ${largeArc} 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`,
                `L ${x3.toFixed(2)} ${y3.toFixed(2)}`,
                `A ${rInner} ${rInner} 0 ${largeArc} 0 ${x4.toFixed(2)} ${y4.toFixed(2)}`,
                "Z",
            ].join(" ");
            angle = endAngle;
            return `<path d="${d}" fill="${seg.color}" stroke="#090d16" stroke-width="1.5" class="pie-slice" data-idx="${idx}"/>`;
        }).join("");

        const centerText = isArtistsPie
            ? `${totalVal.toLocaleString()}`
            : (isMin ? `${Math.round(totalVal / 60)}h` : `${totalVal.toLocaleString()}`);
        const centerSub = isArtistsPie ? "artists" : (isMin ? "attributed" : "listens");
        const unitSuffix = isArtistsPie ? "a" : (isMin ? "m" : "p");

        const legendHtml = segments.map(seg => `
            <div class="pie-legend-item">
                <div class="pie-legend-left">
                    <span class="pie-swatch" style="background:${seg.color};"></span>
                    ${seg.code !== "XX" ? flagHtml(seg.code, seg.label) : ""}
                    <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(seg.label)}</span>
                </div>
                <div class="pie-legend-val">${seg.pct.toFixed(1)}% (${Math.round(seg.val)}${unitSuffix})</div>
            </div>
        `).join("");

        countryPieContainer.innerHTML = `
            <svg viewBox="0 0 220 220" class="pie-svg">
                ${paths}
                <text x="${cx}" y="${cy - 4}" text-anchor="middle" fill="#f8fafc" font-family="var(--font-display)" font-size="18" font-weight="700">${centerText}</text>
                <text x="${cx}" y="${cy + 14}" text-anchor="middle" fill="#94a3b8" font-size="11">${centerSub}</text>
            </svg>
            <div class="pie-legend">${legendHtml}</div>
        `;

        countryPieContainer.querySelectorAll(".pie-slice").forEach(el => {
            const seg = segments[parseInt(el.getAttribute("data-idx"), 10)];
            if (!seg) return;
            el.addEventListener("mouseenter", () => {
                const tipMetric = isArtistsPie
                    ? `${seg.val.toLocaleString()} artists`
                    : (isMin ? `${Math.round(seg.val).toLocaleString()} mins` : `${seg.val.toLocaleString()} listens`);
                mapTooltip.innerHTML = `
                    <div style="font-weight:700;display:flex;align-items:center;gap:6px;">
                        ${seg.code !== "XX" ? flagHtml(seg.code, seg.label) : ""}
                        <span>${escapeHtml(seg.label)}</span>
                    </div>
                    <div style="margin-top:3px;color:#7dd3fc;font-family:var(--font-mono);">${seg.pct.toFixed(1)}% • ${tipMetric}</div>
                `;
                mapTooltip.style.display = "block";
            });
            el.addEventListener("mousemove", e => positionTooltip(e.clientX, e.clientY));
            el.addEventListener("mouseleave", () => { mapTooltip.style.display = "none"; });
        });
    }

    // =========================================================================
    // HABITS & ANALYTICS (Metric-aware!)
    // =========================================================================
    function renderHabits(habits) {
        if (!habits) return;
        const isMin = state.metric === "minutes";

        const hourlyContainer = document.getElementById("hourly-bars");
        hourlyContainer.innerHTML = "";
        const maxHourly = Math.max(...Object.values(habits.hourly).map(h => isMin ? h.minutes_listened : h.play_count), 1);

        for (let hour = 0; hour < 24; hour++) {
            const hData = habits.hourly[hour] || { minutes_listened: 0, play_count: 0 };
            const val = isMin ? hData.minutes_listened : hData.play_count;
            const pct = Math.round((val / maxHourly) * 100);
            const row = document.createElement("div");
            row.className = "chart-row";
            row.innerHTML = `
                <div class="chart-row-label">${hour.toString().padStart(2, "0")}:00</div>
                <div class="chart-row-bar-track"><div class="chart-row-bar-fill" style="width:${pct}%;"></div></div>
                <div class="chart-row-val num">${isMin ? `${Math.round(val)}m` : `${val}p`}</div>
            `;
            hourlyContainer.appendChild(row);
        }

        const dowContainer = document.getElementById("dow-bars");
        dowContainer.innerHTML = "";
        const maxDow = Math.max(...Object.values(habits.day_of_week).map(d => isMin ? d.minutes_listened : d.play_count), 1);

        for (let i = 0; i < 7; i++) {
            const dData = habits.day_of_week[i];
            const val = isMin ? dData.minutes_listened : dData.play_count;
            const pct = Math.round((val / maxDow) * 100);
            const col = document.createElement("div");
            col.className = "v-bar-col";
            col.innerHTML = `
                <div class="v-bar-val num">${isMin ? `${Math.round(val)}m` : `${val}p`}</div>
                <div class="v-bar-track"><div class="v-bar-fill" style="height:${pct}%;"></div></div>
                <div class="v-bar-label">${dData.day_name.substring(0, 3)}</div>
            `;
            dowContainer.appendChild(col);
        }

        const monthlyContainer = document.getElementById("monthly-bars");
        monthlyContainer.innerHTML = "";
        const maxMonthly = Math.max(...habits.monthly.map(m => isMin ? m.minutes_listened : m.play_count), 1);

        habits.monthly.forEach(m => {
            const val = isMin ? m.minutes_listened : m.play_count;
            const pct = Math.round((val / maxMonthly) * 100);
            const col = document.createElement("div");
            col.className = "v-bar-col";
            col.innerHTML = `
                <div class="v-bar-val num">${isMin ? `${Math.round(val)}m` : `${val}p`}</div>
                <div class="v-bar-track" style="height:140px;"><div class="v-bar-fill" style="height:${pct}%;"></div></div>
                <div class="v-bar-label">${escapeHtml(m.month)}</div>
            `;
            monthlyContainer.appendChild(col);
        });
    }
});
