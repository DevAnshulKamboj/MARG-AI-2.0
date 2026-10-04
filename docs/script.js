// ================= CONFIG =================

// Leave empty when this page is served by the FastAPI app itself
// (http://localhost:8000/). If you host the HTML/CSS/JS somewhere else
// (GitHub Pages, Netlify), set this to your deployed backend URL, e.g.
// "https://your-backend.example.com" (no trailing slash).
const API_BASE = window.location.hostname.endsWith("github.io")
    ? "https://thousands-settle-performer-airfare.trycloudflare.com"
    : (window.location.port === "8000" ? "" : "http://127.0.0.1:8000");


// Where to send the user after a successful login.
// Set this to your dashboard page once you have one, e.g. "/static/dashboard.html".
const DASHBOARD_URL = "dashboard/";
const TOKEN_KEY = "marg_access_token";


// ================= CAPTCHA =================
// Note: this CAPTCHA runs in the browser only. It stops accidental
// submits but is not real bot protection (the API does not check it).

let currentCaptcha = "";

function generateCaptcha() {
    const characters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";

    currentCaptcha = "";
    for (let i = 0; i < 5; i++) {
        currentCaptcha += characters[Math.floor(Math.random() * characters.length)];
    }

    document.getElementById("captchaCode").textContent = currentCaptcha;
}

// Generate CAPTCHA when page loads
generateCaptcha();


// ================= HELPERS =================

function showMessage(text, isError = true) {
    const box = document.getElementById("message");
    box.textContent = text;
    box.className = "message " + (isError ? "error" : "success");
}

function setLoading(isLoading) {
    const btn = document.getElementById("signinBtn");
    btn.disabled = isLoading;
    btn.textContent = isLoading ? "Signing in..." : "↪ Sign in";
}

// FastAPI returns errors as {"detail": "..."} for our own errors and
// {"detail": [{msg: "..."}]} for validation errors (e.g. bad email format).
function extractError(data, fallback) {
    if (data && typeof data.detail === "string") return data.detail;
    if (data && Array.isArray(data.detail) && data.detail.length > 0) {
        const msg = data.detail[0].msg || fallback;
        return msg.replace(/^Value error, /, "");
    }
    return fallback;
}


// ================= LOGIN =================

async function loginUser() {
    const email = document.getElementById("username").value.trim();
    const password = document.getElementById("password").value;
    const captcha = document.getElementById("captchaInput").value.trim();

    if (email === "") {
        showMessage("Please enter your email");
        return;
    }

    if (password === "") {
        showMessage("Please enter your password");
        return;
    }

    if (captcha.toUpperCase() !== currentCaptcha) {
        showMessage("Invalid CAPTCHA");
        generateCaptcha();
        document.getElementById("captchaInput").value = "";
        return;
    }

    setLoading(true);
    showMessage("", false);

    try {
        const response = await fetch(API_BASE + "/api/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email: email, password: password }),
        });

        const data = await response.json().catch(() => null);

        if (!response.ok) {
            showMessage(extractError(data, "Login failed. Please try again."));
            generateCaptcha();
            document.getElementById("captchaInput").value = "";
            return;
        }

        //Clear any old token from the previous localStorage version
        localStorage.removeItem(TOKEN_KEY);

        // sessionStorage is tied to this tab and wiped when the tab closes
        sessionStorage.setItem(TOKEN_KEY, data.access_token);
        showMessage("Login successful", false);

        if (DASHBOARD_URL) {
            window.location.replace(DASHBOARD_URL);   // same tab, so the token comes along
            return;
        }
            
    } catch (err) {
        showMessage("Cannot reach the server. Please try again.");
    } finally {
        setLoading(false);
    }
}


// ================= PRESS ENTER TO SIGN IN =================

["username", "password", "captchaInput"].forEach(function (id) {
    document.getElementById(id).addEventListener("keydown", function (e) {
        if (e.key === "Enter") {
            loginUser();
        }
    });
});
