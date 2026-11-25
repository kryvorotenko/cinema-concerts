// Calls to the system through nginx: base address, current user (X-User-Id until Web LR3), Problem Details.
// Serve the client outside Compose:  python -m http.server 8081 --bind 127.0.0.1 --directory web/client
// The origin 127.0.0.1:8081 is not the allowed CLIENT_ORIGIN: open http://localhost:8081 instead.

export const API = localStorage.getItem("api") ?? "http://localhost:8080";

export class Problem extends Error {
    constructor(status, body) {
        super(body?.title ?? `HTTP ${status}`);
        this.status = status;
        this.body = body;
    }
}

let userId = sessionStorage.getItem("user") ?? "";

export function setUser(value) {
    userId = value;
    sessionStorage.setItem("user", value);
}

export const currentUser = () => userId;

export async function call(method, path, {body, headers = {}} = {}) {
    let reply;
    try {
        reply = await fetch(API + path, {
            method,
            headers: {
                ...(body !== undefined ? {"Content-Type": "application/json"} : {}),
                ...(userId ? {"X-User-Id": userId} : {}),
                ...headers,
            },
            body: body !== undefined ? JSON.stringify(body) : undefined,
        });
    } catch (error) {
        // no answer at all: the request may or may not have been executed
        throw new Problem(0, {title: "Немає відповіді від сервера", detail: String(error)});
    }

    const type = reply.headers.get("content-type") ?? "";
    const data = type.includes("json") ? await reply.json() : await reply.text();
    if (!reply.ok) {
        throw new Problem(reply.status, typeof data === "object" ? data : {title: data});
    }

    return {status: reply.status, headers: reply.headers, data};
}

// O1.5 on the client: follow next_cursor until it is null, so that no page is missed.
export async function readAllPages(path, limit = 20) {
    const items = [];
    let cursor = null;
    do {
        const query = new URLSearchParams({limit: String(limit), ...(cursor ? {cursor} : {})});
        const {data} = await call("GET", `${path}?${query}`);
        items.push(...data.items);
        cursor = data.next_cursor ?? null;
    } while (cursor);
    return items;
}

export const money = ({amount_minor, currency}) => `${(amount_minor / 100).toFixed(2)} ${currency}`;
