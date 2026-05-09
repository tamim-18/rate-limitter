-- Leaky bucket (meter formulation) — atomic Lua, single round trip.
--
-- KEYS[1] : bucket key (e.g. rl:lb:<client>:<endpoint>)
-- ARGV[1] : capacity      (max simultaneous "fill" before overflow)
-- ARGV[2] : window_seconds (capacity drains fully over this interval)
--
-- Returns {allowed, remaining, retry_after_ms, reset_at_ms} where
--   allowed        = 0 | 1
--   remaining      = max(0, floor(capacity - level))
--   retry_after_ms = 0 if allowed else ms until one slot drains free
--   reset_at_ms    = epoch ms when the bucket will be empty
--
-- Dual of token_bucket: level = C - tokens at every moment. We compute
-- the leak lazily (max(0, level - elapsed * r_ms)) so an idle bucket
-- costs zero work, then check `level + 1 <= capacity` to decide.

local key      = KEYS[1]
local capacity = tonumber(ARGV[1])
local window_s = tonumber(ARGV[2])

local leak_per_ms = capacity / (window_s * 1000)

local t = redis.call('TIME')
local now_ms = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)

local state = redis.call('HMGET', key, 'level', 'last_drain_ms')
local level = tonumber(state[1])
local last  = tonumber(state[2])

if level == nil then
    -- First sight of this bucket: start empty (friendly default,
    -- mirrors token_bucket's "start full").
    level = 0
    last  = now_ms
else
    local elapsed = now_ms - last
    if elapsed > 0 then
        level = math.max(0, level - elapsed * leak_per_ms)
        last  = now_ms
    end
end

local allowed        = 0
local retry_after_ms = 0
if level + 1 <= capacity then
    level   = level + 1
    allowed = 1
else
    -- Time until one slot is free again (level drains from current
    -- to (capacity - 1)).
    retry_after_ms = math.ceil((level + 1 - capacity) / leak_per_ms)
end

-- "Empty again" projection — used for X-RateLimit-Reset.
local reset_at_ms = now_ms + math.ceil(level / leak_per_ms)

redis.call('HSET',    key, 'level', level, 'last_drain_ms', last)
redis.call('PEXPIRE', key, window_s * 2000)

local remaining = capacity - level
if remaining < 0 then remaining = 0 end

return {allowed, math.floor(remaining), retry_after_ms, reset_at_ms}
