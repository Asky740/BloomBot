async function waterPlant() {
    const btn = document.getElementById('waterBtn');
    const progress = document.getElementById('progress');
    const snackbar = document.getElementById('snackbar');
    
    btn.disabled = true;
    progress.style.display = 'inline-block';
    
    try {
      const response = await fetch('/water');
      if (response.ok) {
        showSnackbar('✅ Zalévání úspěšné');
        setTimeout(() => location.reload(), 1000);
      }
    } catch (error) {
      showSnackbar('❌ Chyba při komunikaci');
    } finally {
      btn.disabled = false;
      progress.style.display = 'none';
    }
  }
  
  function showSnackbar(message) {
    const snackbar = document.getElementById('snackbar');
    snackbar.textContent = message;
    snackbar.style.display = 'block';
    setTimeout(() => snackbar.style.display = 'none', 3000);
  }
  
  // Automatická aktualizace každých 30 sekund
  setInterval(() => location.reload(), 30000);
  