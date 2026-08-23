local function safe_call(object, method, ...)
    if not object then return nil end
    local fn = object[method]
    if type(fn) ~= "function" then return nil end
    local ok, value = pcall(fn, object, ...)
    if not ok then return nil end
    return value
end

local resolve_app = Resolve()
if not resolve_app then error("Resolve unavailable") end
local project_manager = resolve_app:GetProjectManager()
local project = project_manager and project_manager:GetCurrentProject() or nil
if not project then error("No current project") end
local current = project:GetCurrentTimeline()
print("TVIZ_HELPER_INSPECT project=" .. tostring(project:GetName()) .. " current=" .. tostring(current and current:GetName() or "nil"))

for timeline_index = 1, tonumber(project:GetTimelineCount() or 0) do
    local timeline = project:GetTimelineByIndex(timeline_index)
    local name = timeline and tostring(timeline:GetName() or "") or ""
    if name:sub(1, 14) == "TVIZ__SOURCE__" then
        local start_frame = tonumber(safe_call(timeline, "GetStartFrame"))
        local end_frame = tonumber(safe_call(timeline, "GetEndFrame"))
        local item_values = safe_call(timeline, "GetItemListInTrack", "video", 1)
        local item_count = 0
        local zero_duration = 0
        local min_start = nil
        local max_end = nil
        local first_duration = nil
        local last_duration = nil
        if type(item_values) == "table" then
            for _, item in pairs(item_values) do
                if type(item) == "userdata" or type(item) == "table" then
                    local item_start = tonumber(safe_call(item, "GetStart"))
                    local item_end = tonumber(safe_call(item, "GetEnd"))
                    local item_duration = tonumber(safe_call(item, "GetDuration"))
                    if item_start and item_end then
                        item_count = item_count + 1
                        if not min_start or item_start < min_start then min_start = item_start end
                        if not max_end or item_end > max_end then max_end = item_end end
                        if item_count == 1 then first_duration = item_duration end
                        last_duration = item_duration
                        if not item_duration or item_duration <= 0 then zero_duration = zero_duration + 1 end
                    end
                end
            end
        end
        print(table.concat({
            "TVIZ_HELPER",
            "index=" .. tostring(timeline_index),
            "name=" .. name,
            "start=" .. tostring(start_frame),
            "end=" .. tostring(end_frame),
            "length=" .. tostring(start_frame and end_frame and (end_frame - start_frame) or nil),
            "v1_count=" .. tostring(item_count),
            "v1_min_start=" .. tostring(min_start),
            "v1_max_end=" .. tostring(max_end),
            "first_duration=" .. tostring(first_duration),
            "last_duration=" .. tostring(last_duration),
            "zero_duration=" .. tostring(zero_duration),
            "locked=" .. tostring(safe_call(timeline, "GetIsTrackLocked", "video", 1)),
            "enabled=" .. tostring(safe_call(timeline, "GetIsTrackEnabled", "video", 1)),
            "fps=" .. tostring(safe_call(timeline, "GetSetting", "timelineFrameRate")),
            "width=" .. tostring(safe_call(timeline, "GetSetting", "timelineResolutionWidth")),
            "height=" .. tostring(safe_call(timeline, "GetSetting", "timelineResolutionHeight")),
        }, " "))
    end
end
