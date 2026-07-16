document.querySelectorAll(".js-copy-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const container = btn.closest(".js-copy-container");
    const src = container.querySelector(".js-copy-source");

    navigator.clipboard.writeText(src.textContent.trim());

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
