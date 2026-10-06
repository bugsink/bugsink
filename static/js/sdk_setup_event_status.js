(function () {
    const container = document.getElementById("sdk-setup-event-status");
    if (!container) {
        return;
    }

    const message = container.querySelector("[data-event-status-message]");
    const initialEventCount = Number(container.dataset.eventCount);
    let eventCount = initialEventCount;
    let isVisible = false;

    function showEventCount(newEventCount) {
        const receivedEventCount = newEventCount - initialEventCount;
        if (receivedEventCount <= 0) {
            return;
        }

        const eventWord = receivedEventCount === 1 ? "event" : "events";
        message.textContent =
            `${receivedEventCount.toLocaleString()} ${eventWord} received since opening this page.`;

        if (!isVisible) {
            container.style.visibility = "visible";
            container.removeAttribute("aria-hidden");
            window.requestAnimationFrame(() => {
                container.style.gridTemplateRows = "1fr";
                container.style.opacity = "1";
                container.style.marginTop = "1rem";
            });
            isVisible = true;
        }
    }

    async function pollEventCount() {
        try {
            const response = await fetch(container.dataset.statusUrl, {
                cache: "no-store",
                headers: {"Accept": "application/json"},
            });
            const contentType = response.headers.get("Content-Type") || "";
            if (response.ok && contentType.startsWith("application/json")) {
                const data = await response.json();
                const newEventCount = data.digested_event_count;

                if (newEventCount !== eventCount) {
                    showEventCount(newEventCount);
                    eventCount = newEventCount;
                }
            }
        } catch (error) {
            console.warn("Failed to fetch SDK setup status:", error);
        } finally {
            window.setTimeout(pollEventCount, 2000);
        }
    }

    window.setTimeout(pollEventCount, 2000);
})();
