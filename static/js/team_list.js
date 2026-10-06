"use strict";

function followContainedLink(circleDiv) {
    const link = circleDiv.querySelector("a");
    window.location.href = link.href;
}

function initializeLeaveModal() {
    const modal = document.getElementById('leaveModal');
    const cancelBtn = document.getElementById('cancelLeave');
    const leaveActionInput = document.getElementById('leaveAction');

    document.querySelectorAll('.leave-button').forEach(button => {
        button.addEventListener('click', () => {
            leaveActionInput.value = 'leave:' + button.getAttribute('data-team-id');
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
