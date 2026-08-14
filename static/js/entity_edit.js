"use strict";

/**
 * Initializes delete functionality for entity edit pages
 */
function initializeDeleteModal() {
    const modal = document.getElementById('deleteModal');
    const deleteBtn = document.getElementById('deleteButton');
    const cancelBtn = document.getElementById('cancelDelete');

    if (!modal || !deleteBtn || !cancelBtn) {
        console.error('One or more required elements not found');
        return;
    }

    deleteBtn.addEventListener('click', () => {
        modal.showModal();
    });

    cancelBtn.addEventListener('click', () => {
        modal.close();
    });
}

document.addEventListener('DOMContentLoaded', function() {
    initializeDeleteModal();
});
