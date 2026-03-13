/* Scholar Watch Dashboard JavaScript */

document.addEventListener("DOMContentLoaded", function () {
    // Tab switching
    document.querySelectorAll(".tab-btn").forEach(function (btn) {
        btn.addEventListener("click", function () {
            var group = btn.closest(".tabs").dataset.tabGroup;
            // Deactivate all tabs and panels in this group
            document.querySelectorAll('.tabs[data-tab-group="' + group + '"] .tab-btn').forEach(function (b) {
                b.classList.remove("active");
            });
            document.querySelectorAll('.tab-panel[data-tab-group="' + group + '"]').forEach(function (p) {
                p.classList.remove("active");
            });
            // Activate clicked tab and its panel
            btn.classList.add("active");
            var panel = document.getElementById(btn.dataset.tab);
            if (panel) {
                panel.classList.add("active");
                // Plotly charts need a resize when they become visible
                panel.querySelectorAll(".js-plotly-plot").forEach(function (plot) {
                    Plotly.Plots.resize(plot);
                });
            }
        });
    });

    // Auto-refresh charts if data attributes are present
    document.querySelectorAll("[data-refresh-url]").forEach(function (el) {
        const url = el.dataset.refreshUrl;
        const interval = parseInt(el.dataset.refreshInterval || "60000", 10);

        if (url && interval > 0) {
            setInterval(function () {
                fetch(url)
                    .then(function (r) { return r.json(); })
                    .then(function (data) {
                        // Dispatch custom event for chart update
                        el.dispatchEvent(new CustomEvent("data-update", { detail: data }));
                    })
                    .catch(function (err) {
                        console.error("Refresh failed:", err);
                    });
            }, interval);
        }
    });
});

/**
 * Submit the compare form with selected researcher IDs.
 */
function submitCompare() {
    var form = document.getElementById("compare-form");
    if (form) {
        form.submit();
    }
}
