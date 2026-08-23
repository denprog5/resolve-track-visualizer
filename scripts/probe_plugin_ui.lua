local resolve = Resolve()
if not resolve then error("TVIZ_UI_PROBE_ERROR Resolve returned no value") end
local fusion = resolve:Fusion()
if not fusion then error("TVIZ_UI_PROBE_ERROR Fusion returned no value") end
local ui = fusion.UIManager
if not ui then error("TVIZ_UI_PROBE_ERROR UIManager returned no value") end
local window = ui:FindWindow("com.local.davinci.trackvisualizer.lua")
if not window then error("TVIZ_UI_PROBE_ERROR plugin window was not created") end
local skin = window:Find("SkinSelector")
local palette = window:Find("PaletteSelector")
local update = window:Find("UpdateFromTimeline")
local language_mode = window:Find("LanguageMode")
if not skin or not palette or not update or not language_mode then
    error("TVIZ_UI_PROBE_ERROR required theme controls are missing")
end
local requested_language = tostring(os.getenv("TVIZ_UI_LANG") or ""):lower()
if requested_language ~= "en" and requested_language ~= "ru" then
    error("TVIZ_UI_PROBE_ERROR set TVIZ_UI_LANG=en or TVIZ_UI_LANG=ru before launching Resolve")
end
local original_index = tonumber(skin.CurrentIndex) or 0
local expected = requested_language == "ru"
    and { "Классический", "Минимал", "Портретное стекло" }
    or { "Classic", "Minimal", "Portrait Glass" }
local expected_update = requested_language == "ru"
    and "Создать / обновить визуализаторы"
    or "Create / update visualizers"
local language_labels = requested_language == "ru"
    and { ["Авто (системный)"] = true, ["English"] = true, ["Русский"] = true }
    or { ["Auto (system)"] = true, ["English"] = true, ["Russian"] = true }
if tostring(update.Text or "") ~= expected_update then
    error("TVIZ_UI_PROBE_ERROR update button locale mismatch: " .. tostring(update.Text or ""))
end
if not language_labels[tostring(language_mode.CurrentText or "")] then
    error("TVIZ_UI_PROBE_ERROR language selector locale mismatch: " .. tostring(language_mode.CurrentText or ""))
end
for index, label in ipairs(expected) do
    skin.CurrentIndex = index - 1
    if bmd and type(bmd.wait) == "function" then bmd.wait(0.2) end
    if tonumber(skin.CurrentIndex) ~= index - 1 or tostring(skin.CurrentText or "") ~= label then
        error("TVIZ_UI_PROBE_ERROR skin selector did not expose " .. label)
    end
    if tostring(palette.CurrentText or "") == "" then
        error("TVIZ_UI_PROBE_ERROR palette selector is empty for " .. label)
    end
end
skin.CurrentIndex = original_index
if bmd and type(bmd.wait) == "function" then bmd.wait(0.2) end
pcall(function() window:Close() end)
print("TVIZ_UI_PROBE_OK lang=" .. requested_language .. " skins=3 contextual_palettes=1 language_selector=1")
