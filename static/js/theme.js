(function () {
  var root = document.documentElement;
  try {
    var theme = localStorage.getItem("tn_theme");
    if (!theme) theme = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    root.dataset.theme = theme;
    root.dataset.view = localStorage.getItem("tn_view") || "feed";
    if (localStorage.getItem("tn_dev") === "1") root.classList.add("dev-view");
  } catch (e) {
    root.dataset.theme = "light"; root.dataset.view = "feed";
  }
})();
