function copyText(text) {
  if (navigator.clipboard) {
    return navigator.clipboard.writeText(text);
  }

  // navigator.clipboard is only exposed in secure contexts. Bugsink should also work in local/internal HTTP setups,
  // such as http://bugsink:8000, where the copy button is a convenience and the failure mode is mild. execCommand is
  // deprecated and may disappear eventually, but it is still widely supported enough to be a useful fallback here.
  const textArea = document.createElement("textarea");
  textArea.value = text;
  textArea.style.position = "fixed";
  textArea.style.top = "0";
  textArea.style.left = "0";
  textArea.style.opacity = "0";

  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();

  const copied = document.execCommand("copy");
  document.body.removeChild(textArea);

  if (!copied) {
    throw new Error("copy failed");
  }
}

document.querySelectorAll(".js-copy-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const container = btn.closest(".js-copy-container");
    const src = container.querySelector(".js-copy-source");

    copyText(src.textContent.trim());

    const label = btn.querySelector(".js-copy-label");
    const copyIcon = btn.querySelector(".js-copy-svg");
    const copiedIcon = btn.querySelector(".js-copied-svg");

    label.textContent = "Copied!";
    copyIcon.classList.add("hidden");
    copiedIcon.classList.remove("hidden");

    setTimeout(() => {
      label.textContent = "Copy";
      copyIcon.classList.remove("hidden");
      copiedIcon.classList.add("hidden");
    }, 2500);
  });
});
