"use strict";

/**
 * Initializes delete functionality for user list page
 */
function initializeDeleteModal() {
    const modal = document.getElementById('deleteModal');
    const deleteButtons = document.querySelectorAll('.delete-button');
    const cancelBtn = document.getElementById('cancelDelete');
    const deleteActionInput = document.getElementById('deleteAction');

    if (!modal || deleteButtons.length === 0 || !cancelBtn || !deleteActionInput) {
        console.error('One or more required elements not found');
        return;
    }

    deleteButtons.forEach(button => {
        button.addEventListener('click', () => {
            const userId = button.getAttribute('data-user-id');
            deleteActionInput.value = 'delete:' + userId;
            modal.classList.remove('hidden');
        });
    });

    cancelBtn.addEventListener('click', () => {
        modal.classList.add('hidden');
    });
}

document.addEventListener('DOMContentLoaded', function() {
    initializeDeleteModal();
});
