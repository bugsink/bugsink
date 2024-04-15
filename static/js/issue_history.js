"use strict";

function toggleCommentEditable(element) {
    const balloon = element.closest(".js-balloon");
    balloon.querySelector(".js-comment-editable").classList.toggle("hidden");
    balloon.querySelector(".js-comment-plain").classList.toggle("hidden");
}

function deleteComment(deleteUrl) {
    if (window.confirm("Are you sure you want to delete this comment?")) {
        fetch(deleteUrl, {
            method: 'POST',
            headers: { "X-CSRFToken": csrftoken },
        }).then((response) => {
            // yes this is super-indirect, but it "works for now" and we might revisit this whole bit anyway (e.g. use HTMX)
            // if we revisit this and figure out we want to do what we do here, but more directly (i.e. just post a form) read this one:
            // https://stackoverflow.com/questions/133925/javascript-post-request-like-a-form-submit
            // in other words, in that case the simplest way forward is probably just to create that form and post it instead of using the fetch API
            window.location.reload();
        })
    }
}

function submitOnCtrlEnter(e) {
    if (e.key === "Enter" && e.ctrlKey) {
        e.preventDefault();
        e.target.form.submit();
    }
}
