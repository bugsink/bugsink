"use strict";

function followContainedLink(circleDiv) {
    const link = circleDiv.querySelector("a");
    window.location.href = link.href;
}
