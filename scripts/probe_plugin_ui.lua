-- Manual UI probe. Open Track Visualizer first, then run this from
-- Workspace -> Scripts (copy it into Scripts/Utility) or the Fusion console.
-- It checks the panel language, the skin list and that every skin has a palette,
-- then restores the selected skin. It does not touch the timeline.
local resolve = Resolve()
if not resolve then error("TVIZ_UI_PROBE_ERROR Resolve returned no value") end
local fusion = resolve:Fusion()
if not fusion then error("TVIZ_UI_PROBE_ERROR Fusion returned no value") end
local ui = fusion.UIManager
if not ui then error("TVIZ_UI_PROBE_ERROR UIManager returned no value") end
local window = ui:FindWindow("com.local.davinci.trackvisualizer.lua")
if not window then error("TVIZ_UI_PROBE_ERROR open Track Visualizer before running the probe") end

local items = window:GetItems()
local create = items.CreatePlayers
local skin = items.SkinSelector
local palette = items.PaletteSelector
local language_mode = items.LanguageMode
if not create or not skin or not palette or not language_mode then
    error("TVIZ_UI_PROBE_ERROR required controls are missing")
end

local LOCALES = {
    en = {
        create = "Create players",
        skins = { "Classic", "Minimal", "Portrait Glass", "Compact", "Wave" },
        languages = { ["Auto (system)"] = true, ["English"] = true, ["Russian"] = true },
    },
    ru = {
        create = "Создать плееры",
        skins = { "Классический", "Минимал", "Вертикальное стекло", "Компактный", "Волна" },
        languages = { ["Авто (системный)"] = true, ["Английский"] = true, ["Русский"] = true },
    },
}

local language
for code, locale in pairs(LOCALES) do
    if tostring(create.Text or "") == locale.create then language = code end
end
if not language then
    error("TVIZ_UI_PROBE_ERROR unknown create button text: " .. tostring(create.Text or ""))
end
local locale = LOCALES[language]
if not locale.languages[tostring(language_mode.CurrentText or "")] then
    error("TVIZ_UI_PROBE_ERROR language selector locale mismatch: " .. tostring(language_mode.CurrentText or ""))
end

local original_index = tonumber(skin.CurrentIndex) or 0
for index, label in ipairs(locale.skins) do
    skin.CurrentIndex = index - 1
    if bmd and type(bmd.wait) == "function" then bmd.wait(0.3) end
    if tostring(skin.CurrentText or "") ~= label then
        error("TVIZ_UI_PROBE_ERROR skin " .. index .. " is " .. tostring(skin.CurrentText or "") .. ", expected " .. label)
    end
    if tostring(palette.CurrentText or "") == "" then
        error("TVIZ_UI_PROBE_ERROR palette selector is empty for " .. label)
    end
end
skin.CurrentIndex = original_index
print("TVIZ_UI_PROBE_OK lang=" .. language .. " skins=" .. #locale.skins)
