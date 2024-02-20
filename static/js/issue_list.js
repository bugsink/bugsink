"use strict";

function toggleContainedCheckbox(circleDiv) {
    const checkbox = circleDiv.querySelector("[type=\"checkbox\"]");
    checkbox.checked = !checkbox.checked;
}

function matchIssueCheckboxesStateToMain(elementContainingMainCheckbox) {
    const mainCheckbox = elementContainingMainCheckbox.querySelector("[type=\"checkbox\"]");
    const checkboxes = document.querySelectorAll(".js-issue-checkbox");
    for (let i = 0; i < checkboxes.length; i++) {
        checkboxes[i].checked = mainCheckbox.checked;
    }
}
