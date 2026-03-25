

document.addEventListener('DOMContentLoaded', function () {

    
    if (localStorage.getItem('openUrgenteModal') === 'true') {
        
        setTimeout(() => {
            
            openReportsModal();
            
            
            localStorage.removeItem('openUrgenteModal');

            
            const btnFix = document.querySelector('.btn-fix-stoc');
            if (btnFix) {
                btnFix.style.animation = "pulse-gold 2s infinite";
            }
        }, 500);
    }

    
    console.log("Sistemul de Rapoarte inițializat.");
});


async function openReportsModal() {
    const modal = document.getElementById('reportsModal');
    if (modal) {
        
        modal.style.display = 'flex';
        modal.classList.add('active'); 
        
        
        document.body.classList.add('modal-open');

        
        const tableBody = document.getElementById('reportsTableBody');
        if (tableBody) {
            tableBody.innerHTML = `
                <tr>
                    <td colspan="4" style="text-align:center; padding: 2rem;">
                        <i class="fas fa-spinner fa-spin"></i> Se încarcă datele din baza de date...
                    </td>
                </tr>`;
        }

        
        await refreshReportsData();
    }
}

function closeReportsModal() {
    const modal = document.getElementById('reportsModal');
    if (modal) {
        modal.style.display = 'none';
        modal.classList.remove('active');
        
        document.body.classList.remove('modal-open');
    }
}


async function refreshReportsData() {
    try {
        
        const response = await fetch('/api/stats/reports');
        if (!response.ok) throw new Error("Eroare la comunicarea cu serverul");
        
        const data = await response.json();

        
        if (document.getElementById('rep-total-items')) {
            document.getElementById('rep-total-items').textContent = data.stats.total_items || 0;
            document.getElementById('rep-total-ok').textContent = data.stats.total_ok || 0;
            document.getElementById('rep-total-short').textContent = data.stats.total_shortage || 0;
            document.getElementById('rep-total-surplus').textContent = data.stats.total_surplus || 0;
        }

        
        const tableBody = document.getElementById('reportsTableBody');
        if (!tableBody) return;

        tableBody.innerHTML = ''; 

        if (!data.products || data.products.length === 0) {
            tableBody.innerHTML = '<tr><td colspan="4" class="text-center">Nu există produse în bază.</td></tr>';
            return;
        }

        data.products.forEach(p => {
            const status = p.last_audit_status || 'synced';
            const diff = p.last_audit_diff || 0;
            
            
            const statusLabels = {
                'shortage': 'LIPSĂ',
                'surplus': 'SURPLUS',
                'synced': 'OK'
            };

            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><strong>${p.name}</strong></td>
                <td><code>${p.sku}</code></td>
                <td><span class="status-indicator ${status}">${statusLabels[status] || 'OK'}</span></td>
                <td class="text-center"><strong>${diff > 0 ? '+' + diff : diff}</strong></td>
            `;
            tableBody.appendChild(tr);
        });

        console.log("Tabel rapoarte actualizat cu date din DB.");

    } catch (error) {
        console.error("Eroare la preluarea datelor:", error);
        const tableBody = document.getElementById('reportsTableBody');
        if (tableBody) {
            tableBody.innerHTML = `
                <tr>
                    <td colspan="4" style="text-align:center; color: red; padding: 1rem;">
                        <i class="fas fa-exclamation-triangle"></i> Eroare: Nu s-au putut prelua datele.
                    </td>
                </tr>`;
        }
    }
}


async function exportData(format) {
    
    const btn = event.currentTarget;
    const originalContent = btn.innerHTML;
    
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Se descarcă...';
    
    try {
        console.log(`Cerere export pentru formatul: ${format}`);
        const response = await fetch(`/rapoarte/export/${format}`);
        
        if (!response.ok) throw new Error("Serverul a returnat o eroare");

        
        const blob = await response.blob();
        
        
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        
        
        const extensie = format === 'excel' ? 'xlsx' : 'pdf';
        a.download = `Raport_Audit_${new Date().toISOString().slice(0,10)}.${extensie}`;
        
        
        document.body.appendChild(a);
        a.click();
        
        
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);

    } catch (error) {
        console.error("Eroare la export:", error);
        alert("Eroare la descărcare. Verificați consola pentru detalii.");
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalContent;
    }
}