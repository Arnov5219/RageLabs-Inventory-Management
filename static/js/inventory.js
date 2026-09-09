// ==============================================================
// LAUNDRYRAGE INVENTORY MANAGEMENT — PRODUCTION CLIENT CORE
// Features: Offline sync, Conflict protection, Live sync status,
//           Confirmation dialogs, Search/Filters, Monitoring
// ==============================================================

// ── CSRF Helper ───────────────────────────────────────────────
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

// ── Toast Notification System (Debounced & Actionable) ────────
const _recentToasts = new Map();

function showToast(message, type = 'success', options = {}) {
    const container = document.querySelector('.toast-container');
    if (!container) return;

    // Suppress duplicate toasts within 2.5 seconds
    const now = Date.now();
    if (_recentToasts.has(message) && (now - _recentToasts.get(message)) < 2500) {
        return;
    }
    _recentToasts.set(message, now);

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;

    const icon = document.createElement('span');
    icon.className = 'toast-icon';
    if (type === 'success') icon.innerHTML = '✓';
    else if (type === 'error') icon.innerHTML = '✕';
    else if (type === 'warning') icon.innerHTML = '⚠';
    else icon.innerHTML = 'ℹ';

    const msg = document.createElement('span');
    msg.className = 'toast-message';
    msg.innerText = message;

    toast.appendChild(icon);
    toast.appendChild(msg);

    // Optional Retry Action Button
    if (options.retryCallback && typeof options.retryCallback === 'function') {
        const retryBtn = document.createElement('button');
        retryBtn.className = 'toast-retry-btn';
        retryBtn.innerText = 'Retry';
        retryBtn.onclick = (e) => {
            e.stopPropagation();
            toast.remove();
            options.retryCallback();
        };
        toast.appendChild(retryBtn);
    }

    container.appendChild(toast);

    setTimeout(() => { toast.classList.add('show'); }, 10);

    const autoDismiss = setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => { toast.remove(); }, 300);
    }, options.duration || 4500);

    toast.addEventListener('click', () => {
        clearTimeout(autoDismiss);
        toast.classList.remove('show');
        setTimeout(() => { toast.remove(); }, 200);
    });
}

// ── Confirmation Dialog Manager (Feature 7) ───────────────────
const ConfirmDialog = {
    modal: null,
    titleEl: null,
    msgEl: null,
    currEl: null,
    newEl: null,
    proceedBtn: null,
    cancelBtn: null,
    closeBtn: null,
    resolver: null,

    init() {
        this.modal = document.getElementById('confirm-dialog-modal');
        if (!this.modal) return;
        this.titleEl = document.getElementById('confirm-dialog-title');
        this.msgEl = document.getElementById('confirm-dialog-msg');
        this.currEl = document.getElementById('confirm-dialog-curr');
        this.newEl = document.getElementById('confirm-dialog-new');
        this.proceedBtn = document.getElementById('confirm-dialog-proceed');
        this.cancelBtn = document.getElementById('confirm-dialog-cancel');
        this.closeBtn = document.getElementById('confirm-dialog-close');

        const closeHandler = () => this.close(false);
        if (this.cancelBtn) this.cancelBtn.addEventListener('click', closeHandler);
        if (this.closeBtn) this.closeBtn.addEventListener('click', closeHandler);
        this.modal.addEventListener('click', (e) => {
            if (e.target === this.modal) closeHandler();
        });

        if (this.proceedBtn) {
            this.proceedBtn.addEventListener('click', () => {
                this.close(true);
            });
        }
    },

    ask({ title, message, currentStock, newStock, confirmText = 'Confirm', isDanger = true }) {
        return new Promise((resolve) => {
            if (!this.modal) {
                // Fallback to native confirm if modal element not found
                return resolve(window.confirm(`${title}\n\n${message}`));
            }
            this.resolver = resolve;
            if (this.titleEl) this.titleEl.innerText = title;
            if (this.msgEl) this.msgEl.innerText = message;
            if (this.currEl) this.currEl.innerText = currentStock;
            if (this.newEl) this.newEl.innerText = newStock;
            if (this.proceedBtn) {
                this.proceedBtn.innerText = confirmText;
                this.proceedBtn.style.background = isDanger ? '#DC2626' : '#0F172A';
                this.proceedBtn.style.borderColor = isDanger ? '#DC2626' : '#0F172A';
            }
            this.modal.style.display = 'flex';
            this.modal.classList.add('active');
        });
    },

    close(confirmed) {
        if (this.modal) {
            this.modal.classList.remove('active');
            this.modal.style.display = 'none';
        }
        if (this.resolver) {
            this.resolver(confirmed);
            this.resolver = null;
        }
    }
};

// ── Network & Offline Queue Manager (Features 1 & 5) ──────────
const NetworkManager = {
    isOnline: navigator.onLine,
    queueKey: 'lr_offline_stock_queue',
    syncIndicator: null,
    offlineBanner: null,
    isSyncing: false,

    init() {
        this.syncIndicator = document.getElementById('sync-status-indicator');
        this.offlineBanner = document.getElementById('global-offline-banner');

        window.addEventListener('online', () => this.handleNetworkChange(true));
        window.addEventListener('offline', () => this.handleNetworkChange(false));

        if (this.syncIndicator) {
            this.syncIndicator.addEventListener('click', () => {
                if (this.getQueue().length > 0 && this.isOnline && !this.isSyncing) {
                    this.drainQueue();
                }
            });
        }

        this.updateUI();

        // Periodic health check heartbeat every 35s
        setInterval(() => this.checkConnectivity(), 35000);

        // If online at start and items in queue, attempt drain
        if (this.isOnline && this.getQueue().length > 0) {
            this.drainQueue();
        }
    },

    async checkConnectivity() {
        try {
            const res = await fetch('/api/health/', { method: 'GET', cache: 'no-store' });
            if (res.ok) {
                if (!this.isOnline) this.handleNetworkChange(true);
            } else {
                if (this.isOnline) this.handleNetworkChange(false);
            }
        } catch (e) {
            if (this.isOnline) this.handleNetworkChange(false);
        }
    },

    handleNetworkChange(onlineState) {
        const wasOffline = !this.isOnline && onlineState;
        this.isOnline = onlineState;
        this.updateUI();

        if (wasOffline) {
            showToast('✓ Connection restored. Syncing pending changes...', 'success');
            this.drainQueue();
        } else if (!onlineState) {
            showToast("You're Offline. Changes will sync when reconnected.", 'warning');
        }
    },

    updateUI() {
        const queue = this.getQueue();
        if (this.offlineBanner) {
            this.offlineBanner.style.display = this.isOnline ? 'none' : 'block';
        }

        if (!this.syncIndicator) return;
        this.syncIndicator.className = 'sync-status-indicator';

        if (!this.isOnline) {
            this.syncIndicator.classList.add('sync-offline');
            this.syncIndicator.querySelector('.sync-text').innerText = 'Offline';
            this.syncIndicator.title = 'Offline — actions are queued locally';
        } else if (this.isSyncing) {
            this.syncIndicator.classList.add('sync-syncing');
            this.syncIndicator.querySelector('.sync-text').innerText = 'Syncing...';
            this.syncIndicator.title = 'Syncing pending inventory adjustments';
        } else if (queue.length > 0) {
            this.syncIndicator.classList.add('sync-pending');
            this.syncIndicator.querySelector('.sync-text').innerText = `${queue.length} Pending`;
            this.syncIndicator.title = `${queue.length} change(s) waiting to sync. Click to retry.`;
        } else {
            this.syncIndicator.classList.add('sync-live');
            this.syncIndicator.querySelector('.sync-text').innerText = 'Live Synced';
            this.syncIndicator.title = 'All inventory data is up to date';
        }
    },

    getQueue() {
        try {
            return JSON.parse(localStorage.getItem(this.queueKey) || '[]');
        } catch {
            return [];
        }
    },

    saveQueue(queue) {
        localStorage.setItem(this.queueKey, JSON.stringify(queue));
        this.updateUI();
    },

    enqueue(item) {
        const queue = this.getQueue();
        queue.push({
            id: 'q_' + Date.now() + '_' + Math.random().toString(36).substr(2, 4),
            timestamp: Date.now(),
            ...item
        });
        this.saveQueue(queue);

        // Visually mark affected card
        const card = document.querySelector(`.product-card[data-product-id="${item.product_id}"]`);
        if (card) {
            card.classList.add('is-queued');
            let badge = card.querySelector('.queued-badge-label');
            if (!badge) {
                badge = document.createElement('span');
                badge.className = 'queued-badge-label';
                badge.innerText = '⏳ Queued';
                const headerBlock = card.querySelector('.product-header-block');
                if (headerBlock) headerBlock.appendChild(badge);
            }
        }

        showToast("⚠ You're offline. Update queued to sync automatically.", 'warning');
    },

    async drainQueue() {
        const queue = this.getQueue();
        if (queue.length === 0 || this.isSyncing || !this.isOnline) return;

        this.isSyncing = true;
        this.updateUI();

        try {
            const response = await fetch('/stock/sync-queue/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCookie('csrftoken')
                },
                body: JSON.stringify({ items: queue })
            });

            const data = await response.json();
            if (response.ok && data.success) {
                // Remove queued indicators
                document.querySelectorAll('.product-card.is-queued').forEach(card => {
                    card.classList.remove('is-queued');
                    const badge = card.querySelector('.queued-badge-label');
                    if (badge) badge.remove();
                });

                // Clear queue
                this.saveQueue([]);
                showToast('✓ All changes synced successfully.', 'success');
            } else {
                this.syncIndicator.classList.remove('sync-syncing');
                this.syncIndicator.classList.add('sync-failed');
                this.syncIndicator.querySelector('.sync-text').innerText = 'Sync Failed';
                showToast('Unable to complete queue sync. Will retry automatically.', 'warning');
            }
        } catch (err) {
            console.error('Queue sync error:', err);
            this.syncIndicator.classList.remove('sync-syncing');
            this.syncIndicator.classList.add('sync-failed');
            this.syncIndicator.querySelector('.sync-text').innerText = 'Sync Failed';
        } finally {
            this.isSyncing = false;
            this.updateUI();
        }
    }
};

// ── Low Stock Alert Tracker (Feature 14 — prevents spam + Android Native Notification) ──────
const LowStockTracker = {
    history: new Set(),

    notify(alert) {
        if (!alert || !alert.product_name) return;
        const key = `${alert.product_id}_${alert.current_stock}`;
        if (this.history.has(key)) return;
        this.history.add(key);

        const title = `🚨 Low Stock: ${alert.product_name}`;
        const msg = `${alert.product_name} is low on stock (${alert.current_stock} / ${alert.threshold} ${alert.unit} remaining).`;

        showToast(
            `🚨 Low Stock Alert: ${alert.product_name} is below minimum (${alert.current_stock} / ${alert.threshold} ${alert.unit})`,
            'error',
            { duration: 6000 }
        );

        // Native Android Notification via Capacitor
        if (window.Capacitor && window.Capacitor.isPluginAvailable && window.Capacitor.isPluginAvailable('LocalNotifications')) {
            try {
                window.Capacitor.Plugins.LocalNotifications.schedule({
                    notifications: [
                        {
                            title: title,
                            body: msg,
                            id: Math.floor(Math.random() * 1000000),
                            schedule: { at: new Date(Date.now() + 200) },
                            sound: null,
                            actionTypeId: '',
                            extra: null
                        }
                    ]
                });
            } catch (err) {
                console.debug('Capacitor native notification note:', err);
            }
        }
    }
};

// ── Card Stock Display Updater ────────────────────────────────
function updateCardStockDisplay(card, newQuantity, remainingPercentage, status, baseStock, unit) {
    const badge = card.querySelector('.stock-badge');
    const pctEl = card.querySelector('.percentage-remaining');
    const pillVal = card.querySelector('.pill-value');
    const pillInput = card.querySelector('.pill-value-input');
    const bullet = card.querySelector('.stock-bullet');
    const roundedQty = parseFloat(newQuantity).toFixed(0);
    const roundedBase = parseFloat(baseStock || 0).toFixed(0);

    card.dataset.currentStock = roundedQty;
    card.dataset.productStatus = status;

    if (badge) {
        badge.className = 'stock-badge';
        if (status === 'RED') {
            badge.classList.add('low');
            badge.innerText = 'LOW';
        } else if (status === 'YELLOW') {
            badge.classList.add('mod');
            badge.innerText = 'MODERATE';
        } else if (status === 'GREEN') {
            badge.classList.add('suff');
            badge.innerText = 'SUFFICIENT';
        } else {
            badge.classList.add('no-base');
            badge.innerText = 'NO BASE';
        }
    }

    if (bullet) {
        if (status === 'RED') bullet.innerText = '🔴';
        else if (status === 'YELLOW') bullet.innerText = '🟡';
        else if (status === 'GREEN') bullet.innerText = '🟢';
        else bullet.innerText = '⚪';
    }

    const qtySpan = card.querySelector('.product-info-area span:not(.stock-bullet)');
    if (qtySpan) {
        if (remainingPercentage !== null && remainingPercentage !== undefined && remainingPercentage !== '') {
            qtySpan.innerText = `${roundedQty} / ${roundedBase} ${unit} remaining`;
        } else {
            qtySpan.innerText = `${roundedQty} ${unit} remaining`;
        }
    }

    if (pctEl) {
        if (remainingPercentage !== null && remainingPercentage !== undefined && remainingPercentage !== '') {
            pctEl.innerText = `${parseFloat(remainingPercentage).toFixed(0)}% remaining`;
        } else {
            pctEl.innerText = 'Base stock not set';
        }
    }

    if (pillVal) pillVal.innerText = roundedQty;
    if (pillInput) pillInput.value = roundedQty;
}

// ── Search & Advanced Filtering (Feature 16) ──────────────────
const ProductFilterManager = {
    searchInput: null,
    clearBtn: null,
    chipBtns: [],
    sortSelect: null,
    emptyState: null,
    countBadge: null,
    cards: [],
    currentFilter: 'all',
    currentSort: 'default',
    searchQuery: '',

    init() {
        this.searchInput = document.getElementById('inventory-search-input');
        this.clearBtn = document.getElementById('search-clear-btn');
        this.chipBtns = Array.from(document.querySelectorAll('.filter-chip'));
        this.sortSelect = document.getElementById('inventory-sort-select');
        this.emptyState = document.getElementById('filter-empty-state');
        this.countBadge = document.getElementById('product-count-badge');
        this.cards = Array.from(document.querySelectorAll('.product-card'));
        const resetBtn = document.getElementById('reset-filters-btn');

        if (this.cards.length === 0) return;

        // Search Input Listener with input debouncing
        if (this.searchInput) {
            this.searchInput.addEventListener('input', (e) => {
                this.searchQuery = e.target.value.trim().toLowerCase();
                if (this.clearBtn) {
                    this.clearBtn.style.display = this.searchQuery ? 'flex' : 'none';
                }
                this.applyFilters();
            });
        }

        if (this.clearBtn) {
            this.clearBtn.addEventListener('click', () => {
                if (this.searchInput) {
                    this.searchInput.value = '';
                    this.searchQuery = '';
                    this.clearBtn.style.display = 'none';
                    this.applyFilters();
                }
            });
        }

        // Filter Chips
        this.chipBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                this.chipBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                this.currentFilter = btn.dataset.filter || 'all';
                this.applyFilters();
            });
        });

        // Sort Dropdown
        if (this.sortSelect) {
            this.sortSelect.addEventListener('change', (e) => {
                this.currentSort = e.target.value;
                this.applySort();
            });
        }

        // Reset Filters Button
        if (resetBtn) {
            resetBtn.addEventListener('click', () => {
                if (this.searchInput) this.searchInput.value = '';
                this.searchQuery = '';
                if (this.clearBtn) this.clearBtn.style.display = 'none';
                this.chipBtns.forEach(b => b.classList.remove('active'));
                const allChip = this.chipBtns.find(b => b.dataset.filter === 'all');
                if (allChip) allChip.classList.add('active');
                this.currentFilter = 'all';
                if (this.sortSelect) this.sortSelect.value = 'default';
                this.currentSort = 'default';
                this.applyFilters();
            });
        }
    },

    applyFilters() {
        let visibleCount = 0;

        this.cards.forEach(card => {
            const name = (card.dataset.productName || '').toLowerCase();
            const status = card.dataset.productStatus || '';

            const matchesSearch = !this.searchQuery || name.includes(this.searchQuery);
            let matchesStatus = true;
            if (this.currentFilter !== 'all') {
                matchesStatus = (status === this.currentFilter);
            }

            if (matchesSearch && matchesStatus) {
                card.style.display = '';
                visibleCount++;
            } else {
                card.style.display = 'none';
            }
        });

        if (this.countBadge) {
            this.countBadge.innerText = `${visibleCount} Item${visibleCount === 1 ? '' : 's'}`;
        }

        if (this.emptyState) {
            this.emptyState.style.display = (visibleCount === 0) ? 'block' : 'none';
        }

        this.applySort();
    },

    applySort() {
        const grid = document.querySelector('.product-grid');
        if (!grid) return;

        const visibleCards = this.cards.filter(c => c.style.display !== 'none');

        visibleCards.sort((a, b) => {
            if (this.currentSort === 'stock-asc') {
                return parseFloat(a.dataset.currentStock || 0) - parseFloat(b.dataset.currentStock || 0);
            } else if (this.currentSort === 'stock-desc') {
                return parseFloat(b.dataset.currentStock || 0) - parseFloat(a.dataset.currentStock || 0);
            } else if (this.currentSort === 'name-asc') {
                return (a.dataset.productName || '').localeCompare(b.dataset.productName || '');
            }
            return 0; // Default DOM order
        });

        visibleCards.forEach(card => grid.appendChild(card));
    }
};

// ── App Startup Initialization & Splash (Feature 8) ───────────
function initAppStartup() {
    const splash = document.getElementById('app-startup-splash');
    if (splash) {
        splash.style.display = 'none';
        splash.remove();
    }

    // Cache products locally for offline viewing
    try {
        const productData = [];
        document.querySelectorAll('.product-card').forEach(c => {
            productData.push({
                id: c.dataset.productId,
                name: c.dataset.productName,
                unit: c.dataset.productUnit,
                stock: c.dataset.currentStock,
                status: c.dataset.productStatus
            });
        });
        if (productData.length > 0) {
            localStorage.setItem('lr_cached_inventory', JSON.stringify(productData));
        }
    } catch (e) {
        // Safe failover
    }
}

// ── Global Error & Crash Reporting (Feature 19) ───────────────
function initCrashReporting() {
    const reportCrash = (msg, src, line, col, stack) => {
        try {
            fetch('/api/log-client-error/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCookie('csrftoken')
                },
                body: JSON.stringify({
                    message: String(msg || 'Unknown'),
                    source: String(src || 'unknown'),
                    lineno: line || 0,
                    colno: col || 0,
                    url: window.location.href,
                    userAgent: navigator.userAgent
                })
            }).catch(() => { });
        } catch {
            // Ignore logging transport failures
        }
    };

    window.addEventListener('error', (e) => {
        reportCrash(e.message, e.filename, e.lineno, e.colno, e.error?.stack);
    });

    window.addEventListener('unhandledrejection', (e) => {
        reportCrash(e.reason?.message || e.reason, 'promise', 0, 0, e.reason?.stack);
    });
}

// ── Firebase Live Sync (Spark Free Plan) ──────────────────────
const FirebaseLiveSync = {
    app: null,
    initialized: false,

    init() {
        if (!window.firebase || this.initialized) return;

        const projectId = document.body.dataset.firebaseProject || 'laundryrage-inventory';
        const branchCode = document.body.dataset.branchCode || 'OD3301LR-JGM';

        const firebaseConfig = {
            projectId: projectId,
            databaseURL: `https://${projectId}-default-rtdb.asia-south1.firebasedatabase.app`
        };

        try {
            if (!firebase.apps || firebase.apps.length === 0) {
                this.app = firebase.initializeApp(firebaseConfig);
            } else {
                this.app = firebase.apps[0];
            }
            this.initialized = true;

            // Connect Realtime Database listener if available
            this.initRTDBListener(branchCode);

            // Connect Firestore listener if available
            this.initFirestoreListener(branchCode);
        } catch (err) {
            console.debug('Firebase client init notice:', err);
        }
    },

    initRTDBListener(branchCode) {
        try {
            if (!firebase.database) return;
            const rtdb = firebase.database();
            const branchRef = rtdb.ref(`branches/${branchCode}/products`);

            branchRef.on('child_changed', (snapshot) => {
                const productId = snapshot.key;
                const data = snapshot.val();
                if (data) this.applyRemoteStockUpdate(productId, data);
            });
        } catch (e) {
            console.debug('Firebase RTDB listener notice:', e);
        }
    },

    initFirestoreListener(branchCode) {
        try {
            if (!firebase.firestore) return;
            const fs = firebase.firestore();
            fs.collection('branches').doc(String(branchCode)).collection('products')
                .onSnapshot((snapshot) => {
                    snapshot.docChanges().forEach((change) => {
                        if (change.type === 'modified' || change.type === 'added') {
                            const productId = change.doc.id;
                            const data = change.doc.data();
                            if (data) this.applyRemoteStockUpdate(productId, data);
                        }
                    });
                }, (err) => {
                    console.debug('Firestore listener notice:', err);
                });
        } catch (e) {
            console.debug('Firestore listener notice:', e);
        }
    },

    applyRemoteStockUpdate(productId, data) {
        const card = document.querySelector(`.product-card[data-product-id="${productId}"]`);
        if (!card) return;

        const currentDisplay = parseFloat(card.dataset.currentStock);
        const incomingStock = parseFloat(data.stock);

        if (!isNaN(currentDisplay) && Math.abs(currentDisplay - incomingStock) < 0.001) {
            return;
        }

        const cleanStock = (incomingStock % 1 === 0) ? String(parseInt(incomingStock, 10)) : String(incomingStock);

        card.dataset.currentStock = cleanStock;
        if (data.status) card.dataset.productStatus = data.status;

        const stockValueEl = card.querySelector('.stock-value');
        if (stockValueEl) {
            stockValueEl.innerText = cleanStock;
            stockValueEl.classList.add('stock-updated-pulse');
            setTimeout(() => stockValueEl.classList.remove('stock-updated-pulse'), 1200);
        }

        const statusBadge = card.querySelector('.product-status-badge');
        if (statusBadge && data.status) {
            statusBadge.innerText = data.status;
            statusBadge.className = 'product-status-badge';
            if (data.status === 'In Stock') {
                statusBadge.classList.add('status-in-stock');
            } else if (data.status === 'Low Stock') {
                statusBadge.classList.add('status-low-stock');
            } else if (data.status === 'Out of Stock') {
                statusBadge.classList.add('status-out-of-stock');
            }
        }
    }
};

// ── Main App Initialization ────────────────────────────────────
function initApp() {
    initAppStartup();
    initCrashReporting();
    ConfirmDialog.init();
    NetworkManager.init();
    ProductFilterManager.init();
    FirebaseLiveSync.init();

    // 1. Set Monthly Base Stock Modal Overlay (AJAX)
    const modalOverlay = document.getElementById('restock-modal');
    const modalForm = document.getElementById('restock-form');

    if (modalOverlay && modalForm) {
        const modalClose = modalOverlay.querySelector('.modal-close');
        const modalCancel = modalOverlay.querySelector('.btn-secondary');
        const modalTitle = modalOverlay.querySelector('.modal-header h2');
        const modalProductIdInput = document.getElementById('modal-product-id');
        const modalQuantityInput = document.getElementById('modal-quantity');
        const submitBtn = modalForm.querySelector('button[type="submit"]');

        document.querySelectorAll('.stock-badge').forEach(badge => {
            badge.addEventListener('click', () => {
                const card = badge.closest('.product-card');
                const productId = card.dataset.productId;
                const productName = card.querySelector('.product-name').innerText;
                const unit = card.dataset.productUnit;

                modalProductIdInput.value = productId;
                modalTitle.innerText = `Set Monthly Base Stock for ${productName}`;
                modalQuantityInput.value = '';
                modalQuantityInput.placeholder = `Base amount in ${unit}`;

                modalOverlay.classList.add('active');
                modalQuantityInput.focus();
            });
        });

        const closeModal = () => modalOverlay.classList.remove('active');
        if (modalClose) modalClose.addEventListener('click', closeModal);
        if (modalCancel) modalCancel.addEventListener('click', closeModal);
        modalOverlay.addEventListener('click', (e) => {
            if (e.target === modalOverlay) closeModal();
        });

        modalForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const productId = modalProductIdInput.value;
            const quantity = parseFloat(modalQuantityInput.value);

            if (isNaN(quantity) || quantity <= 0) {
                showToast('Please specify a positive base stock quantity.', 'warning');
                return;
            }

            if (!NetworkManager.isOnline) {
                showToast('Setting base stock requires an active internet connection.', 'warning');
                return;
            }

            submitBtn.disabled = true;
            submitBtn.classList.add('btn-loading');
            submitBtn.innerText = 'Saving...';

            try {
                const response = await fetch('/stock/adjust-ajax/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCookie('csrftoken')
                    },
                    body: JSON.stringify({
                        product_id: productId,
                        quantity: quantity,
                        action: 'set_base'
                    })
                });

                const data = await response.json();
                if (response.ok && data.success) {
                    const card = document.querySelector(`.product-card[data-product-id="${productId}"]`);
                    if (card) {
                        const unit = card.dataset.productUnit;
                        updateCardStockDisplay(card, data.new_quantity, data.remaining_percentage, data.status, data.base_stock, unit);
                    }
                    showToast('Monthly base stock updated successfully.', 'success');
                    closeModal();
                } else if (response.status === 403) {
                    showToast(data.error || 'Permission denied. Only administrators can set base stock.', 'error');
                } else {
                    showToast(data.error || 'Failed to update base stock.', 'warning');
                }
            } catch (error) {
                console.error('AJAX Error:', error);
                showToast('Unable to update base stock. Please check your connection and try again.', 'error');
            } finally {
                submitBtn.disabled = false;
                submitBtn.classList.remove('btn-loading');
                submitBtn.innerText = 'Set Base Stock';
            }
        });
    }

    // 2. Direct On-Card Editing logic (Stock changes strictly locked until 'Edit' is pressed)
    document.querySelectorAll('.product-card').forEach(card => {
        const editBtn = card.querySelector('.edit-btn');
        const minusBtn = card.querySelector('.pill-btn.minus');
        const plusBtn = card.querySelector('.pill-btn.plus');
        const valEl = card.querySelector('.pill-value');
        const inputEl = card.querySelector('.pill-value-input');
        const pillSelector = card.querySelector('.pill-selector');

        if (!editBtn || !valEl || !inputEl) return;

        const productId = card.dataset.productId;
        const productName = card.querySelector('.product-name')?.innerText || 'Product';
        const unit = card.dataset.productUnit || '';

        // Ensure buttons start disabled until Edit is pressed
        if (minusBtn) minusBtn.disabled = true;
        if (plusBtn) plusBtn.disabled = true;

        // If user clicks on locked stepper outside of edit mode, inform them
        if (pillSelector) {
            pillSelector.addEventListener('click', (e) => {
                if (!card.classList.contains('is-editing')) {
                    showToast('Click "Edit" to adjust stock.', 'info');
                }
            });
        }

        // Stepper: + and - buttons only adjust the editable draft input when in Edit mode
        if (plusBtn) {
            plusBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                if (!card.classList.contains('is-editing')) return;
                const cur = parseFloat(inputEl.value) || 0;
                inputEl.value = Math.round(cur + 1);
            });
        }

        if (minusBtn) {
            minusBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                if (!card.classList.contains('is-editing')) return;
                const cur = parseFloat(inputEl.value) || 0;
                inputEl.value = Math.max(0, Math.round(cur - 1));
            });
        }

        // Edit button handler
        editBtn.addEventListener('click', async (e) => {
            e.preventDefault();
            e.stopPropagation();
            const isEditing = editBtn.classList.contains('active-edit');
            const currentStock = parseFloat(card.dataset.currentStock || valEl.innerText || 0);

            if (!isEditing) {
                // Enter Edit Mode
                card.classList.add('is-editing');
                editBtn.classList.add('active-edit');
                editBtn.innerText = 'Done';
                if (minusBtn) minusBtn.disabled = false;
                if (plusBtn) plusBtn.disabled = false;
                valEl.style.display = 'none';
                inputEl.style.display = 'inline-block';
                inputEl.value = Math.round(currentStock);
                inputEl.focus();
                inputEl.select();
            } else {
                // Done / Save clicked - save value
                const newValue = parseFloat(inputEl.value);
                if (isNaN(newValue) || newValue < 0) {
                    showToast('Please specify a valid non-negative quantity.', 'warning');
                    return;
                }

                if (newValue % 1 !== 0) {
                    showToast('Quantity must be a whole number.', 'warning');
                    return;
                }

                // If stock didn't change, just exit edit mode
                if (newValue === currentStock) {
                    card.classList.remove('is-editing');
                    editBtn.classList.remove('active-edit');
                    editBtn.innerText = 'Edit';
                    if (minusBtn) minusBtn.disabled = true;
                    if (plusBtn) plusBtn.disabled = true;
                    inputEl.style.display = 'none';
                    valEl.style.display = 'inline-block';
                    return;
                }

                // Confirmation check for large stock drop (Feature 7)
                const dropAmount = currentStock - newValue;
                if (dropAmount >= 10 || (currentStock > 0 && dropAmount > (currentStock * 0.5))) {
                    const confirmed = await ConfirmDialog.ask({
                        title: 'Reduce Stock?',
                        message: `You are about to remove ${dropAmount} ${unit} of "${productName}".`,
                        currentStock: `${currentStock} ${unit}`,
                        newStock: `${newValue} ${unit}`,
                        confirmText: 'Confirm Reduction',
                        isDanger: true
                    });
                    if (!confirmed) return;
                }

                // If offline, queue update safely (Feature 1)
                if (!NetworkManager.isOnline) {
                    NetworkManager.enqueue({
                        product_id: productId,
                        action: 'edit',
                        quantity: newValue,
                        expected_stock: currentStock,
                        notes: 'Offline card edit'
                    });
                    // Optimistic update
                    updateCardStockDisplay(card, newValue, null, card.dataset.productStatus, null, unit);
                    card.classList.remove('is-editing');
                    editBtn.classList.remove('active-edit');
                    editBtn.innerText = 'Edit';
                    if (minusBtn) minusBtn.disabled = true;
                    if (plusBtn) plusBtn.disabled = true;
                    inputEl.style.display = 'none';
                    valEl.style.display = 'inline-block';
                    showToast('Stock update saved offline. Will sync when back online.', 'info');
                    return;
                }

                editBtn.disabled = true;
                editBtn.classList.add('btn-loading');
                editBtn.innerText = 'Saving...';

                try {
                    const response = await fetch('/stock/adjust-ajax/', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': getCookie('csrftoken')
                        },
                        body: JSON.stringify({
                            product_id: productId,
                            quantity: newValue,
                            action: 'edit',
                            expected_stock: currentStock,
                            notes: 'Manual stock edit via card'
                        })
                    });

                    const data = await response.json();

                    if (response.status === 409) {
                        // Multi-device conflict detected (Feature 11)
                        if (data.current_stock) {
                            updateCardStockDisplay(card, data.current_stock, null, card.dataset.productStatus, data.base_stock, unit);
                        }
                        showToast(data.error || 'This product was updated on another device. Latest stock reloaded.', 'warning');
                        editBtn.innerText = 'Done';
                        return;
                    }

                    if (response.ok && data.success) {
                        updateCardStockDisplay(card, data.new_quantity, data.remaining_percentage, data.status, data.base_stock, unit);
                        showToast('Stock updated successfully', 'success');

                        if (data.low_stock_alert) {
                            LowStockTracker.notify(data.low_stock_alert);
                        }

                        // Exit Edit Mode
                        card.classList.remove('is-editing');
                        editBtn.classList.remove('active-edit');
                        editBtn.innerText = 'Edit';
                        if (minusBtn) minusBtn.disabled = true;
                        if (plusBtn) plusBtn.disabled = true;
                        inputEl.style.display = 'none';
                        valEl.style.display = 'inline-block';
                    } else if (response.status === 403) {
                        showToast(data.error || 'Permission denied. You can only manage your assigned branch.', 'error');
                        editBtn.innerText = 'Done';
                    } else {
                        showToast(data.error || 'Unable to update stock.', 'warning');
                        editBtn.innerText = 'Done';
                    }
                } catch (error) {
                    console.error('AJAX Error:', error);
                    showToast('Unable to update stock. Please check your connection.', 'error', {
                        retryCallback: () => editBtn.click()
                    });
                    editBtn.innerText = 'Done';
                } finally {
                    editBtn.disabled = false;
                    editBtn.classList.remove('btn-loading');
                }
            }
        });
    });

    // 4. Export History to Google Sheets AJAX handler with offline check & loading state
    const exportHistoryBtn = document.getElementById('btn-export-history');
    if (exportHistoryBtn) {
        exportHistoryBtn.addEventListener('click', async (e) => {
            e.preventDefault();
            if (exportHistoryBtn.disabled) return;

            if (!NetworkManager.isOnline) {
                showToast('Google Sheets export requires an active internet connection.', 'warning');
                return;
            }

            const form = exportHistoryBtn.closest('form');
            if (!form) return;

            const checkedBoxes = form.querySelectorAll('input[name="months"]:checked');
            if (checkedBoxes.length === 0) {
                showToast('Please select at least one month to export.', 'warning');
                return;
            }

            const params = new URLSearchParams();
            checkedBoxes.forEach(cb => {
                params.append('months', cb.value);
            });
            params.append('export', 'google_sheets');

            const originalHtml = exportHistoryBtn.innerHTML;
            exportHistoryBtn.disabled = true;
            exportHistoryBtn.classList.add('btn-loading');
            exportHistoryBtn.innerHTML = `<span>Exporting to Google Sheets...</span>`;

            try {
                const targetUrl = (form.getAttribute('action') || window.location.pathname) + '?' + params.toString();
                const response = await fetch(targetUrl, {
                    method: 'GET',
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest',
                        'Accept': 'application/json'
                    }
                });

                const data = await response.json();
                if (response.ok && data.success) {
                    showToast('✓ History successfully exported to Google Sheets', 'success');
                    if (data.spreadsheet_url) {
                        window.open(data.spreadsheet_url, '_blank');
                    }
                } else {
                    showToast(data.error || 'Google Sheets export failed.', 'warning');
                }
            } catch (err) {
                console.error('Export Error:', err);
                showToast('Unable to connect to Google Sheets. Please check network connection.', 'error');
            } finally {
                exportHistoryBtn.disabled = false;
                exportHistoryBtn.classList.remove('btn-loading');
                exportHistoryBtn.innerHTML = originalHtml;
            }
        });
    }
}

// Resilient execution: invoke immediately if document already loaded/interactive
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initApp);
} else {
    initApp();
}
