(function () {
  "use strict";
  var el = document.getElementById("map");
  if (!el || !window.L) return;
  var pins = [];
  try { pins = JSON.parse(el.dataset.pins || "[]"); } catch (e) { pins = []; }
  var center = (el.dataset.center || "0,0").split(",").map(Number);
  var COLORS = { active: "#17a05f", upcoming: "#2f6fe4", stale: "#e3a008", expired: "#7b8798", withdrawn: "#d64533" };

  var map = L.map(el, { scrollWheelZoom: false }).setView(center, 12);
  map.on("click", function () { map.scrollWheelZoom.enable(); });

  if (el.dataset.tiles === "1") {
    var tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors'
    }).addTo(map);
    var warned = false;
    tiles.on("tileerror", function () {
      if (warned) return;
      warned = true;
      var note = document.createElement("p");
      note.className = "map-note";
      note.textContent = "Map tiles could not load (are you offline?). Pins are still placed by their coordinates.";
      el.insertAdjacentElement("afterend", note);
    });
  }

  function popup(pin) {
    var box = document.createElement("div");
    var link = document.createElement("a");
    link.href = pin.url; link.textContent = pin.title; link.style.fontWeight = "600";
    box.appendChild(link);
    [["Routes", pin.routes.join(", ")], ["Status", pin.status], ["Area", pin.area || "not stated"]].forEach(function (row) {
      var p = document.createElement("div"); p.textContent = row[0] + ": " + row[1]; box.appendChild(p);
    });
    return box;
  }

  var points = [];
  pins.forEach(function (pin) {
    var marker = L.circleMarker([pin.lat, pin.lon], {
      radius: 11, color: "#ffffff", weight: 3, fillColor: COLORS[pin.status] || "#475569", fillOpacity: 0.95
    }).addTo(map);
    marker.bindPopup(popup(pin));
    marker.bindTooltip(pin.routes.join(", "), { permanent: false });
    points.push([pin.lat, pin.lon]);
  });

  if (points.length === 1) map.setView(points[0], 15);
  else if (points.length > 1) map.fitBounds(points, { padding: [40, 40], maxZoom: 15 });
  else if (!el.dataset.single) {
    var empty = document.createElement("p");
    empty.className = "map-note";
    empty.textContent = "No notices in this view have coordinates, so there is nothing to pin.";
    el.insertAdjacentElement("afterend", empty);
  }
})();
