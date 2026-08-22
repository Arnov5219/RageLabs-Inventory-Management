// CSRF Cookie extraction helper
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            // Does this cookie string begin with the name we want?
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

// Toast notification helper
function showToast(message, type = 'success') {
    const container = document.querySelector('.toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    
    const icon = document.createElement('span');
    icon.className = 'toast-icon';
    icon.innerHTML = type === 'success' ? '✓' : '⚠';
    
    const msg = document.createElement('span');
    msg.className = 'toast-message';
    msg.innerText = message;
    
    toast.appendChild(icon);
    toast.appendChild(msg);
    container.appendChild(toast);
    
    // Trigger animation
    setTimeout(() => {
        toast.classList.add('show');
    }, 10);
    
    // Auto-remove
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => {
            toast.remove();
        }, 300);
    }, 4000);
}

// Adjust quantity inputs on browsing cards (pill selectors)
document.addEventListener('DOMContentLoaded', () => {
    // Helper function to update badge and quantity value on a product card
    const updateCardStockDisplay = (card, newQuantity, remainingPercentage, status, baseStock, unit) => {
        const badge = card.querySelector('.stock-badge');
        const pctEl = card.querySelector('.percentage-remaining');
        const pillVal = card.querySelector('.pill-value');
        const pillInput = card.querySelector('.pill-value-input');
        const roundedQty = parseFloat(newQuantity).toFixed(0);
        const roundedBase = parseFloat(baseStock || 0).toFixed(0);
        
        if (badge) {
            if (remainingPercentage !== null && remainingPercentage !== undefined && remainingPercentage !== '') {
                badge.innerText = `${roundedQty} / ${roundedBase} ${unit} remaining`;
            } else {
                badge.innerText = `${roundedQty} ${unit} remaining (No Base Stock)`;
            }
            
            badge.className = 'stock-badge';
            if (status === 'RED') {
                badge.classList.add('low');
            } else if (status === 'YELLOW') {
                badge.classList.add('mod');
            } else if (status === 'GREEN') {
                badge.classList.add('suff');
            } else {
                badge.classList.add('no-base');
            }
        }
        
        if (pctEl) {
            if (remainingPercentage !== null && remainingPercentage !== undefined && remainingPercentage !== '') {
                const roundedPct = parseFloat(remainingPercentage).toFixed(0);
                pctEl.innerText = `${roundedPct}% remaining`;
            } else {
                pctEl.innerText = 'Base stock not set';
            }
        }
        
        if (pillVal) {
            pillVal.innerText = roundedQty;
        }
        if (pillInput) {
            pillInput.value = roundedQty;
        }
    };

    // Pill Selectors (+ / - buttons)
    document.querySelectorAll('.pill-selector').forEach(selector => {
        const minusBtn = selector.querySelector('.minus');
        const plusBtn = selector.querySelector('.plus');
        const valueSpan = selector.querySelector('.pill-value');
        const input = selector.querySelector('.pill-value-input');
        const card = selector.closest('.product-card');
        const unit = card.dataset.productUnit;

        if (!minusBtn || !plusBtn || !input) return;

        const step = parseFloat(input.step) || 1;
        const min = parseFloat(input.min) || 0;

        const setQuantity = (quantity) => {
            input.value = Math.max(min, quantity).toString();
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
        };

        minusBtn.addEventListener('click', () => {
            const current = parseFloat(input.value);
            setQuantity((Number.isFinite(current) ? current : min) - step);
        });

        plusBtn.addEventListener('click', () => {
            const current = parseFloat(input.value);
            setQuantity((Number.isFinite(current) ? current : min) + step);
        });
    });

    // Set Monthly Base Stock Modal overlay functionality (AJAX)
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

        const closeModal = () => {
            modalOverlay.classList.remove('active');
        };

        modalClose.addEventListener('click', closeModal);
        modalCancel.addEventListener('click', closeModal);
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

            submitBtn.disabled = true;
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
                if (data.success) {
                    const card = document.querySelector(`.product-card[data-product-id="${productId}"]`);
                    if (card) {
                        const unit = card.dataset.productUnit;
                        updateCardStockDisplay(card, data.new_quantity, data.remaining_percentage, data.status, data.base_stock, unit);
                    }
                    showToast('Monthly base stock updated successfully.', 'success');
                    closeModal();
                } else {
                    showToast(data.error || 'Failed to update base stock.', 'warning');
                }
            } catch (error) {
                console.error('AJAX Error:', error);
                showToast('An error occurred. Please try again.', 'warning');
            } finally {
                submitBtn.disabled = false;
                submitBtn.innerText = 'Set Base Stock';
            }
        });
    }

    // Direct On-Card Editing logic (Edit / Done state toggle)
    document.querySelectorAll('.edit-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const card = btn.closest('.product-card');
            const productId = card.dataset.productId;
            const unit = card.dataset.productUnit;
            const isEditing = btn.classList.contains('active-edit');
            
            const valEl = card.querySelector('.pill-value');
            const inputEl = card.querySelector('.pill-value-input');
            
            if (!isEditing) {
                // Enter Edit Mode
                btn.classList.add('active-edit');
                btn.innerText = 'Done';
                valEl.style.display = 'none';
                inputEl.style.display = 'inline-block';
                inputEl.focus();
                inputEl.select();
            } else {
                // Done clicked - save value
                const newValue = parseFloat(inputEl.value);
                if (isNaN(newValue) || newValue < 0) {
                    showToast('Please specify a valid quantity.', 'warning');
                    return;
                }
                
                // Confirm integer validation
                if (newValue % 1 !== 0) {
                    showToast('Quantity must be a whole number.', 'warning');
                    return;
                }
                
                btn.disabled = true;
                btn.innerText = 'Saving...';
                
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
                            notes: 'Manual stock edit via card'
                        })
                    });
                    
                    const data = await response.json();
                    if (data.success) {
                        updateCardStockDisplay(card, data.new_quantity, data.remaining_percentage, data.status, data.base_stock, unit);
                        showToast('Stock quantity updated successfully.', 'success');
                        
                        // Exit Edit Mode
                        btn.classList.remove('active-edit');
                        btn.innerText = 'Edit';
                        inputEl.style.display = 'none';
                        valEl.style.display = 'inline-block';
                    } else {
                        showToast(data.error || 'Failed to edit stock.', 'warning');
                        btn.innerText = 'Done';
                    }
                } catch (error) {
                    console.error('AJAX Error:', error);
                    showToast('An error occurred. Please try again.', 'warning');
                    btn.innerText = 'Done';
                } finally {
                    btn.disabled = false;
                }
            }
        });
    });
});
