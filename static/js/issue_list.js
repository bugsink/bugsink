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

function matchMainCheckboxStateToIssueCheckboxes() {
    const checkboxes = document.querySelectorAll(".js-issue-checkbox");
    let allChecked = true;
    let allUnchecked = true;

    for (let i = 0; i < checkboxes.length; i++) {
        if (checkboxes[i].checked) {
            allUnchecked = false;
        }
        if (!checkboxes[i].checked) {
            allChecked = false;
        }
        if (!allChecked && !allUnchecked) {
            break;
        }
    }

    const mainCheckbox = document.querySelector(".js-main-checkbox");
    if (allChecked) {
        mainCheckbox.checked = true;
    }
    if (allUnchecked) {
        mainCheckbox.checked = false;
    }
}

function followContainedLink(circleDiv) {
    const link = circleDiv.querySelector("a");
    window.location.href = link.href;
}
