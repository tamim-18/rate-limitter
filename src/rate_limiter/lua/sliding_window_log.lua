-- Sliding window log — atomic Lua, exact rate enforcement.
--
-- KEYS[1] : log key (e.g. rl:swl:<client>:<endpoint>)
-- ARGV[1] : capacity      (max_requests inside any rolling W-second interval)
-- ARGV[2] : window_seconds
--
-- Returns {allowed, remaining, retry_after_ms, reset_at_ms} where
--   allowed        = 0 | 1
--   remaining      = max(0, capacity - count_after_decision)
--   retry_after_ms = 0 if allowed else (oldest + W) - now
--   reset_at_ms    = epoch ms when the log will next be empty
--
-- State is one ZSET per key: members are uniquified `<now_ms>:<seq>`,
-- scores are the request timestamp in ms. We prune entries older than
-- `now - W` on every call, count what remains, and decide. On allow we
-- ZADD the request; on deny we do NOT (the set IS the truth — adding a
-- denied request would push the effective rate over capacity).
--
-- TTL is refreshed every call: the set meaningfully exists only as long
-- as the client is active. Once silent for W seconds, every entry is
-- expired and the key disappears with no work required.

local key      = KEYS[1]
local capacity = tonumber(ARGV[1])
local window_s = tonumber(ARGV[2])

local t = redis.call('TIME')
local now_ms     = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local window_ms  = window_s * 1000
local cutoff     = now_ms - window_ms

-- 1. Drop entries that have aged out of the rolling window.
redis.call('ZREMRANGEBYSCORE', key, 0, cutoff)

-- 2. Count what survived. count is the number of requests in (now-W, now].
local count = redis.call('ZCARD', key)

local allowed        = 0
local retry_after_ms = 0
local reset_at_ms    = now_ms + window_ms

if count < capacity then
    -- 3a. Allow: stamp this request into the log with a unique member.
    --     `count` doubles as a per-call sequence (no two ZADDs in the
    --     same Lua execution share the same value).
    redis.call('ZADD', key, now_ms, now_ms .. ':' .. count)
    allowed     = 1
    count       = count + 1
    reset_at_ms = now_ms + window_ms
else
    -- 3b. Deny: oldest entry's age tells us when a slot opens.
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    if #oldest >= 2 then
        local oldest_ms = tonumber(oldest[2])
        retry_after_ms = (oldest_ms + window_ms) - now_ms
        if retry_after_ms < 0 then retry_after_ms = 0 end
    end
    -- Reset = when the newest entry expires; the log is empty after that.
    local newest = redis.call('ZRANGE', key, -1, -1, 'WITHSCORES')
    if #newest >= 2 then
        reset_at_ms = tonumber(newest[2]) + window_ms
    end
end

redis.call('PEXPIRE', key, window_ms)

local remaining = capacity - count
if remaining < 0 then remaining = 0 end

return {allowed, remaining, retry_after_ms, reset_at_ms}
