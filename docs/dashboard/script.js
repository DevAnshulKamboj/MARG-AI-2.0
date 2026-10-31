const API_BASE = window.location.hostname.endsWith("github.io")
<<<<<<< HEAD
    ? "https://action-ala-experts-pubmed.trycloudflare.com"
    : (window.location.port === "8000" ? "" : "http://127.0.0.1:8001");
=======
    ? "https://action-ala-experts-pubmed.trycloudflare.com"
    : (window.location.port === "8000" ? "" : "http://127.0.0.1:8000");
>>>>>>> 85f6f14ed98e4779bffa28329a700da5efe31301
const TOKEN_KEY = "marg_access_token";
const LOGIN_URL = "../";

// remove any old token left over from the localStorage version
localStorage.removeItem(TOKEN_KEY);

function goToLogin() {
    sessionStorage.removeItem(TOKEN_KEY);
    window.location.replace(LOGIN_URL);
}

async function checkAuthentication() {
    const token = sessionStorage.getItem(TOKEN_KEY);
    if (!token) return goToLogin();

    try {
        const response = await fetch(API_BASE + "/api/me", {
            headers: { "Authorization": "Bearer " + token }
        });
        if (!response.ok) return goToLogin();

        document.body.style.visibility = "visible";
    } catch (error) {
        console.error("Authentication check failed:", error);
        goToLogin();
    }
}

window.addEventListener("pageshow", (e) => {
    if (e.persisted) checkAuthentication();
});

checkAuthentication();
