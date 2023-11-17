"use strict";

function toggleFrameVisibility(frameHeader) {
    const frameDetails = frameHeader.parentNode.querySelector(".js-frame-details");
    if (frameDetails.classList.contains("hidden")) {
        frameDetails.classList.remove("hidden");
        frameDetails.classList.add("xl:flex");  // add back
    } else {
        frameDetails.classList.add("hidden");
        frameDetails.classList.remove("xl:flex");  // this appears to be necessary, not sure why
    }
}


function showAllFrames(frameHeader) {
    document.querySelectorAll(".js-frame-details").forEach((frameDetails) => {
        frameDetails.classList.remove("hidden");
        frameDetails.classList.add("xl:flex");
    });
}

function showInAppFrames(frameHeader) {
    document.querySelectorAll(".js-frame-details").forEach((frameDetails) => {
        if (frameDetails.classList.contains("js-in-app")) {
            frameDetails.classList.remove("hidden");
            frameDetails.classList.add("xl:flex");  // add back
        } else {
            frameDetails.classList.add("hidden");
            frameDetails.classList.remove("xl:flex");  // this appears to be necessary, not sure why
        }
    });
}

function hideAllFrames(frameHeader) {
    document.querySelectorAll(".js-frame-details").forEach((frameDetails) => {
        frameDetails.classList.add("hidden");
        frameDetails.classList.remove("xl:flex");  // this appears to be necessary, not sure why
    });
}
