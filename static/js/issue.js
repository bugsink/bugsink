"use strict";

// This is the important part!
function collapseSection(element) {
  if (element.getAttribute("data-collapsed") === "true") {
    return;
  }

  element.classList.remove("xl:flex");  // this appears to be necessary, not sure why

  // get the height of the element's inner content, regardless of its actual size
  var sectionHeight = element.scrollHeight;

  // temporarily disable all css transitions
  var elementTransition = element.style.transition;
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

  element.classList.add("xl:flex");  // add back

  // get the height of the element's inner content, regardless of its actual size
  var sectionHeight = element.scrollHeight;

  // have the element transition to the height of its inner content
  element.style.height = sectionHeight + 'px';

  // when the next css transition finishes (which should be the one we just triggered)
  const foo = function(e) {
    // remove this event listener so it only gets triggered once
    element.removeEventListener('transitionend', foo);
    
    // remove "height" from the element's inline styles, so it can return to its initial value
    element.style.removeProperty("height");
  }

  element.addEventListener('transitionend', foo);

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
}


function showAllFrames(frameHeader) {
    document.querySelectorAll(".js-frame-details").forEach((frameDetails) => {
        expandSection(frameDetails);
    });
}

function showInAppFrames(frameHeader) {
    document.querySelectorAll(".js-frame-details").forEach((frameDetails) => {
        if (frameDetails.classList.contains("js-in-app")) {
            expandSection(frameDetails);
        } else {
            collapseSection(frameDetails);
        }
    });
}

function hideAllFrames(frameHeader) {
    document.querySelectorAll(".js-frame-details").forEach((frameDetails) => {
        collapseSection(frameDetails);
    });
}
