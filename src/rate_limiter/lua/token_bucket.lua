-- Token bucket — atomic Lua, single round trip per request.
--
-- KEYS[1] : bucket key (e.g. rl:tb:<client>:<endpoint>)
-- ARGV[1] : capacity        (max_requests)
-- ARGV[2] : window_seconds  (capacity refilled fully over this window)
--
-- Returns {allowed, remaining, retry_after_ms, reset_at_ms} where
--   allowed        = 0 | 1
--   remaining      = floor(tokens left after this request)
--   retry_after_ms = 0 if allowed else ms until 1 token is available
--   reset_at_ms    = epoch ms when the bucket will be full again
--
-- State is one hash per key: {tokens (float), last_refill_ms (int)}.
-- Refill is lazy (computed on read) so an idle bucket costs zero work.
-- TTL is 2× window so abandoned buckets evict themselves; live buckets
-- get their TTL refreshed on every call.

local key      = KEYS[1]
local capacity = tonumber(ARGV[1])
local window_s = tonumber(ARGV[2])

-- Tokens per millisecond. e.g. 100 req / 60s = 100/60000 ≈ 0.00167 tok/ms.
local refill_per_ms = capacity / (window_s * 1000)

-- Source time from Redis. Never trust the client's clock — replicas drift.
local t = redis.call('TIME')
local now_ms = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)

local state = redis.call('HMGET', key, 'tokens', 'last_refill_ms')
local tokens = tonumber(state[1])
local last   = tonumber(state[2])

if tokens == nil then
    -- First sight of this bucket: start full. Generous, but matches the
    -- principle of least surprise (a fresh client should not be denied).
    tokens = capacity
    last   = now_ms
else
    local elapsed = now_ms - last
    if elapsed > 0 then
        tokens = math.min(capacity, tokens + elapsed * refill_per_ms)
        last   = now_ms
    end
end

local allowed        = 0
local retry_after_ms = 0
if tokens >= 1 then
    tokens  = tokens - 1
    allowed = 1
else
    -- Time until tokens crosses 1. ceil so we never tell a client to come
    -- back too early and get denied a second time.
    retry_after_ms = math.ceil((1 - tokens) / refill_per_ms)
end

-- "Full again" projection — used for X-RateLimit-Reset.
local missing     = capacity - tokens
local reset_at_ms = now_ms + math.ceil(missing / refill_per_ms)

redis.call('HSET',   key, 'tokens', tokens, 'last_refill_ms', last)
redis.call('PEXPIRE', key, window_s * 2000)

return {allowed, math.floor(tokens), retry_after_ms, reset_at_ms}
