"use strict";

function toggleCommentEditable(element) {
    const balloon = element.closest(".js-balloon");
    balloon.querySelector(".js-comment-editable").classList.toggle("hidden");
    balloon.querySelector(".js-comment-plain").classList.toggle("hidden");
}
