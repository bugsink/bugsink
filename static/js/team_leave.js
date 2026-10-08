"use strict";

function initializeLeaveModal() {
    const modal = document.getElementById('leaveModal');
    const cancelBtn = document.getElementById('cancelLeave');
    const leaveActionInput = document.getElementById('leaveAction');

    document.querySelectorAll('.leave-button').forEach(button => {
        button.addEventListener('click', () => {
            leaveActionInput.value = button.getAttribute('data-leave-action');
            modal.classList.remove('hidden');
        });
    });

    cancelBtn.addEventListener('click', () => {
        modal.classList.add('hidden');
    });
}

document.addEventListener('DOMContentLoaded', function() {
    initializeLeaveModal();
});
