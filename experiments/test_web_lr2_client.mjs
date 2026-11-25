import assert from "node:assert/strict";

globalThis.localStorage = {getItem: () => null};
globalThis.sessionStorage = {getItem: () => "usr-alice", setItem: () => {}};

const {callIdempotent, OutcomeUnknown, Problem} = await import("../web/client/api.js");

const problem = (status, type, headers = {}) =>
    new Response(JSON.stringify({type: `https://example.edu/problems/${type}`, title: type, status}), {
        status,
        headers: {"content-type": "application/problem+json", ...headers},
    });
const created = () =>
    new Response(JSON.stringify({id: "h1"}), {status: 201, headers: {"content-type": "application/json"}});

let passed = 0;
const ok = (what) => console.log(`ok   ${what}`) || passed++;

async function scenario(steps, options = {}) {
    const seen = [];
    globalThis.fetch = async (url, init) => {
        seen.push({key: init.headers["Idempotency-Key"], body: init.body, at: Date.now()});
        const step = steps[Math.min(seen.length - 1, steps.length - 1)];
        if (step === "network") throw new TypeError("Failed to fetch");
        return step();
    };
    const delays = [];
    const run = callIdempotent("POST", "/v1/holds", {
        body: {category_id: "c", seats: 1},
        baseMs: 5,
        capMs: 20,
        onRetry: ({delay}) => delays.push(delay),
        ...options,
    });
    return {seen, delays, run};
}

{
    const {seen, run} = await scenario(["network", () => problem(503, "overloaded", {"retry-after": "0"}), created]);
    const reply = await run;
    assert.equal(reply.status, 201);
    assert.equal(reply.attempts, 3);
    assert.equal(new Set(seen.map((s) => s.key)).size, 1);
    assert.equal(new Set(seen.map((s) => s.body)).size, 1);
    ok("O2.4 network error and 503 are retried with the same key and the same body");
}

{
    const {seen, delays, run} = await scenario([() => problem(503, "overloaded", {"retry-after": "1"}), created]);
    await run;
    assert.ok(delays[0] >= 1000, `delay ${delays[0]}`);
    assert.ok(seen[1].at - seen[0].at >= 990);
    ok("O2.4 the next attempt is not earlier than Retry-After");
}

{
    const {run} = await scenario([() => problem(409, "request-in-progress", {"retry-after": "0"}), created]);
    assert.equal((await run).attempts, 2);
    ok("O2.4 409 request-in-progress is retried");
}

{
    const {seen, run} = await scenario([() => problem(422, "invalid-request")]);
    await assert.rejects(run, (e) => e instanceof Problem && e.status === 422);
    assert.equal(seen.length, 1);
    ok("O2.4 a definite error (422) is not retried");
}

{
    const {seen, run} = await scenario([() => problem(409, "not-enough-seats")]);
    await assert.rejects(run, (e) => e instanceof Problem && e.status === 409);
    assert.equal(seen.length, 1);
    ok("O2.4 409 not-enough-seats is final, not retried");
}

{
    const {seen, run} = await scenario(["network"], {maxAttempts: 4});
    await assert.rejects(run, (e) => e instanceof OutcomeUnknown && e.key === seen[0].key);
    assert.equal(seen.length, 4);
    assert.equal(new Set(seen.map((s) => s.key)).size, 1);
    ok("O2.4 attempts are limited; the result is reported as unknown with the key to repeat");
}

{
    const {seen, run} = await scenario(["network"], {maxAttempts: 50, maxTimeMs: 60, baseMs: 30, capMs: 30});
    await assert.rejects(run, (e) => e instanceof OutcomeUnknown);
    assert.ok(seen.length < 50);
    ok("O2.4 total time is limited");
}

{
    const {run} = await scenario([() => problem(503, "overloaded")], {maxAttempts: 2});
    await assert.rejects(run, (e) => e instanceof Problem && e.status === 503);
    ok("persistent 503 is reported as 503: the server did not start the work");
}

{
    const delays = [];
    globalThis.fetch = async () => {
        throw new TypeError("Failed to fetch");
    };
    await assert.rejects(
        callIdempotent("POST", "/v1/holds", {body: {}, maxAttempts: 6, baseMs: 100, capMs: 800, onRetry: ({delay}) => delays.push(delay)}),
        OutcomeUnknown,
    );
    const ceilings = [100, 200, 400, 800, 800];
    assert.ok(delays.every((d, i) => d >= 0 && d <= ceilings[i]), JSON.stringify(delays));
    ok(`exponential backoff with jitter stays under 100, 200, 400, 800, 800 ms (got ${delays.map(Math.round)})`);
}

console.log(`\n${passed} checks passed`);
