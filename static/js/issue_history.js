"use strict";

function makeCommentEditable(element) {
    const balloon = element.closest(".js-balloon");
    balloon.querySelector(".js-comment-editable").classList.remove("hidden");
    balloon.querySelector(".js-comment-plain").classList.add("hidden");
}
