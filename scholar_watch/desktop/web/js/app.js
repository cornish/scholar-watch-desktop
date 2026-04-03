/* Scholar Watch Desktop - Shared JavaScript */

function escapeHtml(str) {
    if (!str) return "";
    var div = document.createElement("div");
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

function showAlert(message, type) {
    var area = document.getElementById("alert-area");
    if (!area) return;
    var div = document.createElement("div");
    div.className = "alert alert-" + (type || "info");
    div.textContent = message;
    area.appendChild(div);
    setTimeout(function () { div.remove(); }, 5000);
}

function renderDelta(deltas, field) {
    if (!deltas || deltas[field] == null || deltas[field] === 0) return "";
    var val = deltas[field];
    if (val > 0) {
        return ' <span class="delta-indicator delta-up" title="since ' + escapeHtml(deltas.since) + '">' +
            '<span class="delta-arrow">&#9650;</span>' + val + '</span>';
    } else {
        return ' <span class="delta-indicator delta-down" title="since ' + escapeHtml(deltas.since) + '">' +
            '<span class="delta-arrow">&#9660;</span>' + Math.abs(val) + '</span>';
    }
}

function renderChart(divId, plotlyJson) {
    var el = document.getElementById(divId);
    if (!el || !plotlyJson) return;
    var data = plotlyJson.data || [];
    var layout = plotlyJson.layout || {};
    layout.autosize = true;
    Plotly.newPlot(el, data, layout, { responsive: true });
}

function initTabs() {
    document.querySelectorAll(".tab-btn").forEach(function (btn) {
        btn.addEventListener("click", function () {
            var group = btn.closest(".tabs").dataset.tabGroup;
            document.querySelectorAll('.tabs[data-tab-group="' + group + '"] .tab-btn').forEach(function (b) {
                b.classList.remove("active");
            });
            document.querySelectorAll('.tab-panel[data-tab-group="' + group + '"]').forEach(function (p) {
                p.classList.remove("active");
            });
            btn.classList.add("active");
            var panel = document.getElementById(btn.dataset.tab);
            if (panel) {
                panel.classList.add("active");
                // Resize Plotly charts when tab becomes visible
                panel.querySelectorAll(".js-plotly-plot").forEach(function (plot) {
                    Plotly.Plots.resize(plot);
                });
            }
        });
    });
}

async function updateNotifBadge() {
    try {
        var count = await eel.get_unread_count()();
        var badge = document.getElementById("notif-badge");
        if (badge) {
            if (count > 0) {
                badge.textContent = count;
                badge.style.display = "flex";
            } else {
                badge.style.display = "none";
            }
        }
    } catch (e) {
        // Ignore - eel may not be ready yet
    }
}
