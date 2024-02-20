"use strict";

function toggleContainedCheckbox(td) {
    const checkbox = td.querySelector("[type=\"checkbox\"]");
    checkbox.checked = !checkbox.checked;
}
