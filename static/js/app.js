(function () {
  "use strict";
  var root = document.documentElement;
  var csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || "";
  var ROUTE_RE = /^[A-Z0-9][A-Z0-9._-]{0,11}$/;

  function store(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* storage unavailable */ } }
  function load(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }

  function toast(message, kind) {
    var box = document.getElementById("toasts");
    if (!box) return;
    var el = document.createElement("div");
    el.className = "toast toast-" + kind;
    el.textContent = message;
    box.appendChild(el);
    setTimeout(function () { el.remove(); }, kind === "error" ? 9000 : 5000);
  }

  function ago(iso) {
    var seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
    var future = seconds < 0; seconds = Math.abs(seconds);
    var text;
    if (seconds < 60) text = "moments";
    else if (seconds < 3600) text = Math.floor(seconds / 60) + " min";
    else if (seconds < 86400) { var h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60); text = h + " h" + (m ? " " + m + " min" : ""); }
    else { var d = Math.floor(seconds / 86400), hh = Math.floor((seconds % 86400) / 3600); text = d + " d" + (hh ? " " + hh + " h" : ""); }
    return future ? "in " + text : text + " ago";
  }
  function tickTimes() {
    document.querySelectorAll("time[data-ts]").forEach(function (el) {
      if (el.closest(".timeline")) return;
      el.textContent = ago(el.dataset.ts);
    });
  }

  /* ---- theme, developer view, layout ---- */
  var themeBtn = document.getElementById("theme-toggle");
  function paintTheme() {
    var dark = root.dataset.theme === "dark";
    if (themeBtn) { themeBtn.textContent = dark ? "Light mode" : "Dark mode"; themeBtn.setAttribute("aria-pressed", dark ? "true" : "false"); }
  }
  if (themeBtn) {
    themeBtn.addEventListener("click", function () {
      root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
      store("tn_theme", root.dataset.theme); paintTheme();
    });
    paintTheme();
  }
  var devToggle = document.getElementById("dev-toggle");
  if (devToggle) {
    devToggle.checked = root.classList.contains("dev-view");
    devToggle.addEventListener("change", function () {
      root.classList.toggle("dev-view", devToggle.checked);
      store("tn_dev", devToggle.checked ? "1" : "0");
    });
  }
  function paintView() {
    document.querySelectorAll(".seg button[data-view]").forEach(function (b) {
      b.setAttribute("aria-pressed", b.dataset.view === root.dataset.view ? "true" : "false");
    });
  }
  document.querySelectorAll(".seg button[data-view]").forEach(function (b) {
    b.addEventListener("click", function () { root.dataset.view = b.dataset.view; store("tn_view", b.dataset.view); paintView(); });
  });
  paintView();

  /* ---- refresh and live change banner ---- */
  var button = document.getElementById("refresh-btn");
  if (button) {
    button.addEventListener("click", function () {
      var label = button.querySelector(".btn-label");
      button.disabled = true; button.classList.add("is-loading"); button.setAttribute("aria-busy", "true");
      label.textContent = "Checking sources...";
      fetch("/api/refresh", { method: "POST", headers: { "X-CSRF-Token": csrf } })
        .then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); })
        .then(function (res) {
          if (res.ok) {
            var s = res.data.summary;
            toast("Checked " + s.sources_checked + " source(s): " + s.new + " new, " + s.revised + " revised, " + s.withdrawn + " withdrawn.", "success");
            setTimeout(function () { window.location.reload(); }, 900);
          } else {
            toast(res.data.error || "The refresh failed.", "error");
            if (res.data.detail) { setTimeout(function () { window.location.reload(); }, 2500); }
          }
        })
        .catch(function () { toast("Could not reach the TransitNotice server. Check that it is running.", "error"); })
        .finally(function () {
          button.disabled = false; button.classList.remove("is-loading"); button.removeAttribute("aria-busy");
          label.textContent = "Check sources now";
        });
    });
  }
  var verify = document.querySelector("[data-change-token]");
  if (verify) {
    var initial = verify.dataset.changeToken;
    setInterval(function () {
      fetch("/api/stats").then(function (r) { return r.json(); }).then(function (data) {
        if (data.ok && data.change_token !== initial) {
          var banner = document.getElementById("change-banner");
          if (banner) banner.hidden = false;
        }
      }).catch(function () {});
    }, 20000);
  }
  document.querySelectorAll(".filters select, .filters input[type=date]").forEach(function (el) {
    el.addEventListener("change", function () { el.form.submit(); });
  });

  /* ---- weather ---- */
  var weather = document.getElementById("weather");
  if (weather) {
    function line(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; e.textContent = text; return e; }
    fetch(weather.dataset.url).then(function (r) { return r.json(); }).then(function (w) {
      weather.replaceChildren(line("h2", "", "Weather"));
      if (!w.ok) { weather.appendChild(line("p", "muted small", w.error || "Weather is unavailable right now.")); return; }
      var main = line("div", "weather-main", "");
      main.appendChild(line("span", "weather-temp", Math.round(w.temperature_c) + "\u00b0C"));
      main.appendChild(line("span", "", w.summary));
      weather.appendChild(main);
      var dl = document.createElement("dl");
      [["Wind", w.wind_kmh + " km/h"], ["Rain now", w.precipitation_mm + " mm"], ["Area", w.label]].forEach(function (p) {
        dl.appendChild(line("dt", "", p[0])); dl.appendChild(line("dd", "", p[1]));
      });
      weather.appendChild(dl);
      var credit = document.createElement("a");
      credit.href = w.credit_url; credit.textContent = w.credit; credit.rel = "noopener noreferrer"; credit.target = "_blank";
      var p = line("p", "weather-credit", "Context only. "); p.appendChild(credit); weather.appendChild(p);
    }).catch(function () {
      weather.replaceChildren(line("h2", "", "Weather"), line("p", "muted small", "Weather is unavailable right now."));
    });
  }

  /* ---- follow routes (needs an account) ---- */
  var account = document.body.dataset.account === "1";
  var followed = (document.body.dataset.followed || "").split(",").filter(Boolean);
  function paintFollow() {
    document.querySelectorAll("[data-follow]").forEach(function (b) {
      var on = followed.indexOf(b.dataset.follow) !== -1;
      b.textContent = (on ? "Following " : "Follow ") + b.dataset.follow;
      b.setAttribute("aria-pressed", on ? "true" : "false"); b.classList.toggle("is-on", on);
    });
  }
  function change(action, route, done) {
    route = route.toUpperCase();
    if (!ROUTE_RE.test(route)) { toast("That is not a valid route ID.", "error"); return; }
    if (!account) {
      window.location.assign("/account?tab=login&next=" + encodeURIComponent(window.location.pathname + window.location.search));
      return;
    }
    fetch("/api/my-routes", { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify({ action: action, route: route }) })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.ok) { followed = d.routes; paintFollow(); toast(action === "add" ? "Following route " + route + "." : "Stopped following " + route + ".", "success"); if (done) done(); }
        else toast(d.error || "Could not save.", "error");
      })
      .catch(function () { toast("Could not reach the server.", "error"); });
  }
  document.querySelectorAll("[data-follow]").forEach(function (b) {
    b.addEventListener("click", function () { change(followed.indexOf(b.dataset.follow) === -1 ? "add" : "remove", b.dataset.follow); });
  });
  paintFollow();

  var mine = document.getElementById("my-routes");
  if (mine) {
    document.querySelectorAll("[data-unfollow]").forEach(function (b) {
      b.addEventListener("click", function () { change("remove", b.dataset.unfollow, function () { window.location.reload(); }); });
    });
    var add = document.getElementById("add-route-btn"), sel = document.getElementById("add-route-select");
    if (add && sel) add.addEventListener("click", function () { if (sel.value) change("add", sel.value, function () { window.location.reload(); }); });
  }

  /* ---- back button: previous page of this site, else the Notices list ---- */
  var back = document.querySelector("[data-back]");
  if (back) {
    back.addEventListener("click", function (e) {
      var sameSite = false;
      try { sameSite = document.referrer && new URL(document.referrer).origin === window.location.origin; } catch (err) { sameSite = false; }
      if (sameSite && window.history.length > 1) { e.preventDefault(); window.history.back(); }
    });
  }

  tickTimes();
  setInterval(tickTimes, 30000);
})();
