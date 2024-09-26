"use strict";

function toggleFoo(element) {
    element.classList.toggle("rotate-180");
}
    
function distanceToWindowBottom() {
    // https://stackoverflow.com/a/2800676/339144
    let scrollPosition = window.pageYOffset;
    let windowSize     = window.innerHeight;
    let bodyHeight     = document.querySelector("html").offsetHeight;
    return Math.max(bodyHeight - (scrollPosition + windowSize), 0);
}

onscroll = (event) => {
    setBodyMinHeight();
};

function setBodyMinHeight() {
  let body = document.querySelector("html");
  let bodyHeightPreCollapse = body.offsetHeight;
  // console.log("was actually", bodyHeightPreCollapse, "minimally", body.style.minHeight);
  body.style.minHeight = (bodyHeightPreCollapse - distanceToWindowBottom()) + "px";
  // console.log("is now actually", document.html.offsetHeight, "minimally", html.style.minHeight);
}

function collapseSection(element) {
  if (element.getAttribute("data-collapsed") === "true") {
    return;
  }

  // get the height of the element's inner content, regardless of its actual size
  const sectionHeight = element.scrollHeight;

  setBodyMinHeight();

  // temporarily disable all css transitions
  const elementTransition = element.style.transition;
  element.style.transition = '';

  // on the next frame (as soon as the previous style change has taken effect),
  // explicitly set the element's height to its current pixel height, so we
  // aren't transitioning out of 'auto'
  requestAnimationFrame(function() {
    element.style.height = sectionHeight + 'px';
    element.style.transition = elementTransition;

    // on the next frame (as soon as the previous style change has taken effect),
    // have the element transition to height: 0
    requestAnimationFrame(function() {
      element.style.height = 0 + 'px';
    });
  });

  // mark the section as "currently collapsed"
  element.setAttribute('data-collapsed', 'true');
}

function expandSection(element) {
  if (element.getAttribute("data-collapsed") !== "true") {
    return;
  }

  setBodyMinHeight();

  // get the height of the element's inner content, regardless of its actual size
  const sectionHeight = element.scrollHeight;

  // have the element transition to the height of its inner content
  let explicitlySetValue = sectionHeight + 'px';
  element.style.height = explicitlySetValue;

  // when the next css transition finishes (which should be the one we just triggered)
  const onTransitioned = function(e) {
    // remove this event listener so it only gets triggered once
    element.removeEventListener('transitionend', onTransitioned);
    
    // remove "height" from the element's inline styles, so it can return to its initial value
    if (element.style.height == explicitlySetValue) {
        element.style.removeProperty("height");
    }
  }

  element.addEventListener('transitionend', onTransitioned);

  // mark the section as "currently not collapsed"
  element.setAttribute('data-collapsed', 'false');
}

function toggleFrameVisibility(frameHeader) {
    const frameDetails = frameHeader.parentNode.querySelector(".js-frame-details");
    if (frameDetails.getAttribute("data-collapsed") === "true") {
        expandSection(frameDetails);
    } else {
        collapseSection(frameDetails);
    }
    frameHeader.querySelector(".js-chevron").classList.toggle("rotate-180");
}


function showAllFrames() {
    document.querySelectorAll(".js-frame-details").forEach((frameDetails) => {
        expandSection(frameDetails);
    });
    document.querySelectorAll(".js-chevron").forEach((chevron) => {
        chevron.classList.add("rotate-180");
    });
}

function showInAppFrames() {
    document.querySelectorAll(".js-frame-details").forEach((frameDetails) => {
        if (frameDetails.classList.contains("js-in-app")) {
            expandSection(frameDetails);
            frameDetails.parentNode.querySelector(".js-chevron").classList.add("rotate-180");
        } else {
            collapseSection(frameDetails);
            frameDetails.parentNode.querySelector(".js-chevron").classList.remove("rotate-180");
        }
    });
    // this works because when there are repeated ids a browser will just jump to the first one.
    // the less lazy way would be to just have a single such id
    window.location = window.location.origin + window.location.pathname + '#in-app';
}

function showRaisingFrame() {
    document.querySelectorAll(".js-frame-details").forEach((frameDetails) => {
        if (frameDetails.classList.contains("js-raising-frame")) {
            expandSection(frameDetails);
            frameDetails.parentNode.querySelector(".js-chevron").classList.add("rotate-180");
        } else {
            collapseSection(frameDetails);
            frameDetails.parentNode.querySelector(".js-chevron").classList.remove("rotate-180");
        }
    });
    window.location = window.location.origin + window.location.pathname + '#raise';
}

function hideAllFrames() {
    document.querySelectorAll(".js-frame-details").forEach((frameDetails) => {
        collapseSection(frameDetails);
    });
    document.querySelectorAll(".js-chevron").forEach((chevron) => {
        chevron.classList.remove("rotate-180");
    });
}
