export const API = localStorage.getItem("api") ?? "http://localhost:8080";

export class Problem extends Error {
    constructor(status, body, retryAfter = null) {
        super(body?.title ?? `HTTP ${status}`);
        this.status = status;
        this.body = body;
        this.retryAfter = retryAfter;
    }
}

export class OutcomeUnknown extends Error {
    constructor(key, last) {
        super("Результат невідомий");
        this.key = key;
        this.last = last;
    }
}

export async function call(method, path, {body, headers = {}} = {}) {
    let reply;
    try {
        reply = await fetch(API + path, {
            method,
            credentials: "include",
            headers: {
                ...(body !== undefined ? {"Content-Type": "application/json"} : {}),
                ...headers,
            },
            body: body !== undefined ? JSON.stringify(body) : undefined,
        });
    } catch (error) {
        throw new Problem(0, {title: "Немає відповіді від сервера", detail: String(error)});
    }

    const type = reply.headers.get("content-type") ?? "";
    const raw = await reply.text();
    const data = type.includes("json") && raw ? JSON.parse(raw) : raw;
    if (!reply.ok) {
        const retryAfter = Number(reply.headers.get("retry-after"));
        throw new Problem(
            reply.status,
            typeof data === "object" ? data : {title: data},
            Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : null,
        );
    }

    return {status: reply.status, headers: reply.headers, data};
}

export const login = (loginName, password) => call("POST", "/v1/auth/login", {body: {login: loginName, password}});

export const logout = () => call("POST", "/v1/auth/logout");

export const me = () => call("GET", "/v1/me");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const isInProgress = (error) => error.status === 409 && String(error.body?.type ?? "").endsWith("request-in-progress");

export async function callIdempotent(
    method,
    path,
    {body, key = crypto.randomUUID(), maxAttempts = 5, maxTimeMs = 20000, baseMs = 400, capMs = 5000, onRetry} = {},
) {
    const started = Date.now();
    let last = null;
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
        try {
            const reply = await call(method, path, {body, headers: {"Idempotency-Key": key}});
            return {...reply, key, attempts: attempt};
        } catch (error) {
            if (!(error instanceof Problem)) {
                throw error;
            }
            last = error;
            const retryable = [0, 502, 503, 504].includes(error.status) || isInProgress(error);
            if (!retryable) {
                throw error;
            }
            if (attempt === maxAttempts) {
                break;
            }
            const backoff = Math.random() * Math.min(capMs, baseMs * 2 ** (attempt - 1));
            const delay = Math.max(backoff, (error.retryAfter ?? 0) * 1000);
            if (Date.now() - started + delay > maxTimeMs) {
                break;
            }
            onRetry?.({attempt, delay, error});
            await sleep(delay);
        }
    }
    if (last.status === 503) {
        throw last;
    }
    throw new OutcomeUnknown(key, last);
}

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
