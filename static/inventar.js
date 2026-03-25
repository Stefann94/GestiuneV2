

function initSafeStates() {

    document.querySelectorAll('.product-row').forEach(row => {

        const input = row.querySelector('.faptic-input');

        const indicator = row.querySelector('.status-indicator');

        if (input && indicator && !row.hasAttribute('data-safe-val')) {

            row.setAttribute('data-safe-val', input.value);

            row.setAttribute('data-safe-html', indicator.innerHTML);

            row.setAttribute('data-safe-class', indicator.className);

        }

    });

}


document.addEventListener('DOMContentLoaded', initSafeStates);


function applyCombinedFilters() {

    const searchInput = document.getElementById('inventorySearch');

    const searchQuery = searchInput ? searchInput.value.toLowerCase().trim() : '';

   
    const activePill = document.querySelector('.pill-audit.active');

    const activeStatus = activePill ? activePill.getAttribute('data-filter') : 'all';

   
    document.querySelectorAll('.product-row').forEach(row => {

        const name = row.querySelector('.editable-name').textContent.toLowerCase();

        const sku = row.querySelector('.editable-sku').textContent.toLowerCase();

        const rowStatus = row.getAttribute('data-status') || 'synced';

       
        const matchesText = name.includes(searchQuery) || sku.includes(searchQuery);

       
        const isEditing = row.classList.contains('is-editing');

        let matchesStatus = (activeStatus === 'all' || rowStatus === activeStatus);

       
        if (isEditing) {

            matchesStatus = true; 

        }


        if (matchesText && matchesStatus) {

            row.style.display = '';

        } else {

            row.style.display = 'none';

        }

    });

}


function filterInventory() { applyCombinedFilters(); }


function filterByStatus(status) {

    document.querySelectorAll('.pill-audit').forEach(p => p.classList.remove('active'));

    const activeBtn = document.querySelector(`[data-filter="${status}"]`);

    if (activeBtn) activeBtn.classList.add('active');

    applyCombinedFilters();

}


function updateRowStatus(input) {

    const row = input.closest('tr');

    if (!row) return;


    const systemReference = parseInt(row.getAttribute('data-system-stock')) || 0;

    const fapticStock = parseInt(input.value) || 0;

   
    const statusSpan = row.querySelector('.status-indicator');

    const saveBtn = row.querySelector('.btn-sync');


    row.classList.add('is-editing', 'modified');


    const diff = fapticStock - systemReference;


    if (diff === 0) {

        statusSpan.textContent = 'OK';

        statusSpan.className = 'status-indicator synced';

        row.setAttribute('data-status', 'synced');

    } else if (diff < 0) {

        statusSpan.textContent = `Lipsă (${Math.abs(diff)})`;

        statusSpan.className = 'status-indicator shortage';

        row.setAttribute('data-status', 'shortage');

    } else {

        statusSpan.textContent = `Surplus (${diff})`;

        statusSpan.className = 'status-indicator surplus';

        row.setAttribute('data-status', 'surplus');

    }


    if (saveBtn) saveBtn.disabled = false;

   
    applyCombinedFilters();

}

window.jumpToAuditProduct = function(productId) {
    const suggestionsBox = document.getElementById('search-suggestions');
    if (suggestionsBox) suggestionsBox.style.display = 'none';

    openInventoryModal();

    setTimeout(() => {
        const row = document.querySelector(`.product-row[data-id="${productId}"]`);

        if (row) {
            
            document.querySelectorAll('.product-row').forEach(r => r.classList.remove('highlight-target'));

            document.getElementById('inventorySearch').value = '';
            filterByStatus('all'); 

            row.scrollIntoView({ behavior: 'smooth', block: 'center' });
            row.classList.add('highlight-target');

            const fapticInput = row.querySelector('.faptic-input');
            if (fapticInput) fapticInput.focus();

            
            setTimeout(() => {
                row.classList.remove('highlight-target');
            }, 2000); 
            
        }
    }, 300);
};


async function saveAuditRow(btn) {

    const row = btn.closest('tr');

    const productId = row.getAttribute('data-id');

    const fapticInput = row.querySelector('.faptic-input');

    const fapticValue = parseInt(fapticInput.value) || 0;


    const originalContent = btn.innerHTML;

    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

    btn.disabled = true;


    try {

        const response = await fetch('/api/audit-save', {

            method: 'POST',

            headers: { 'Content-Type': 'application/json' },

            body: JSON.stringify({

                id: productId,

                stock: fapticValue,

                name: row.querySelector('.editable-name').textContent.trim(),

                sku: row.querySelector('.editable-sku').textContent.trim()

            })

        });


        const data = await response.json();


        if (data.status === 'success') {

            
            row.setAttribute('data-status', data.new_status);
           

            const statusSpan = row.querySelector('.status-indicator');

            if (data.new_status === 'shortage') {

                statusSpan.textContent = `Lipsă (${Math.abs(data.new_diff)})`;

                statusSpan.className = 'status-indicator shortage';

            } else if (data.new_status === 'surplus') {

                statusSpan.textContent = `Surplus (${data.new_diff})`;

                statusSpan.className = 'status-indicator surplus';

            } else {

                statusSpan.textContent = 'OK';

                statusSpan.className = 'status-indicator synced';

            }


            if (typeof refreshHeroStats === "function") refreshHeroStats();


            row.setAttribute('data-safe-val', fapticValue);

            row.setAttribute('data-safe-html', statusSpan.innerHTML);

            row.setAttribute('data-safe-class', statusSpan.className);


            row.classList.remove('is-editing', 'modified');


            btn.innerHTML = '<i class="fas fa-check"></i>';

            setTimeout(() => {

                btn.innerHTML = originalContent;

                btn.disabled = false;

                
                applyCombinedFilters();

            }, 800);

        } else {

            alert("Eroare: " + data.message);

            btn.innerHTML = originalContent;

            btn.disabled = false;

        }

    } catch (e) {

        console.error(e);

        alert("Eroare de conexiune!");

        btn.innerHTML = originalContent;

        btn.disabled = false;

    }

}


async function deleteProductRow(button, id) {
    if (!confirm("Ești sigur că vrei să ștergi definitiv acest produs? Toate datele vor fi arhivate în Jurnal.")) return;

    
    button.disabled = true;
    const originalContent = button.innerHTML;
    button.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

    try {
        const response = await fetch(`/api/product-delete/${id}`, { 
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' }
        });
        
        const result = await response.json();

        if (result.status === 'success') {
            
            const row = button.closest('tr');
            row.style.transition = 'all 0.5s ease';
            row.style.opacity = '0';
            row.style.transform = 'translateX(20px)';

            setTimeout(() => {
                row.remove();
                
                
                location.reload(); 
            }, 500);

        } else {
            alert("Eroare de la server: " + result.message);
            button.disabled = false;
            button.innerHTML = originalContent;
        }
    } catch (error) {
        console.error("Eroare la fetch stergere:", error);
        alert("Eroare de rețea. Produsul nu a putut fi șters.");
        button.disabled = false;
        button.innerHTML = originalContent;
    }
}


function openInventoryModal() {
    const modal = document.getElementById('inventoryModal');
    if (modal) {
        modal.style.display = 'flex';
        toggleParentScroll(true); 
        initSafeStates();
    }
}

function closeInventoryModal() {
    const modal = document.getElementById('inventoryModal');
    if (modal) {
        modal.style.display = 'none';
        toggleParentScroll(false); 
        applyCombinedFilters();
    }
}


function resetAllUnsavedChanges() {
    
    localStorage.setItem('openUrgenteModal', 'true');
    
    
    window.location.href = '/dashboard'; 
}