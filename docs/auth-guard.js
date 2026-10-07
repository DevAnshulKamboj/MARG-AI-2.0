(function () {
  var TOKEN_KEY = "marg_access_token";
  var LOGIN_PAGE = "../index.html";

  function check() {
    if (!sessionStorage.getItem(TOKEN_KEY)) {
      window.stop(); // stop loading the rest of the page (and logout.js)
      document.documentElement.innerHTML =
        '<head><title>Not authorised</title></head>' +
        '<body style="margin:0;font-family:Arial,sans-serif;background:#202124;color:#bdc1c6;text-align:center;padding-top:15vh">' +
        '<h2 style="color:#e8eaed;font-weight:500">This page isn\'t working</h2>' +
        '<p>You are not authorised to view this page. Please log in.</p>' +
        '<p style="font-size:13px;color:#9aa0a6">HTTP ERROR 403</p>' +
        '<a href="' + LOGIN_PAGE + '" style="color:#8ab4f8;text-decoration:none">Go to login</a>' +
        '</body>';
    }
  }

  check();                                    // normal load
  window.addEventListener("pageshow", check); // Back/Forward restores
})();