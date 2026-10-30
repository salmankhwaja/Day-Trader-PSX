/* Applies the saved theme before first paint. A separate file because the dashboard's
   Content-Security-Policy allows no inline scripts (dashboard.py inlines it in the one-file build). */
(function () {
  try {
    var t = JSON.parse(localStorage.getItem("pkm.theme"));
    if (t) document.documentElement.setAttribute("data-theme", t);
  } catch (e) {}
})();
