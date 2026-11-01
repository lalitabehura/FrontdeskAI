/* Frontdesk AI widget loader.
 * Usage: <script src="https://YOUR_APP/widget.js" data-key="wk_..." async></script>
 * Creates an isolated iframe (no access to the host page) and resizes it on request. */
(function () {
  "use strict";
  var script = document.currentScript || document.querySelector('script[src*="widget.js"][data-key]');
  if (!script || window.__frontdeskLoaded) return;
  window.__frontdeskLoaded = true;
  var key = script.getAttribute("data-key") || "";
  if (!/^wk_[A-Za-z0-9_-]{10,60}$/.test(key)) { console.warn("Frontdesk: invalid data-key"); return; }
  var origin = new URL(script.src, location.href).origin;
  var position = script.getAttribute("data-position") === "left" ? "left" : "right";

  var frame = document.createElement("iframe");
  frame.src = origin + "/widget/" + encodeURIComponent(key) + "?page=" + encodeURIComponent(location.href.slice(0, 400));
  frame.title = "Chat with us";
  frame.setAttribute("allow", "");
  frame.setAttribute("referrerpolicy", "strict-origin-when-cross-origin");
  var s = frame.style;
  s.position = "fixed"; s.bottom = "16px"; s[position] = "16px"; s.width = "84px"; s.height = "84px";
  s.border = "0"; s.zIndex = "2147483000"; s.background = "transparent"; s.colorScheme = "normal";
  s.maxWidth = "calc(100vw - 32px)"; s.maxHeight = "calc(100vh - 32px)";

  window.addEventListener("message", function (e) {
    if (e.origin !== origin || e.source !== frame.contentWindow || !e.data || e.data.type !== "fd:state") return;
    var small = window.innerWidth < 480;
    if (e.data.position === "left" || e.data.position === "right") {
      s.left = s.right = "auto"; s[e.data.position] = small && e.data.open ? "0" : "16px";
    }
    if (e.data.open) {
      s.width = small ? "100vw" : "400px"; s.height = small ? "100vh" : "640px";
      s.bottom = small ? "0" : "16px"; s.maxWidth = small ? "100vw" : "calc(100vw - 32px)";
      s.maxHeight = small ? "100vh" : "calc(100vh - 32px)";
    } else {
      s.width = "84px"; s.height = "84px"; s.bottom = "16px";
    }
  });
  (document.body || document.documentElement).appendChild(frame);
})();
