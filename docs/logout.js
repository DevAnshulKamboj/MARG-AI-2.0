    (function () {
    
          var LOGIN_PAGE = "../index.html";
  var TOKEN_KEY = "marg_access_token";

  // auth-guard.js already shows the error page when logged out
  if (!sessionStorage.getItem(TOKEN_KEY)) return;

  // Popup styles
  var style = document.createElement("style");
  style.textContent =
    ".lo-overlay{position:fixed;inset:0;background:rgba(0,0,0,.5);display:none;align-items:center;justify-content:center;z-index:9999}" +
    ".lo-overlay.show{display:flex}" +
    ".lo-box{background:#fff;width:340px;max-width:90%;border-radius:6px;border-top:4px solid #263e69;padding:22px;font-family:Arial,Helvetica,sans-serif;box-shadow:0 8px 24px rgba(0,0,0,.3)}" +
    ".lo-title{margin:0 0 8px;font-size:18px;color:#263e69}" +
    ".lo-text{margin:0 0 20px;font-size:14px;color:#333}" +
    ".lo-actions{display:flex;justify-content:flex-end;gap:10px}" +
    ".lo-btn{padding:8px 18px;font-size:14px;border-radius:4px;cursor:pointer;border:1px solid #263e69}" +
    ".lo-cancel{background:#fff;color:#263e69}" +
    ".lo-confirm{background:#263e69;color:#fff}" +
    "#logoutLink{color:inherit;text-decoration:none;cursor:pointer}" +
    "#logoutLink:hover{text-decoration:underline}";
  document.head.appendChild(style);

  // Popup HTML
  var overlay = document.createElement("div");
  overlay.className = "lo-overlay";
  overlay.innerHTML =
    '<div class="lo-box" role="dialog" aria-modal="true" aria-labelledby="lo-title">' +
      '<h3 class="lo-title" id="lo-title">Logout</h3>' +
      '<p class="lo-text">Are you sure you want to logout?</p>' +
      '<div class="lo-actions">' +
        '<button type="button" class="lo-btn lo-cancel">Cancel</button>' +
        '<button type="button" class="lo-btn lo-confirm">Logout</button>' +
      '</div>' +
    '</div>';
  document.body.appendChild(overlay);

  function open()  { overlay.classList.add("show"); }
  function close() { overlay.classList.remove("show"); }

  function doLogout() {
    sessionStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(TOKEN_KEY);
    window.location.replace(LOGIN_PAGE);
  }

  overlay.querySelector(".lo-cancel").addEventListener("click", close);
  overlay.querySelector(".lo-confirm").addEventListener("click", doLogout);
  overlay.addEventListener("click", function (e) { if (e.target === overlay) close(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") close(); });

  var link = document.getElementById("logoutLink");
  if (link) {
    link.addEventListener("click", function (e) { e.preventDefault(); open(); });
  }
})();