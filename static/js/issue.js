"use strict";

function toggleFrameVisibility(frameHeader) {
    const frameDetails = frameHeader.parentNode.querySelector(".js-frame-details");
    console.log("FD", frameDetails);
    if (frameDetails.classList.contains("hidden")) {
        frameDetails.classList.remove("hidden");
        frameDetails.classList.add("xl:flex");  // add back
    } else {
        frameDetails.classList.add("hidden");
        frameDetails.classList.remove("xl:flex");  // this appears to be necessary, not sure why
    }
}
