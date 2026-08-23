local function fail(message)
    error("TVIZ_PRODUCTION_PROBE_ERROR " .. tostring(message), 0)
end

local function checked(label, object, method_name, ...)
    if not object then fail(label .. ": missing object") end
    local method = object[method_name]
    if type(method) ~= "function" then fail(label .. ": missing " .. method_name) end
    local ok, value = pcall(method, object, ...)
    if not ok then fail(label .. ": " .. tostring(value)) end
    return value
end

local function read_lines(path)
    local handle = io.open(path, "rb")
    if not handle then fail("cannot read cases file: " .. tostring(path)) end
    local lines = {}
    for line in handle:lines() do
        line = tostring(line):match("^%s*(.-)%s*$")
        if line ~= "" then table.insert(lines, line) end
    end
    handle:close()
    return lines
end

local function normalize_items(items)
    local result = {}
    if type(items) ~= "table" then return result end
    for key, value in pairs(items) do
        local candidate = value
        local ok = pcall(function() return candidate:GetName() end)
        if not ok then
            candidate = key
            ok = pcall(function() return candidate:GetName() end)
        end
        if ok then table.insert(result, candidate) end
    end
    table.sort(result, function(left, right)
        return tonumber(checked("item start", left, "GetStart")) < tonumber(checked("item start", right, "GetStart"))
    end)
    return result
end

local function split_case(line)
    local jobs_path, manifest_path, skin, count, duration = line:match("^(.-)|(.-)|([^|]+)|(%d+)|(%d+)$")
    if not jobs_path or not manifest_path or not skin or not count or not duration then fail("invalid case line: " .. tostring(line)) end
    skin = tostring(skin):match("^%s*(.-)%s*$")
    return jobs_path, manifest_path, skin, tonumber(count), tonumber(duration)
end

local resolve = Resolve()
if not resolve then fail("Resolve returned no value") end
local project_manager = checked("Resolve:GetProjectManager", resolve, "GetProjectManager")
local source_script = os.getenv("TVIZ_PROBE_SOURCE_SCRIPT") or ""
local cases_path = os.getenv("TVIZ_PROBE_CASES") or ""
if source_script == "" or cases_path == "" then fail("probe paths are not configured") end

local project_name = "TVIZ Production Probe " .. os.date("!%Y%m%dT%H%M%SZ") .. "-" .. tostring(math.floor((os.clock() % 1) * 1000000))
local project = checked("ProjectManager:CreateProject", project_manager, "CreateProject", project_name)
if not project then fail("CreateProject returned no project") end

local cleanup_required = true
local ok, result = pcall(function()
    local media_pool = checked("Project:GetMediaPool", project, "GetMediaPool")
    local timeline = checked("MediaPool:CreateEmptyTimeline", media_pool, "CreateEmptyTimeline", "Timeline 1")
    if not timeline then fail("CreateEmptyTimeline returned no timeline") end
    checked("Timeline:SetSetting fps", timeline, "SetSetting", "timelineFrameRate", "24")
    checked("Timeline:SetSetting width", timeline, "SetSetting", "timelineResolutionWidth", "1920")
    checked("Timeline:SetSetting height", timeline, "SetSetting", "timelineResolutionHeight", "1080")
    checked("Project:SetCurrentTimeline", project, "SetCurrentTimeline", timeline)

    local cases = read_lines(cases_path)
    if #cases ~= 3 then fail("expected three skin cases, got " .. tostring(#cases)) end
    local generations = {}
    for case_index, line in ipairs(cases) do
        local jobs_path, manifest_path, expected_skin, expected_count, expected_duration = split_case(line)
        _G.TVIZ_INTERNAL_PROBE = {
            jobs_path = jobs_path,
            manifest_path = manifest_path,
            video_track = 2,
            replace_all = true,
        }
        local probe_result = dofile(source_script)
        _G.TVIZ_INTERNAL_PROBE = nil
        if type(probe_result) ~= "table" or tonumber(probe_result.inserted) ~= expected_count then
            fail("production script returned invalid result for case " .. tostring(case_index))
        end
        if generations[probe_result.generation] then fail("helper generation was reused") end
        generations[probe_result.generation] = true

        local items = normalize_items(checked("Timeline:GetItemListInTrack", timeline, "GetItemListInTrack", "video", 2))
        if #items ~= expected_count then
            fail("V2 contains " .. tostring(#items) .. " items after replacement; expected " .. tostring(expected_count))
        end
        local previous_source_by_helper = {}
        local names = {}
        for item_index, item in ipairs(items) do
            local name = tostring(checked("TimelineItem:GetName", item, "GetName") or "")
            if names[name] then fail("duplicate target item name: " .. name) end
            names[name] = true
            local duration = tonumber(checked("TimelineItem:GetDuration", item, "GetDuration"))
            if duration ~= expected_duration then fail("unexpected target duration for item " .. tostring(item_index) .. ": " .. tostring(duration)) end
            local source_ok, source_start = pcall(function() return item:GetSourceStartFrame() end)
            if source_ok and tonumber(source_start) then
                source_start = tonumber(source_start)
                local helper_item = checked("TimelineItem:GetMediaPoolItem", item, "GetMediaPoolItem")
                local helper_id = tostring(checked("Helper MediaPoolItem:GetUniqueId", helper_item, "GetUniqueId") or "")
                local previous_source = previous_source_by_helper[helper_id]
                if previous_source ~= nil and source_start <= previous_source then
                    fail("nested source ranges are not increasing inside helper " .. helper_id)
                end
                previous_source_by_helper[helper_id] = source_start
            end
            local comp_count = tonumber(checked("TimelineItem:GetFusionCompCount", item, "GetFusionCompCount")) or 0
            if comp_count ~= 1 then fail("expected one Fusion comp on item " .. tostring(item_index)) end
            local comp = checked("TimelineItem:GetFusionCompByIndex", item, "GetFusionCompByIndex", 1)
            local skin = checked("FusionComp:GetData(tviz_skin)", comp, "GetData", "tviz_skin")
            if tostring(skin or "") ~= expected_skin then
                fail("Fusion skin mismatch: " .. tostring(skin) .. " instead of " .. expected_skin)
            end
        end
    end

    checked("ProjectManager:SaveProject", project_manager, "SaveProject")
    checked("ProjectManager:CloseProject", project_manager, "CloseProject", project)
    local reopened = checked("ProjectManager:LoadProject", project_manager, "LoadProject", project_name)
    if not reopened then fail("project did not reopen") end
    local reopened_timeline = checked("Project:GetTimelineByIndex", reopened, "GetTimelineByIndex", 1)
    local reopened_items = normalize_items(checked("Timeline:GetItemListInTrack after reload", reopened_timeline, "GetItemListInTrack", "video", 2))
    if #reopened_items ~= 3 then fail("reloaded V2 item count mismatch") end
    for index, item in ipairs(reopened_items) do
        local comp_count = tonumber(checked("Reloaded item:GetFusionCompCount", item, "GetFusionCompCount")) or 0
        if comp_count ~= 1 then fail("Fusion comp missing after reload on item " .. tostring(index)) end
    end
    checked("ProjectManager:CloseProject(reopened)", project_manager, "CloseProject", reopened)
    checked("ProjectManager:DeleteProject", project_manager, "DeleteProject", project_name)
    cleanup_required = false
    return "TVIZ_PRODUCTION_PROBE_OK cases=3 production_tracks=49 generations=3 reloaded=1"
end)

_G.TVIZ_INTERNAL_PROBE = nil
if cleanup_required then
    pcall(function()
        local current = project_manager:GetCurrentProject()
        if current and current:GetName() == project_name then project_manager:CloseProject(current) end
    end)
    pcall(function() project_manager:DeleteProject(project_name) end)
end
if not ok then fail(result) end
print(result)
