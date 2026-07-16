(function () {
    const meta = document.querySelector('meta[name="csrf-token"]');
    const token = meta ? meta.getAttribute("content") : "";
    if (!token) return;

    const fieldName = "csrf_token";
    const unsafeMethods = new Set(["POST", "PUT", "PATCH", "DELETE"]);

    function isUnsafeMethod(method) {
        return unsafeMethods.has(String(method || "GET").toUpperCase());
    }

    function isSameOrigin(url) {
        if (!url) return true;
        try {
            return new URL(url, window.location.href).origin === window.location.origin;
        } catch (e) {
            return false;
        }
    }

    document.addEventListener("submit", function (event) {
        const form = event.target;
        if (!form || form.tagName !== "FORM") return;
        if (!isUnsafeMethod(form.method)) return;
        if (!isSameOrigin(form.action)) return;
        if (form.querySelector(`input[name="${fieldName}"]`)) return;

        const input = document.createElement("input");
        input.type = "hidden";
        input.name = fieldName;
        input.value = token;
        form.appendChild(input);
    }, true);

    if (window.fetch) {
        const originalFetch = window.fetch.bind(window);
        window.fetch = function (input, init) {
            const requestInit = init || {};
            const method = requestInit.method || (input && input.method) || "GET";
            const url = typeof input === "string" ? input : input && input.url;

            if (isUnsafeMethod(method) && isSameOrigin(url)) {
                const headers = new Headers(requestInit.headers || (input && input.headers) || {});
                if (!headers.has("X-CSRFToken") && !headers.has("X-CSRF-Token")) {
                    headers.set("X-CSRFToken", token);
                }
                requestInit.headers = headers;
            }

            return originalFetch(input, requestInit);
        };
    }
}());
