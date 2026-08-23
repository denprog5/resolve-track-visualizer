local function safe_string(value)
    local ok, text = pcall(tostring, value)
    if not ok then
        return "unprintable error"
    end
    return text
end

local PROBE_DURATION = 250
local PROBE_LAST_FRAME = PROBE_DURATION - 1

local function ascii_line(value)
    local text = safe_string(value)
    text = text:gsub("[\r\n\t]+", " ")
    text = text:gsub("[%z\1-\31\127-\255]", "?")
    text = text:gsub(" +", " ")
    return text
end

local function fail(message)
    error(message, 0)
end

local function checked_call(label, object, method_name, ...)
    if object == nil or object == false then
        fail(label .. ": object unavailable")
    end

    local lookup_ok, method = pcall(function()
        return object[method_name]
    end)
    if not lookup_ok then
        fail(label .. ": method lookup failed: " .. safe_string(method))
    end
    if type(method) ~= "function" then
        fail(label .. ": method unavailable")
    end

    local ok, a, b, c, d, e, f = pcall(method, object, ...)
    if not ok then
        fail(label .. " failed: " .. safe_string(a))
    end
    return a, b, c, d, e, f
end

local function safe_call(object, method_name, ...)
    if object == nil or object == false then
        return false, nil, "object unavailable"
    end

    local lookup_ok, method = pcall(function()
        return object[method_name]
    end)
    if not lookup_ok then
        return false, nil, "method lookup failed: " .. safe_string(method)
    end
    if type(method) ~= "function" then
        return false, nil, "method unavailable"
    end

    local ok, a, b, c, d = pcall(method, object, ...)
    if not ok then
        return false, nil, safe_string(a)
    end
    return true, a, b, c, d
end

local function require_value(label, value)
    if value == nil or value == false then
        fail(label .. " returned no value")
    end
    return value
end

local function require_true(label, value)
    if value ~= true then
        fail(label .. " did not return true")
    end
    return value
end

local function require_not_false(label, value)
    if value == false then
        fail(label .. " returned false")
    end
    return value
end

local function require_number(label, value)
    local number = tonumber(value)
    if number == nil then
        fail(label .. " did not return a number")
    end
    return number
end

local function first_table_value(label, values)
    if type(values) ~= "table" then
        fail(label .. " did not return a table")
    end
    if values[1] ~= nil then
        return values[1]
    end
    for _, value in pairs(values) do
        if value ~= nil then
            return value
        end
    end
    fail(label .. " returned an empty table")
end

local function set_input(tool, input_name, value, time)
    local label = "SetInput(" .. input_name .. ")"
    local result
    if time == nil then
        result = checked_call(label, tool, "SetInput", input_name, value)
    else
        result = checked_call(label, tool, "SetInput", input_name, value, time)
    end
    require_not_false(label, result)
end

local function connect_input(tool, input_name, source)
    local label = "ConnectInput(" .. input_name .. ")"
    local result = checked_call(label, tool, "ConnectInput", input_name, source)
    require_not_false(label, result)
end

local function add_modifier(tool, input_name, modifier_name)
    local result = checked_call(
        "AddModifier(" .. input_name .. ", " .. modifier_name .. ")",
        tool,
        "AddModifier",
        input_name,
        modifier_name
    )
    require_true(
        "AddModifier(" .. input_name .. ", " .. modifier_name .. ")",
        result
    )
end

local function get_input(tool, input_name, time)
    return checked_call(
        "GetInput(" .. input_name .. ", " .. tostring(time) .. ")",
        tool,
        "GetInput",
        input_name,
        time
    )
end

local function point_component(point, index, key)
    local ok, value = pcall(function() return point[index] end)
    if ok and value ~= nil then return tonumber(value) end
    ok, value = pcall(function() return point[key] end)
    if ok and value ~= nil then return tonumber(value) end
    return nil
end

local function require_close(label, actual, expected)
    actual = tonumber(actual)
    expected = tonumber(expected)
    if not actual or not expected or math.abs(actual - expected) > 0.0001 then
        fail(label .. " expected=" .. safe_string(expected) .. " actual=" .. safe_string(actual))
    end
end

local function make_point(x, y)
    local point_constructor = rawget(_G, "Point")
    if point_constructor == nil then
        return {x, y}
    end
    local ok, point = pcall(point_constructor, x, y)
    if not ok then
        fail("Point construction failed: " .. safe_string(point))
    end
    return require_value("Point", point)
end

local project_manager = nil
local original_project = nil
local original_name = ""
local probe_name = nil
local probe_project = nil
local loaded_probe_project = nil
local probe_created = false
local probe_deleted = false
local stale_probes_deleted = 0

local function get_resolve()
    local resolve_app = rawget(_G, "resolve")
    if type(resolve_app) == "function" then
        local ok, result = pcall(resolve_app)
        if not ok then
            fail("resolve() failed: " .. safe_string(result))
        end
        resolve_app = result
    end

    if resolve_app == nil then
        local resolve_constructor = rawget(_G, "Resolve")
        if resolve_constructor ~= nil then
            local ok, result = pcall(resolve_constructor)
            if not ok then
                fail("Resolve() failed: " .. safe_string(result))
            end
            resolve_app = result
        end
    end

    if resolve_app == nil then
        local fusion_app = rawget(_G, "app") or rawget(_G, "fu")
        if fusion_app ~= nil then
            resolve_app = checked_call("app:GetResolve", fusion_app, "GetResolve")
        end
    end

    return require_value("Resolve", resolve_app)
end

local function require_active_probe(label)
    local current = require_value(
        label .. ": GetCurrentProject",
        checked_call(label .. ": GetCurrentProject", project_manager, "GetCurrentProject")
    )
    local current_name = require_value(
        label .. ": current GetName",
        checked_call(label .. ": current GetName", current, "GetName")
    )
    if current_name ~= probe_name then
        fail(label .. ": active project is not the probe")
    end
    return current
end

local function run_probe()
    local resolve_app = get_resolve()
    project_manager = require_value(
        "GetProjectManager",
        checked_call("Resolve:GetProjectManager", resolve_app, "GetProjectManager")
    )

    original_project = checked_call(
        "ProjectManager:GetCurrentProject",
        project_manager,
        "GetCurrentProject"
    )
    if original_project ~= nil and original_project ~= false then
        local name = checked_call("Original project:GetName", original_project, "GetName")
        if name ~= nil and name ~= false then
            original_name = safe_string(name)
        end
        if os.getenv("TVIZ_PROBE_ALLOW_SWITCH") ~= "1" then
            fail("A project is already open; refusing to switch away from it")
        end
    end

    local project_names = checked_call(
        "ProjectManager:GetProjectListInCurrentFolder",
        project_manager,
        "GetProjectListInCurrentFolder"
    )
    if type(project_names) == "table" then
        for _, project_name in pairs(project_names) do
            if type(project_name) == "string" and
                project_name:sub(1, 16) == "TVIZ Live Probe " and
                project_name ~= original_name then
                require_true(
                    "ProjectManager:DeleteProject(stale probe)",
                    checked_call(
                        "ProjectManager:DeleteProject(stale probe)",
                        project_manager,
                        "DeleteProject",
                        project_name
                    )
                )
                stale_probes_deleted = stale_probes_deleted + 1
            end
        end
    end

    local carrier_path = os.getenv("TVIZ_PROBE_CARRIER")
    if type(carrier_path) ~= "string" or carrier_path == "" then
        fail("TVIZ_PROBE_CARRIER is required and must be non-empty")
    end

    local timestamp = os.date("!%Y%m%dT%H%M%SZ")
    if timestamp == nil then
        fail("Could not create probe timestamp")
    end
    local clock_suffix = math.floor((os.clock() % 1) * 1000000)
    probe_name = "TVIZ Live Probe " .. timestamp .. string.format("-%06d", clock_suffix)

    probe_project = require_value(
        "ProjectManager:CreateProject",
        checked_call(
            "ProjectManager:CreateProject",
            project_manager,
            "CreateProject",
            probe_name
        )
    )
    probe_created = true
    require_active_probe("CreateProject verification")

    local media_pool = require_value(
        "Project:GetMediaPool",
        checked_call("Project:GetMediaPool", probe_project, "GetMediaPool")
    )
    local imported = checked_call(
        "MediaPool:ImportMedia",
        media_pool,
        "ImportMedia",
        {carrier_path}
    )
    local carrier = require_value(
        "Imported carrier",
        first_table_value("MediaPool:ImportMedia", imported)
    )

    local helper_timeline = require_value(
        "MediaPool:CreateEmptyTimeline(helper)",
        checked_call(
            "MediaPool:CreateEmptyTimeline(helper)",
            media_pool,
            "CreateEmptyTimeline",
            "TVIZ Carrier Source"
        )
    )
    require_true(
        "Project:SetCurrentTimeline(helper)",
        checked_call(
            "Project:SetCurrentTimeline(helper)",
            probe_project,
            "SetCurrentTimeline",
            helper_timeline
        )
    )
    local helper_items = checked_call(
        "MediaPool:AppendToTimeline(helper PNG)",
        media_pool,
        "AppendToTimeline",
        {carrier}
    )
    local helper_item = require_value(
        "Helper PNG timeline item",
        first_table_value("MediaPool:AppendToTimeline(helper PNG)", helper_items)
    )
    local helper_duration = require_number(
        "Helper PNG item:GetDuration",
        checked_call("Helper PNG item:GetDuration", helper_item, "GetDuration")
    )
    if helper_duration <= 0 then
        fail("Helper PNG item duration must be positive")
    end
    local helper_start = require_number(
        "Helper timeline:GetStartFrame",
        checked_call("Helper timeline:GetStartFrame", helper_timeline, "GetStartFrame")
    )
    local helper_end = require_number(
        "Helper timeline:GetEndFrame",
        checked_call("Helper timeline:GetEndFrame", helper_timeline, "GetEndFrame")
    )
    local helper_coverage = helper_end - helper_start
    while helper_coverage < PROBE_DURATION do
        local repeat_count = math.ceil((PROBE_DURATION - helper_coverage) / helper_duration)
        local batch = {}
        local batch_index = 1
        while batch_index <= repeat_count do
            batch[batch_index] = carrier
            batch_index = batch_index + 1
        end
        checked_call(
            "MediaPool:AppendToTimeline(repeated helper PNG)",
            media_pool,
            "AppendToTimeline",
            batch
        )
        helper_end = require_number(
            "Helper timeline:GetEndFrame after repeat",
            checked_call(
                "Helper timeline:GetEndFrame after repeat",
                helper_timeline,
                "GetEndFrame"
            )
        )
        helper_coverage = helper_end - helper_start
    end
    if helper_coverage < PROBE_DURATION then
        fail("Helper PNG sequence did not cover the probe duration")
    end
    require_true(
        "Helper timeline:SetTrackEnable(false)",
        checked_call(
            "Helper timeline:SetTrackEnable(false)",
            helper_timeline,
            "SetTrackEnable",
            "video",
            1,
            false
        )
    )
    local disabled_state = checked_call(
        "Helper timeline:GetIsTrackEnabled(false)",
        helper_timeline,
        "GetIsTrackEnabled",
        "video",
        1
    )
    if disabled_state ~= false then fail("Helper V1 did not enter the disabled probe state") end
    require_not_false(
        "Helper timeline:SetTrackLock(false)",
        checked_call(
            "Helper timeline:SetTrackLock(false)",
            helper_timeline,
            "SetTrackLock",
            "video",
            1,
            false
        )
    )
    require_true(
        "Helper timeline:SetTrackEnable(true)",
        checked_call(
            "Helper timeline:SetTrackEnable(true)",
            helper_timeline,
            "SetTrackEnable",
            "video",
            1,
            true
        )
    )
    local enabled_state = checked_call(
        "Helper timeline:GetIsTrackEnabled(true)",
        helper_timeline,
        "GetIsTrackEnabled",
        "video",
        1
    )
    if enabled_state ~= true then fail("Helper V1 did not return to the enabled state") end
    local reused_source_start = helper_coverage
    local reused_before = helper_coverage
    checked_call(
        "MediaPool:AppendToTimeline(reused helper PNG)",
        media_pool,
        "AppendToTimeline",
        {carrier}
    )
    helper_end = require_number(
        "Helper timeline:GetEndFrame after reuse",
        checked_call("Helper timeline:GetEndFrame after reuse", helper_timeline, "GetEndFrame")
    )
    local reused_still_duration = helper_end - helper_start - reused_before
    if reused_still_duration <= 0 then
        fail("Reused helper timeline did not grow after PNG append")
    end
    local reused_coverage = reused_still_duration
    while reused_coverage < PROBE_DURATION do
        local batch_count = math.ceil((PROBE_DURATION - reused_coverage) / reused_still_duration)
        local batch = {}
        for batch_index = 1, batch_count do batch[batch_index] = carrier end
        checked_call(
            "MediaPool:AppendToTimeline(reused helper PNG batch)",
            media_pool,
            "AppendToTimeline",
            batch
        )
        helper_end = require_number(
            "Helper timeline:GetEndFrame after reuse batch",
            checked_call(
                "Helper timeline:GetEndFrame after reuse batch",
                helper_timeline,
                "GetEndFrame"
            )
        )
        reused_coverage = helper_end - helper_start - reused_before
    end
    if reused_coverage < PROBE_DURATION then
        fail("Reused helper PNG sequence did not cover the probe duration")
    end
    local helper_media_item = require_value(
        "Helper timeline:GetMediaPoolItem",
        checked_call(
            "Helper timeline:GetMediaPoolItem",
            helper_timeline,
            "GetMediaPoolItem"
        )
    )

    local timeline = require_value(
        "MediaPool:CreateEmptyTimeline",
        checked_call(
            "MediaPool:CreateEmptyTimeline",
            media_pool,
            "CreateEmptyTimeline",
            "TVIZ Probe"
        )
    )
    require_true(
        "Project:SetCurrentTimeline",
        checked_call(
            "Project:SetCurrentTimeline",
            probe_project,
            "SetCurrentTimeline",
            timeline
        )
    )

    local video_track_count = require_number(
        "Timeline:GetTrackCount(video)",
        checked_call("Timeline:GetTrackCount(video)", timeline, "GetTrackCount", "video")
    )
    if video_track_count < 1 then
        require_true(
            "Timeline:AddTrack(video)",
            checked_call("Timeline:AddTrack(video)", timeline, "AddTrack", "video")
        )
        video_track_count = require_number(
            "Timeline:GetTrackCount(video) after AddTrack",
            checked_call(
                "Timeline:GetTrackCount(video) after AddTrack",
                timeline,
                "GetTrackCount",
                "video"
            )
        )
    end
    if video_track_count < 1 then
        fail("Timeline V1 is unavailable")
    end

    local start_frame_value = checked_call(
        "Timeline:GetStartFrame",
        timeline,
        "GetStartFrame"
    )
    local record_frame = 0
    if start_frame_value ~= nil and start_frame_value ~= false then
        record_frame = require_number("Timeline:GetStartFrame", start_frame_value)
    end

    local appended = checked_call(
        "MediaPool:AppendToTimeline",
        media_pool,
        "AppendToTimeline",
        {{
            mediaPoolItem = helper_media_item,
            startFrame = reused_source_start,
            endFrame = reused_source_start + PROBE_DURATION,
            recordFrame = record_frame,
            trackIndex = 1,
            mediaType = 1
        }}
    )
    local timeline_item = require_value(
        "Appended timeline item",
        first_table_value("MediaPool:AppendToTimeline", appended)
    )

    local item_start = require_number(
        "TimelineItem:GetStart",
        checked_call("TimelineItem:GetStart", timeline_item, "GetStart")
    )
    if item_start ~= record_frame then
        fail("Appended item start does not equal recordFrame")
    end
    local item_duration = require_number(
        "TimelineItem:GetDuration",
        checked_call("TimelineItem:GetDuration", timeline_item, "GetDuration")
    )
    if item_duration ~= PROBE_DURATION then
        fail(
            "Appended item duration is not " .. safe_string(PROBE_DURATION) ..
            ": actual=" .. safe_string(item_duration) ..
            " helperStillDuration=" .. safe_string(helper_duration)
        )
    end

    local v1_items = checked_call(
        "Timeline:GetItemListInTrack(video, 1)",
        timeline,
        "GetItemListInTrack",
        "video",
        1
    )
    if type(v1_items) ~= "table" then
        fail("Timeline:GetItemListInTrack(video, 1) did not return a table")
    end
    local found_on_v1 = false
    for _, candidate in pairs(v1_items) do
        if candidate == timeline_item then
            found_on_v1 = true
        elseif type(candidate) == "userdata" or type(candidate) == "table" then
            local start_ok, candidate_start = safe_call(candidate, "GetStart")
            local duration_ok, candidate_duration = safe_call(candidate, "GetDuration")
            if start_ok and duration_ok and
                tonumber(candidate_start) == record_frame and
                tonumber(candidate_duration) == PROBE_DURATION then
                found_on_v1 = true
            end
        end
    end
    if not found_on_v1 then
        fail("Appended item was not found on V1")
    end

    require_true(
        "TimelineItem:SetName",
        checked_call("TimelineItem:SetName", timeline_item, "SetName", "TVIZ__probe")
    )

    local comp = require_value(
        "TimelineItem:AddFusionComp",
        checked_call("TimelineItem:AddFusionComp", timeline_item, "AddFusionComp")
    )
    local media_in = require_value(
        "FusionComp:FindTool(MediaIn1)",
        checked_call("FusionComp:FindTool(MediaIn1)", comp, "FindTool", "MediaIn1")
    )
    local media_out = require_value(
        "FusionComp:FindTool(MediaOut1)",
        checked_call("FusionComp:FindTool(MediaOut1)", comp, "FindTool", "MediaOut1")
    )

    require_not_false(
        "FusionComp:SetAttrs",
        checked_call(
            "FusionComp:SetAttrs",
            comp,
            "SetAttrs",
            {
                COMPN_GlobalStart = 0,
                COMPN_GlobalEnd = PROBE_LAST_FRAME,
                COMPN_RenderStart = 0,
                COMPN_RenderEnd = PROBE_LAST_FRAME
            }
        )
    )
    require_not_false(
        "FusionComp:SetData",
        checked_call(
            "FusionComp:SetData",
            comp,
            "SetData",
            "TVIZ_LiveProbe",
            "ok"
        )
    )

    local rectangle = require_value(
        "FusionComp:AddTool(RectangleMask)",
        checked_call(
            "FusionComp:AddTool(RectangleMask)",
            comp,
            "AddTool",
            "RectangleMask",
            false,
            -2,
            0
        )
    )
    local background = require_value(
        "FusionComp:AddTool(Background)",
        checked_call(
            "FusionComp:AddTool(Background)",
            comp,
            "AddTool",
            "Background",
            false,
            0,
            0
        )
    )
    local first_merge = require_value(
        "FusionComp:AddTool(Merge)",
        checked_call("FusionComp:AddTool(Merge)", comp, "AddTool", "Merge", false, 2, 0)
    )
    local text_plus = require_value(
        "FusionComp:AddTool(TextPlus)",
        checked_call("FusionComp:AddTool(TextPlus)", comp, "AddTool", "TextPlus", false, 2, 1)
    )
    local second_merge = require_value(
        "FusionComp:AddTool(second Merge)",
        checked_call(
            "FusionComp:AddTool(second Merge)",
            comp,
            "AddTool",
            "Merge",
            false,
            4,
            0
        )
    )
    local ellipse = require_value(
        "FusionComp:AddTool(EllipseMask)",
        checked_call(
            "FusionComp:AddTool(EllipseMask)",
            comp,
            "AddTool",
            "EllipseMask",
            false,
            2,
            2
        )
    )
    local knob_background = require_value(
        "FusionComp:AddTool(knob Background)",
        checked_call(
            "FusionComp:AddTool(knob Background)",
            comp,
            "AddTool",
            "Background",
            false,
            4,
            2
        )
    )
    local third_merge = require_value(
        "FusionComp:AddTool(third Merge)",
        checked_call(
            "FusionComp:AddTool(third Merge)",
            comp,
            "AddTool",
            "Merge",
            false,
            6,
            0
        )
    )

    set_input(rectangle, "Width", 0.80)
    set_input(rectangle, "Height", 0.50)
    add_modifier(rectangle, "Width", "BezierSpline")
    add_modifier(rectangle, "Center", "Path")
    set_input(rectangle, "Width", 0.10, 0)
    set_input(rectangle, "Width", 0.80, PROBE_LAST_FRAME)
    set_input(rectangle, "Center", make_point(0.1, 0.5), 0)
    set_input(rectangle, "Center", make_point(0.9, 0.5), PROBE_LAST_FRAME)

    set_input(background, "UseFrameFormatSettings", 1)
    set_input(background, "TopLeftRed", 0.08)
    set_input(background, "TopLeftGreen", 0.35)
    set_input(background, "TopLeftBlue", 0.90)
    set_input(background, "TopLeftAlpha", 0.80)
    connect_input(background, "EffectMask", rectangle)
    connect_input(first_merge, "Background", media_in)
    connect_input(first_merge, "Foreground", background)

    add_modifier(text_plus, "StyledText", "BezierSpline")
    set_input(text_plus, "StyledText", "TVIZ live probe", 0)
    set_input(text_plus, "StyledText", "TVIZ live probe last frame", PROBE_LAST_FRAME)
    set_input(text_plus, "Size", 0.08)
    set_input(text_plus, "Center", make_point(0.5, 0.5))
    connect_input(second_merge, "Background", first_merge)
    connect_input(second_merge, "Foreground", text_plus)

    set_input(ellipse, "Width", 0.04)
    set_input(ellipse, "Height", 0.04)
    add_modifier(ellipse, "Center", "Path")
    set_input(ellipse, "Center", make_point(0.1, 0.7), 0)
    set_input(ellipse, "Center", make_point(0.9, 0.7), PROBE_LAST_FRAME)
    set_input(knob_background, "UseFrameFormatSettings", 1)
    set_input(knob_background, "TopLeftRed", 0.95)
    set_input(knob_background, "TopLeftGreen", 0.30)
    set_input(knob_background, "TopLeftBlue", 0.15)
    set_input(knob_background, "TopLeftAlpha", 1.0)
    connect_input(knob_background, "EffectMask", ellipse)
    connect_input(third_merge, "Background", second_merge)
    connect_input(third_merge, "Foreground", knob_background)
    connect_input(media_out, "Input", third_merge)

    require_close("Rectangle Width at frame 0", get_input(rectangle, "Width", 0), 0.10)
    require_close("Rectangle Width at last frame", get_input(rectangle, "Width", PROBE_LAST_FRAME), 0.80)
    local width_at_middle = tonumber(get_input(rectangle, "Width", math.floor(PROBE_LAST_FRAME / 2)))
    if not width_at_middle or width_at_middle <= 0.10 or width_at_middle >= 0.80 then
        fail("Rectangle Width did not animate between keyframes")
    end
    local text_at_start = get_input(text_plus, "StyledText", 0)
    local text_before_end = get_input(text_plus, "StyledText", PROBE_LAST_FRAME - 1)
    local text_at_end = get_input(text_plus, "StyledText", PROBE_LAST_FRAME)
    if text_at_start ~= "TVIZ live probe" or text_before_end ~= "TVIZ live probe" or text_at_end ~= "TVIZ live probe last frame" then
        fail("StyledText keyframes were not evaluated")
    end
    local center_at_start = get_input(ellipse, "Center", 0)
    local center_at_middle = get_input(ellipse, "Center", math.floor(PROBE_LAST_FRAME / 2))
    local center_at_end = get_input(ellipse, "Center", PROBE_LAST_FRAME)
    require_close("Ellipse Center X at frame 0", point_component(center_at_start, 1, "X"), 0.1)
    require_close("Ellipse Center X at last frame", point_component(center_at_end, 1, "X"), 0.9)
    local center_middle_x = point_component(center_at_middle, 1, "X")
    if not center_middle_x or center_middle_x <= 0.1 or center_middle_x >= 0.9 then
        fail("Ellipse Center did not animate between keyframes")
    end

    local main_output = require_value(
        "MediaOut1:FindMainOutput(1)",
        checked_call("MediaOut1:FindMainOutput(1)", media_out, "FindMainOutput", 1)
    )
    local output_image = checked_call(
        "MediaOut1 main output:GetValue(0)",
        main_output,
        "GetValue",
        0
    )
    if output_image == nil or output_image == false then
        fail("MediaOut1 main output:GetValue(0) returned no image")
    end

    require_active_probe("SaveProject safety check")
    require_true(
        "ProjectManager:SaveProject",
        checked_call("ProjectManager:SaveProject", project_manager, "SaveProject")
    )

    local fusion_count = require_number(
        "TimelineItem:GetFusionCompCount",
        checked_call(
            "TimelineItem:GetFusionCompCount",
            timeline_item,
            "GetFusionCompCount"
        )
    )
    if fusion_count < 1 then
        fail("Timeline item has no Fusion composition after save")
    end

    require_true(
        "ProjectManager:CloseProject(probe)",
        checked_call(
            "ProjectManager:CloseProject(probe)",
            project_manager,
            "CloseProject",
            probe_project
        )
    )

    loaded_probe_project = require_value(
        "ProjectManager:LoadProject(probe)",
        checked_call(
            "ProjectManager:LoadProject(probe)",
            project_manager,
            "LoadProject",
            probe_name
        )
    )
    require_active_probe("LoadProject verification")

    local timeline_count = require_number(
        "Reloaded project:GetTimelineCount",
        checked_call(
            "Reloaded project:GetTimelineCount",
            loaded_probe_project,
            "GetTimelineCount"
        )
    )
    local reloaded_timeline = nil
    local timeline_index = 1
    while timeline_index <= timeline_count do
        local candidate = require_value(
            "Reloaded project:GetTimelineByIndex",
            checked_call(
                "Reloaded project:GetTimelineByIndex",
                loaded_probe_project,
                "GetTimelineByIndex",
                timeline_index
            )
        )
        local candidate_name = checked_call(
            "Reloaded timeline:GetName",
            candidate,
            "GetName"
        )
        if candidate_name == "TVIZ Probe" then
            reloaded_timeline = candidate
            break
        end
        timeline_index = timeline_index + 1
    end
    require_value("Reloaded timeline TVIZ Probe", reloaded_timeline)

    local reloaded_video_tracks = require_number(
        "Reloaded timeline:GetTrackCount(video)",
        checked_call(
            "Reloaded timeline:GetTrackCount(video)",
            reloaded_timeline,
            "GetTrackCount",
            "video"
        )
    )
    if reloaded_video_tracks < 1 then
        fail("Reloaded timeline has no V1")
    end

    local reloaded_items = checked_call(
        "Reloaded timeline:GetItemListInTrack(video, 1)",
        reloaded_timeline,
        "GetItemListInTrack",
        "video",
        1
    )
    if type(reloaded_items) ~= "table" then
        fail("Reloaded V1 item list is not a table")
    end
    local reloaded_item = nil
    for _, candidate in pairs(reloaded_items) do
        if type(candidate) == "userdata" or type(candidate) == "table" then
            local name_ok, candidate_name = safe_call(candidate, "GetName")
            if name_ok and candidate_name == "TVIZ__probe" then
                reloaded_item = candidate
                break
            end
        end
    end
    require_value("Reloaded V1 item TVIZ__probe", reloaded_item)

    local reloaded_fusion_count = require_number(
        "Reloaded item:GetFusionCompCount",
        checked_call(
            "Reloaded item:GetFusionCompCount",
            reloaded_item,
            "GetFusionCompCount"
        )
    )
    if reloaded_fusion_count < 1 then
        fail("Reloaded item has no Fusion composition")
    end

    require_true(
        "ProjectManager:CloseProject(reloaded probe)",
        checked_call(
            "ProjectManager:CloseProject(reloaded probe)",
            project_manager,
            "CloseProject",
            loaded_probe_project
        )
    )
    loaded_probe_project = nil

    if original_name ~= "" then
        require_value(
            "ProjectManager:LoadProject(original)",
            checked_call(
                "ProjectManager:LoadProject(original)",
                project_manager,
                "LoadProject",
                original_name
            )
        )
    end

    require_true(
        "ProjectManager:DeleteProject(probe)",
        checked_call(
            "ProjectManager:DeleteProject(probe)",
            project_manager,
            "DeleteProject",
            probe_name
        )
    )
    probe_deleted = true

    return {
        fusion_count = fusion_count,
        helper_duration = helper_duration,
        reused_still_duration = reused_still_duration,
        reloaded_fusion_count = reloaded_fusion_count,
        output_image = true
    }
end

local function cleanup()
    local errors = {}
    local function add_error(message)
        errors[#errors + 1] = message
    end

    if project_manager ~= nil then
        local current_ok, current, current_error = safe_call(
            project_manager,
            "GetCurrentProject"
        )
        if not current_ok then
            add_error("cleanup GetCurrentProject failed: " .. safe_string(current_error))
        elseif current ~= nil and current ~= false then
            local is_probe = current == probe_project or current == loaded_probe_project
            if not is_probe and probe_created and probe_name ~= nil then
                local name_ok, current_name, name_error = safe_call(current, "GetName")
                if not name_ok then
                    add_error("cleanup current GetName failed: " .. safe_string(name_error))
                elseif current_name == probe_name then
                    is_probe = true
                end
            end

            if is_probe then
                local close_ok, close_result, close_error = safe_call(
                    project_manager,
                    "CloseProject",
                    current
                )
                if not close_ok then
                    add_error("cleanup CloseProject failed: " .. safe_string(close_error))
                elseif close_result ~= true then
                    add_error("cleanup CloseProject did not return true")
                end
            end
        end

        local before_delete_ok, before_delete_current, before_delete_error = safe_call(
            project_manager,
            "GetCurrentProject"
        )
        if not before_delete_ok then
            add_error("cleanup pre-delete GetCurrentProject failed: " .. safe_string(before_delete_error))
        elseif (before_delete_current == nil or before_delete_current == false) and original_name ~= "" then
            local restore_ok, restored, restore_error = safe_call(
                project_manager,
                "LoadProject",
                original_name
            )
            if not restore_ok then
                add_error("cleanup pre-delete restore failed: " .. safe_string(restore_error))
            elseif restored == nil or restored == false then
                add_error("cleanup pre-delete restore returned no project")
            end
        end

        if probe_created and not probe_deleted and probe_name ~= nil then
            local delete_ok, delete_result, delete_error = safe_call(
                project_manager,
                "DeleteProject",
                probe_name
            )
            if not delete_ok then
                add_error("cleanup DeleteProject failed: " .. safe_string(delete_error))
            elseif delete_result ~= true then
                add_error("cleanup DeleteProject did not return true")
            else
                probe_deleted = true
            end
        end

        local final_current_ok, final_current, final_current_error = safe_call(
            project_manager,
            "GetCurrentProject"
        )
        if not final_current_ok then
            add_error(
                "restore GetCurrentProject failed: " .. safe_string(final_current_error)
            )
        elseif (final_current == nil or final_current == false) and original_name ~= "" then
            local load_ok, restored, load_error = safe_call(
                project_manager,
                "LoadProject",
                original_name
            )
            if not load_ok then
                add_error("restore LoadProject failed: " .. safe_string(load_error))
            elseif restored == nil or restored == false then
                add_error("restore LoadProject returned no project")
            end
        end
    end

    if #errors > 0 then
        return table.concat(errors, "; ")
    end
    return nil
end

local run_ok, result_or_error = xpcall(run_probe, function(err)
    return safe_string(err)
end)
local cleanup_error = cleanup()

if run_ok and cleanup_error == nil then
    local result = result_or_error
    print(ascii_line(
        "TVIZ_PROBE_OK project=\"" .. probe_name ..
        "\" helper_still_duration=" .. safe_string(result.helper_duration) ..
        " reused_still_duration=" .. safe_string(result.reused_still_duration) ..
        " fusion_comp_count=" .. safe_string(result.fusion_count) ..
        " reloaded_fusion_comp_count=" .. safe_string(result.reloaded_fusion_count) ..
        " output_image=1 cleaned=1 stale_cleaned=" .. safe_string(stale_probes_deleted)
    ))
else
    local error_text
    if run_ok then
        error_text = "cleanup: " .. safe_string(cleanup_error)
    elseif cleanup_error ~= nil then
        error_text = safe_string(result_or_error) .. "; cleanup: " .. cleanup_error
    else
        error_text = safe_string(result_or_error)
    end
    local error_line = ascii_line("TVIZ_PROBE_ERROR " .. error_text)
    print(error_line)
    error(error_line, 0)
end
