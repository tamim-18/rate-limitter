-- Fixed window counter — atomic Lua, single round trip per request.
--
-- KEYS[1] : key prefix (e.g. rl:fw:<client>:<endpoint>); window index
--           is appended here so the middleware stays clock-agnostic.
-- ARGV[1] : capacity      (max_requests per window)
-- ARGV[2] : window_seconds
--
-- Returns {allowed, remaining, retry_after_ms, reset_at_ms} where
--   allowed        = 0 | 1
--   remaining      = max(0, capacity - count)
--   retry_after_ms = 0 if allowed else ms until the window flips
--   reset_at_ms    = epoch ms of the next window boundary
--
-- State is one integer per (client, window) key with TTL = window_seconds,
-- set only on the first INCR of the window. Subsequent INCRs MUST NOT
-- refresh the TTL; the counter has to die exactly at the window boundary
-- so the next window starts from a missing key (which INCR treats as 0).

local key_prefix = KEYS[1]
local capacity   = tonumber(ARGV[1])
local window_s   = tonumber(ARGV[2])

local t = redis.call('TIME')
local now_ms        = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local now_s         = tonumber(t[1])
local window_idx    = math.floor(now_s / window_s)
local window_start  = window_idx * window_s
local window_end_ms = (window_start + window_s) * 1000

local key = key_prefix .. ':' .. window_idx
local count = redis.call('INCR', key)
if count == 1 then
    redis.call('EXPIRE', key, window_s)
end

local allowed        = 0
local retry_after_ms = 0
if count <= capacity then
    allowed = 1
else
    retry_after_ms = window_end_ms - now_ms
end

local remaining = capacity - count
if remaining < 0 then remaining = 0 end

return {allowed, remaining, retry_after_ms, window_end_ms}
