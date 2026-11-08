local PLUGIN_ID = "com.local.davinci.trackvisualizer.lua"
local VISUALIZER_PREFIX = "TVIZ__"
local CARRIER_PREFIX = "TVIZ_carrier_"
local MEDIA_BIN_NAME = "Track Visualizer"
local SETTINGS_VERSION = 2
local JOBS_VERSION = 3
local MANIFEST_VERSION = 4
local PLACE_BATCH = 4
local TICK_MS = 100

local INSTALL_ROOT = [[__INSTALL_ROOT__]]
local ENGINE_EXECUTABLE = [[__ENGINE_EXECUTABLE__]]
local RUNNER_EXECUTABLE = [[__RUNNER_EXECUTABLE__]]
local FFMPEG_EXECUTABLE = [[__FFMPEG_EXECUTABLE__]]
local FFPROBE_EXECUTABLE = [[__FFPROBE_EXECUTABLE__]]

local function platform_descriptor(forced_name)
    local name = tostring(forced_name or ""):lower()
    if name == "osx" or name == "darwin" or name == "mac" then name = "macos" end
    if name ~= "windows" and name ~= "macos" and name ~= "linux" then
        local jit_os = tostring(jit and jit.os or "")
        if jit_os == "Windows" or package.config:sub(1, 1) == "\\" then
            name = "windows"
        elseif jit_os == "OSX" or tostring(package.cpath or ""):find(".dylib", 1, true) then
            name = "macos"
        else
            name = "linux"
        end
    end
    local windows = name == "windows"
    return {
        name = name,
        windows = windows,
        macos = name == "macos",
        linux = name == "linux",
        separator = windows and "\\" or "/",
        executable_suffix = windows and ".exe" or "",
        case_sensitive_paths = not windows,
    }
end

local platform_probe_config = rawget(_G, "TVIZ_INTERNAL_PROBE")
local PLATFORM = platform_descriptor(type(platform_probe_config) == "table"
    and platform_probe_config.platform_only == true and platform_probe_config.platform or nil)

local WIN32 = { attempted = false, ffi = nil, kernel32 = nil, error = nil }

local function win32_api()
    if not PLATFORM.windows then return nil, "Win32 API is available only on Windows" end
    if WIN32.attempted then
        if WIN32.kernel32 then return WIN32 end
        return nil, WIN32.error
    end
    WIN32.attempted = true

    local ffi_ok, ffi = pcall(require, "ffi")
    if not ffi_ok then
        WIN32.error = "LuaJIT FFI unavailable: " .. tostring(ffi)
        return nil, WIN32.error
    end
    local declared = pcall(function() return ffi.typeof("tviz_WIN32_API_V2_MARKER") end)
    if not declared then
        local cdef_ok, cdef_error = pcall(function()
            ffi.cdef[[
                typedef struct tviz_WIN32_API_V2_MARKER { int unused; } tviz_WIN32_API_V2_MARKER;

                typedef struct tviz_STARTUPINFOW {
                    uint32_t cb;
                    uint16_t *lpReserved;
                    uint16_t *lpDesktop;
                    uint16_t *lpTitle;
                    uint32_t dwX;
                    uint32_t dwY;
                    uint32_t dwXSize;
                    uint32_t dwYSize;
                    uint32_t dwXCountChars;
                    uint32_t dwYCountChars;
                    uint32_t dwFillAttribute;
                    uint32_t dwFlags;
                    uint16_t wShowWindow;
                    uint16_t cbReserved2;
                    uint8_t *lpReserved2;
                    void *hStdInput;
                    void *hStdOutput;
                    void *hStdError;
                } tviz_STARTUPINFOW;

                typedef struct tviz_PROCESS_INFORMATION {
                    void *hProcess;
                    void *hThread;
                    uint32_t dwProcessId;
                    uint32_t dwThreadId;
                } tviz_PROCESS_INFORMATION;

                int __stdcall MultiByteToWideChar(
                    unsigned int codePage,
                    uint32_t flags,
                    const char *source,
                    int sourceLength,
                    uint16_t *destination,
                    int destinationLength
                );
                int __stdcall WideCharToMultiByte(
                    unsigned int codePage,
                    uint32_t flags,
                    const uint16_t *source,
                    int sourceLength,
                    char *destination,
                    int destinationLength,
                    const char *defaultCharacter,
                    int *usedDefaultCharacter
                );
                uint32_t __stdcall GetEnvironmentVariableW(const uint16_t *name, uint16_t *buffer, uint32_t size);
                int __stdcall GetUserPreferredUILanguages(uint32_t flags, uint32_t *count, uint16_t *buffer, uint32_t *size);
                int __stdcall GetUserDefaultLocaleName(uint16_t *localeName, int localeNameCount);
                void * __stdcall CreateFileW(
                    const uint16_t *fileName,
                    uint32_t desiredAccess,
                    uint32_t shareMode,
                    void *securityAttributes,
                    uint32_t creationDisposition,
                    uint32_t flagsAndAttributes,
                    void *templateFile
                );
                int __stdcall ReadFile(void *file, void *buffer, uint32_t bytesToRead, uint32_t *bytesRead, void *overlapped);
                int __stdcall WriteFile(void *file, const void *buffer, uint32_t bytesToWrite, uint32_t *bytesWritten, void *overlapped);
                int __stdcall FlushFileBuffers(void *file);
                int __stdcall SetFilePointerEx(void *file, int64_t distance, int64_t *newPosition, uint32_t moveMethod);
                int __stdcall DeleteFileW(const uint16_t *fileName);
                int __stdcall MoveFileExW(const uint16_t *existingFileName, const uint16_t *newFileName, uint32_t flags);
                int __stdcall ReplaceFileW(
                    const uint16_t *replacedFileName,
                    const uint16_t *replacementFileName,
                    const uint16_t *backupFileName,
                    uint32_t replaceFlags,
                    void *exclude,
                    void *reserved
                );
                int __stdcall CreateDirectoryW(const uint16_t *pathName, void *securityAttributes);
                int __stdcall CreateProcessW(
                    const uint16_t *applicationName,
                    uint16_t *commandLine,
                    void *processAttributes,
                    void *threadAttributes,
                    int inheritHandles,
                    uint32_t creationFlags,
                    void *environment,
                    const uint16_t *currentDirectory,
                    tviz_STARTUPINFOW *startupInfo,
                    tviz_PROCESS_INFORMATION *processInformation
                );
                int __stdcall CloseHandle(void *handle);
                uint32_t __stdcall GetLastError(void);
            ]]
        end)
        if not cdef_ok then
            WIN32.error = "FFI declarations failed: " .. tostring(cdef_error)
            return nil, WIN32.error
        end
    end

    local load_ok, kernel32 = pcall(ffi.load, "kernel32")
    if not load_ok then
        WIN32.error = "kernel32 unavailable: " .. tostring(kernel32)
        return nil, WIN32.error
    end
    WIN32.ffi = ffi
    WIN32.kernel32 = kernel32
    return WIN32
end

local function win32_utf16(value)
    local api, api_error = win32_api()
    if not api then return nil, api_error end
    value = tostring(value or "")
    local count = api.kernel32.MultiByteToWideChar(65001, 0, value, -1, nil, 0)
    if count == 0 then return nil, "UTF-8 path conversion failed: " .. tostring(tonumber(api.kernel32.GetLastError())) end
    local result = api.ffi.new("uint16_t[?]", count)
    if api.kernel32.MultiByteToWideChar(65001, 0, value, -1, result, count) == 0 then
        return nil, "UTF-8 path conversion failed: " .. tostring(tonumber(api.kernel32.GetLastError()))
    end
    return result
end

local function win32_utf8(value, character_count)
    local api, api_error = win32_api()
    if not api then return nil, api_error end
    character_count = tonumber(character_count) or 0
    if character_count == 0 then return "" end
    local count = api.kernel32.WideCharToMultiByte(65001, 0, value, character_count, nil, 0, nil, nil)
    if count == 0 then return nil, "UTF-16 conversion failed: " .. tostring(tonumber(api.kernel32.GetLastError())) end
    local result = api.ffi.new("char[?]", count)
    if api.kernel32.WideCharToMultiByte(65001, 0, value, character_count, result, count, nil, nil) == 0 then
        return nil, "UTF-16 conversion failed: " .. tostring(tonumber(api.kernel32.GetLastError()))
    end
    return api.ffi.string(result, count)
end

local function win32_environment_value(name)
    local api, api_error = win32_api()
    if not api then return nil, api_error end
    local wide_name, conversion_error = win32_utf16(name)
    if not wide_name then return nil, conversion_error end
    local required = api.kernel32.GetEnvironmentVariableW(wide_name, nil, 0)
    if required == 0 then return nil end
    local buffer = api.ffi.new("uint16_t[?]", required)
    local copied = api.kernel32.GetEnvironmentVariableW(wide_name, buffer, required)
    if copied == 0 or copied >= required then
        return nil, "GetEnvironmentVariableW failed: " .. tostring(tonumber(api.kernel32.GetLastError()))
    end
    return win32_utf8(buffer, copied)
end

-- The system color dialog, shown in-process: it opens instantly over the panel, unlike a
-- PowerShell dialog, which takes seconds to start and can open behind Resolve.
local WIN32_COLOR = { attempted = false, custom = nil }

local function win32_color_api()
    if WIN32_COLOR.attempted then
        if WIN32_COLOR.comdlg32 then return WIN32_COLOR end
        return nil, WIN32_COLOR.error
    end
    WIN32_COLOR.attempted = true
    local api, api_error = win32_api()
    if not api then
        WIN32_COLOR.error = api_error
        return nil, api_error
    end
    local ffi = api.ffi
    local declared = pcall(function() return ffi.typeof("tviz_CHOOSECOLORW_V1") end)
    if not declared then
        local cdef_ok, cdef_error = pcall(function()
            ffi.cdef[[
                typedef struct tviz_CHOOSECOLORW_V1 {
                    uint32_t lStructSize;
                    void *hwndOwner;
                    void *hInstance;
                    uint32_t rgbResult;
                    uint32_t *lpCustColors;
                    uint32_t Flags;
                    intptr_t lCustData;
                    void *lpfnHook;
                    const uint16_t *lpTemplateName;
                } tviz_CHOOSECOLORW_V1;
                typedef uintptr_t (__stdcall *tviz_CCHOOKPROC_V1)(void *dialog, uint32_t message, uintptr_t wparam, intptr_t lparam);
                int __stdcall ChooseColorW(tviz_CHOOSECOLORW_V1 *chooseColor);
                void * __stdcall GetForegroundWindow(void);
                int __stdcall ShowWindow(void *window, int command);
                int __stdcall SetForegroundWindow(void *window);
                int __stdcall PostMessageW(void *window, uint32_t message, uintptr_t wparam, intptr_t lparam);
            ]]
        end)
        if not cdef_ok then
            WIN32_COLOR.error = "Color dialog declarations failed: " .. tostring(cdef_error)
            return nil, WIN32_COLOR.error
        end
    end
    local comdlg_ok, comdlg32 = pcall(ffi.load, "comdlg32")
    local user_ok, user32 = pcall(ffi.load, "user32")
    if not comdlg_ok or not user_ok then
        WIN32_COLOR.error = "comdlg32/user32 unavailable: " .. tostring(comdlg_ok and user32 or comdlg32)
        return nil, WIN32_COLOR.error
    end
    WIN32_COLOR.ffi = ffi
    WIN32_COLOR.comdlg32 = comdlg32
    WIN32_COLOR.user32 = user32
    WIN32_COLOR.custom = ffi.new("uint32_t[16]")
    -- fuscript.exe, which runs this panel, starts minimized, and the dialog inherits that state:
    -- restore it and bring it to the front whenever it would open or end up minimized.
    local restore_message = 0x8001
    WIN32_COLOR.hook = ffi.cast("tviz_CCHOOKPROC_V1", function(dialog, message, wparam)
        if message == 0x0110 then -- WM_INITDIALOG
            user32.PostMessageW(dialog, restore_message, 0, 0)
            return 1
        elseif message == 0x0005 and tonumber(wparam) == 1 then -- WM_SIZE, SIZE_MINIMIZED
            user32.PostMessageW(dialog, restore_message, 0, 0)
        elseif message == restore_message then
            user32.ShowWindow(dialog, 9) -- SW_RESTORE
            user32.SetForegroundWindow(dialog)
            return 1
        end
        return 0
    end)
    return WIN32_COLOR
end

-- Returns the chosen color as {r, g, b}, false when the user cancels, or nil and an error.
-- ``swatches`` (up to 16 {r, g, b}) fill the dialog's custom colors the first time.
local function win32_choose_color(r, g, b, swatches)
    local api, api_error = win32_color_api()
    if not api then return nil, api_error end
    local function colorref(cr, cg, cb) return cr + cg * 256 + cb * 65536 end
    if not api.seeded then
        api.seeded = true
        for index, color in ipairs(swatches or {}) do
            if index > 16 then break end
            api.custom[index - 1] = colorref(color[1], color[2], color[3])
        end
    end
    local dialog = api.ffi.new("tviz_CHOOSECOLORW_V1")
    dialog.lStructSize = api.ffi.sizeof(dialog)
    dialog.hwndOwner = api.user32.GetForegroundWindow()
    dialog.rgbResult = colorref(r, g, b)
    dialog.lpCustColors = api.custom
    dialog.lpfnHook = api.hook
    -- CC_RGBINIT | CC_FULLOPEN | CC_ENABLEHOOK | CC_ANYCOLOR
    dialog.Flags = 0x00000001 + 0x00000002 + 0x00000010 + 0x00000100
    if api.comdlg32.ChooseColorW(dialog) == 0 then return false end
    local value = tonumber(dialog.rgbResult)
    return { value % 256, math.floor(value / 256) % 256, math.floor(value / 65536) % 256 }
end
-- The dialog calls back into Lua (the hook), which LuaJIT allows only from interpreted code.
pcall(function() require("jit").off(win32_choose_color) end)

-- Mirror of davinci_track_visualizer.skins.catalog(); tests/test_lua_catalog.py keeps it in sync.
-- BEGIN GENERATED SKIN_CATALOG (scripts/sync_lua_catalog.py)
local SKIN_CATALOG = {
    anchors = { "bottom_left", "bottom_center", "bottom_right", "top_left", "top_center", "top_right", "center" },
    base_sizes = {
        classic = { 640, 160 },
        compact = { 600, 96 },
        minimal = { 640, 176 },
        portrait_glass = { 420, 640 },
        wave = { 720, 208 },
    },
    bool_keys = { "show_cover", "show_artist", "show_title", "show_brand", "show_time", "show_progress", "show_knob", "show_bars", "glass_enabled", "uppercase_artist", "time_bold", "scroll_title" },
    color_keys = { "panel_color", "border_color", "primary_text_color", "secondary_text_color", "accent_color", "track_color" },
    default_palettes = {
        classic = "Default",
        compact = "Mint",
        minimal = "GoldSignal",
        portrait_glass = "Lavender",
        wave = "Midnight",
    },
    defaults = {
        classic = {
            accent_color = "#EBEEF0",
            anchor = "bottom_left",
            artist_font_family = "Segoe UI",
            artist_size = 16,
            bar_count = 72,
            border_alpha = 82,
            border_color = "#FFFFFF",
            brand_text = "aplus.fm",
            corner_radius = 14,
            glass_enabled = true,
            glass_strength = 46,
            margin_x = 48,
            margin_y = 48,
            meta_size = 14,
            panel_alpha = 154,
            panel_color = "#121619",
            primary_text_color = "#F5F7F8",
            progress_basis = "track",
            progress_style = "wave",
            scale = 100,
            scroll_title = true,
            secondary_text_color = "#EEF3F5",
            show_artist = true,
            show_bars = true,
            show_brand = true,
            show_cover = true,
            show_knob = true,
            show_progress = true,
            show_time = true,
            show_title = true,
            time_bold = false,
            time_font_family = "Segoe UI",
            time_mode = "elapsed_total",
            title_font_family = "Segoe UI",
            title_size = 26,
            track_color = "#EBEEF0",
            uppercase_artist = false,
        },
        compact = {
            accent_color = "#4FE3B5",
            anchor = "bottom_left",
            artist_font_family = "Segoe UI",
            artist_size = 16,
            bar_count = 72,
            border_alpha = 60,
            border_color = "#7CE0C3",
            brand_text = "aplus.fm",
            corner_radius = 48,
            glass_enabled = false,
            glass_strength = 0,
            margin_x = 48,
            margin_y = 48,
            meta_size = 15,
            panel_alpha = 214,
            panel_color = "#0E1714",
            primary_text_color = "#F2FFF9",
            progress_basis = "track",
            progress_style = "wave",
            scale = 100,
            scroll_title = true,
            secondary_text_color = "#A7E8D3",
            show_artist = true,
            show_bars = true,
            show_brand = true,
            show_cover = true,
            show_knob = true,
            show_progress = true,
            show_time = true,
            show_title = true,
            time_bold = false,
            time_font_family = "Segoe UI",
            time_mode = "elapsed_total",
            title_font_family = "Segoe UI",
            title_size = 24,
            track_color = "#A7E8D3",
            uppercase_artist = false,
        },
        minimal = {
            accent_color = "#FFD84A",
            anchor = "bottom_left",
            artist_font_family = "Courier New",
            artist_size = 16,
            bar_count = 72,
            border_alpha = 255,
            border_color = "#F2A900",
            brand_text = "aplus.fm",
            corner_radius = 2,
            glass_enabled = false,
            glass_strength = 0,
            margin_x = 48,
            margin_y = 48,
            meta_size = 30,
            panel_alpha = 224,
            panel_color = "#241704",
            primary_text_color = "#FFD84A",
            progress_basis = "track",
            progress_style = "wave",
            scale = 100,
            scroll_title = true,
            secondary_text_color = "#F2A900",
            show_artist = true,
            show_bars = true,
            show_brand = true,
            show_cover = true,
            show_knob = true,
            show_progress = false,
            show_time = true,
            show_title = true,
            time_bold = true,
            time_font_family = "Segoe UI",
            time_mode = "elapsed_total",
            title_font_family = "Impact",
            title_size = 32,
            track_color = "#F2A900",
            uppercase_artist = true,
        },
        portrait_glass = {
            accent_color = "#A78BFA",
            anchor = "bottom_left",
            artist_font_family = "Segoe UI",
            artist_size = 17,
            bar_count = 72,
            border_alpha = 92,
            border_color = "#C4B5FD",
            brand_text = "aplus.fm",
            corner_radius = 24,
            glass_enabled = true,
            glass_strength = 70,
            margin_x = 48,
            margin_y = 48,
            meta_size = 15,
            panel_alpha = 164,
            panel_color = "#171125",
            primary_text_color = "#FFF8ED",
            progress_basis = "track",
            progress_style = "wave",
            scale = 100,
            scroll_title = true,
            secondary_text_color = "#D8CCF2",
            show_artist = true,
            show_bars = true,
            show_brand = true,
            show_cover = true,
            show_knob = false,
            show_progress = true,
            show_time = true,
            show_title = true,
            time_bold = false,
            time_font_family = "Segoe UI",
            time_mode = "split",
            title_font_family = "Segoe UI",
            title_size = 30,
            track_color = "#D8CCF2",
            uppercase_artist = true,
        },
        wave = {
            accent_color = "#7AA2FF",
            anchor = "bottom_left",
            artist_font_family = "Segoe UI",
            artist_size = 17,
            bar_count = 96,
            border_alpha = 70,
            border_color = "#AEBBDD",
            brand_text = "aplus.fm",
            corner_radius = 18,
            glass_enabled = true,
            glass_strength = 55,
            margin_x = 48,
            margin_y = 48,
            meta_size = 15,
            panel_alpha = 176,
            panel_color = "#0B0F1A",
            primary_text_color = "#F3F6FF",
            progress_basis = "track",
            progress_style = "wave",
            scale = 100,
            scroll_title = true,
            secondary_text_color = "#AEBBDD",
            show_artist = true,
            show_bars = true,
            show_brand = true,
            show_cover = true,
            show_knob = true,
            show_progress = true,
            show_time = true,
            show_title = true,
            time_bold = false,
            time_font_family = "Segoe UI",
            time_mode = "split",
            title_font_family = "Segoe UI",
            title_size = 30,
            track_color = "#AEBBDD",
            uppercase_artist = true,
        },
    },
    enums = {
        anchor = { "bottom_left", "bottom_center", "bottom_right", "top_left", "top_center", "top_right", "center" },
        progress_basis = { "track", "clip" },
        progress_style = { "wave", "line" },
        time_mode = { "elapsed_total", "split", "elapsed", "remaining", "none" },
    },
    features = {
        classic = { "cover", "artist", "title", "brand", "time", "progress", "knob", "bars", "glass", "progress_style" },
        compact = { "cover", "artist", "title", "time", "progress", "knob" },
        minimal = { "artist", "title", "time", "progress" },
        portrait_glass = { "cover", "artist", "title", "time", "progress", "knob", "bars", "glass", "progress_style" },
        wave = { "cover", "artist", "title", "brand", "time", "bars", "knob", "glass" },
    },
    int_ranges = {
        artist_size = { 8, 96 },
        bar_count = { 8, 200 },
        border_alpha = { 0, 255 },
        corner_radius = { 0, 64 },
        glass_strength = { 0, 100 },
        margin_x = { 0, 2000 },
        margin_y = { 0, 2000 },
        meta_size = { 8, 96 },
        panel_alpha = { 0, 255 },
        scale = { 25, 400 },
        title_size = { 8, 96 },
    },
    palette_keys = { "panel_color", "panel_alpha", "border_color", "border_alpha", "primary_text_color", "secondary_text_color", "accent_color", "track_color", "glass_strength" },
    palette_order = { "Default", "Violet", "Ice", "Amber", "Neon", "Ultraviolet", "Acid", "Crimson", "Steel", "Ember", "GoldSignal", "Mint", "Lavender", "Midnight" },
    palettes = {
        Acid = {
            accent_color = "#F4FF00",
            border_alpha = 108,
            border_color = "#B8FF3D",
            glass_strength = 58,
            panel_alpha = 184,
            panel_color = "#0D120B",
            primary_text_color = "#E8FF65",
            secondary_text_color = "#B8FF3D",
            track_color = "#52612E",
        },
        Amber = {
            accent_color = "#FF9D3B",
            border_alpha = 76,
            border_color = "#FFB86B",
            glass_strength = 60,
            panel_alpha = 156,
            panel_color = "#21160D",
            primary_text_color = "#FFF2DB",
            secondary_text_color = "#FFD29A",
            track_color = "#FFD29A",
        },
        Crimson = {
            accent_color = "#FF2E2E",
            border_alpha = 116,
            border_color = "#E04444",
            glass_strength = 48,
            panel_alpha = 190,
            panel_color = "#16090A",
            primary_text_color = "#FFF1E8",
            secondary_text_color = "#FF7A66",
            track_color = "#692929",
        },
        Default = {
            accent_color = "#EBEEF0",
            border_alpha = 82,
            border_color = "#FFFFFF",
            glass_strength = 46,
            panel_alpha = 154,
            panel_color = "#121619",
            primary_text_color = "#F5F7F8",
            secondary_text_color = "#EEF3F5",
            track_color = "#EBEEF0",
        },
        Ember = {
            accent_color = "#FF3D00",
            border_alpha = 110,
            border_color = "#FF6A2A",
            glass_strength = 52,
            panel_alpha = 188,
            panel_color = "#170D08",
            primary_text_color = "#FFE1C2",
            secondary_text_color = "#FF9A52",
            track_color = "#71321C",
        },
        GoldSignal = {
            accent_color = "#FFD84A",
            border_alpha = 255,
            border_color = "#F2A900",
            glass_strength = 0,
            panel_alpha = 224,
            panel_color = "#241704",
            primary_text_color = "#FFD84A",
            secondary_text_color = "#F2A900",
            track_color = "#F2A900",
        },
        Ice = {
            accent_color = "#70E7FF",
            border_alpha = 74,
            border_color = "#B8F2FF",
            glass_strength = 72,
            panel_alpha = 150,
            panel_color = "#101C23",
            primary_text_color = "#F7FDFF",
            secondary_text_color = "#C9F5FF",
            track_color = "#D7F9FF",
        },
        Lavender = {
            accent_color = "#A78BFA",
            border_alpha = 92,
            border_color = "#C4B5FD",
            glass_strength = 70,
            panel_alpha = 164,
            panel_color = "#171125",
            primary_text_color = "#FFF8ED",
            secondary_text_color = "#D8CCF2",
            track_color = "#D8CCF2",
        },
        Midnight = {
            accent_color = "#7AA2FF",
            border_alpha = 70,
            border_color = "#AEBBDD",
            glass_strength = 55,
            panel_alpha = 176,
            panel_color = "#0B0F1A",
            primary_text_color = "#F3F6FF",
            secondary_text_color = "#AEBBDD",
            track_color = "#AEBBDD",
        },
        Mint = {
            accent_color = "#4FE3B5",
            border_alpha = 60,
            border_color = "#7CE0C3",
            glass_strength = 0,
            panel_alpha = 214,
            panel_color = "#0E1714",
            primary_text_color = "#F2FFF9",
            secondary_text_color = "#A7E8D3",
            track_color = "#A7E8D3",
        },
        Neon = {
            accent_color = "#00F5D4",
            border_alpha = 118,
            border_color = "#00E5FF",
            glass_strength = 72,
            panel_alpha = 178,
            panel_color = "#090B16",
            primary_text_color = "#FF3DF2",
            secondary_text_color = "#9AF7FF",
            track_color = "#43506B",
        },
        Steel = {
            accent_color = "#D5DADE",
            border_alpha = 104,
            border_color = "#A9B2BC",
            glass_strength = 42,
            panel_alpha = 194,
            panel_color = "#111417",
            primary_text_color = "#F1F3F5",
            secondary_text_color = "#A9B2BC",
            track_color = "#4A5158",
        },
        Ultraviolet = {
            accent_color = "#FF4FD8",
            border_alpha = 112,
            border_color = "#8D5CFF",
            glass_strength = 76,
            panel_alpha = 176,
            panel_color = "#10091E",
            primary_text_color = "#F4EEFF",
            secondary_text_color = "#C4A7FF",
            track_color = "#655089",
        },
        Violet = {
            accent_color = "#FFB454",
            border_alpha = 82,
            border_color = "#B77CFF",
            glass_strength = 68,
            panel_alpha = 158,
            panel_color = "#1A1028",
            primary_text_color = "#FFF4D6",
            secondary_text_color = "#DCCBFF",
            track_color = "#DCCBFF",
        },
    },
    progress_bases = { "track", "clip" },
    progress_styles = { "wave", "line" },
    schema = 2,
    skins = { "classic", "minimal", "portrait_glass", "compact", "wave" },
    text_limits = {
        artist_font_family = 80,
        brand_text = 40,
        time_font_family = 80,
        title_font_family = 80,
    },
    time_modes = { "elapsed_total", "split", "elapsed", "remaining", "none" },
}
-- END GENERATED SKIN_CATALOG

local FONT_FAMILIES = {
    "Segoe UI",
    "Arial",
    "Calibri",
    "Tahoma",
    "Verdana",
    "Trebuchet MS",
    "Georgia",
    "Times New Roman",
    "Courier New",
    "Impact",
    "Montserrat",
    "Inter",
    "Roboto",
    "Open Sans",
}

local I18N = {
    en = {
        ["window.title"] = "Track Visualizer",
        ["app.subtitle"] = "Music player overlays for the audio clips on your timeline.",
        ["tab.create"] = "Players",
        ["tab.style"] = "Look",
        ["tab.presets"] = "Library",
        ["tab.log"] = "Service",
        ["section.timeline"] = "Timeline",
        ["field.audio_tracks"] = "Audio tracks",
        ["hint.audio_tracks"] = "For example 1-3 or 1,2",
        ["field.video_track"] = "Video track",
        ["field.switch_mode"] = "Overlapping tracks",
        ["hint.switch_mode"] = "Where one player hands over to the next when tracks overlap in a crossfade. A clip that plays entirely inside another track gets no player.",
        ["switch_mode.overlap_middle"] = "Switch in the middle of the crossfade",
        ["switch_mode.next_start"] = "Switch when the next track starts",
        ["switch_mode.current_end"] = "Switch when the current track ends",
        ["field.update_scope"] = "Only clips",
        ["scope.placeholder"] = "all, 3,5-7 or @playhead",
        ["scope.alias_all"] = "all",
        ["scope.alias_current"] = "current",
        ["scope.hint"] = "Empty = all clips; 3,5-7 = clip numbers from the list; @playhead = the clip under the playhead.",
        ["action.list_clips"] = "List clips",
        ["section.style_summary"] = "Player look",
        ["action.customize"] = "Fine-tune the look",
        ["action.save_as_preset"] = "Save as preset",
        ["hint.audio_tracks_tip"] = "Audio tracks with music clips, for example 1-3 or 1,2.",
        ["hint.video_track_tip"] = "Players are placed on this video track. Use an empty track.",
        ["field.preset"] = "Preset",
        ["preset.current_style"] = "Custom settings",
        ["preset.option"] = "{name}  ·  {skin}",
        ["preset.summary"] = "Skin and palette come from preset \"{name}\". Changing them switches to custom settings.",
        ["field.active_style"] = "{skin} · {palette}",
        ["action.create"] = "Create players",
        ["action.cancel"] = "Cancel",
        ["action.remove_players"] = "Remove players",
        ["action.remove_confirm"] = "Click again to remove",
        ["field.status"] = "Status",
        ["status.ready"] = "Ready",
        ["status.scanning"] = "Reading the timeline...",
        ["status.engine_start"] = "Preparing players...",
        ["status.engine_progress"] = "Preparing players {index}/{total}",
        ["status.placing"] = "Placing players {index}/{total}",
        ["status.done"] = "Done: {count} players on V{track}",
        ["status.done_with_errors"] = "Done with problems: {count} placed, {failed} failed. See the log.",
        ["status.cancelling"] = "Cancelling...",
        ["status.cancelled"] = "Cancelled: {placed} of {total} players placed",
        ["status.error"] = "Error: {message}",
        ["status.removed"] = "Removed {count} players from V{track}",
        ["status.busy"] = "Working...",
        ["error.last"] = "Last error: {message}",
        ["error.unknown"] = "Unknown error",
        ["error.log_prefix"] = "ERROR: {message}",
        ["error.busy"] = "Another operation is still running.",
        ["preview.idle"] = "Click the preview to open it full size",
        ["preview.rendering"] = "Rendering preview...",
        ["preview.failed"] = "Preview failed: {details}",
        ["preview.sample_title"] = "Preview Track Title",
        ["preview.sample_artist"] = "Artist Name",
        ["field.skin"] = "Skin",
        ["field.palette"] = "Palette",
        ["action.apply"] = "Apply",
        ["skin.classic"] = "Classic",
        ["skin.minimal"] = "Minimal",
        ["skin.portrait_glass"] = "Portrait Glass",
        ["skin.compact"] = "Compact",
        ["skin.wave"] = "Wave",
        ["palette.Custom"] = "Custom",
        ["palette.Default"] = "Default",
        ["palette.Violet"] = "Violet",
        ["palette.Ice"] = "Ice",
        ["palette.Amber"] = "Amber",
        ["palette.Neon"] = "Neon",
        ["palette.Ultraviolet"] = "Ultraviolet",
        ["palette.Acid"] = "Acid",
        ["palette.Crimson"] = "Crimson Rock",
        ["palette.Steel"] = "Steel",
        ["palette.Ember"] = "Coal and Flame",
        ["palette.GoldSignal"] = "Gold Signal",
        ["palette.Mint"] = "Mint",
        ["palette.Lavender"] = "Lavender",
        ["palette.Midnight"] = "Midnight",
        ["style.tab_layout"] = "Layout",
        ["style.tab_colors"] = "Colors",
        ["style.tab_text"] = "Text",
        ["field.anchor"] = "Position",
        ["anchor.bottom_left"] = "Bottom left",
        ["anchor.bottom_center"] = "Bottom center",
        ["anchor.bottom_right"] = "Bottom right",
        ["anchor.top_left"] = "Top left",
        ["anchor.top_center"] = "Top center",
        ["anchor.top_right"] = "Top right",
        ["anchor.center"] = "Center",
        ["field.scale"] = "Size, %",
        ["field.margin_x"] = "Margins: side",
        ["field.margin_y"] = "top/bottom",
        ["field.elements"] = "Elements",
        ["field.cover"] = "Cover",
        ["field.artist"] = "Artist",
        ["field.title_toggle"] = "Title",
        ["field.brand"] = "Brand",
        ["field.time"] = "Time",
        ["field.progress"] = "Progress",
        ["field.progress_style"] = "Progress style",
        ["progress_style.wave"] = "Waveform",
        ["progress_style.line"] = "Line",
        ["field.knob"] = "Playhead marker",
        ["field.bars"] = "Waveform",
        ["field.glass"] = "Glass",
        ["field.uppercase_artist"] = "Artist in capitals",
        ["field.scroll_title"] = "Scroll long titles",
        ["field.time_mode"] = "Time display",
        ["time_mode.elapsed_total"] = "Elapsed / total",
        ["time_mode.split"] = "Elapsed and total at the ends",
        ["time_mode.elapsed"] = "Elapsed",
        ["time_mode.remaining"] = "Remaining",
        ["time_mode.none"] = "Hidden",
        ["field.progress_basis"] = "Progress shows",
        ["progress_basis.track"] = "Position in the whole track",
        ["progress_basis.clip"] = "Position in the clip",
        ["field.bar_count"] = "Waveform bars",
        ["field.brand_text"] = "Brand label",
        ["field.fallback_logo"] = "Default cover",
        ["hint.fallback_logo"] = "Used when a track has no embedded cover art.",
        ["action.choose_png"] = "Choose...",
        ["action.default"] = "Default",
        ["field.panel"] = "Panel",
        ["field.border"] = "Border",
        ["field.primary_text"] = "Title text",
        ["field.secondary_text"] = "Artist and time",
        ["field.accent"] = "Accent (played)",
        ["field.track"] = "Track (unplayed)",
        ["field.opacity"] = "Opacity",
        ["field.glass_strength"] = "Glass strength",
        ["field.radius"] = "Corner radius",
        ["field.color"] = "Click to pick a color",
        ["field.title_font"] = "Title font",
        ["field.artist_font"] = "Artist font",
        ["field.time_font"] = "Time font",
        ["field.size"] = "Size",
        ["field.time_bold"] = "Bold",
        ["action.reset_style"] = "Reset skin to defaults",
        ["presets.title"] = "Presets",
        ["presets.hint"] = "A preset stores the skin and every style setting: layout, elements, colors and fonts.",
        ["field.preset_list"] = "Saved",
        ["field.preset_name"] = "Name",
        ["action.preset_apply"] = "Apply",
        ["action.preset_delete"] = "Delete",
        ["action.preset_save"] = "Save current look",
        ["action.preset_rename"] = "Rename",
        ["action.preset_export"] = "Export",
        ["action.preset_import"] = "Import...",
        ["action.open_presets_folder"] = "Open folder",
        ["presets.empty"] = "No presets yet",
        ["palettes.title"] = "Palettes",
        ["palettes.hint"] = "A palette stores only colors and opacity, so it can be reused with any skin.",
        ["field.palette_name"] = "Name",
        ["action.palette_save"] = "Save current colors",
        ["action.palette_delete"] = "Delete",
        ["palette.custom_mark"] = "{name} (mine)",
        ["section.updates"] = "Updates",
        ["field.auto_update"] = "Update automatically",
        ["action.check_updates"] = "Check now",
        ["update.version"] = "Installed version: {version}",
        ["update.dev_install"] = "Updates work only for Windows installs made with the installer.",
        ["update.checking"] = "Checking for updates...",
        ["update.downloading"] = "Downloading the update: {percent}%",
        ["update.up_to_date"] = "You have the latest version ({version}).",
        ["update.ready"] = "Version {version} is downloaded and verified. It installs as soon as the panel is idle.",
        ["update.installing"] = "Installing the update... This takes a few seconds.",
        ["update.installing_version"] = "Installing update {version}",
        ["update.installed"] = "Updated to {version}. Close and reopen Track Visualizer to use the new version.",
        ["update.reopen"] = "Track Visualizer was updated to {version}. Close and reopen the panel first.",
        ["update.failed"] = "Update failed; the current version is kept: {details}",
        ["update.install_timeout"] = "the installer did not finish in 10 minutes",
        ["log.preset_saved"] = "Preset saved: {name}",
        ["log.preset_applied"] = "Preset applied: {name}",
        ["log.preset_deleted"] = "Preset deleted: {name}",
        ["log.preset_renamed"] = "Preset renamed: {old} -> {name}",
        ["log.preset_exported"] = "Preset exported: {path}",
        ["log.preset_imported"] = "Imported: {name}",
        ["log.palette_saved"] = "Palette saved: {name}",
        ["log.palette_deleted"] = "Palette deleted: {name}",
        ["log.palette_applied"] = "Palette \"{palette}\" applied to {skin}",
        ["log.skin_active"] = "Active skin: {skin}",
        ["log.style_reset"] = "Skin reset to defaults: {skin}",
        ["error.preset_name_required"] = "Enter a name first.",
        ["error.preset_not_selected"] = "Select a preset first.",
        ["error.palette_builtin"] = "Built-in palettes cannot be deleted.",
        ["error.import_invalid"] = "The file is not a Track Visualizer preset or palette: {path}",
        ["diagnostics.title"] = "Log",
        ["section.interface"] = "Interface",
        ["diagnostics.paths"] = "Log: {log}\nClip property dump: {dump}\nLast error: {error}",
        ["field.language"] = "Language",
        ["language.auto"] = "Auto (system)",
        ["language.en"] = "English",
        ["language.ru"] = "Russian",
        ["language.restart_hint"] = "Close and reopen Track Visualizer after changing the language.",
        ["language.saved_reopen"] = "Language saved. Close and reopen Track Visualizer to update every label.",
        ["action.copy_log"] = "Copy log",
        ["action.open_log"] = "Open log",
        ["action.clear_log"] = "Clear log",
        ["action.cleanup_legacy"] = "Remove old helper timelines",
        ["hint.cleanup_legacy"] = "Earlier versions created TVIZ__SOURCE helper timelines. They can be removed once no old players use them in this timeline.",
        ["log.legacy_none"] = "No old helper timelines were found for this timeline.",
        ["log.legacy_removed"] = "Removed old helper timelines: {count}",
        ["log.legacy_in_use"] = "Old players still use helper timelines here ({count}). Recreate them with this version first.",
        ["error.runner_missing"] = "Track Visualizer runner was not found: {path}",
        ["error.runner_launch"] = "Could not launch the Track Visualizer runner: {details}",
        ["error.windows_wide_launch"] = "Unicode-safe Windows launch is unavailable for this path: {details}",
        ["error.runner_timeout"] = "Runner did not finish within {seconds} seconds",
        ["error.runner_exit"] = "The engine stopped with code {code}: {details}",
        ["error.runner_completion"] = "Runner wrote an invalid completion file: {path}",
        ["error.engine_missing"] = "Track Visualizer engine was not found: {path}",
        ["error.settings_temp_open"] = "Could not open the temporary settings file: {details}",
        ["error.settings_temp_write"] = "Could not write the temporary settings file: {details}",
        ["error.settings_temp_verify"] = "Temporary settings verification failed",
        ["error.settings_invalid_json"] = "Refusing to replace settings with invalid JSON",
        ["error.settings_backup"] = "Could not back up settings before replacement: {details}",
        ["error.settings_replace"] = "Could not replace settings: {details}",
        ["log.clip_properties_no_path"] = "Clip properties without a path: {details}",
        ["log.overlap_same_start"] = "Clips starting at the same frame: kept the higher audio track ({count})",
        ["log.zero_length"] = "Skipped a zero-length player: {name}",
        ["log.switch_trimmed"] = "Player ends early for the next track: {name} {from}f -> {to}f",
        ["log.switch_delayed"] = "Player starts {frames}f later, after the previous track: {name}",
        ["log.overlay_skipped"] = "No separate player: {name} plays entirely inside another track",
        ["log.clip_numbers"] = "Clips on the timeline:",
        ["log.more_clips"] = "...and {count} more clips",
        ["error.no_clip_at_playhead"] = "No audio clip under the playhead at {time}",
        ["log.playhead_selected"] = "Clip #{number} is under the playhead",
        ["error.scope_invalid"] = "Clips: enter numbers such as 3,5-7, leave empty for all, or use @playhead.",
        ["error.unknown_clip_numbers"] = "Unknown clip numbers: {numbers}",
        ["log.partial_update"] = "Updating only: {clips}",
        ["log.track_missing"] = "Skipped A{track}: the track does not exist",
        ["summary.track_missing"] = "A{track} missing (count={count})",
        ["log.clip_no_path"] = "Skipped an audio clip without a file path: {name}",
        ["log.clip_dump"] = "Clip property dump: {path}",
        ["log.timeline_resolution"] = "Timeline: {width}x{height}, {fps} fps",
        ["error.resolution"] = "Resolve did not report the timeline resolution.",
        ["warning.fps_fallback"] = "Warning: the timeline frame rate could not be read; using 30 fps.",
        ["warning.playback_rate"] = "Playback frame rate ({playback} fps) does not match the timeline ({timeline} fps): Resolve will play at the wrong speed with crackling sound. Set Playback frame rate to {timeline} in File → Project Settings → Master Settings.",
        ["error.video_track_index"] = "Invalid video track: {track}",
        ["error.video_track_add"] = "Resolve did not add the video track: {details}",
        ["error.video_track_count"] = "Resolve did not increase the video track count after AddTrack",
        ["error.video_track_create"] = "Could not create video track V{track}",
        ["error.project_required"] = "Open or create a DaVinci Resolve project first.",
        ["error.timeline_required"] = "Open a timeline first.",
        ["error.no_audio_clips"] = "No audio clips were found on A{tracks}.{hint}{details}",
        ["error.no_audio_path_hint"] = " Resolve sees the clips but does not report their audio files. A clip property dump was written to the log folder.",
        ["error.details"] = " Details: {details}",
        ["log.audio_found"] = "Audio clips on A{tracks}: {count}",
        ["log.clips_listed"] = "Listed clips on A{tracks}: {count}",
        ["log.scope_help"] = "Use these numbers in the Clips field: 3,5-7, or @playhead.",
        ["log.run_start"] = "Creating {count} players: {skin}, {width}x{height} @ {fps} fps",
        ["log.carrier_ready"] = "Carrier clip: {name}",
        ["log.players_removed"] = "Removed {count} old players from V{track}",
        ["log.cancel_requested"] = "Cancel requested.",
        ["log.run_done"] = "Placed {count} players in {seconds} s",
        ["error.manifest_missing"] = "The engine did not write its manifest: {path}",
        ["error.manifest_invalid"] = "The engine manifest is invalid: {details}",
        ["error.timeline_changed"] = "The current timeline changed during the run. Players were placed only on \"{name}\".",
        ["error.carrier_import"] = "Resolve could not import the carrier clip: {path}",
        ["error.track_conflict"] = "V{track} already has other clips at {time}. Choose an empty video track.",
        ["warning.player_failed"] = "Player was not placed for \"{name}\": {details}",
        ["warning.engine"] = "Engine warning: {details}",
        ["notice.color_manual"] = "The system color picker is unavailable on this platform. Enter a #RRGGBB value manually.",
        ["error.choose_png"] = "Choose a .png file for the fallback cover",
        ["log.logo_selected"] = "Fallback cover selected: {path}",
        ["log.logo_default"] = "Fallback cover reset to the default",
    },
    ru = {
        ["window.title"] = "Track Visualizer",
        ["app.subtitle"] = "Плееры с обложкой, названием и прогрессом для аудиоклипов на таймлайне.",
        ["tab.create"] = "Плееры",
        ["tab.style"] = "Вид",
        ["tab.presets"] = "Библиотека",
        ["tab.log"] = "Сервис",
        ["section.timeline"] = "Таймлайн",
        ["field.audio_tracks"] = "Аудиодорожки",
        ["hint.audio_tracks"] = "Например 1-3 или 1,2",
        ["field.video_track"] = "Видеодорожка",
        ["field.switch_mode"] = "Наложение треков",
        ["hint.switch_mode"] = "Где один плеер сменяется другим, когда треки перекрываются в кроссфейде. Клип, целиком звучащий внутри другого трека, плеера не получает.",
        ["switch_mode.overlap_middle"] = "Сменить в середине перехода",
        ["switch_mode.next_start"] = "Сменить, когда начался следующий трек",
        ["switch_mode.current_end"] = "Сменить, когда закончился текущий трек",
        ["field.update_scope"] = "Только клипы",
        ["scope.placeholder"] = "все, 3,5-7 или @playhead",
        ["scope.alias_all"] = "все",
        ["scope.alias_current"] = "текущий",
        ["scope.hint"] = "Пусто = все клипы; 3,5-7 = номера из списка; @playhead = клип под плейхедом.",
        ["action.list_clips"] = "Список клипов",
        ["section.style_summary"] = "Вид плеера",
        ["action.customize"] = "Настроить детали",
        ["action.save_as_preset"] = "Сохранить как пресет",
        ["hint.audio_tracks_tip"] = "Аудиодорожки с музыкой, например 1-3 или 1,2.",
        ["hint.video_track_tip"] = "На эту видеодорожку встанут плееры. Лучше выбрать пустую.",
        ["field.preset"] = "Пресет",
        ["preset.current_style"] = "Свои настройки",
        ["preset.option"] = "{name}  ·  {skin}",
        ["preset.summary"] = "Скин и палитра взяты из пресета «{name}». Если их изменить, включатся свои настройки.",
        ["field.active_style"] = "{skin} · {palette}",
        ["action.create"] = "Создать плееры",
        ["action.cancel"] = "Отмена",
        ["action.remove_players"] = "Удалить плееры",
        ["action.remove_confirm"] = "Нажмите ещё раз для удаления",
        ["field.status"] = "Статус",
        ["status.ready"] = "Готово к работе",
        ["status.scanning"] = "Читаю таймлайн...",
        ["status.engine_start"] = "Готовлю плееры...",
        ["status.engine_progress"] = "Готовлю плееры {index}/{total}",
        ["status.placing"] = "Размещаю плееры {index}/{total}",
        ["status.done"] = "Готово: {count} плееров на V{track}",
        ["status.done_with_errors"] = "Готово с проблемами: размещено {count}, ошибок {failed}. Подробности в журнале.",
        ["status.cancelling"] = "Отменяю...",
        ["status.cancelled"] = "Отменено: размещено {placed} из {total}",
        ["status.error"] = "Ошибка: {message}",
        ["status.removed"] = "Удалено плееров с V{track}: {count}",
        ["status.busy"] = "Выполняется...",
        ["error.last"] = "Последняя ошибка: {message}",
        ["error.unknown"] = "Неизвестная ошибка",
        ["error.log_prefix"] = "ОШИБКА: {message}",
        ["error.busy"] = "Предыдущая операция ещё выполняется.",
        ["preview.idle"] = "Нажмите на превью, чтобы открыть крупно",
        ["preview.rendering"] = "Рисую превью...",
        ["preview.failed"] = "Превью не получилось: {details}",
        ["preview.sample_title"] = "Название трека",
        ["preview.sample_artist"] = "Исполнитель",
        ["field.skin"] = "Скин",
        ["field.palette"] = "Палитра",
        ["action.apply"] = "Применить",
        ["skin.classic"] = "Классический",
        ["skin.minimal"] = "Минимал",
        ["skin.portrait_glass"] = "Вертикальное стекло",
        ["skin.compact"] = "Компактный",
        ["skin.wave"] = "Волна",
        ["palette.Custom"] = "Своя",
        ["palette.Default"] = "Стандарт",
        ["palette.Violet"] = "Фиолетовый",
        ["palette.Ice"] = "Лёд",
        ["palette.Amber"] = "Янтарь",
        ["palette.Neon"] = "Неон",
        ["palette.Ultraviolet"] = "Ультрафиолет",
        ["palette.Acid"] = "Кислотный",
        ["palette.Crimson"] = "Багровый рок",
        ["palette.Steel"] = "Сталь",
        ["palette.Ember"] = "Угли и пламя",
        ["palette.GoldSignal"] = "Золотой сигнал",
        ["palette.Mint"] = "Мята",
        ["palette.Lavender"] = "Лаванда",
        ["palette.Midnight"] = "Полночь",
        ["style.tab_layout"] = "Расположение",
        ["style.tab_colors"] = "Цвета",
        ["style.tab_text"] = "Текст",
        ["field.anchor"] = "Положение",
        ["anchor.bottom_left"] = "Снизу слева",
        ["anchor.bottom_center"] = "Снизу по центру",
        ["anchor.bottom_right"] = "Снизу справа",
        ["anchor.top_left"] = "Сверху слева",
        ["anchor.top_center"] = "Сверху по центру",
        ["anchor.top_right"] = "Сверху справа",
        ["anchor.center"] = "По центру",
        ["field.scale"] = "Размер, %",
        ["field.margin_x"] = "Отступы: сбоку",
        ["field.margin_y"] = "сверху/снизу",
        ["field.elements"] = "Элементы",
        ["field.cover"] = "Обложка",
        ["field.artist"] = "Исполнитель",
        ["field.title_toggle"] = "Название",
        ["field.brand"] = "Бренд",
        ["field.time"] = "Время",
        ["field.progress"] = "Прогресс",
        ["field.progress_style"] = "Вид прогресса",
        ["progress_style.wave"] = "Волна",
        ["progress_style.line"] = "Полоска",
        ["field.knob"] = "Маркер позиции",
        ["field.bars"] = "Волна",
        ["field.glass"] = "Стекло",
        ["field.uppercase_artist"] = "Исполнитель заглавными",
        ["field.scroll_title"] = "Прокручивать длинное название",
        ["field.time_mode"] = "Показ времени",
        ["time_mode.elapsed_total"] = "Прошло / всего",
        ["time_mode.split"] = "Прошло и всего по краям",
        ["time_mode.elapsed"] = "Прошло",
        ["time_mode.remaining"] = "Осталось",
        ["time_mode.none"] = "Скрыто",
        ["field.progress_basis"] = "Прогресс показывает",
        ["progress_basis.track"] = "Позицию во всём треке",
        ["progress_basis.clip"] = "Позицию в клипе",
        ["field.bar_count"] = "Столбиков волны",
        ["field.brand_text"] = "Текст бренда",
        ["field.fallback_logo"] = "Обложка по умолчанию",
        ["hint.fallback_logo"] = "Используется, если у трека нет встроенной обложки.",
        ["action.choose_png"] = "Выбрать...",
        ["action.default"] = "По умолчанию",
        ["field.panel"] = "Панель",
        ["field.border"] = "Рамка",
        ["field.primary_text"] = "Название",
        ["field.secondary_text"] = "Исполнитель и время",
        ["field.accent"] = "Акцент (проиграно)",
        ["field.track"] = "Дорожка (не проиграно)",
        ["field.opacity"] = "Непрозрачность",
        ["field.glass_strength"] = "Сила стекла",
        ["field.radius"] = "Скругление",
        ["field.color"] = "Нажмите, чтобы выбрать цвет",
        ["field.title_font"] = "Шрифт названия",
        ["field.artist_font"] = "Шрифт исполнителя",
        ["field.time_font"] = "Шрифт времени",
        ["field.size"] = "Размер",
        ["field.time_bold"] = "Жирный",
        ["action.reset_style"] = "Сбросить скин",
        ["presets.title"] = "Пресеты",
        ["presets.hint"] = "Пресет хранит скин и все настройки стиля: расположение, элементы, цвета и шрифты.",
        ["field.preset_list"] = "Сохранённые",
        ["field.preset_name"] = "Название",
        ["action.preset_apply"] = "Применить",
        ["action.preset_delete"] = "Удалить",
        ["action.preset_save"] = "Сохранить текущий вид",
        ["action.preset_rename"] = "Переименовать",
        ["action.preset_export"] = "Экспорт",
        ["action.preset_import"] = "Импорт...",
        ["action.open_presets_folder"] = "Открыть папку",
        ["presets.empty"] = "Пресетов пока нет",
        ["palettes.title"] = "Палитры",
        ["palettes.hint"] = "Палитра хранит только цвета и прозрачность, её можно применять к любому скину.",
        ["field.palette_name"] = "Название",
        ["action.palette_save"] = "Сохранить текущие цвета",
        ["action.palette_delete"] = "Удалить",
        ["palette.custom_mark"] = "{name} (моя)",
        ["section.updates"] = "Обновления",
        ["field.auto_update"] = "Обновлять автоматически",
        ["action.check_updates"] = "Проверить сейчас",
        ["update.version"] = "Установлена версия {version}",
        ["update.dev_install"] = "Обновления работают только для установки через установщик в Windows.",
        ["update.checking"] = "Проверяю обновления...",
        ["update.downloading"] = "Скачиваю обновление: {percent}%",
        ["update.up_to_date"] = "У вас последняя версия ({version}).",
        ["update.ready"] = "Версия {version} скачана и проверена. Установится, как только панель освободится.",
        ["update.installing"] = "Устанавливаю обновление... Это займёт несколько секунд.",
        ["update.installing_version"] = "Устанавливаю обновление {version}",
        ["update.installed"] = "Обновлено до {version}. Закройте и снова откройте Track Visualizer, чтобы работать в новой версии.",
        ["update.reopen"] = "Track Visualizer обновлён до {version}. Сначала закройте и снова откройте панель.",
        ["update.failed"] = "Не удалось обновиться, текущая версия сохранена: {details}",
        ["update.install_timeout"] = "установщик не завершился за 10 минут",
        ["log.preset_saved"] = "Пресет сохранён: {name}",
        ["log.preset_applied"] = "Пресет применён: {name}",
        ["log.preset_deleted"] = "Пресет удалён: {name}",
        ["log.preset_renamed"] = "Пресет переименован: {old} -> {name}",
        ["log.preset_exported"] = "Пресет экспортирован: {path}",
        ["log.preset_imported"] = "Импортировано: {name}",
        ["log.palette_saved"] = "Палитра сохранена: {name}",
        ["log.palette_deleted"] = "Палитра удалена: {name}",
        ["log.palette_applied"] = "Палитра «{palette}» применена к скину «{skin}»",
        ["log.skin_active"] = "Активный скин: {skin}",
        ["log.style_reset"] = "Скин сброшен: {skin}",
        ["error.preset_name_required"] = "Сначала введите название.",
        ["error.preset_not_selected"] = "Сначала выберите пресет.",
        ["error.palette_builtin"] = "Встроенные палитры удалить нельзя.",
        ["error.import_invalid"] = "Файл не является пресетом или палитрой Track Visualizer: {path}",
        ["diagnostics.title"] = "Журнал",
        ["section.interface"] = "Интерфейс",
        ["diagnostics.paths"] = "Журнал: {log}\nСвойства клипов: {dump}\nПоследняя ошибка: {error}",
        ["field.language"] = "Язык",
        ["language.auto"] = "Авто (системный)",
        ["language.en"] = "Английский",
        ["language.ru"] = "Русский",
        ["language.restart_hint"] = "После смены языка закройте и снова откройте Track Visualizer.",
        ["language.saved_reopen"] = "Язык сохранён. Закройте и снова откройте Track Visualizer, чтобы обновить все подписи.",
        ["action.copy_log"] = "Копировать",
        ["action.open_log"] = "Открыть файл",
        ["action.clear_log"] = "Очистить",
        ["action.cleanup_legacy"] = "Удалить старые служебные таймлайны",
        ["hint.cleanup_legacy"] = "Прошлые версии создавали служебные таймлайны TVIZ__SOURCE. Их можно удалить, когда в этом таймлайне не осталось старых плееров.",
        ["log.legacy_none"] = "Старых служебных таймлайнов для этого таймлайна нет.",
        ["log.legacy_removed"] = "Удалено старых служебных таймлайнов: {count}",
        ["log.legacy_in_use"] = "Здесь ещё есть старые плееры ({count}). Сначала пересоздайте их этой версией.",
        ["error.runner_missing"] = "Не найден исполнитель Track Visualizer: {path}",
        ["error.runner_launch"] = "Не удалось запустить исполнитель Track Visualizer: {details}",
        ["error.windows_wide_launch"] = "Unicode-запуск Windows недоступен для этого пути: {details}",
        ["error.runner_timeout"] = "Исполнитель не завершился за {seconds} с",
        ["error.runner_exit"] = "Движок остановился с кодом {code}: {details}",
        ["error.runner_completion"] = "Исполнитель записал некорректный файл завершения: {path}",
        ["error.engine_missing"] = "Не найден движок Track Visualizer: {path}",
        ["error.settings_temp_open"] = "Не удалось открыть временный файл настроек: {details}",
        ["error.settings_temp_write"] = "Не удалось записать временный файл настроек: {details}",
        ["error.settings_temp_verify"] = "Проверка временного файла настроек не прошла",
        ["error.settings_invalid_json"] = "Настройки не заменены: получился некорректный JSON",
        ["error.settings_backup"] = "Не удалось сохранить резервную копию настроек: {details}",
        ["error.settings_replace"] = "Не удалось заменить настройки: {details}",
        ["log.clip_properties_no_path"] = "Свойства клипа без пути: {details}",
        ["log.overlap_same_start"] = "Клипы с одинаковым началом: оставлена верхняя аудиодорожка ({count})",
        ["log.zero_length"] = "Пропущен плеер нулевой длины: {name}",
        ["log.switch_trimmed"] = "Плеер заканчивается раньше из-за следующего трека: {name} {from}f -> {to}f",
        ["log.switch_delayed"] = "Плеер начинается на {frames}f позже, после предыдущего трека: {name}",
        ["log.overlay_skipped"] = "Без отдельного плеера: {name} целиком звучит внутри другого трека",
        ["log.clip_numbers"] = "Клипы на таймлайне:",
        ["log.more_clips"] = "...и ещё {count}",
        ["error.no_clip_at_playhead"] = "Под плейхедом нет аудиоклипа ({time})",
        ["log.playhead_selected"] = "Под плейхедом клип #{number}",
        ["error.scope_invalid"] = "Клипы: укажите номера вроде 3,5-7, оставьте пустым для всех или используйте @playhead.",
        ["error.unknown_clip_numbers"] = "Нет клипов с номерами: {numbers}",
        ["log.partial_update"] = "Обновляю только: {clips}",
        ["log.track_missing"] = "Пропущена A{track}: такой дорожки нет",
        ["summary.track_missing"] = "A{track} отсутствует (count={count})",
        ["log.clip_no_path"] = "Пропущен аудиоклип без пути к файлу: {name}",
        ["log.clip_dump"] = "Свойства клипов сохранены: {path}",
        ["log.timeline_resolution"] = "Таймлайн: {width}x{height}, {fps} кадр/с",
        ["error.resolution"] = "Resolve не сообщил разрешение таймлайна.",
        ["warning.fps_fallback"] = "Внимание: частоту кадров таймлайна прочитать не удалось, использую 30.",
        ["warning.playback_rate"] = "Частота воспроизведения ({playback} кадр/с) не совпадает с частотой таймлайна ({timeline} кадр/с): Resolve будет играть с неправильной скоростью, а звук — хрипеть. Поставьте Playback frame rate = {timeline} в File → Project Settings → Master Settings.",
        ["error.video_track_index"] = "Неверный номер видеодорожки: {track}",
        ["error.video_track_add"] = "Resolve не добавил видеодорожку: {details}",
        ["error.video_track_count"] = "Resolve не увеличил число видеодорожек после AddTrack",
        ["error.video_track_create"] = "Не удалось создать видеодорожку V{track}",
        ["error.project_required"] = "Сначала откройте или создайте проект DaVinci Resolve.",
        ["error.timeline_required"] = "Сначала откройте таймлайн.",
        ["error.no_audio_clips"] = "На A{tracks} не найдено аудиоклипов.{hint}{details}",
        ["error.no_audio_path_hint"] = " Resolve видит клипы, но не сообщает пути к их файлам. Свойства клипов записаны в папку журнала.",
        ["error.details"] = " Подробности: {details}",
        ["log.audio_found"] = "Аудиоклипов на A{tracks}: {count}",
        ["log.clips_listed"] = "Клипы на A{tracks}: {count}",
        ["log.scope_help"] = "Эти номера можно указать в поле «Клипы»: 3,5-7 или @playhead.",
        ["log.run_start"] = "Создаю плееры: {count}, {skin}, {width}x{height} @ {fps} кадр/с",
        ["log.carrier_ready"] = "Несущий клип: {name}",
        ["log.players_removed"] = "Удалено старых плееров с V{track}: {count}",
        ["log.cancel_requested"] = "Запрошена отмена.",
        ["log.run_done"] = "Размещено плееров: {count} за {seconds} с",
        ["error.manifest_missing"] = "Движок не записал манифест: {path}",
        ["error.manifest_invalid"] = "Некорректный манифест движка: {details}",
        ["error.timeline_changed"] = "Текущий таймлайн сменился во время работы. Плееры размещались только в «{name}».",
        ["error.carrier_import"] = "Resolve не смог импортировать несущий клип: {path}",
        ["error.track_conflict"] = "На V{track} уже есть другие клипы в {time}. Выберите пустую видеодорожку.",
        ["warning.player_failed"] = "Плеер для «{name}» не размещён: {details}",
        ["warning.engine"] = "Предупреждение движка: {details}",
        ["notice.color_manual"] = "Системный выбор цвета недоступен на этой платформе. Введите значение #RRGGBB вручную.",
        ["error.choose_png"] = "Выберите файл .png для обложки по умолчанию",
        ["log.logo_selected"] = "Выбрана обложка по умолчанию: {path}",
        ["log.logo_default"] = "Обложка по умолчанию сброшена",
    },
}

local active_language = "en"
local language_mode = "auto"
local LANGUAGE_MODES = { "auto", "en", "ru" }

local function tr(key, values)
    local catalog = I18N[active_language] or I18N.en
    local text = catalog[key] or I18N.en[key] or tostring(key)
    if values then
        text = text:gsub("{([%w_]+)}", function(name)
            local value = values[name]
            return value == nil and ("{" .. name .. "}") or tostring(value)
        end)
    end
    return text
end

local function language_from_tag(value)
    local code = tostring(value or ""):lower():match("^%s*([a-z][a-z])")
    if code == "ru" then return "ru" end
    if code then return "en" end
    return nil
end

local function windows_preferred_language()
    local ok, result = pcall(function()
        local api = assert(win32_api())
        local count = api.ffi.new("uint32_t[1]")
        local size = api.ffi.new("uint32_t[1]")
        api.kernel32.GetUserPreferredUILanguages(0x00000008, count, nil, size)
        local buffer = nil
        local limit = 0
        if tonumber(size[0]) > 1 then
            limit = tonumber(size[0])
            buffer = api.ffi.new("uint16_t[?]", limit)
            if api.kernel32.GetUserPreferredUILanguages(0x00000008, count, buffer, size) == 0 then buffer = nil end
        end
        if not buffer then
            buffer = api.ffi.new("uint16_t[85]")
            if api.kernel32.GetUserDefaultLocaleName(buffer, 85) == 0 then return nil end
            limit = 85
        end
        local chars = {}
        local index = 0
        while index < limit and tonumber(buffer[index]) ~= 0 do
            local value = tonumber(buffer[index])
            if value > 127 then return nil end
            chars[#chars + 1] = string.char(value)
            index = index + 1
        end
        return language_from_tag(table.concat(chars))
    end)
    return ok and result or nil
end

local function macos_preferred_language()
    local ok, result = pcall(function()
        local ffi = require("ffi")
        pcall(function()
            ffi.cdef[[
                void *CFLocaleCopyPreferredLanguages(void);
                long CFArrayGetCount(const void *array);
                const void *CFArrayGetValueAtIndex(const void *array, long index);
                unsigned char CFStringGetCString(const void *string, char *buffer, long bufferSize, uint32_t encoding);
                void CFRelease(const void *value);
            ]]
        end)
        local core = ffi.load("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        local languages = core.CFLocaleCopyPreferredLanguages()
        if languages == nil then return nil end
        local language = nil
        if core.CFArrayGetCount(languages) > 0 then
            local value = core.CFArrayGetValueAtIndex(languages, 0)
            local buffer = ffi.new("char[128]")
            if value ~= nil and core.CFStringGetCString(value, buffer, 128, 0x08000100) ~= 0 then
                language = language_from_tag(ffi.string(buffer))
            end
        end
        core.CFRelease(languages)
        return language
    end)
    return ok and result or nil
end

local function environment_language()
    for _, name in ipairs({ "LC_ALL", "LC_MESSAGES" }) do
        local value = os.getenv(name)
        if value and value ~= "" then
            return language_from_tag(value) or "en"
        end
    end
    local base = os.getenv("LANG")
    if base and base ~= "" and not language_from_tag(base) then return "en" end
    local preferred = os.getenv("LANGUAGE")
    if preferred and preferred ~= "" then return language_from_tag(preferred) or "en" end
    if base and base ~= "" then return language_from_tag(base) or "en" end
    return nil
end

local function detect_system_language()
    local language = nil
    if PLATFORM.windows then
        language = windows_preferred_language()
    elseif PLATFORM.macos then
        language = macos_preferred_language()
    end
    return language or environment_language() or "en"
end

local function effective_language(mode)
    local forced = tostring(os.getenv("TVIZ_UI_LANG") or ""):lower()
    if forced == "en" or forced == "ru" then return forced end
    if mode == "en" or mode == "ru" then return mode end
    return detect_system_language()
end

active_language = effective_language(language_mode)

local resolve = nil
local fusion = rawget(_G, "fusion")
local ui = nil
local dispatcher = nil
local win = nil

local function starts_with(text, prefix)
    text = tostring(text or "")
    return string.sub(text, 1, string.len(prefix)) == prefix
end

local function trim(text)
    return tostring(text or ""):match("^%s*(.-)%s*$")
end

local function configured_path(value)
    value = tostring(value or "")
    if value ~= "" and not starts_with(value, "__") then
        return value
    end
    return ""
end

local function path_join(left, right)
    left = tostring(left or "")
    right = tostring(right or "")
    if left == "" then return right end
    if right == "" then return left end
    local last = string.sub(left, -1)
    if last == PLATFORM.separator or PLATFORM.windows and (last == "\\" or last == "/") then
        return left .. right
    end
    return left .. PLATFORM.separator .. right
end

local function dirname(path)
    path = tostring(path or "")
    if PLATFORM.windows then return path:match("^(.*)[\\/][^\\/]*$") or "." end
    return path:match("^(.*)/[^/]*$") or "."
end

local function native_executable_name(base_name)
    return tostring(base_name or "") .. PLATFORM.executable_suffix
end

local function path_identity(path)
    local value = trim(path)
    if PLATFORM.windows then return value:gsub("/", "\\"):lower() end
    return value
end

local function percent_decode(value)
    local invalid = false
    local decoded = tostring(value or ""):gsub("%%(%x%x)", function(hex)
        local byte = tonumber(hex, 16)
        if byte == 0 then invalid = true return "" end
        return string.char(byte)
    end)
    if invalid then return "" end
    return decoded
end

local function path_from_file_uri(value)
    local text = tostring(value or "")
    if text:sub(1, 7):lower() ~= "file://" then return text end
    local remainder = text:sub(8)
    local path = remainder
    if remainder:match("^%a:/") then
        path = remainder
    elseif remainder:sub(1, 1) ~= "/" then
        local authority, rest = remainder:match("^([^/]*)(/.*)$")
        if not authority then return "" end
        if authority:lower() == "localhost" then
            path = rest
        else
            path = "//" .. authority .. rest
        end
    end
    path = percent_decode(path)
    if path:match("^/%a:[\\/]") then path = path:sub(2) end
    if PLATFORM.windows then path = path:gsub("/", "\\") end
    return path
end

local function is_absolute_path(path)
    local value = tostring(path or "")
    local from_file_uri = value:sub(1, 7):lower() == "file://"
    if from_file_uri then value = path_from_file_uri(value) end
    return value:match("^/") ~= nil
        or value:match("^%a:[\\/]") ~= nil
        or value:match("^\\\\[^\\]") ~= nil
        or value:match("^//[^/]") ~= nil
        or from_file_uri and value:match("^\\") ~= nil
end

local function file_exists(path)
    if PLATFORM.windows then
        local api = win32_api()
        if not api then return false end
        local wide_path = win32_utf16(path)
        if not wide_path then return false end
        local handle = api.kernel32.CreateFileW(wide_path, 0, 7, nil, 3, 0x02000080, nil)
        if handle == api.ffi.cast("void *", -1) then return false end
        api.kernel32.CloseHandle(handle)
        return true
    end
    local handle = io.open(path, "rb")
    if handle then
        handle:close()
        return true
    end
    return false
end

local function quote_posix(value)
    return "'" .. tostring(value or ""):gsub("'", "'\"'\"'") .. "'"
end

local function win32_error(operation, api)
    return operation .. " failed: Win32 error " .. tostring(tonumber(api.kernel32.GetLastError()))
end

local function create_windows_directory(path)
    local api, api_error = win32_api()
    if not api then return false, api_error end
    local wide_path, conversion_error = win32_utf16(path)
    if not wide_path then return false, conversion_error end
    if api.kernel32.CreateDirectoryW(wide_path, nil) ~= 0 then return true end
    local code = tonumber(api.kernel32.GetLastError())
    if code == 183 then return true end
    return false, "CreateDirectoryW failed: Win32 error " .. tostring(code)
end

local function mkdir_p(path)
    path = tostring(path or "")
    if path == "" or path == "." then return true end
    if PLATFORM.windows then
        local normalized = path:gsub("/", "\\")
        if normalized:match("^%a:\\$") or normalized:match("^%a:$")
            or normalized == "\\" or normalized:match("^\\\\[^\\]+\\[^\\]+\\?$") then
            return true
        end
        normalized = normalized:gsub("\\+$", "")
        local parent = dirname(normalized)
        if parent ~= "." and parent ~= normalized then mkdir_p(parent) end
        local created, create_error = create_windows_directory(normalized)
        if not created then error(create_error) end
        return true
    end
    if path == "/" then return true end
    local result, reason, code = os.execute("mkdir -p -- " .. quote_posix(path))
    if result ~= true and result ~= 0 then
        error("mkdir -p failed: " .. tostring(reason or result) .. " " .. tostring(code or ""))
    end
    return true
end

local function read_file(path)
    if PLATFORM.windows then
        local api = win32_api()
        if not api then return "" end
        local wide_path = win32_utf16(path)
        if not wide_path then return "" end
        local handle = api.kernel32.CreateFileW(wide_path, 0x80000000, 7, nil, 3, 0x80, nil)
        if handle == api.ffi.cast("void *", -1) then return "" end
        local buffer_size = 65536
        local buffer = api.ffi.new("uint8_t[?]", buffer_size)
        local bytes_read = api.ffi.new("uint32_t[1]")
        local parts = {}
        while true do
            if api.kernel32.ReadFile(handle, buffer, buffer_size, bytes_read, nil) == 0 then
                api.kernel32.CloseHandle(handle)
                return ""
            end
            local count = tonumber(bytes_read[0])
            if count == 0 then break end
            parts[#parts + 1] = api.ffi.string(buffer, count)
        end
        api.kernel32.CloseHandle(handle)
        return table.concat(parts)
    end
    local handle = io.open(path, "rb")
    if not handle then return "" end
    local data = handle:read("*a") or ""
    handle:close()
    return data
end

local function write_file_raw(path, data, append, flush)
    data = tostring(data or "")
    if PLATFORM.windows then
        local api, api_error = win32_api()
        if not api then return false, api_error, "open" end
        local wide_path, conversion_error = win32_utf16(path)
        if not wide_path then return false, conversion_error, "open" end
        local disposition = append and 4 or 2
        local handle = api.kernel32.CreateFileW(wide_path, 0x40000000, 1, nil, disposition, 0x80, nil)
        if handle == api.ffi.cast("void *", -1) then return false, win32_error("CreateFileW", api), "open" end
        if append and api.kernel32.SetFilePointerEx(handle, 0, nil, 2) == 0 then
            local pointer_error = win32_error("SetFilePointerEx", api)
            api.kernel32.CloseHandle(handle)
            return false, pointer_error, "write"
        end
        local offset = 0
        local length = string.len(data)
        local source = api.ffi.cast("const uint8_t *", data)
        local bytes_written = api.ffi.new("uint32_t[1]")
        while offset < length do
            local count = math.min(length - offset, 1048576)
            if api.kernel32.WriteFile(handle, source + offset, count, bytes_written, nil) == 0
                or tonumber(bytes_written[0]) ~= count then
                local write_error = win32_error("WriteFile", api)
                api.kernel32.CloseHandle(handle)
                return false, write_error, "write"
            end
            offset = offset + count
        end
        if flush and api.kernel32.FlushFileBuffers(handle) == 0 then
            local flush_error = win32_error("FlushFileBuffers", api)
            api.kernel32.CloseHandle(handle)
            return false, flush_error, "flush"
        end
        if api.kernel32.CloseHandle(handle) == 0 then return false, win32_error("CloseHandle", api), "close" end
        return true
    end

    local handle, open_error = io.open(path, append and "ab" or "wb")
    if not handle then return false, open_error, "open" end
    local write_ok, write_error = handle:write(data)
    if not write_ok then
        handle:close()
        return false, write_error, "write"
    end
    if flush then
        local flush_ok, flush_error = handle:flush()
        if not flush_ok then
            handle:close()
            return false, flush_error, "flush"
        end
    end
    local close_ok, close_error = handle:close()
    if not close_ok then return false, close_error, "close" end
    return true
end

local function write_file(path, data)
    mkdir_p(dirname(path))
    local ok, write_error = write_file_raw(path, data, false, false)
    if not ok then error(write_error) end
end

local function append_file(path, data)
    mkdir_p(dirname(path))
    local ok, write_error = write_file_raw(path, data, true, false)
    if not ok then error(write_error) end
end

local function remove_file(path)
    if PLATFORM.windows then
        local api, api_error = win32_api()
        if not api then return false, api_error end
        local wide_path, conversion_error = win32_utf16(path)
        if not wide_path then return false, conversion_error end
        if api.kernel32.DeleteFileW(wide_path) ~= 0 then return true end
        return false, win32_error("DeleteFileW", api)
    end
    return os.remove(path)
end

local function move_file(source, destination, replace_existing, backup_path)
    if PLATFORM.windows then
        local api, api_error = win32_api()
        if not api then return false, api_error end
        local wide_source, source_error = win32_utf16(source)
        if not wide_source then return false, source_error end
        local wide_destination, destination_error = win32_utf16(destination)
        if not wide_destination then return false, destination_error end
        if replace_existing and backup_path then
            local wide_backup, backup_error = win32_utf16(backup_path)
            if not wide_backup then return false, backup_error end
            if api.kernel32.ReplaceFileW(wide_destination, wide_source, wide_backup, 0, nil, nil) ~= 0 then return true end
            return false, win32_error("ReplaceFileW", api)
        end
        local flags = replace_existing and 0x00000009 or 0x00000008
        if api.kernel32.MoveFileExW(wide_source, wide_destination, flags) ~= 0 then return true end
        return false, win32_error("MoveFileExW", api)
    end
    return os.rename(source, destination)
end


local function wait_seconds(seconds)
    seconds = tonumber(seconds) or 0.1
    if bmd and type(bmd.wait) == "function" then
        pcall(function() bmd.wait(seconds) end)
        return
    end
    if fusion and type(fusion.Sleep) == "function" then
        pcall(function() fusion:Sleep(math.floor(seconds * 1000)) end)
    end
end

local function html_escape(value)
    local text = tostring(value or "")
    text = text:gsub("&", "&amp;"):gsub("<", "&lt;"):gsub(">", "&gt;")
    return text
end

local function short_text(value, limit)
    limit = limit or 160
    local text = tostring(value or ""):gsub("[\r\n]+", " ")
    if string.len(text) > limit then
        return string.sub(text, 1, limit - 3) .. "..."
    end
    return text
end

local function environment_value(environment, name)
    if type(environment) == "table" then return environment[name] end
    if PLATFORM.windows then return win32_environment_value(name) end
    return os.getenv(name)
end

local function user_home(environment, configured_home)
    if configured_home and tostring(configured_home) ~= "" then return tostring(configured_home) end
    if PLATFORM.windows then
        local profile = environment_value(environment, "USERPROFILE")
        if profile and profile ~= "" then return profile end
        local drive = environment_value(environment, "HOMEDRIVE") or ""
        local path = environment_value(environment, "HOMEPATH") or ""
        if drive ~= "" and path ~= "" then return drive .. path end
    end
    local home = environment_value(environment, "HOME")
    if home and home ~= "" then return home end
    return "."
end

local function default_install_root(environment, configured_home)
    local override = environment_value(environment, "DAVINCI_TRACK_VISUALIZER_HOME")
    if override and override ~= "" then return override end
    local home = user_home(environment, configured_home)
    if PLATFORM.windows then
        local base = environment_value(environment, "LOCALAPPDATA")
        if not base or base == "" then base = path_join(path_join(home, "AppData"), "Local") end
        return path_join(base, "DavinciTrackVisualizer")
    end
    if PLATFORM.macos then
        return path_join(path_join(path_join(home, "Library"), "Application Support"), "DavinciTrackVisualizer")
    end
    local base = environment_value(environment, "XDG_DATA_HOME")
    if not base or base == "" then base = path_join(path_join(home, ".local"), "share") end
    return path_join(base, "DavinciTrackVisualizer")
end

local function install_root()
    local configured = configured_path(INSTALL_ROOT)
    if configured ~= "" then return configured end
    return default_install_root()
end

local function engine_path()
    local configured = configured_path(ENGINE_EXECUTABLE)
    if configured ~= "" and file_exists(configured) then return configured end
    return path_join(install_root(), native_executable_name("TrackVisualizerEngine"))
end

local function runner_path()
    local configured = configured_path(RUNNER_EXECUTABLE)
    if configured ~= "" and file_exists(configured) then return configured end
    return path_join(install_root(), native_executable_name("TrackVisualizerRunner"))
end

local function ffmpeg_path(name, configured)
    local value = configured_path(configured)
    if value ~= "" and file_exists(value) then return value end
    local candidate = path_join(install_root(), name)
    if file_exists(candidate) then return candidate end
    return name
end

local function settings_path()
    return path_join(install_root(), "settings.json")
end

local function tmp_dir()
    return path_join(install_root(), "tmp")
end

local function clip_dump_path()
    return path_join(tmp_dir(), "clip_property_dump.txt")
end

local function log_path()
    return path_join(tmp_dir(), "track_visualizer_log.txt")
end

local function default_fallback_logo_path()
    return path_join(install_root(), "aplus.png")
end

if type(platform_probe_config) == "table" and platform_probe_config.platform_only == true then
    return {
        platform = PLATFORM.name,
        separator = PLATFORM.separator,
        case_sensitive_paths = PLATFORM.case_sensitive_paths,
        executable_name = native_executable_name("TrackVisualizerRunner"),
        quoted_posix = quote_posix("runner's path"),
        install_root = default_install_root(platform_probe_config.environment, platform_probe_config.home),
        joined_path = path_join(tostring(platform_probe_config.join_left or "root"), tostring(platform_probe_config.join_right or "child")),
        same_case_path = path_identity("/Media/Track.png") == path_identity("/media/track.png"),
        absolute_paths = {
            posix = is_absolute_path("/media/track.wav"),
            drive = is_absolute_path("C:\\Media\\track.wav"),
            unc = is_absolute_path("\\\\server\\share\\track.wav"),
            file_uri = is_absolute_path("file:///media/Track%20One.wav"),
        },
        decoded_file_uri = path_from_file_uri(tostring(platform_probe_config.file_uri or "file:///media/Track%20One.wav")),
    }
end

resolve = Resolve()
fusion = fusion or resolve:Fusion()
ui = fusion.UIManager
dispatcher = bmd.UIDispatcher(ui)

local function copy_table(source)
    local target = {}
    for key, value in pairs(source or {}) do
        if type(value) == "table" then
            target[key] = copy_table(value)
        else
            target[key] = value
        end
    end
    return target
end

local function update_table(target, source)
    for key, value in pairs(source or {}) do
        target[key] = value
    end
    return target
end

local function json_quote(value)
    local text = tostring(value or "")
    text = text:gsub('\\', '\\\\')
    text = text:gsub('"', '\\"')
    text = text:gsub('\b', '\\b')
    text = text:gsub('\f', '\\f')
    text = text:gsub('\n', '\\n')
    text = text:gsub('\r', '\\r')
    text = text:gsub('\t', '\\t')
    text = text:gsub('[%z\1-\31]', function(char)
        return string.format('\\u%04x', string.byte(char))
    end)
    return '"' .. text .. '"'
end

local function is_array(tbl)
    if type(tbl) ~= "table" then return false end
    local count = 0
    local max_index = 0
    for key, _ in pairs(tbl) do
        if type(key) ~= "number" then return false end
        if key > max_index then max_index = key end
        count = count + 1
    end
    return max_index == count
end

local function json_encode(value, indent)
    indent = indent or ""
    local value_type = type(value)
    if value_type == "nil" then return "null" end
    if value_type == "boolean" then return value and "true" or "false" end
    if value_type == "number" then return tostring(value) end
    if value_type == "string" then return json_quote(value) end
    if value_type ~= "table" then return json_quote(tostring(value)) end

    local next_indent = indent .. "  "
    local parts = {}
    if is_array(value) then
        for index = 1, #value do
            table.insert(parts, next_indent .. json_encode(value[index], next_indent))
        end
        if #parts == 0 then return "[]" end
        return "[\n" .. table.concat(parts, ",\n") .. "\n" .. indent .. "]"
    end

    local keys = {}
    for key, _ in pairs(value) do table.insert(keys, key) end
    table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
    for _, key in ipairs(keys) do
        table.insert(parts, next_indent .. json_quote(key) .. ": " .. json_encode(value[key], next_indent))
    end
    if #parts == 0 then return "{}" end
    return "{\n" .. table.concat(parts, ",\n") .. "\n" .. indent .. "}"
end

local JSON_NULL = {}

local function json_decode(text)
    text = tostring(text or "")
    if text:sub(1, 3) == "\239\187\191" then text = text:sub(4) end
    local position = 1
    local length = #text

    local function decode_error(message)
        error("Invalid JSON at position " .. tostring(position) .. ": " .. message)
    end

    local function skip_whitespace()
        while position <= length and text:sub(position, position):match("%s") do
            position = position + 1
        end
    end

    local function utf8_char(codepoint)
        if codepoint <= 0x7F then
            return string.char(codepoint)
        elseif codepoint <= 0x7FF then
            return string.char(0xC0 + math.floor(codepoint / 0x40), 0x80 + (codepoint % 0x40))
        elseif codepoint <= 0xFFFF then
            return string.char(
                0xE0 + math.floor(codepoint / 0x1000),
                0x80 + (math.floor(codepoint / 0x40) % 0x40),
                0x80 + (codepoint % 0x40)
            )
        elseif codepoint <= 0x10FFFF then
            return string.char(
                0xF0 + math.floor(codepoint / 0x40000),
                0x80 + (math.floor(codepoint / 0x1000) % 0x40),
                0x80 + (math.floor(codepoint / 0x40) % 0x40),
                0x80 + (codepoint % 0x40)
            )
        end
        decode_error("invalid Unicode code point")
    end

    local parse_value

    local function parse_hex_escape()
        local hex = text:sub(position, position + 3)
        if #hex ~= 4 or not hex:match("^[0-9A-Fa-f]+$") then
            decode_error("expected a \\uXXXX sequence")
        end
        position = position + 4
        return tonumber(hex, 16)
    end

    local function parse_string()
        if text:sub(position, position) ~= '"' then decode_error("expected a string") end
        position = position + 1
        local parts = {}
        local chunk_start = position
        while position <= length do
            local byte = text:byte(position)
            if byte == 34 then
                if position > chunk_start then table.insert(parts, text:sub(chunk_start, position - 1)) end
                position = position + 1
                return table.concat(parts)
            elseif byte == 92 then
                if position > chunk_start then table.insert(parts, text:sub(chunk_start, position - 1)) end
                position = position + 1
                local escaped = text:sub(position, position)
                local simple = {
                    ['"'] = '"',
                    ['\\'] = '\\',
                    ['/'] = '/',
                    ['b'] = '\b',
                    ['f'] = '\f',
                    ['n'] = '\n',
                    ['r'] = '\r',
                    ['t'] = '\t',
                }
                if simple[escaped] then
                    table.insert(parts, simple[escaped])
                    position = position + 1
                elseif escaped == "u" then
                    position = position + 1
                    local codepoint = parse_hex_escape()
                    if codepoint >= 0xD800 and codepoint <= 0xDBFF then
                        if text:sub(position, position + 1) ~= "\\u" then
                            decode_error("high surrogate without a low surrogate")
                        end
                        position = position + 2
                        local low = parse_hex_escape()
                        if low < 0xDC00 or low > 0xDFFF then
                            decode_error("invalid surrogate pair")
                        end
                        codepoint = 0x10000 + (codepoint - 0xD800) * 0x400 + (low - 0xDC00)
                    elseif codepoint >= 0xDC00 and codepoint <= 0xDFFF then
                        decode_error("low surrogate without a high surrogate")
                    end
                    table.insert(parts, utf8_char(codepoint))
                else
                    decode_error("unknown escape sequence")
                end
                chunk_start = position
            elseif byte < 32 then
                decode_error("control character in string")
            else
                position = position + 1
            end
        end
        decode_error("unterminated string")
    end

    local function parse_number()
        local start_position = position
        if text:sub(position, position) == "-" then position = position + 1 end
        local first = text:sub(position, position)
        if first == "0" then
            position = position + 1
            if text:sub(position, position):match("%d") then decode_error("leading zero in number") end
        elseif first:match("[1-9]") then
            repeat position = position + 1 until not text:sub(position, position):match("%d")
        else
            decode_error("expected a number")
        end
        if text:sub(position, position) == "." then
            position = position + 1
            if not text:sub(position, position):match("%d") then decode_error("missing digits after decimal point") end
            repeat position = position + 1 until not text:sub(position, position):match("%d")
        end
        local exponent = text:sub(position, position)
        if exponent == "e" or exponent == "E" then
            position = position + 1
            local sign = text:sub(position, position)
            if sign == "+" or sign == "-" then position = position + 1 end
            if not text:sub(position, position):match("%d") then decode_error("missing digits in exponent") end
            repeat position = position + 1 until not text:sub(position, position):match("%d")
        end
        local value = tonumber(text:sub(start_position, position - 1))
        if value == nil then decode_error("could not parse number") end
        return value
    end

    local function parse_array()
        position = position + 1
        skip_whitespace()
        local result = {}
        if text:sub(position, position) == "]" then
            position = position + 1
            return result
        end
        local index = 1
        while true do
            result[index] = parse_value()
            index = index + 1
            skip_whitespace()
            local separator = text:sub(position, position)
            if separator == "]" then
                position = position + 1
                return result
            end
            if separator ~= "," then decode_error("expected a comma or ]") end
            position = position + 1
            skip_whitespace()
        end
    end

    local function parse_object()
        position = position + 1
        skip_whitespace()
        local result = {}
        if text:sub(position, position) == "}" then
            position = position + 1
            return result
        end
        while true do
            if text:sub(position, position) ~= '"' then decode_error("object key must be a string") end
            local key = parse_string()
            skip_whitespace()
            if text:sub(position, position) ~= ":" then decode_error("expected a colon") end
            position = position + 1
            skip_whitespace()
            result[key] = parse_value()
            skip_whitespace()
            local separator = text:sub(position, position)
            if separator == "}" then
                position = position + 1
                return result
            end
            if separator ~= "," then decode_error("expected a comma or }") end
            position = position + 1
            skip_whitespace()
        end
    end

    parse_value = function()
        skip_whitespace()
        local token = text:sub(position, position)
        if token == '"' then return parse_string() end
        if token == "{" then return parse_object() end
        if token == "[" then return parse_array() end
        if token == "-" or token:match("%d") then return parse_number() end
        if text:sub(position, position + 3) == "true" then position = position + 4 return true end
        if text:sub(position, position + 4) == "false" then position = position + 5 return false end
        if text:sub(position, position + 3) == "null" then position = position + 4 return JSON_NULL end
        decode_error("unexpected value")
    end

    local result = parse_value()
    skip_whitespace()
    if position <= length then decode_error("extra data after the root value") end
    return result
end

local function normalize_hex(value, fallback)
    fallback = fallback or "#FFFFFF"
    local text = trim(value ~= nil and value or fallback)
    if not starts_with(text, "#") then text = "#" .. text end
    if string.len(text) == 4 then
        text = "#" .. text:sub(2, 2):rep(2) .. text:sub(3, 3):rep(2) .. text:sub(4, 4):rep(2)
    end
    if string.len(text) ~= 7 or not text:match("^#[0-9A-Fa-f]+$") then
        return fallback
    end
    return string.upper(text)
end

local function hex_to_rgb(hex_value)
    local text = normalize_hex(hex_value, "#FFFFFF")
    return tonumber(text:sub(2, 3), 16) or 255, tonumber(text:sub(4, 5), 16) or 255, tonumber(text:sub(6, 7), 16) or 255
end



-- ------------------------------------------------------------------------------------------
-- Style catalogue helpers (skins, defaults, palettes)

local Style = {}

function Style.contains(list, value)
    for _, item in ipairs(list or {}) do
        if item == value then return true end
    end
    return false
end

function Style.is_skin(value)
    return type(value) == "string" and Style.contains(SKIN_CATALOG.skins, value)
end

function Style.supports(skin, feature)
    return Style.contains(SKIN_CATALOG.features[skin], feature)
end

function Style.defaults(skin)
    return copy_table(SKIN_CATALOG.defaults[Style.is_skin(skin) and skin or "classic"])
end

function Style.sanitize(skin, source)
    local design = Style.defaults(skin)
    if type(source) ~= "table" or source == JSON_NULL then return design end
    for key, default in pairs(design) do
        local value = source[key]
        if value ~= nil and value ~= JSON_NULL then
            if type(default) == "boolean" then
                if type(value) == "boolean" then design[key] = value
                elseif type(value) == "number" then design[key] = value ~= 0
                elseif type(value) == "string" then
                    local lowered = value:lower()
                    if lowered == "true" or lowered == "1" or lowered == "yes" then design[key] = true
                    elseif lowered == "false" or lowered == "0" or lowered == "no" then design[key] = false end
                end
            elseif type(default) == "number" then
                local number = tonumber(value)
                local range = SKIN_CATALOG.int_ranges[key]
                if number and number == number and number ~= math.huge and number ~= -math.huge then
                    number = math.floor(number + 0.5)
                    if range then number = math.max(range[1], math.min(range[2], number)) end
                    design[key] = number
                end
            elseif key:match("_color$") then
                design[key] = normalize_hex(value, default)
            elseif SKIN_CATALOG.enums[key] then
                if Style.contains(SKIN_CATALOG.enums[key], value) then design[key] = value end
            else
                local text = trim(tostring(value))
                local limit = SKIN_CATALOG.text_limits[key] or 80
                if text == "" and key:match("font_family$") then text = default end
                design[key] = string.sub(text, 1, limit)
            end
        end
    end
    -- Designs saved before the progress style toggled the waveform and the line separately
    -- (mirrors _migrate_progress_style in skins.py).
    if Style.supports(skin, "progress_style") and (source.progress_style == nil or source.progress_style == JSON_NULL) then
        local bars = source.show_bars ~= false and source.show_bars ~= 0
        local line = source.show_progress ~= false and source.show_progress ~= 0
        if not bars and not line then
            design.show_progress = false
        else
            design.progress_style = (line and not bars) and "line" or "wave"
            design.show_progress = true
        end
    end
    return design
end

function Style.skin_label(skin)
    return tr("skin." .. tostring(skin))
end

function Style.builtin_palette(name)
    return SKIN_CATALOG.palettes[name]
end

function Style.palette_label(name, settings)
    if name == "Custom" or Style.builtin_palette(name) then return tr("palette." .. tostring(name)) end
    return tr("palette.custom_mark", { name = tostring(name) })
end

-- ------------------------------------------------------------------------------------------
-- Settings: per-skin working styles, user presets and palettes

local Settings = { data = nil, dirty_ticks = nil }

function Settings.defaults(existing_settings)
    local styles = {}
    for _, skin in ipairs(SKIN_CATALOG.skins) do styles[skin] = Style.defaults(skin) end
    return {
        settings_version = SETTINGS_VERSION,
        active_skin = "classic",
        styles = styles,
        palette_names = copy_table(SKIN_CATALOG.default_palettes),
        presets = {},
        palettes = {},
        timeline = { audio_tracks = "1-3", video_track = 2, switch_mode = "overlap_middle", scope = "" },
        fallback_logo_path = default_fallback_logo_path(),
        -- Releases before localization were Russian-only, so migrate their settings explicitly to Russian.
        language_mode = existing_settings and "ru" or "auto",
        auto_update = true,
        update_checked_at = 0,
    }
end

function Settings.migrate_v1(settings, root)
    -- Settings v1 stored a profile per skin: base player size in pixels, margin and design.
    if type(root.profiles) ~= "table" or root.profiles == JSON_NULL then return end
    for _, skin in ipairs(SKIN_CATALOG.skins) do
        local profile = root.profiles[skin]
        if type(profile) == "table" and profile ~= JSON_NULL then
            local design = type(profile.design) == "table" and copy_table(profile.design) or {}
            local base = SKIN_CATALOG.base_sizes[skin]
            local width = tonumber(profile.base_width or profile.width)
            if width and base then design.scale = math.floor(width / base[1] * 100 + 0.5) end
            local margin = tonumber(profile.margin)
            if margin then
                design.margin_x = margin
                design.margin_y = margin
            end
            if type(design.meta_size) == "number" and skin == "classic" then design.meta_size = math.min(design.meta_size, 16) end
            settings.styles[skin] = Style.sanitize(skin, design)
            if type(profile.palette) == "string" then settings.palette_names[skin] = profile.palette end
        end
    end
    if Style.is_skin(root.active_skin) then settings.active_skin = root.active_skin end
end

function Settings.sanitize_presets(source)
    local presets = {}
    if type(source) ~= "table" or source == JSON_NULL then return presets end
    for _, preset in ipairs(source) do
        if type(preset) == "table" and type(preset.name) == "string" and trim(preset.name) ~= "" and Style.is_skin(preset.skin) then
            table.insert(presets, {
                name = string.sub(trim(preset.name), 1, 60),
                skin = preset.skin,
                design = Style.sanitize(preset.skin, preset.design),
            })
        end
    end
    return presets
end

function Settings.sanitize_palette_colors(source)
    local colors = {}
    local defaults = SKIN_CATALOG.palettes.Default
    for _, key in ipairs(SKIN_CATALOG.palette_keys) do
        local value = type(source) == "table" and source[key] or nil
        if key:match("_color$") then
            colors[key] = normalize_hex(value, defaults[key])
        else
            local number = tonumber(value) or defaults[key]
            local range = SKIN_CATALOG.int_ranges[key] or { 0, 255 }
            colors[key] = math.max(range[1], math.min(range[2], math.floor(number + 0.5)))
        end
    end
    return colors
end

function Settings.sanitize_palettes(source)
    local palettes = {}
    if type(source) ~= "table" or source == JSON_NULL then return palettes end
    for _, palette in ipairs(source) do
        if type(palette) == "table" and type(palette.name) == "string" and trim(palette.name) ~= ""
            and not Style.builtin_palette(trim(palette.name)) and trim(palette.name) ~= "Custom" then
            table.insert(palettes, { name = string.sub(trim(palette.name), 1, 60), colors = Settings.sanitize_palette_colors(palette.colors) })
        end
    end
    return palettes
end

local function load_settings()
    local path = settings_path()
    local backup_path = path .. ".bak"
    local recovered_text = nil
    if not file_exists(path) and file_exists(backup_path) then
        local restored = move_file(backup_path, path)
        if not restored then recovered_text = read_file(backup_path) end
    end
    local existing_settings = file_exists(path) or recovered_text ~= nil
    local settings = Settings.defaults(existing_settings)
    local text = recovered_text or read_file(path)
    if text == "" then return settings end
    local decode_ok, root = pcall(function() return json_decode(text) end)
    if not decode_ok or type(root) ~= "table" or root == JSON_NULL then return settings end

    if root.language_mode == "auto" or root.language_mode == "en" or root.language_mode == "ru" then
        settings.language_mode = root.language_mode
    end
    if type(root.fallback_logo_path) == "string" and trim(root.fallback_logo_path) ~= "" then
        settings.fallback_logo_path = root.fallback_logo_path
    end
    if type(root.auto_update) == "boolean" then settings.auto_update = root.auto_update end
    if tonumber(root.update_checked_at) then settings.update_checked_at = tonumber(root.update_checked_at) end
    -- Testing only: read update.json and the installer from a folder. The signature is still required.
    if type(root.update_source_dir) == "string" and trim(root.update_source_dir) ~= "" then
        settings.update_source_dir = root.update_source_dir
    end
    if tonumber(root.settings_version) == SETTINGS_VERSION then
        if Style.is_skin(root.active_skin) then settings.active_skin = root.active_skin end
        if type(root.styles) == "table" and root.styles ~= JSON_NULL then
            for _, skin in ipairs(SKIN_CATALOG.skins) do
                if type(root.styles[skin]) == "table" then settings.styles[skin] = Style.sanitize(skin, root.styles[skin]) end
            end
        end
        if type(root.palette_names) == "table" and root.palette_names ~= JSON_NULL then
            for _, skin in ipairs(SKIN_CATALOG.skins) do
                if type(root.palette_names[skin]) == "string" then settings.palette_names[skin] = root.palette_names[skin] end
            end
        end
        settings.presets = Settings.sanitize_presets(root.presets)
        settings.palettes = Settings.sanitize_palettes(root.palettes)
        if type(root.timeline) == "table" and root.timeline ~= JSON_NULL then
            local timeline = root.timeline
            if type(timeline.audio_tracks) == "string" then settings.timeline.audio_tracks = timeline.audio_tracks end
            local video_track = tonumber(timeline.video_track)
            if video_track and video_track >= 1 and video_track <= 64 then settings.timeline.video_track = math.floor(video_track) end
            for _, mode in ipairs({ "overlap_middle", "next_start", "current_end" }) do
                if timeline.switch_mode == mode then settings.timeline.switch_mode = mode end
            end
            if type(timeline.scope) == "string" then settings.timeline.scope = timeline.scope end
        end
    else
        Settings.migrate_v1(settings, root)
    end
    return settings
end

local function write_settings_safely(path, data)
    local temporary_path = path .. ".tmp." .. tostring(os.time()) .. "." .. tostring(math.random(100000, 999999))
    local backup_path = path .. ".bak"
    mkdir_p(dirname(path))
    local write_ok, write_error, write_stage = write_file_raw(temporary_path, data, false, true)
    if not write_ok then
        remove_file(temporary_path)
        if write_stage == "open" then error(tr("error.settings_temp_open", { details = write_error })) end
        error(tr("error.settings_temp_write", { details = write_error }))
    end
    if read_file(temporary_path) ~= data then
        remove_file(temporary_path)
        error(tr("error.settings_temp_verify"))
    end
    local decode_ok, decoded = pcall(function() return json_decode(data) end)
    if not decode_ok or type(decoded) ~= "table" or decoded == JSON_NULL then
        remove_file(temporary_path)
        error(tr("error.settings_invalid_json"))
    end

    local had_original = file_exists(path)
    if file_exists(backup_path) then
        local removed, remove_error = remove_file(backup_path)
        if not removed and file_exists(backup_path) then
            remove_file(temporary_path)
            error(tr("error.settings_backup", { details = remove_error }))
        end
    end
    if had_original and not PLATFORM.windows then
        local original_data = read_file(path)
        local backup_ok, backup_error = write_file_raw(backup_path, original_data, false, true)
        if not backup_ok then
            remove_file(temporary_path)
            error(tr("error.settings_backup", { details = backup_error }))
        end
        if read_file(backup_path) ~= original_data then
            remove_file(temporary_path)
            remove_file(backup_path)
            error(tr("error.settings_backup", { details = "backup verification failed" }))
        end
    end
    local replace_ok, replace_error = move_file(
        temporary_path,
        path,
        had_original,
        had_original and PLATFORM.windows and backup_path or nil
    )
    if not replace_ok then
        local rollback_error = nil
        if had_original and not file_exists(path) then
            if file_exists(backup_path) then
                local restored, restore_error = move_file(backup_path, path)
                if not restored then rollback_error = restore_error end
            else
                rollback_error = "backup file is unavailable"
            end
        end
        if not rollback_error then remove_file(temporary_path) end
        local details = tostring(replace_error)
        if rollback_error then details = details .. "; rollback failed: " .. tostring(rollback_error) end
        error(tr("error.settings_replace", { details = details }))
    end
end


local function save_settings(settings)
    local styles = {}
    for _, skin in ipairs(SKIN_CATALOG.skins) do
        styles[skin] = Style.sanitize(skin, type(settings.styles) == "table" and settings.styles[skin] or nil)
    end
    local payload = {
        settings_version = SETTINGS_VERSION,
        active_skin = Style.is_skin(settings.active_skin) and settings.active_skin or "classic",
        styles = styles,
        palette_names = settings.palette_names,
        presets = Settings.sanitize_presets(settings.presets),
        palettes = Settings.sanitize_palettes(settings.palettes),
        timeline = settings.timeline,
        fallback_logo_path = settings.fallback_logo_path,
        language_mode = settings.language_mode == "en" and "en" or settings.language_mode == "ru" and "ru" or "auto",
        auto_update = settings.auto_update ~= false,
        update_checked_at = tonumber(settings.update_checked_at) or 0,
        update_source_dir = settings.update_source_dir,
    }
    write_settings_safely(settings_path(), json_encode(payload, ""))
end

-- ------------------------------------------------------------------------------------------
-- Log and status

local Log = { lines = {}, max_lines = 500 }

function Log.refresh_widget()
    if not win then return end
    local widget = win:Find("Log")
    if not widget then return end
    local count = #Log.lines
    pcall(function() widget.PlainText = table.concat(Log.lines, "\n", 1, math.max(0, count - 1)) end)
    -- Append() scrolls the view to the newest line without selecting text.
    if count > 0 then pcall(function() widget:Append(Log.lines[count]) end) end
end

function Log.append_widget(line)
    local widget = win and win:Find("Log") or nil
    if not widget then return end
    local ok = pcall(function() widget:Append(line) end)
    if not ok then Log.refresh_widget() end
end

function Log.rotate()
    local path = log_path()
    local text = read_file(path)
    if string.len(text) > 1024 * 1024 then
        write_file(path, string.sub(text, -256 * 1024))
    end
    for line in read_file(path):gmatch("[^\r\n]+") do
        table.insert(Log.lines, line)
        if #Log.lines > Log.max_lines then table.remove(Log.lines, 1) end
    end
end

local function append_log(message)
    local line = os.date("%H:%M:%S ") .. tostring(message or "")
    pcall(function() append_file(log_path(), line .. "\n") end)
    table.insert(Log.lines, line)
    while #Log.lines > Log.max_lines do table.remove(Log.lines, 1) end
    Log.append_widget(line)
end

local set_progress

local function set_last_error(message)
    local text = tostring(message or "")
    local error_path = path_join(install_root(), "last_error.txt")
    pcall(function() write_file(error_path, text) end)
    local label = win and win:Find("LastError") or nil
    if label then
        local has_error = trim(text) ~= ""
        label.Text = has_error and tr("error.last", { message = short_text(text, 300) }) or ""
        label.Hidden = not has_error
        pcall(function() label:Update() end)
        pcall(function() win:RecalcLayout() end)
    end
end

local function clean_error(err)
    local message = tostring(err or tr("error.unknown"))
    -- Lua prefixes runtime errors with "file:line:"; users only need the message.
    message = message:gsub("^[^\n]-%.lua:%d+: ", "")
    return message
end

local function report_error(err)
    local message = clean_error(err)
    append_log(tr("error.log_prefix", { message = message }))
    set_last_error(message)
    set_progress(0, tr("status.error", { message = short_text(message, 120) }))
end

function set_progress(percent, status)
    if not win then return end
    local status_label = win:Find("ProgressStatus")
    if status_label and status then status_label.Text = status end
    local bar = win:Find("ProgressBar")
    if bar and percent then
        local fraction = math.max(0, math.min(1, (tonumber(percent) or 0) / 100))
        local edge = string.format("%.4f", fraction)
        local after = string.format("%.4f", math.min(1, fraction + 0.0005))
        bar.StyleSheet = "QLabel { min-height: 4px; max-height: 4px; border-radius: 2px; border: none; "
            .. "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #5b8def, stop:" .. edge .. " #5b8def, "
            .. "stop:" .. after .. " #26282e, stop:1 #26282e); }"
    end
end

-- ------------------------------------------------------------------------------------------
-- Runner: file-queue launches without console windows

local function launch_runner_native(executable)
    if not PLATFORM.windows then return false, "CreateProcessW is available only on Windows" end
    local api, api_error = win32_api()
    if not api then return false, api_error end
    local application, application_error = win32_utf16(executable)
    if not application then return false, "Runner path conversion failed: " .. tostring(application_error) end
    local working_directory, cwd_error = win32_utf16(dirname(executable))
    if not working_directory then return false, "Runner cwd conversion failed: " .. tostring(cwd_error) end

    local startup = api.ffi.new("tviz_STARTUPINFOW[1]")
    startup[0].cb = api.ffi.sizeof(startup[0])
    startup[0].dwFlags = 0x00000001
    startup[0].wShowWindow = 0
    local process = api.ffi.new("tviz_PROCESS_INFORMATION[1]")
    local created = api.kernel32.CreateProcessW(
        application,
        nil,
        nil,
        nil,
        0,
        0x08000000,
        nil,
        working_directory,
        startup,
        process
    )
    if created == 0 then return false, win32_error("CreateProcessW", api) end
    api.kernel32.CloseHandle(process[0].hThread)
    api.kernel32.CloseHandle(process[0].hProcess)
    return true
end

-- Quotes one argument for CommandLineToArgvW and the MSVC runtime.
local function win32_quote_argument(value)
    value = tostring(value or "")
    if value ~= "" and not value:find('[%s"]') then return value end
    local quoted = value:gsub('(\\*)"', function(slashes) return slashes .. slashes .. '\\"' end)
    quoted = quoted:gsub("(\\+)$", "%1%1")
    return '"' .. quoted .. '"'
end

-- Starts a console program without a window and without waiting (the self-update installer).
local function launch_process_native(executable, arguments)
    if not PLATFORM.windows then return false, "CreateProcessW is available only on Windows" end
    local api, api_error = win32_api()
    if not api then return false, api_error end
    local parts = { win32_quote_argument(executable) }
    for _, argument in ipairs(arguments or {}) do parts[#parts + 1] = win32_quote_argument(argument) end
    local application, application_error = win32_utf16(executable)
    if not application then return false, "Path conversion failed: " .. tostring(application_error) end
    local command_line, command_error = win32_utf16(table.concat(parts, " "))
    if not command_line then return false, "Command line conversion failed: " .. tostring(command_error) end
    local working_directory, cwd_error = win32_utf16(dirname(executable))
    if not working_directory then return false, "Working directory conversion failed: " .. tostring(cwd_error) end
    local startup = api.ffi.new("tviz_STARTUPINFOW[1]")
    startup[0].cb = api.ffi.sizeof(startup[0])
    startup[0].dwFlags = 0x00000001
    startup[0].wShowWindow = 0
    local process = api.ffi.new("tviz_PROCESS_INFORMATION[1]")
    local created = api.kernel32.CreateProcessW(
        application,
        command_line,
        nil,
        nil,
        0,
        0x08000000,
        nil,
        working_directory,
        startup,
        process
    )
    if created == 0 then return false, win32_error("CreateProcessW", api) end
    api.kernel32.CloseHandle(process[0].hThread)
    api.kernel32.CloseHandle(process[0].hProcess)
    return true
end

local function launch_runner_posix(executable)
    if PLATFORM.windows then return false, "POSIX launcher is unavailable on Windows" end
    local command = "nohup " .. quote_posix(executable) .. " </dev/null >/dev/null 2>&1 &"
    local result, reason, code = os.execute(command)
    if result == true or result == 0 then return true end
    return false, "detached shell launch failed: " .. tostring(reason or result) .. " " .. tostring(code or "")
end

local function contains_non_ascii(value)
    return tostring(value or ""):find("[\128-\255]") ~= nil
end

local function wait_for_runner_claim(task_path)
    for _ = 1, 200 do
        if not file_exists(task_path) then return true end
        wait_seconds(0.05)
    end
    return not file_exists(task_path)
end


local function queue_runner_task(config, name)
    local runner = runner_path()
    if PLATFORM.windows and contains_non_ascii(runner) then
        local api, api_error = win32_api()
        if not api then
            error(tr("error.runner_launch", {
                details = tr("error.windows_wide_launch", { details = api_error }),
            }))
        end
    end
    if not file_exists(runner) then error(tr("error.runner_missing", { path = runner })) end

    local task_stem = (name or "task") .. "_" .. tostring(os.time()) .. "_" .. tostring(math.random(100000, 999999))
    local queue_dir = path_join(dirname(runner), "tmp")
    mkdir_p(queue_dir)
    local task_path = path_join(queue_dir, "runner_launch_" .. task_stem .. ".json")
    local stdout_template = tostring(config.stdout_path or "")
    local done_template = tostring(config.done_path or "")
    local stdout_path = stdout_template ~= "" and (stdout_template .. "." .. task_stem) or ""
    local done_path = done_template ~= "" and (done_template .. "." .. task_stem) or ""
    local queued_config = {}
    for key, value in pairs(config) do queued_config[key] = value end
    queued_config.stdout_path = stdout_path
    queued_config.done_path = done_path
    if tostring(queued_config.mode or "run") == "open" then
        queued_config.done_path = ""
        done_path = ""
    end
    if file_exists(task_path) then error("Runner task path collision: " .. task_path) end
    if stdout_path ~= "" and file_exists(stdout_path) then error("Runner stdout path collision: " .. stdout_path) end
    if done_path ~= "" and file_exists(done_path) then error("Runner completion path collision: " .. done_path) end
    write_file(task_path, json_encode(queued_config, ""))

    local claimed = false
    local launched = false
    local launch_error = nil
    if PLATFORM.windows then
        launched, launch_error = launch_runner_native(runner)
    else
        launched, launch_error = launch_runner_posix(runner)
    end
    -- Long-running tasks are claimed asynchronously so the panel never blocks on runner start-up.
    local asynchronous = done_path ~= "" and tostring(queued_config.mode or "run") ~= "open"
    if launched then claimed = asynchronous or wait_for_runner_claim(task_path) end
    if not claimed then
        remove_file(task_path)
        if PLATFORM.windows and contains_non_ascii(runner) and not launched then
            launch_error = tr("error.windows_wide_launch", { details = launch_error })
        end
        error(tr("error.runner_launch", { details = launch_error or "runner did not claim the queued task" }))
    end
    if tostring(queued_config.mode or "run") == "open" or done_path == "" then return nil end
    return {
        task_path = task_path,
        stdout_path = stdout_path,
        done_path = done_path,
        processed_len = 0,
        started = os.time(),
        timeout = tonumber(config.timeout_seconds) or 21600,
        claimed = false,
        claim_deadline = os.time() + 15,
    }
end

local function read_runner_lines(task, on_line)
    if task.stdout_path == "" then return end
    local text = read_file(task.stdout_path)
    local current_len = string.len(text)
    if current_len <= task.processed_len then return end
    local chunk = string.sub(text, task.processed_len + 1)
    -- Only consume complete lines; a partial last line is read on the next poll.
    local last_newline = chunk:match(".*()\n")
    if not last_newline then return end
    task.processed_len = task.processed_len + last_newline
    for line in string.sub(chunk, 1, last_newline):gmatch("[^\r\n]+") do
        if trim(line) ~= "" and on_line then on_line(line) end
    end
end

-- Returns nil while the task runs and true after a successful exit; raises on failure.
local function poll_runner_task(task, on_line)
    if not task.claimed then
        if file_exists(task.task_path) then
            if os.time() > task.claim_deadline then
                remove_file(task.task_path)
                error(tr("error.runner_launch", { details = "runner did not claim the queued task" }))
            end
            return nil
        end
        task.claimed = true
        task.started = os.time()
    end
    read_runner_lines(task, on_line)
    if not file_exists(task.done_path) then
        if os.time() - task.started > task.timeout then
            error(tr("error.runner_timeout", { seconds = task.timeout }))
        end
        return nil
    end
    local done_text = read_file(task.done_path)
    if trim(done_text) == "" then return nil end
    local stdout_text = task.stdout_path ~= "" and read_file(task.stdout_path) or ""
    if string.len(stdout_text) > task.processed_len and on_line then
        for line in string.sub(stdout_text, task.processed_len + 1):gmatch("[^\r\n]+") do
            if trim(line) ~= "" then on_line(line) end
        end
        task.processed_len = string.len(stdout_text)
    end
    local completion_ok, completion = pcall(function() return json_decode(done_text) end)
    local code = completion_ok and type(completion) == "table" and completion ~= JSON_NULL
        and completion.returncode or nil
    remove_file(task.done_path)
    if task.stdout_path ~= "" then remove_file(task.stdout_path) end
    remove_file(task.task_path)
    if type(code) ~= "number" or code ~= code or code % 1 ~= 0 then
        error(tr("error.runner_completion", { path = task.done_path }))
    end
    if code ~= 0 then
        local details = ""
        for line in stdout_text:gmatch("[^\r\n]+") do
            if line:match("^Error: ") then details = line:sub(8) end
        end
        if details == "" then details = short_text(stdout_text, 500) end
        error(tr("error.runner_exit", { code = code, details = details }))
    end
    return true
end

-- Blocking variant for short helper tasks (colour picker, opening files).
local function run_runner_config(config, name)
    local task = queue_runner_task(config, name)
    if not task then return end
    while true do
        if poll_runner_task(task, append_log) then return end
        wait_seconds(0.1)
    end
end

-- ------------------------------------------------------------------------------------------
-- UI field helpers

local function text_field(element_id, fallback)
    local element = win:Find(element_id)
    if not element then return tostring(fallback or "") end
    local value = element.CurrentText or element.Text
    if value == nil or value == "" then return tostring(fallback or "") end
    return tostring(value)
end

local function int_field(element_id, default, minimum, maximum)
    local element = win:Find(element_id)
    local raw = nil
    if element then
        pcall(function() raw = element.Value end)
        if raw == nil then
            pcall(function() raw = element.Text end)
        end
    end
    local value = tonumber(raw) or default
    value = math.floor(value + 0.5)
    if value < minimum then value = minimum end
    if value > maximum then value = maximum end
    return value
end

local function check_field(element_id, default)
    local element = win:Find(element_id)
    if not element or element.Checked == nil then return default end
    return element.Checked == true or element.Checked == 1
end

local function set_text(element_id, value)
    local element = win:Find(element_id)
    if element then
        local text = tostring(value or "")
        pcall(function() element:SetEditText(text) end)
        pcall(function() element.CurrentText = text end)
        pcall(function() element.Text = text end)
    end
end

local function set_number(element_id, value)
    local element = win:Find(element_id)
    if element then
        pcall(function() element.Value = tonumber(value) or 0 end)
    end
end

local function configure_spinbox(element_id, minimum, maximum, value)
    local element = win:Find(element_id)
    if not element then return end
    pcall(function() element:SetRange(minimum, maximum) end)
    pcall(function() element.Minimum = minimum end)
    pcall(function() element.Maximum = maximum end)
    pcall(function() element.Value = value end)
end

local function set_checked(element_id, value)
    local element = win:Find(element_id)
    if element then element.Checked = value and true or false end
end

local function language_mode_index(mode)
    for index, value in ipairs(LANGUAGE_MODES) do
        if value == mode then return index - 1 end
    end
    return 0
end

local function language_mode_from_ui()
    local element = win and win:Find("LanguageMode") or nil
    local index = nil
    if element then pcall(function() index = tonumber(element.CurrentIndex) end) end
    return LANGUAGE_MODES[(index or language_mode_index(language_mode)) + 1] or "auto"
end

local save_current_style


local function windows_powershell_path()
    if not PLATFORM.windows then return "" end
    for _, variable in ipairs({ "SystemRoot", "WINDIR" }) do
        local system_root = trim(environment_value(nil, variable))
        if system_root ~= "" and is_absolute_path(system_root) then
            local directory = path_join(path_join(system_root, "System32"), "WindowsPowerShell")
            local candidate = path_join(path_join(directory, "v1.0"), "powershell.exe")
            if file_exists(candidate) then return candidate end
        end
    end
    return ""
end

-- The caller runs Editor.changed(), which stores the style, updates the swatch and the preview.
-- Saving here first would make that change look like a no-op.
local function apply_picked_color(field_id, selected)
    selected = normalize_hex(selected, "")
    if selected ~= "" then set_text(field_id, selected) end
end

local function pick_windows_color(field_id, fallback, swatches)
    if not PLATFORM.windows then error("Windows color picker called on a non-Windows platform") end
    local current = normalize_hex(text_field(field_id, fallback), fallback)
    local r, g, b = hex_to_rgb(current)
    local chosen, dialog_error = win32_choose_color(r, g, b, swatches)
    if chosen then
        apply_picked_color(field_id, string.format("#%02X%02X%02X", chosen[1], chosen[2], chosen[3]))
        return
    end
    if chosen == false then return end
    append_log("Color dialog unavailable, using PowerShell: " .. tostring(dialog_error))
    local powershell_path = windows_powershell_path()
    if powershell_path == "" then
        error("Windows PowerShell was not found under SystemRoot or WINDIR")
    end
    local root = install_root()
    mkdir_p(root)
    local picker_stem = tostring(os.time()) .. "_" .. tostring(math.random(100000, 999999))
    local script_path = path_join(root, "pick_color_" .. picker_stem .. ".ps1")
    local result_path = path_join(root, "picked_color_" .. picker_stem .. ".txt")
    local stdout_path = path_join(tmp_dir(), "color_picker_stdout.txt")
    local done_path = path_join(tmp_dir(), "color_picker_done.json")
    if file_exists(script_path) or file_exists(result_path) then error("Color picker path collision") end

    local script = table.concat({
        "param([string]$ResultPath)",
        "Add-Type -AssemblyName System.Windows.Forms",
        "Add-Type -AssemblyName System.Drawing",
        "$dialog = New-Object System.Windows.Forms.ColorDialog",
        "$dialog.FullOpen = $true",
        "$dialog.AllowFullOpen = $true",
        "$dialog.AnyColor = $true",
        "$dialog.Color = [System.Drawing.Color]::FromArgb(" .. tostring(r) .. "," .. tostring(g) .. "," .. tostring(b) .. ")",
        "$owner = New-Object System.Windows.Forms.Form",
        "$owner.TopMost = $true",
        "$owner.ShowInTaskbar = $false",
        "$owner.WindowState = 'Minimized'",
        "$owner.Show()",
        "if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {",
        "  $hex = '#{0:X2}{1:X2}{2:X2}' -f $dialog.Color.R, $dialog.Color.G, $dialog.Color.B",
        "  Set-Content -LiteralPath $ResultPath -Value $hex -Encoding ASCII",
        "}",
        "$owner.Close()",
    }, "\r\n")
    local picker_ok, selected = pcall(function()
        write_file(script_path, script)
        run_runner_config({
            mode = "run",
            cwd = root,
            command = {
                powershell_path, "-NoLogo", "-NoProfile", "-NonInteractive",
                "-Sta", "-WindowStyle", "Hidden", "-File", script_path,
                "-ResultPath", result_path,
            },
            stdout_path = stdout_path,
            done_path = done_path,
            timeout_seconds = 3600,
        }, "color_picker")
        return trim(read_file(result_path))
    end)
    remove_file(result_path)
    remove_file(script_path)
    if not picker_ok then error(selected) end
    apply_picked_color(field_id, selected)
end



-- ------------------------------------------------------------------------------------------
-- Timeline scanning

local function frame(value)
    return math.floor((tonumber(value) or 0) + 0.5)
end

local function seconds(value)
    local parsed = tonumber(value) or 0
    if parsed < 0 then return 0 end
    return parsed
end

-- Reads a frame-rate setting ("30", "29.97 DF", "23,976") from the timeline, then the project.
local function read_frame_rate(project, timeline, key)
    for _, owner in ipairs({ timeline, project }) do
        local ok, raw = pcall(function() return owner:GetSetting(key) end)
        if ok and raw and tostring(raw) ~= "" then
            local fps_text = tostring(raw)
            fps_text = fps_text:gsub("DF", ""):gsub("df", ""):gsub(",", ".")
            fps_text = fps_text:match("%d+%.?%d*") or ""
            local value = tonumber(fps_text)
            if value and value > 0 then return value end
        end
    end
    return nil
end

-- Returns the timeline frame rate and whether it fell back to 30.
local function timeline_fps(project, timeline)
    local value = read_frame_rate(project, timeline, "timelineFrameRate")
    if value then return value, false end
    return 30, true
end

local function format_rate(value)
    if math.abs(value - math.floor(value + 0.5)) < 0.001 then return tostring(math.floor(value + 0.5)) end
    return (string.format("%.3f", value):gsub("0+$", ""))
end

-- Resolve plays the timeline at the project's playback frame rate. When it differs from the
-- timeline frame rate, playback runs at the wrong speed with crackling audio; the players
-- themselves are still correct. Returns the warning text, or "" when the rates match.
local function playback_rate_warning(project, timeline)
    local timeline_rate = read_frame_rate(project, timeline, "timelineFrameRate")
    local playback_rate = read_frame_rate(project, timeline, "timelinePlaybackFrameRate")
    if not timeline_rate or not playback_rate or math.abs(timeline_rate - playback_rate) < 0.01 then return "" end
    return tr("warning.playback_rate", { playback = format_rate(playback_rate), timeline = format_rate(timeline_rate) })
end

local function timeline_resolution(project, timeline)
    local owners = {
        { value = timeline, label = "timeline" },
        { value = project, label = "project" },
    }
    local families = {
        { width = "timelineResolutionWidth", height = "timelineResolutionHeight", label = "timelineResolution" },
        { width = "timelineOutputResolutionWidth", height = "timelineOutputResolutionHeight", label = "timelineOutputResolution" },
    }
    for _, owner in ipairs(owners) do
        for _, family in ipairs(families) do
            local width_ok, width_raw = pcall(function() return owner.value:GetSetting(family.width) end)
            local height_ok, height_raw = pcall(function() return owner.value:GetSetting(family.height) end)
            local width = width_ok and tonumber(width_raw) or nil
            local height = height_ok and tonumber(height_raw) or nil
            if width and height and width > 0 and height > 0 then
                return math.floor(width + 0.5), math.floor(height + 0.5), owner.label .. "." .. family.label
            end
        end
    end
    return nil, nil, nil
end

local function parse_track_list(text)
    local tracks = {}
    local seen = {}
    text = tostring(text or ""):gsub(";", ",")
    for chunk in text:gmatch("[^,]+") do
        chunk = trim(chunk)
        local left, right = chunk:match("^(%d+)%s*%-%s*(%d+)$")
        if left and right then
            local start_track = tonumber(left)
            local end_track = tonumber(right)
            if start_track > end_track then start_track, end_track = end_track, start_track end
            for track = start_track, end_track do
                if track >= 1 and not seen[track] then
                    seen[track] = true
                    table.insert(tracks, track)
                end
            end
        else
            local track = tonumber(chunk)
            if track and track >= 1 and not seen[track] then
                seen[track] = true
                table.insert(tracks, track)
            end
        end
    end
    if #tracks == 0 then table.insert(tracks, 1) end
    return tracks
end

local function parse_number_ranges(text)
    local numbers = {}
    text = tostring(text or ""):gsub(";", ",")
    for chunk in text:gmatch("[^,]+") do
        chunk = trim(chunk)
        local left, right = chunk:match("^(%d+)%s*%-%s*(%d+)$")
        if left and right then
            local start_number = tonumber(left)
            local end_number = tonumber(right)
            if start_number > end_number then start_number, end_number = end_number, start_number end
            for number = start_number, end_number do
                if number > 0 then numbers[number] = true end
            end
        else
            local number = tonumber(chunk)
            if number and number > 0 then numbers[number] = true end
        end
    end
    return numbers
end

local function format_frame_time(frame_number, fps)
    frame_number = math.max(0, math.floor(tonumber(frame_number) or 0))
    local fps_int = math.max(1, math.floor((tonumber(fps) or 30) + 0.5))
    local total_seconds = math.floor(frame_number / fps_int)
    local frames = frame_number % fps_int
    local hours = math.floor(total_seconds / 3600)
    local minutes = math.floor((total_seconds % 3600) / 60)
    local secs = total_seconds % 60
    return string.format("%02d:%02d:%02d:%02d", hours, minutes, secs, frames)
end

local function timecode_to_frames(timecode, fps)
    local parts = {}
    for part in tostring(timecode or ""):gsub(";", ":"):gsub("%.", ":"):gmatch("[^:]+") do
        table.insert(parts, tonumber(part) or 0)
    end
    if #parts < 4 then return 0 end
    local fps_int = math.max(1, math.floor((tonumber(fps) or 30) + 0.5))
    local hours = parts[#parts - 3]
    local minutes = parts[#parts - 2]
    local secs = parts[#parts - 1]
    local frames = parts[#parts]
    return (((hours * 60 + minutes) * 60 + secs) * fps_int) + frames
end

local function current_playhead_frame(timeline, fps)
    local current_tc = ""
    local start_tc = "00:00:00:00"
    local timeline_start = 0
    pcall(function() current_tc = timeline:GetCurrentTimecode() or "" end)
    pcall(function() start_tc = timeline:GetStartTimecode() or "00:00:00:00" end)
    pcall(function() timeline_start = tonumber(timeline:GetStartFrame()) or 0 end)
    return timeline_start + math.max(0, timecode_to_frames(current_tc, fps) - timecode_to_frames(start_tc, fps))
end

local function table_count(items)
    local count = 0
    if type(items) ~= "table" then return count end
    for _, _ in pairs(items or {}) do count = count + 1 end
    return count
end

local function get_timeline_items(timeline, track_type, track_index)
    local variants = { track_type, string.lower(track_type), string.upper(string.sub(track_type, 1, 1)) .. string.sub(string.lower(track_type), 2) }
    local first_table = nil
    for _, variant in ipairs(variants) do
        local ok, items = pcall(function() return timeline:GetItemListInTrack(variant, track_index) end)
        if ok and type(items) == "table" then
            if table_count(items) > 0 then return items end
            first_table = first_table or items
        end
        ok, items = pcall(function() return timeline:GetItemsInTrack(variant, track_index) end)
        if ok and type(items) == "table" then
            if table_count(items) > 0 then return items end
            first_table = first_table or items
        end
    end
    if first_table then return first_table end
    return {}
end

local function get_track_count(timeline, track_type)
    local variants = { track_type, string.lower(track_type), string.upper(string.sub(track_type, 1, 1)) .. string.sub(string.lower(track_type), 2) }
    local best = 0
    for _, variant in ipairs(variants) do
        local ok, value = pcall(function() return timeline:GetTrackCount(variant) end)
        local count = ok and tonumber(value) or 0
        if count > best then best = count end
    end
    return best
end

local function has_timeline_method(value, method_name)
    if value == nil or type(value) == "number" or type(value) == "string" or type(value) == "boolean" then
        return false
    end
    if method_name == "GetMediaPoolItem" then
        local ok = pcall(function() value:GetMediaPoolItem() end)
        return ok
    end
    if method_name == "GetName" then
        local ok = pcall(function() value:GetName() end)
        return ok
    end
    local ok, method = pcall(function() return value[method_name] end)
    return ok and type(method) == "function"
end

local function normalize_timeline_items(items, method_name)
    local normalized = {}
    if type(items) ~= "table" then return normalized end
    for key, value in pairs(items or {}) do
        if has_timeline_method(value, method_name) then
            table.insert(normalized, value)
        elseif has_timeline_method(key, method_name) then
            table.insert(normalized, key)
        elseif method_name ~= "GetName" and has_timeline_method(value, "GetName") then
            table.insert(normalized, value)
        elseif method_name ~= "GetName" and has_timeline_method(key, "GetName") then
            table.insert(normalized, key)
        end
    end
    return normalized
end

local function media_file_path(timeline_item)
    local ok_item, media_pool_item = pcall(function() return timeline_item:GetMediaPoolItem() end)
    if not ok_item then return "" end
    if not media_pool_item then return "" end

    local function clean_path(value)
        local text = trim(value or "")
        text = text:gsub('^"', ''):gsub('"$', '')
        return path_from_file_uri(text)
    end

    local function existing_path(value)
        local text = clean_path(value)
        if text ~= "" and file_exists(text) then return text end
        if is_absolute_path(text) then return text end
        for candidate in text:gmatch("[%a]:[^\r\n\"<>|]+") do
            candidate = clean_path(candidate)
            -- Trust absolute paths returned by Resolve's official GetClipProperty() snapshot.
            -- Lua's io.open can fail on Windows paths containing non-ASCII characters.
            if is_absolute_path(candidate) then return candidate end
        end
        return ""
    end

    local function find_path_in_value(value, depth)
        depth = depth or 0
        if depth > 3 or value == nil then return "" end
        if type(value) == "string" or type(value) == "number" then
            return existing_path(tostring(value))
        end
        if type(value) == "table" then
            for _, nested in pairs(value) do
                local found = find_path_in_value(nested, depth + 1)
                if found ~= "" then return found end
            end
        end
        return ""
    end

    local function trusted_absolute_path(value)
        local text = clean_path(value)
        if is_absolute_path(text) then return text end
        return ""
    end

    local ok, props = pcall(function() return media_pool_item:GetClipProperty() end)
    if ok and type(props) == "table" then
        -- Official Resolve API exposes the source path as "File Path" in GetClipProperty().
        -- Do not validate this with Lua io.open: Resolve Lua can fail on Unicode paths.
        local direct_path = trusted_absolute_path(props["File Path"] or props["File path"] or props["file path"])
        if direct_path ~= "" then return direct_path end
        local found = find_path_in_value(props, 0)
        if found ~= "" then return found end
    end

    -- Official API allows querying specific property keys, but the key names can differ by media/version.
    -- Use this only after the documented full property snapshot above did not expose a path.
    local keys = { "File Path", "File Path 1", "File Path 2", "Filename", "File Name", "Path", "Clip Path" }
    for _, key in ipairs(keys) do
        local ok_key, value = pcall(function() return media_pool_item:GetClipProperty(key) end)
        if ok_key then
            local direct_path = trusted_absolute_path(value)
            if direct_path ~= "" then return direct_path end
            local found = find_path_in_value(value, 0)
            if found ~= "" then return found end
        end
    end
    local ok_meta, metadata = pcall(function() return media_pool_item:GetMetadata() end)
    if ok_meta then
        local found = find_path_in_value(metadata, 0)
        if found ~= "" then return found end
    end
    local ok_third, third_party = pcall(function() return media_pool_item:GetThirdPartyMetadata() end)
    if ok_third then
        local found = find_path_in_value(third_party, 0)
        if found ~= "" then return found end
    end

    if ok and type(props) == "table" then
        local sample = {}
        for key, value in pairs(props) do
            if #sample >= 8 then break end
            table.insert(sample, tostring(key) .. "=" .. short_text(tostring(value), 80))
        end
        if #sample > 0 then append_log(tr("log.clip_properties_no_path", { details = table.concat(sample, " | ") })) end
    end
    return ""
end

local function basename(path)
    return tostring(path or ""):match("([^\\/]+)$") or tostring(path or "")
end

local function stem_name(name)
    local base = basename(name)
    return (base:gsub("%.[^%.]+$", ""))
end

local function dump_clip_properties(timeline_item, clip_name)
    local ok_item, media_pool_item = pcall(function() return timeline_item:GetMediaPoolItem() end)
    if not ok_item or not media_pool_item then return end
    local lines = {}
    table.insert(lines, "--- " .. tostring(os.date("%Y-%m-%d %H:%M:%S")) .. " :: " .. tostring(clip_name or "") .. " ---")
    local ok_props, props = pcall(function() return media_pool_item:GetClipProperty() end)
    table.insert(lines, "GetClipProperty(): " .. tostring(ok_props) .. " type=" .. type(props))
    if ok_props and type(props) == "table" then
        local keys = {}
        for key, _ in pairs(props) do table.insert(keys, key) end
        table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
        for _, key in ipairs(keys) do table.insert(lines, tostring(key) .. " = " .. tostring(props[key])) end
    end
    local ok_meta, meta = pcall(function() return media_pool_item:GetMetadata() end)
    table.insert(lines, "GetMetadata(): " .. tostring(ok_meta) .. " type=" .. type(meta))
    if ok_meta and type(meta) == "table" then
        local keys = {}
        for key, _ in pairs(meta) do table.insert(keys, key) end
        table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
        for _, key in ipairs(keys) do table.insert(lines, "META " .. tostring(key) .. " = " .. tostring(meta[key])) end
    end
    append_file(clip_dump_path(), table.concat(lines, "\r\n") .. "\r\n")
end

local function find_source_in_folder(clip_name, source_dir)
    source_dir = trim(source_dir or "")
    if source_dir == "" then return "" end
    local target_base = path_identity(basename(clip_name))
    local target_stem = path_identity(stem_name(clip_name))
    if target_base == "" then return "" end
    local media_storage = resolve:GetMediaStorage()
    if not media_storage then return "" end
    local audio_ext = { mp3 = true, wav = true, m4a = true, aac = true, flac = true, aiff = true, aif = true, ogg = true }
    local visited = {}

    local function scan_folder(folder, depth)
        local folder_key = path_identity(folder)
        if depth > 6 or visited[folder_key] then return "" end
        visited[folder_key] = true
        local ok_files, files = pcall(function() return media_storage:GetFileList(folder) end)
        if ok_files and type(files) == "table" then
            for _, file_path in pairs(files) do
                local file_text = tostring(file_path)
                local raw_base = basename(file_text)
                local file_base = path_identity(raw_base)
                local file_stem = path_identity(stem_name(file_text))
                local ext = string.lower(raw_base:match("%.([^%.]+)$") or "")
                if file_base == target_base or (file_stem == target_stem and audio_ext[ext]) then
                    return file_text
                end
            end
        end
        local ok_dirs, dirs = pcall(function() return media_storage:GetSubFolderList(folder) end)
        if ok_dirs and type(dirs) == "table" then
            for _, child in pairs(dirs) do
                local found = scan_folder(tostring(child), depth + 1)
                if found ~= "" then return found end
            end
        end
        return ""
    end

    return scan_folder(source_dir, 0)
end

local function source_start_time(timeline_item, fps)
    local ok, value = pcall(function() return timeline_item:GetSourceStartTime() end)
    if ok and value ~= nil then return seconds(value) end
    ok, value = pcall(function() return timeline_item:GetSourceStartFrame() end)
    if ok and value ~= nil then return frame(value) / math.max(1.0, fps) end
    return 0.0
end

local function item_unique_id(timeline_item, index, record_frame)
    local ok, unique = pcall(function() return timeline_item:GetUniqueId() end)
    if ok and unique and tostring(unique) ~= "" then return tostring(unique) end
    return "audio_" .. tostring(index) .. "_" .. tostring(record_frame)
end

local function read_item_clip_enabled(timeline_item)
    local ok, enabled = pcall(function() return timeline_item:GetClipEnabled() end)
    if not ok then return true end
    return enabled == true or enabled == 1
end

local function item_frame_value(timeline_item, method_name)
    local ok, value = false, nil
    if method_name == "GetDuration" then
        ok, value = pcall(function() return timeline_item:GetDuration(false) end)
        if not ok or value == nil then ok, value = pcall(function() return timeline_item:GetDuration() end) end
    elseif method_name == "GetStart" then
        ok, value = pcall(function() return timeline_item:GetStart(false) end)
        if not ok or value == nil then ok, value = pcall(function() return timeline_item:GetStart() end) end
    elseif method_name == "GetEnd" then
        ok, value = pcall(function() return timeline_item:GetEnd(false) end)
        if not ok or value == nil then ok, value = pcall(function() return timeline_item:GetEnd() end) end
    else
        local ok_method, method = pcall(function() return timeline_item[method_name] end)
        if not ok_method or type(method) ~= "function" then return 0 end
        ok, value = pcall(function() return method(timeline_item, false) end)
        if not ok or value == nil then
            ok, value = pcall(function() return method(timeline_item) end)
        end
    end
    if not ok or value == nil then return 0 end
    return frame(value)
end

local function sorted_jobs(jobs)
    table.sort(jobs, function(a, b)
        local a_start = tonumber(a.record_frame) or 0
        local b_start = tonumber(b.record_frame) or 0
        if a_start == b_start then
            return (tonumber(a.audio_track) or 0) < (tonumber(b.audio_track) or 0)
        end
        return a_start < b_start
    end)
    return jobs
end


-- Players share one video track, so they must not overlap. In a mix the next track usually starts
-- on another audio track while the current one fades out; the switch mode picks the frame inside
-- that crossfade where the player changes. A later start moves the player's track offset with it,
-- so time, progress and waveform stay in sync with what is heard.
local SWITCH_MODES = { "overlap_middle", "next_start", "current_end" }

local function switch_mode_from_ui()
    local element = win and win:Find("SwitchMode") or nil
    local index = nil
    if element then pcall(function() index = tonumber(element.CurrentIndex) end) end
    return SWITCH_MODES[(index or 0) + 1] or SWITCH_MODES[1]
end

local function switch_frame(current, following, mode)
    local overlap_end = math.min(current.end_frame, following.end_frame)
    if mode == "next_start" then return following.record_frame end
    if mode == "current_end" then return overlap_end end
    return math.floor((following.record_frame + overlap_end) / 2)
end

local function resolve_overlap_jobs(jobs, fps, mode)
    if #jobs == 0 then return {} end
    sorted_jobs(jobs)
    local preferred_by_start = {}
    for _, job in ipairs(jobs) do
        local key = tostring(job.record_frame)
        local previous = preferred_by_start[key]
        if previous == nil or (tonumber(job.audio_track) or 0) > (tonumber(previous.audio_track) or 0) then
            preferred_by_start[key] = job
        end
    end
    local filtered = {}
    for _, job in pairs(preferred_by_start) do table.insert(filtered, job) end
    if #jobs - #filtered > 0 then
        append_log(tr("log.overlap_same_start", { count = #jobs - #filtered }))
    end
    sorted_jobs(filtered)

    local resolved = {}
    for _, job in ipairs(filtered) do
        local item = copy_table(job)
        item.record_frame = tonumber(item.record_frame) or 0
        item.end_frame = tonumber(item.end_frame) or (item.record_frame + (tonumber(item.duration_frames) or 0))
        item.source_end_frame = item.end_frame
        item.original_frames = item.end_frame - item.record_frame
        local keep = item.end_frame > item.record_frame
        while keep and #resolved > 0 do
            local previous = resolved[#resolved]
            if item.record_frame >= previous.end_frame then break end
            if item.end_frame <= previous.source_end_frame then
                -- Starts and ends inside another track: a layer (sample, FX), not the current track.
                keep = false
                append_log(tr("log.overlay_skipped", { name = item.timeline_item_name or "" }))
                break
            end
            local cut = switch_frame(previous, item, mode)
            cut = math.min(math.max(cut, previous.record_frame, item.record_frame), previous.end_frame)
            previous.end_frame = cut
            if cut > item.record_frame then
                item.source_start_time = (tonumber(item.source_start_time) or 0) + (cut - item.record_frame) / math.max(1.0, fps)
                append_log(tr("log.switch_delayed", { name = item.timeline_item_name or "", frames = cut - item.record_frame }))
                item.record_frame = cut
            end
            if previous.end_frame > previous.record_frame then break end
            append_log(tr("log.zero_length", { name = previous.timeline_item_name or "" }))
            table.remove(resolved)
        end
        if keep then table.insert(resolved, item) end
    end
    for _, item in ipairs(resolved) do
        item.duration_frames = item.end_frame - item.record_frame
        item.duration = item.duration_frames / math.max(1.0, fps)
        item.visible_end_frame = item.end_frame
        if item.end_frame < item.source_end_frame then
            append_log(tr("log.switch_trimmed", { name = item.timeline_item_name or "", from = item.original_frames, to = item.duration_frames }))
        end
    end
    return resolved
end

local function log_clip_numbers(jobs, fps)
    if #jobs == 0 then return end
    append_log(tr("log.clip_numbers"))
    local max_items = 60
    for index, job in ipairs(jobs) do
        if index > max_items then break end
        append_log(string.format("#%03d A%d %s +%df  %s", tonumber(job.display_index) or index, tonumber(job.audio_track) or 0, format_frame_time(job.record_frame, fps), tonumber(job.duration_frames) or 0, tostring(job.timeline_item_name or "")))
    end
    if #jobs > max_items then
        append_log(tr("log.more_clips", { count = #jobs - max_items }))
    end
end

local function apply_update_scope(jobs, timeline, fps)
    local spec = trim(text_field("UpdateScope", ""))
    local lowered = spec:lower()
    if spec == "" or lowered == "all" or lowered == "*" or lowered == tr("scope.alias_all"):lower() then
        return jobs, false
    end

    local selected = {}
    if lowered == "@playhead" or lowered == "playhead" or lowered == "current" or lowered == tr("scope.alias_current"):lower() then
        local playhead = current_playhead_frame(timeline, fps)
        local active = nil
        for _, job in ipairs(jobs) do
            local start_frame = tonumber(job.record_frame) or 0
            local end_frame = tonumber(job.visible_end_frame or job.end_frame) or 0
            if start_frame <= playhead and playhead < end_frame then
                if active == nil or start_frame > (tonumber(active.record_frame) or 0) or (start_frame == (tonumber(active.record_frame) or 0) and (tonumber(job.audio_track) or 0) > (tonumber(active.audio_track) or 0)) then
                    active = job
                end
            end
        end
        if not active then
            error(tr("error.no_clip_at_playhead", { time = format_frame_time(playhead, fps) }))
        end
        selected[tonumber(active.display_index)] = true
        append_log(tr("log.playhead_selected", { number = string.format("%03d", tonumber(active.display_index) or 0) }))
    else
        selected = parse_number_ranges(spec)
        local has_any = false
        for _, _ in pairs(selected) do has_any = true break end
        if not has_any then
            error(tr("error.scope_invalid"))
        end
    end

    local by_number = {}
    for _, job in ipairs(jobs) do by_number[tonumber(job.display_index)] = job end
    local missing = {}
    for number, _ in pairs(selected) do
        if by_number[number] == nil then table.insert(missing, number) end
    end
    table.sort(missing)
    if #missing > 0 then
        local parts = {}
        for _, number in ipairs(missing) do table.insert(parts, tostring(number)) end
        error(tr("error.unknown_clip_numbers", { numbers = table.concat(parts, ", ") }))
    end

    local include = copy_table(selected)
    if check_field("SwitchOnNextStart", true) then
        for number, _ in pairs(selected) do
            if by_number[number - 1] then include[number - 1] = true end
        end
    end

    local filtered = {}
    local labels = {}
    for _, job in ipairs(jobs) do
        if include[tonumber(job.display_index)] then
            table.insert(filtered, job)
            table.insert(labels, string.format("#%03d", tonumber(job.display_index) or 0))
        end
    end
    append_log(tr("log.partial_update", { clips = table.concat(labels, ", ") }))
    return filtered, true
end


local function ensure_video_track(timeline, track_index)
    track_index = tonumber(track_index)
    if not track_index or track_index < 1 or track_index > 64 or track_index % 1 ~= 0 then
        error(tr("error.video_track_index", { track = track_index }))
    end
    local track_count = tonumber(timeline:GetTrackCount("video")) or 0
    local attempts = 0
    while track_count < track_index and attempts < 64 do
        local before = track_count
        local add_ok, add_result = pcall(function() return timeline:AddTrack("video") end)
        if not add_ok or add_result == false then
            error(tr("error.video_track_add", { details = add_result }))
        end
        track_count = tonumber(timeline:GetTrackCount("video")) or 0
        if track_count <= before then
            error(tr("error.video_track_count"))
        end
        attempts = attempts + 1
    end
    if track_count < track_index then
        error(tr("error.video_track_create", { track = track_index }))
    end
    pcall(function() timeline:SetTrackLock("video", track_index, false) end)
    pcall(function() timeline:SetTrackEnable("video", track_index, true) end)
end

local function safe_stem(value)
    local text = trim(value):gsub("[^A-Za-z0-9%._%-]+", "_"):gsub("^[%._%-]+", ""):gsub("[%._%-]+$", "")
    if text == "" then return "track" end
    return text
end


local function string_hash(text)
    local hash = 5381
    for index = 1, string.len(text) do
        hash = (hash * 33 + string.byte(text, index)) % 4294967296
    end
    return string.format("%08x", hash)
end

-- ui:Icon and ImportFusionComp need ASCII paths; user profiles are often not ASCII.
local function ascii_work_dir()
    local preferred = tmp_dir()
    if not contains_non_ascii(preferred) then
        mkdir_p(preferred)
        return preferred
    end
    if PLATFORM.windows then
        for _, name in ipairs({ "ProgramData", "PUBLIC" }) do
            local base = trim(environment_value(nil, name) or "")
            if base ~= "" and not contains_non_ascii(base) and is_absolute_path(base) then
                local directory = path_join(path_join(path_join(base, "DavinciTrackVisualizer"), "work"), string_hash(preferred))
                local ok = pcall(function() mkdir_p(directory) end)
                if ok and file_exists(directory) then return directory end
            end
        end
    end
    mkdir_p(preferred)
    return preferred
end

local function output_dir()
    return path_join(path_join(install_root(), "outputs"), "resolve")
end

local function current_project_and_timeline()
    local project_manager = resolve:GetProjectManager()
    local project = project_manager and project_manager:GetCurrentProject() or nil
    if not project then error(tr("error.project_required")) end
    local timeline = project:GetCurrentTimeline()
    if not timeline then error(tr("error.timeline_required")) end
    return project_manager, project, timeline
end

local function timeline_identity(timeline)
    local ok, unique_id = pcall(function() return timeline:GetUniqueId() end)
    if ok and unique_id and tostring(unique_id) ~= "" then return tostring(unique_id) end
    local name_ok, name = pcall(function() return timeline:GetName() end)
    return "name:" .. tostring(name_ok and name or "")
end

local function collect_jobs(project, timeline, apply_scope)
    local audio_tracks = parse_track_list(text_field("AudioTracks", "1"))
    local video_track = int_field("VideoTrack", 2, 1, 64)
    local fps, fps_fallback = timeline_fps(project, timeline)
    if fps_fallback then append_log(tr("warning.fps_fallback")) end
    local jobs = {}
    local scan_summary = {}
    local missing_path_count = 0

    for _, audio_track in ipairs(audio_tracks) do
        local audio_track_count = get_track_count(timeline, "audio")
        if audio_track > audio_track_count then
            append_log(tr("log.track_missing", { track = audio_track }))
            table.insert(scan_summary, tr("summary.track_missing", { track = audio_track, count = audio_track_count }))
        else
            local items = normalize_timeline_items(get_timeline_items(timeline, "audio", audio_track), "GetName")
            table.insert(scan_summary, "A" .. tostring(audio_track) .. ": " .. tostring(#items))
            local index = 0
            for _, item in pairs(items) do
                index = index + 1
                if read_item_clip_enabled(item) then
                    local source_path = media_file_path(item)
                    local name = ""
                    pcall(function() name = item:GetName() or "" end)
                    if source_path == "" then
                        missing_path_count = missing_path_count + 1
                        append_log(tr("log.clip_no_path", { name = name }))
                        dump_clip_properties(item, name)
                        append_log(tr("log.clip_dump", { path = clip_dump_path() }))
                    else
                        local duration_frames = item_frame_value(item, "GetDuration")
                        local start_frame = item_frame_value(item, "GetStart")
                        if duration_frames <= 0 then
                            local end_frame = item_frame_value(item, "GetEnd")
                            duration_frames = math.max(1, end_frame - start_frame)
                        end
                        table.insert(jobs, {
                            id = item_unique_id(item, index, start_frame),
                            source_path = source_path,
                            record_frame = start_frame,
                            end_frame = start_frame + duration_frames,
                            duration_frames = duration_frames,
                            source_start_time = source_start_time(item, fps),
                            audio_track = audio_track,
                            timeline_item_name = name,
                        })
                    end
                end
            end
        end
    end

    jobs = resolve_overlap_jobs(jobs, fps, switch_mode_from_ui())
    for index, job in ipairs(jobs) do job.display_index = index end
    log_clip_numbers(jobs, fps)
    local partial_update = false
    if apply_scope then
        jobs, partial_update = apply_update_scope(jobs, timeline, fps)
    end
    local width, height = timeline_resolution(project, timeline)
    if not width or not height then error(tr("error.resolution")) end
    return {
        fps = fps,
        width = width,
        height = height,
        video_track = video_track,
        audio_tracks = audio_tracks,
        jobs = jobs,
        partial = partial_update,
        summary = table.concat(scan_summary, "; "),
        missing_path_count = missing_path_count,
    }
end

-- ------------------------------------------------------------------------------------------
-- Placement on the target timeline

local Place = {}

function Place.media_bin(media_pool)
    local root_folder = media_pool:GetRootFolder()
    local subfolders = {}
    pcall(function() subfolders = root_folder:GetSubFolderList() or {} end)
    for _, folder in pairs(subfolders) do
        local ok, name = pcall(function() return folder:GetName() end)
        if ok and name == MEDIA_BIN_NAME then return folder end
    end
    local ok, created = pcall(function() return media_pool:AddSubFolder(root_folder, MEDIA_BIN_NAME) end)
    if ok and created then return created end
    return root_folder
end

function Place.carrier_item(media_pool, carrier_path)
    local bin = Place.media_bin(media_pool)
    local wanted = path_identity(carrier_path)
    local clips = {}
    pcall(function() clips = bin:GetClipList() or {} end)
    for _, clip in pairs(clips) do
        local ok, file_path = pcall(function() return clip:GetClipProperty("File Path") end)
        if ok and type(file_path) == "string" and path_identity(file_path) == wanted then return clip end
    end
    local previous = nil
    pcall(function() previous = media_pool:GetCurrentFolder() end)
    pcall(function() media_pool:SetCurrentFolder(bin) end)
    local ok, items = pcall(function() return media_pool:ImportMedia({ carrier_path }) end)
    if previous then pcall(function() media_pool:SetCurrentFolder(previous) end) end
    if not ok or type(items) ~= "table" or not items[1] then
        error(tr("error.carrier_import", { path = carrier_path }))
    end
    return items[1]
end

function Place.item_name(item)
    local name = ""
    pcall(function() name = item:GetName() or "" end)
    return tostring(name)
end

function Place.is_owned_name(name)
    return starts_with(name, VISUALIZER_PREFIX) or starts_with(name, CARRIER_PREFIX)
end

function Place.track_items(timeline, track)
    local result = {}
    for _, item in pairs(normalize_timeline_items(get_timeline_items(timeline, "video", track), "GetName")) do
        local name = Place.item_name(item)
        table.insert(result, {
            item = item,
            name = name,
            owned = Place.is_owned_name(name),
            id = starts_with(name, VISUALIZER_PREFIX) and string.sub(name, string.len(VISUALIZER_PREFIX) + 1) or nil,
            start = item_frame_value(item, "GetStart"),
            finish = item_frame_value(item, "GetEnd"),
        })
    end
    return result
end

function Place.overlaps(entry, job)
    local job_end = job.record_frame + job.duration_frames
    return entry.start < job_end and entry.finish > job.record_frame
end

function Place.remove_previous(timeline, track, jobs, replace_all)
    local ids = {}
    for _, job in ipairs(jobs) do ids[tostring(job.id)] = true end
    local doomed = {}
    for _, entry in ipairs(Place.track_items(timeline, track)) do
        if entry.owned then
            local matches = replace_all or (entry.id and ids[entry.id])
            if not matches then
                for _, job in ipairs(jobs) do
                    if Place.overlaps(entry, job) then matches = true break end
                end
            end
            if matches then table.insert(doomed, entry.item) end
        end
    end
    if #doomed > 0 then
        local ok, result = pcall(function() return timeline:DeleteClips(doomed, false) end)
        if not ok or result == false then error("DeleteClips: " .. tostring(result)) end
    end
    return #doomed
end

function Place.check_conflicts(timeline, track, jobs, fps)
    for _, entry in ipairs(Place.track_items(timeline, track)) do
        if not entry.owned then
            for _, job in ipairs(jobs) do
                if Place.overlaps(entry, job) then
                    error(tr("error.track_conflict", { track = track, time = format_frame_time(math.max(entry.start, job.record_frame), fps) }))
                end
            end
        end
    end
end

-- Appends one batch of carrier clips and attaches their compositions.
function Place.place_batch(media_pool, carrier, track, entries)
    local infos = {}
    for index, entry in ipairs(entries) do
        infos[index] = {
            mediaPoolItem = carrier,
            startFrame = 0,
            endFrame = entry.duration_frames,
            recordFrame = entry.record_frame,
            trackIndex = track,
            mediaType = 1,
        }
    end
    local ok, appended = pcall(function() return media_pool:AppendToTimeline(infos) end)
    local by_start = {}
    if ok and type(appended) == "table" then
        for _, item in pairs(appended) do
            local start = item_frame_value(item, "GetStart")
            by_start[start] = by_start[start] or {}
            table.insert(by_start[start], item)
        end
    end
    local placed, failures, stray = {}, {}, {}
    for _, entry in ipairs(entries) do
        local bucket = by_start[entry.record_frame]
        local item = bucket and table.remove(bucket, 1) or nil
        if not item then
            table.insert(failures, { entry = entry, details = "AppendToTimeline returned no clip" })
        else
            local comp_ok, comp = pcall(function() return item:ImportFusionComp(entry.comp_path) end)
            if not comp_ok or not comp then
                table.insert(stray, item)
                table.insert(failures, { entry = entry, details = "ImportFusionComp failed" })
            else
                pcall(function() item:SetName(VISUALIZER_PREFIX .. tostring(entry.id)) end)
                pcall(function() item:SetClipColor("Teal") end)
                table.insert(placed, entry)
            end
        end
    end
    for _, bucket in pairs(by_start) do
        for _, item in ipairs(bucket) do table.insert(stray, item) end
    end
    return placed, failures, stray
end

function Place.legacy_helpers(project, timeline)
    local suffix = safe_stem(timeline_identity(timeline))
    if string.len(suffix) > 32 then suffix = string.sub(suffix, 1, 32) end
    local helpers = {}
    local count = tonumber(project:GetTimelineCount()) or 0
    for index = 1, count do
        local candidate = project:GetTimelineByIndex(index)
        local name = candidate and tostring(candidate:GetName() or "") or ""
        if starts_with(name, "TVIZ__SOURCE__G") and name:find("__" .. suffix .. "__S", 1, true) then
            table.insert(helpers, candidate)
        end
    end
    return helpers
end

function Place.legacy_players(timeline)
    local count = 0
    local tracks = tonumber(timeline:GetTrackCount("video")) or 0
    for track = 1, tracks do
        for _, entry in ipairs(Place.track_items(timeline, track)) do
            if entry.owned then
                local media_name = ""
                pcall(function() media_name = entry.item:GetMediaPoolItem():GetName() or "" end)
                if not starts_with(tostring(media_name), CARRIER_PREFIX) then count = count + 1 end
            end
        end
    end
    return count
end

-- ------------------------------------------------------------------------------------------
-- Background work: one UI timer drives the pipeline, previews and autosave

local Ticker = { timer = nil, running = false }
local Pipeline = { state = nil }
local Preview = { task = nil, requested = false, countdown = 0, path = nil, serial = 0, frame = { 1920, 1080 } }
local App = { busy_controls = {}, remove_armed = 0 }
local Updater = { task = nil, pending = nil, install = nil, updated = nil, result = nil }

function Ticker.ensure()
    if Ticker.timer and not Ticker.running then
        pcall(function() Ticker.timer:Start() end)
        Ticker.running = true
    end
end

function Ticker.idle()
    return Pipeline.state == nil and Preview.task == nil and not Preview.requested
        and Settings.dirty_ticks == nil and App.remove_armed <= 0 and not Updater.busy()
end

function Ticker.tick()
    Pipeline.tick()
    Preview.tick()
    Updater.tick()
    if Settings.dirty_ticks then
        Settings.dirty_ticks = Settings.dirty_ticks - 1
        if Settings.dirty_ticks <= 0 then
            Settings.dirty_ticks = nil
            local ok, err = pcall(function() save_settings(Settings.data) end)
            if not ok then report_error(err) end
        end
    end
    if App.remove_armed > 0 then
        App.remove_armed = App.remove_armed - 1
        if App.remove_armed <= 0 then App.disarm_remove() end
    end
    if Ticker.idle() and Ticker.timer and Ticker.running then
        pcall(function() Ticker.timer:Stop() end)
        Ticker.running = false
    end
end

function Settings.mark_dirty()
    Settings.dirty_ticks = 15
    Ticker.ensure()
end

function App.set_busy(is_busy)
    for _, element_id in ipairs(App.busy_controls) do
        local element = win and win:Find(element_id) or nil
        if element then pcall(function() element.Enabled = not is_busy end) end
    end
    local cancel = win and win:Find("CancelRun") or nil
    if cancel then
        pcall(function() cancel.Enabled = is_busy and true or false end)
        pcall(function() cancel.Hidden = not is_busy end)
        pcall(function() cancel.Text = tr("action.cancel") end)
    end
    pcall(function() win:RecalcLayout() end)
end

-- Shows or hides the playback/timeline frame-rate mismatch warning; returns its text.
function App.show_rate_warning(project, timeline)
    local text = playback_rate_warning(project, timeline)
    local label = win and win:Find("RateWarning") or nil
    if label then
        pcall(function() label.Text = text end)
        pcall(function() label.Hidden = text == "" end)
        pcall(function() win:RecalcLayout() end)
    end
    return text
end

function Pipeline.start()
    if Pipeline.state then error(tr("error.busy")) end
    -- The installer replaces the engine; after an update this panel still runs the old script.
    if Updater.install then error(tr("update.installing")) end
    if Updater.updated then error(tr("update.reopen", { version = Updater.updated })) end
    Pipeline.state = { phase = "scan", started = os.time(), placed = 0, failed = 0, comps = {} }
    set_last_error("")
    App.set_busy(true)
    set_progress(0, tr("status.scanning"))
    Ticker.ensure()
end

function Pipeline.cancel()
    local state = Pipeline.state
    if not state or state.cancel then return end
    state.cancel = true
    append_log(tr("log.cancel_requested"))
    set_progress(nil, tr("status.cancelling"))
end

function Pipeline.tick()
    local state = Pipeline.state
    if not state then return end
    local ok, err = pcall(function() Pipeline.step(state) end)
    if not ok then Pipeline.finish(state, err) end
end

function Pipeline.engine_line(state, line)
    local index, total = tostring(line):match("^%[(%d+)/(%d+)%]")
    if index then
        set_progress(5 + 55 * tonumber(index) / math.max(1, tonumber(total)), tr("status.engine_progress", { index = index, total = total }))
    end
    if line:match("^Warning: ") then
        append_log(tr("warning.engine", { details = line:sub(10) }))
    elseif not line:match("^Traceback") then
        append_log(line)
    end
end

function Pipeline.step(state)
    if state.cancel and state.phase ~= "place" then
        Pipeline.finish(state, nil)
        return
    end
    if state.phase == "scan" then
        Pipeline.scan(state)
    elseif state.phase == "engine" then
        local done = poll_runner_task(state.task, function(line) Pipeline.engine_line(state, line) end)
        if done then
            state.task = nil
            Pipeline.read_manifest(state)
            state.phase = "prepare"
        end
    elseif state.phase == "prepare" then
        Pipeline.prepare_place(state)
        state.phase = "place"
    elseif state.phase == "place" then
        if state.cancel then
            Pipeline.finish(state, nil)
            return
        end
        Pipeline.place_next(state)
    end
end

function Pipeline.scan(state)
    save_current_style()
    local _, project, timeline = current_project_and_timeline()
    local scan = collect_jobs(project, timeline, true)
    if #scan.jobs == 0 then
        local details = scan.summary ~= "" and tr("error.details", { details = scan.summary }) or ""
        local hint = scan.missing_path_count > 0 and tr("error.no_audio_path_hint") or ""
        error(tr("error.no_audio_clips", { tracks = table.concat(scan.audio_tracks, ","), hint = hint, details = details }))
    end
    append_log(tr("log.audio_found", { tracks = table.concat(scan.audio_tracks, ","), count = #scan.jobs }))
    append_log(tr("log.timeline_resolution", { width = scan.width, height = scan.height, fps = scan.fps }))
    local rate_warning = App.show_rate_warning(project, timeline)
    if rate_warning ~= "" then append_log(rate_warning) end
    Preview.frame = { scan.width, scan.height }
    local skin = Settings.data.active_skin
    local tracks = {}
    for _, job in ipairs(scan.jobs) do
        table.insert(tracks, {
            id = tostring(job.id),
            source_path = job.source_path,
            record_frame = job.record_frame,
            duration_frames = job.duration_frames,
            source_start_time = job.source_start_time,
        })
    end
    local payload = {
        version = JOBS_VERSION,
        skin = skin,
        design = Settings.data.styles[skin],
        timeline = { name = timeline:GetName(), width = scan.width, height = scan.height, fps = scan.fps },
        tracks = tracks,
    }
    local stem = tostring(os.time()) .. "_" .. tostring(math.random(100000, 999999))
    local work = tmp_dir()
    mkdir_p(work)
    local jobs_path = path_join(work, "jobs_" .. stem .. ".json")
    local manifest_path = path_join(work, "manifest_" .. stem .. ".json")
    write_file(jobs_path, json_encode(payload, ""))
    local engine = engine_path()
    if not file_exists(engine) then error(tr("error.engine_missing", { path = engine })) end
    append_log(tr("log.run_start", { count = #tracks, skin = Style.skin_label(skin), width = scan.width, height = scan.height, fps = scan.fps }))
    state.task = queue_runner_task({
        mode = "run",
        cwd = install_root(),
        command = {
            engine, "prepare",
            "--jobs", jobs_path,
            "--out", output_dir(),
            "--manifest", manifest_path,
            "--ffmpeg", ffmpeg_path(native_executable_name("ffmpeg"), FFMPEG_EXECUTABLE),
            "--ffprobe", ffmpeg_path(native_executable_name("ffprobe"), FFPROBE_EXECUTABLE),
        },
        env = { DAVINCI_TRACK_VISUALIZER_LOGO = Settings.data.fallback_logo_path or default_fallback_logo_path() },
        stdout_path = path_join(work, "engine_stdout.txt"),
        done_path = path_join(work, "engine_done.json"),
        timeout_seconds = 6 * 3600,
    }, "prepare")
    state.scan = scan
    state.jobs_path = jobs_path
    state.manifest_path = manifest_path
    state.timeline_id = timeline_identity(timeline)
    state.timeline_name = tostring(timeline:GetName() or "")
    state.phase = "engine"
    set_progress(5, tr("status.engine_start"))
end

function Pipeline.read_manifest(state)
    local text = read_file(state.manifest_path)
    if text == "" then error(tr("error.manifest_missing", { path = state.manifest_path })) end
    local ok, manifest = pcall(function() return json_decode(text) end)
    if not ok or type(manifest) ~= "table" or manifest == JSON_NULL then
        error(tr("error.manifest_invalid", { details = "JSON" }))
    end
    if manifest.schema ~= "tviz.manifest" or tonumber(manifest.version) ~= MANIFEST_VERSION then
        error(tr("error.manifest_invalid", { details = "version" }))
    end
    local carrier = manifest.carrier
    if type(carrier) ~= "table" or type(carrier.path) ~= "string" or not file_exists(carrier.path) then
        error(tr("error.manifest_invalid", { details = "carrier" }))
    end
    local jobs_by_id = {}
    for _, job in ipairs(state.scan.jobs) do jobs_by_id[tostring(job.id)] = job end
    local entries = {}
    for _, track in ipairs(type(manifest.tracks) == "table" and manifest.tracks or {}) do
        local job = jobs_by_id[tostring(track.id)]
        if not job or tonumber(track.record_frame) ~= job.record_frame or tonumber(track.duration_frames) ~= job.duration_frames
            or type(track.comp_path) ~= "string" or not file_exists(track.comp_path) then
            error(tr("error.manifest_invalid", { details = tostring(track.id) }))
        end
        table.insert(entries, {
            id = tostring(track.id),
            record_frame = job.record_frame,
            duration_frames = job.duration_frames,
            comp_path = track.comp_path,
            name = job.timeline_item_name or track.title or "",
        })
        table.insert(state.comps, track.comp_path)
    end
    local failed = type(manifest.failed) == "table" and manifest.failed ~= JSON_NULL and manifest.failed or {}
    for _, failure in ipairs(failed) do
        local job = jobs_by_id[tostring(failure.id)]
        append_log(tr("warning.player_failed", { name = job and job.timeline_item_name or tostring(failure.id), details = tostring(failure.error or "") }))
    end
    state.failed = state.failed + #failed
    if #entries == 0 or #entries + #failed ~= #state.scan.jobs then error(tr("error.manifest_invalid", { details = "tracks" })) end
    state.carrier_path = carrier.path
    state.entries = entries
    state.index = 1
    remove_file(state.jobs_path)
    remove_file(state.manifest_path)
end

function Pipeline.require_same_timeline(state)
    local _, project, timeline = current_project_and_timeline()
    if timeline_identity(timeline) ~= state.timeline_id then
        error(tr("error.timeline_changed", { name = state.timeline_name }))
    end
    return project, timeline
end

function Pipeline.prepare_place(state)
    local project, timeline = Pipeline.require_same_timeline(state)
    local media_pool = project:GetMediaPool()
    local track = state.scan.video_track
    ensure_video_track(timeline, track)
    state.carrier = Place.carrier_item(media_pool, state.carrier_path)
    -- Fusion Loaders register their PNGs in the current Media Pool folder; keep them in our bin.
    pcall(function() state.previous_folder = media_pool:GetCurrentFolder() end)
    state.media_pool = media_pool
    pcall(function() media_pool:SetCurrentFolder(Place.media_bin(media_pool)) end)
    append_log(tr("log.carrier_ready", { name = Place.item_name(state.carrier) }))
    -- Check foreign clips first so a conflict never costs the user their existing players.
    Place.check_conflicts(timeline, track, state.scan.jobs, state.scan.fps)
    local removed = Place.remove_previous(timeline, track, state.scan.jobs, not state.scan.partial)
    if removed > 0 then append_log(tr("log.players_removed", { count = removed, track = track })) end
    set_progress(60, tr("status.placing", { index = 0, total = #state.entries }))
end

function Pipeline.place_next(state)
    local project, timeline = Pipeline.require_same_timeline(state)
    local batch = {}
    while #batch < PLACE_BATCH and state.index <= #state.entries do
        table.insert(batch, state.entries[state.index])
        state.index = state.index + 1
    end
    if #batch > 0 then
        local placed, failures, stray = Place.place_batch(project:GetMediaPool(), state.carrier, state.scan.video_track, batch)
        if #stray > 0 then pcall(function() timeline:DeleteClips(stray, false) end) end
        state.placed = state.placed + #placed
        state.failed = state.failed + #failures
        for _, failure in ipairs(failures) do
            append_log(tr("warning.player_failed", { name = failure.entry.name, details = failure.details }))
        end
        local done = state.index - 1
        set_progress(60 + 40 * done / math.max(1, #state.entries), tr("status.placing", { index = done, total = #state.entries }))
    end
    if state.index > #state.entries then Pipeline.finish(state, nil) end
end

function Pipeline.finish(state, err)
    Pipeline.state = nil
    if state.media_pool and state.previous_folder then
        pcall(function() state.media_pool:SetCurrentFolder(state.previous_folder) end)
    end
    for _, comp_path in ipairs(state.comps or {}) do remove_file(comp_path) end
    App.set_busy(false)
    if err then
        report_error(err)
        return
    end
    local total = state.entries and #state.entries or (state.scan and #state.scan.jobs or 0)
    local track = state.scan and state.scan.video_track or 0
    if state.cancel then
        set_progress(0, tr("status.cancelled", { placed = state.placed, total = total }))
    elseif state.failed > 0 then
        set_progress(100, tr("status.done_with_errors", { count = state.placed, failed = state.failed }))
    else
        set_progress(100, tr("status.done", { count = state.placed, track = track }))
    end
    append_log(tr("log.run_done", { count = state.placed, seconds = os.time() - (state.started or os.time()) }))
end

-- ------------------------------------------------------------------------------------------
-- Style preview rendered by the engine

function Preview.request(delay_ticks)
    Preview.requested = true
    Preview.countdown = delay_ticks or 6
    Ticker.ensure()
end

function Preview.set_label(text)
    for _, element_id in ipairs({ "PreviewStatusCreate", "PreviewStatusStyle" }) do
        local label = win and win:Find(element_id) or nil
        if label then label.Text = text end
    end
end

-- Create shows the whole frame (placement); Style shows a close-up of the player.
function Preview.show(path, close_up)
    Preview.path = path
    Preview.close_up = close_up or path
    local images = { PreviewCreate = path, PreviewStyle = Preview.close_up }
    for element_id, file in pairs(images) do
        local button = win and win:Find(element_id) or nil
        if button then pcall(function() button.Icon = ui:Icon({ File = file }) end) end
    end
    Preview.set_label(tr("preview.idle"))
end

function Preview.launch()
    local engine = engine_path()
    if not file_exists(engine) then error(tr("error.engine_missing", { path = engine })) end
    local work = ascii_work_dir()
    Preview.serial = Preview.serial + 1
    local stem = tostring(os.time()) .. "_" .. tostring(Preview.serial)
    local skin = Settings.data.active_skin
    local design_path = path_join(work, "preview_design.json")
    write_file(design_path, json_encode({ skin = skin, design = Settings.data.styles[skin] }, ""))
    local target = path_join(work, "preview_" .. stem .. ".png")
    local close_up = path_join(work, "preview_" .. stem .. "_close.png")
    Preview.task = queue_runner_task({
        mode = "run",
        cwd = install_root(),
        command = {
            engine, "preview-style",
            "--out", target,
            "--design-json", design_path,
            "--skin", skin,
            "--frame-width", tostring(Preview.frame[1]),
            "--frame-height", tostring(Preview.frame[2]),
            "--preview-width", "720",
            "--title", tr("preview.sample_title"),
            "--artist", tr("preview.sample_artist"),
            "--progress", "0.42",
            "--crop-out", close_up,
        },
        env = { DAVINCI_TRACK_VISUALIZER_LOGO = Settings.data.fallback_logo_path or default_fallback_logo_path() },
        stdout_path = path_join(work, "preview_stdout.txt"),
        done_path = path_join(work, "preview_done.json"),
        timeout_seconds = 120,
    }, "preview")
    Preview.target = target
    Preview.target_close = close_up
    Preview.set_label(tr("preview.rendering"))
end

function Preview.tick()
    if Preview.task then
        local ok, result = pcall(function() return poll_runner_task(Preview.task, nil) end)
        if not ok then
            Preview.task = nil
            Preview.set_label(tr("preview.failed", { details = short_text(clean_error(result), 160) }))
        elseif result then
            Preview.task = nil
            if file_exists(Preview.target) then
                local previous, previous_close = Preview.path, Preview.close_up
                Preview.show(Preview.target, file_exists(Preview.target_close) and Preview.target_close or nil)
                if previous and previous ~= Preview.path then remove_file(previous) end
                if previous_close and previous_close ~= previous and previous_close ~= Preview.close_up then remove_file(previous_close) end
            end
        end
        return
    end
    if Preview.requested then
        if Preview.countdown > 0 then
            Preview.countdown = Preview.countdown - 1
            return
        end
        Preview.requested = false
        local ok, err = pcall(Preview.launch)
        if not ok then
            Preview.task = nil
            Preview.set_label(tr("preview.failed", { details = short_text(clean_error(err), 160) }))
        end
    end
end


-- ------------------------------------------------------------------------------------------
-- Self-update (Windows installs made by the installer)
--
-- The engine checks the signed update.json of the latest GitHub Release and downloads the
-- installer, verifying the Ed25519 signature and the installer's SHA-256 (updater.py). The panel
-- then runs that installer without a window while nothing else uses the engine, and reads its
-- result file. The installer keeps settings, presets, logs and outputs.

local UPDATE_CHECK_INTERVAL = 6 * 3600
local UPDATE_INSTALL_TIMEOUT = 600

function Updater.busy()
    return Updater.task ~= nil or Updater.pending ~= nil or Updater.install ~= nil
end

function Updater.read_json(path)
    local text = read_file(path)
    if text == "" then return nil end
    local ok, data = pcall(function() return json_decode(text) end)
    if ok and type(data) == "table" and data ~= JSON_NULL then return data end
    return nil
end

function Updater.installed_version()
    local data = Updater.read_json(path_join(install_root(), "manifest.json"))
    if not data or data.product ~= "DavinciTrackVisualizer" or type(data.version) ~= "string" then return nil end
    return data.version
end

function Updater.set_status(text)
    local label = win and win:Find("UpdateStatus") or nil
    if label then pcall(function() label.Text = text end) end
end

function Updater.show_version()
    local version = PLATFORM.windows and Updater.installed_version() or nil
    local label = win and win:Find("UpdateVersion") or nil
    if label then
        pcall(function()
            label.Text = version and tr("update.version", { version = version }) or tr("update.dev_install")
        end)
    end
    for _, id in ipairs({ "AutoUpdate", "CheckUpdates" }) do
        local element = win and win:Find(id) or nil
        if element then pcall(function() element.Enabled = version ~= nil end) end
    end
end

function Updater.on_line(line)
    local percent = line:match("^TVIZ_UPDATE_PROGRESS (%d+)")
    if percent then
        Updater.set_status(tr("update.downloading", { percent = percent }))
        return
    end
    local payload = line:match("^TVIZ_UPDATE (.+)$")
    if payload then
        local ok, data = pcall(function() return json_decode(payload) end)
        if ok and type(data) == "table" and data ~= JSON_NULL then Updater.result = data end
    end
end

function Updater.check(manual)
    if Updater.updated then
        if manual then Updater.set_status(tr("update.installed", { version = Updater.updated })) end
        return
    end
    if Updater.busy() then return end
    if not PLATFORM.windows or not Updater.installed_version() then
        if manual then Updater.set_status(tr("update.dev_install")) end
        return
    end
    local engine = engine_path()
    if not file_exists(engine) then error(tr("error.engine_missing", { path = engine })) end
    local command = { engine, "update", "--install-root", install_root(), "--download" }
    if Settings.data.update_source_dir then
        command[#command + 1] = "--source-dir"
        command[#command + 1] = Settings.data.update_source_dir
    end
    Updater.result = nil
    Updater.task = queue_runner_task({
        mode = "run",
        cwd = install_root(),
        command = command,
        stdout_path = path_join(tmp_dir(), "update_stdout.txt"),
        done_path = path_join(tmp_dir(), "update_done.json"),
        timeout_seconds = 1800,
    }, "update")
    Updater.set_status(tr("update.checking"))
    Ticker.ensure()
end

function Updater.auto_check()
    if Settings.data.auto_update == false then return end
    if os.time() - (tonumber(Settings.data.update_checked_at) or 0) < UPDATE_CHECK_INTERVAL then return end
    local ok, err = pcall(function() Updater.check(false) end)
    if not ok then append_log(tr("update.failed", { details = clean_error(err) })) end
end

function Updater.start_install()
    local pending = Updater.pending
    Updater.pending = nil
    local installer = tostring(pending.installer or "")
    if installer == "" or not file_exists(installer) then error("Downloaded installer is missing: " .. installer) end
    local result_path = path_join(tmp_dir(), "update_result.json")
    remove_file(result_path)
    local arguments = {
        "--no-pause",
        "--language", active_language,
        "--install-root", install_root(),
        "--result-file", result_path,
    }
    local state = Updater.read_json(path_join(install_root(), "install-state.json"))
    if state and type(state.script_directory) == "string" then
        arguments[#arguments + 1] = "--resolve-script-dir"
        arguments[#arguments + 1] = state.script_directory
    end
    local launched, launch_error = launch_process_native(installer, arguments)
    if not launched then error(launch_error) end
    Updater.install = { result_path = result_path, version = tostring(pending.latest), started = os.time(), installer = installer }
    App.set_busy(true)
    Updater.set_status(tr("update.installing"))
    set_progress(nil, tr("update.installing"))
    append_log(tr("update.installing_version", { version = tostring(pending.latest) }))
end

function Updater.finish_install(succeeded, details)
    local install = Updater.install or {}
    Updater.install = nil
    App.set_busy(false)
    if succeeded then
        -- A failed install keeps the verified download for the next attempt.
        if install.installer then remove_file(install.installer) end
        Updater.updated = tostring(install.version or "")
        local notice = tr("update.installed", { version = Updater.updated })
        Updater.set_status(notice)
        append_log(notice)
        set_progress(100, notice)
    else
        local message = tr("update.failed", { details = details or "" })
        Updater.set_status(message)
        append_log(message)
        set_progress(0, message)
    end
    Updater.show_version()
end

function Updater.tick()
    if Updater.task then
        local ok, done = pcall(function() return poll_runner_task(Updater.task, Updater.on_line) end)
        if not ok then
            Updater.task = nil
            local details = clean_error(done)
            append_log(tr("update.failed", { details = details }))
            Updater.set_status(tr("update.failed", { details = short_text(details, 160) }))
            return
        end
        if not done then return end
        Updater.task = nil
        Settings.data.update_checked_at = os.time()
        Settings.mark_dirty()
        local result = Updater.result or {}
        if result.status == "ready" then
            Updater.pending = result
            Updater.set_status(tr("update.ready", { version = tostring(result.latest) }))
        elseif result.status == "up_to_date" then
            Updater.set_status(tr("update.up_to_date", { version = tostring(result.current) }))
        else
            Updater.set_status(tr("update.dev_install"))
        end
        return
    end
    if Updater.pending then
        -- The installer stops the engine, so wait until no run or preview is using it.
        if Pipeline.state or Preview.task then return end
        local ok, err = pcall(Updater.start_install)
        if not ok then Updater.finish_install(false, clean_error(err)) end
        return
    end
    local install = Updater.install
    if install then
        local result = Updater.read_json(install.result_path)
        if not result then
            if os.time() - install.started > UPDATE_INSTALL_TIMEOUT then
                Updater.finish_install(false, tr("update.install_timeout"))
            end
            return
        end
        remove_file(install.result_path)
        if type(result.version) == "string" then install.version = result.version end
        Updater.finish_install(result.ok == true, type(result.error) == "string" and result.error or nil)
    end
end


-- ------------------------------------------------------------------------------------------
-- Style editor: settings <-> controls

local Editor = { suppress = false }

Editor.colors = {
    { id = "PanelColor", key = "panel_color", label = "field.panel", alpha = "PanelAlpha", alpha_key = "panel_alpha" },
    { id = "BorderColor", key = "border_color", label = "field.border", alpha = "BorderAlpha", alpha_key = "border_alpha" },
    { id = "PrimaryTextColor", key = "primary_text_color", label = "field.primary_text" },
    { id = "SecondaryTextColor", key = "secondary_text_color", label = "field.secondary_text" },
    { id = "AccentColor", key = "accent_color", label = "field.accent" },
    { id = "TrackColor", key = "track_color", label = "field.track" },
}

Editor.toggles = {
    { id = "ShowCover", key = "show_cover", feature = "cover", label = "field.cover" },
    { id = "ShowArtist", key = "show_artist", feature = "artist", label = "field.artist" },
    { id = "ShowTitle", key = "show_title", feature = "title", label = "field.title_toggle" },
    { id = "ShowBrand", key = "show_brand", feature = "brand", label = "field.brand" },
    { id = "ShowTime", key = "show_time", feature = "time", label = "field.time" },
    { id = "ShowProgress", key = "show_progress", feature = "progress", label = "field.progress" },
    { id = "ShowKnob", key = "show_knob", feature = "knob", label = "field.knob" },
    -- Skins with a progress style show one indicator, so their separate waveform toggle is off.
    { id = "ShowBars", key = "show_bars", feature = "bars", label = "field.bars", exclude = "progress_style" },
    { id = "GlassEnabled", key = "glass_enabled", feature = "glass", label = "field.glass" },
    { id = "UppercaseArtist", key = "uppercase_artist", feature = "artist", label = "field.uppercase_artist" },
    { id = "ScrollTitle", key = "scroll_title", feature = "title", label = "field.scroll_title" },
}

Editor.numbers = {
    { id = "Scale", key = "scale" },
    { id = "MarginX", key = "margin_x" },
    { id = "MarginY", key = "margin_y" },
    { id = "BarCount", key = "bar_count", feature = "bars" },
    { id = "PanelAlpha", key = "panel_alpha" },
    { id = "BorderAlpha", key = "border_alpha" },
    { id = "GlassStrength", key = "glass_strength", feature = "glass" },
    { id = "CornerRadius", key = "corner_radius" },
    { id = "TitleSize", key = "title_size" },
    { id = "ArtistSize", key = "artist_size" },
    { id = "MetaSize", key = "meta_size", feature = "time" },
}

Editor.fonts = {
    { id = "TitleFontFamily", key = "title_font_family" },
    { id = "ArtistFontFamily", key = "artist_font_family" },
    { id = "TimeFontFamily", key = "time_font_family", feature = "time" },
}

Editor.enums = {
    { id = "Anchor", key = "anchor", prefix = "anchor." },
    { id = "TimeMode", key = "time_mode", prefix = "time_mode.", feature = "time" },
    { id = "ProgressBasis", key = "progress_basis", prefix = "progress_basis." },
    { id = "ProgressStyle", key = "progress_style", prefix = "progress_style.", feature = "progress_style" },
}

function Editor.combo_index(element_id)
    local element = win:Find(element_id)
    local index = nil
    if element then pcall(function() index = tonumber(element.CurrentIndex) end) end
    return index or 0
end

function Editor.set_combo(element_id, index)
    local element = win:Find(element_id)
    if element then pcall(function() element.CurrentIndex = index end) end
end

function Editor.fill_combo(element_id, labels, index)
    local element = win:Find(element_id)
    if not element then return end
    pcall(function() element:Clear() end)
    pcall(function() element:AddItems(labels) end)
    pcall(function() element.CurrentIndex = index or 0 end)
end

function Editor.enum_values(key)
    return SKIN_CATALOG.enums[key] or {}
end

function Editor.index_of(list, value)
    for index, item in ipairs(list) do
        if item == value then return index - 1 end
    end
    return 0
end

function Editor.read()
    local skin = Settings.data.active_skin
    local design = copy_table(Settings.data.styles[skin] or Style.defaults(skin))
    for _, color in ipairs(Editor.colors) do design[color.key] = normalize_hex(text_field(color.id, design[color.key]), design[color.key]) end
    for _, toggle in ipairs(Editor.toggles) do design[toggle.key] = check_field(toggle.id, design[toggle.key]) end
    for _, number in ipairs(Editor.numbers) do
        local range = SKIN_CATALOG.int_ranges[number.key] or { 0, 9999 }
        design[number.key] = int_field(number.id, design[number.key], range[1], range[2])
    end
    for _, font in ipairs(Editor.fonts) do
        local value = trim(text_field(font.id, design[font.key]))
        if value ~= "" then design[font.key] = value end
    end
    for _, enum in ipairs(Editor.enums) do
        local values = Editor.enum_values(enum.key)
        design[enum.key] = values[Editor.combo_index(enum.id) + 1] or design[enum.key]
    end
    design.time_bold = check_field("TimeBold", design.time_bold)
    design.brand_text = trim(text_field("BrandText", ""))
    return Style.sanitize(skin, design)
end

function Editor.apply(design)
    Editor.suppress = true
    for _, color in ipairs(Editor.colors) do set_text(color.id, design[color.key]) end
    for _, toggle in ipairs(Editor.toggles) do set_checked(toggle.id, design[toggle.key]) end
    for _, number in ipairs(Editor.numbers) do set_number(number.id, design[number.key]) end
    for _, font in ipairs(Editor.fonts) do set_text(font.id, design[font.key]) end
    for _, enum in ipairs(Editor.enums) do Editor.set_combo(enum.id, Editor.index_of(Editor.enum_values(enum.key), design[enum.key])) end
    set_checked("TimeBold", design.time_bold)
    set_text("BrandText", design.brand_text)
    Editor.suppress = false
    Editor.update_capabilities()
    Editor.update_swatches(design)
end

function Editor.update_swatches(design)
    for _, color in ipairs(Editor.colors) do
        local swatch = win and win:Find("Pick" .. color.id) or nil
        if swatch then pcall(function() swatch.StyleSheet = App.swatch_style(design[color.key]) end) end
    end
end

-- The Preset selector on the main page shows "Custom settings" as soon as the look is edited.
function Editor.reset_quick_preset()
    Editor.active_preset = nil
    local was = Editor.suppress
    Editor.suppress = true
    Editor.set_combo("QuickPreset", 0)
    Editor.suppress = was
    Editor.update_preset_summary()
end

function Editor.update_preset_summary()
    local label = win and win:Find("PresetSummary") or nil
    local row = win and win:Find("PresetSummaryRow") or nil
    if not label or not row then return end
    local text = Editor.active_preset and tr("preset.summary", { name = Editor.active_preset }) or ""
    pcall(function() label.Text = text end)
    pcall(function() row.Hidden = text == "" end)
    pcall(function() win:RecalcLayout() end)
end

function Editor.update_capabilities()
    local skin = Settings.data.active_skin
    local function enable(element_id, enabled)
        local element = win:Find(element_id)
        if element then pcall(function() element.Enabled = enabled and true or false end) end
    end
    for _, toggle in ipairs(Editor.toggles) do
        enable(toggle.id, Style.supports(skin, toggle.feature) and not (toggle.exclude and Style.supports(skin, toggle.exclude)))
    end
    for _, number in ipairs(Editor.numbers) do enable(number.id, number.feature == nil or Style.supports(skin, number.feature)) end
    for _, font in ipairs(Editor.fonts) do enable(font.id, font.feature == nil or Style.supports(skin, font.feature)) end
    for _, enum in ipairs(Editor.enums) do enable(enum.id, enum.feature == nil or Style.supports(skin, enum.feature)) end
    enable("TimeBold", Style.supports(skin, "time"))
    enable("BrandText", Style.supports(skin, "brand"))
end

function Editor.palette_names()
    local names = { "Custom" }
    for _, name in ipairs(SKIN_CATALOG.palette_order) do table.insert(names, name) end
    for _, palette in ipairs(Settings.data.palettes) do table.insert(names, palette.name) end
    return names
end

function Editor.palette_colors(name)
    local builtin = Style.builtin_palette(name)
    if builtin then return builtin end
    for _, palette in ipairs(Settings.data.palettes) do
        if palette.name == name then return palette.colors end
    end
    return nil
end

function Editor.detect_palette(design)
    for _, name in ipairs(Editor.palette_names()) do
        local colors = Editor.palette_colors(name)
        if colors then
            local matches = true
            for _, key in ipairs(SKIN_CATALOG.palette_keys) do
                if design[key] ~= colors[key] then matches = false break end
            end
            if matches then return name end
        end
    end
    return "Custom"
end

function Editor.refresh_palette_combos()
    local names = Editor.palette_names()
    local labels = {}
    for _, name in ipairs(names) do table.insert(labels, Style.palette_label(name)) end
    local skin = Settings.data.active_skin
    local current = Editor.detect_palette(Settings.data.styles[skin])
    Settings.data.palette_names[skin] = current
    local was = Editor.suppress
    Editor.suppress = true
    Editor.fill_combo("PaletteSelector", labels, Editor.index_of(names, current))
    local library = {}
    for index = 2, #labels do table.insert(library, labels[index]) end
    Editor.fill_combo("PaletteLibrary", library, math.max(0, Editor.index_of(names, current) - 1))
    Editor.suppress = was
    local title = win:Find("StyleTitle")
    if title then
        title.Text = tr("field.active_style", { skin = Style.skin_label(skin), palette = Style.palette_label(current) })
    end
end

function Editor.changed()
    if Editor.suppress or not Settings.data then return end
    local skin = Settings.data.active_skin
    local design = Editor.read()
    if json_encode(design, "") == json_encode(Settings.data.styles[skin] or {}, "") then return end
    Settings.data.styles[skin] = design
    Editor.update_capabilities()
    Editor.update_swatches(Settings.data.styles[skin])
    Editor.refresh_palette_combos()
    Editor.reset_quick_preset()
    Settings.mark_dirty()
    Preview.request()
end

function Editor.capture_timeline()
    local timeline = Settings.data.timeline
    timeline.audio_tracks = text_field("AudioTracks", "1")
    timeline.video_track = int_field("VideoTrack", 2, 1, 64)
    timeline.switch_mode = switch_mode_from_ui()
    timeline.scope = text_field("UpdateScope", "")
    Settings.data.fallback_logo_path = trim(text_field("FallbackLogoPath", default_fallback_logo_path()))
end

save_current_style = function()
    if not Settings.data or not win then return end
    if not Editor.suppress then
        Settings.data.styles[Settings.data.active_skin] = Editor.read()
    end
    Editor.capture_timeline()
    Settings.dirty_ticks = nil
    save_settings(Settings.data)
end

function Editor.select_skin(skin)
    if not Style.is_skin(skin) then return end
    Settings.data.active_skin = skin
    Editor.suppress = true
    Editor.set_combo("SkinSelector", Editor.index_of(SKIN_CATALOG.skins, skin))
    Editor.suppress = false
    Editor.apply(Settings.data.styles[skin])
    Editor.refresh_palette_combos()
    Settings.mark_dirty()
    Preview.request(1)
end

function Editor.apply_palette(name)
    local colors = Editor.palette_colors(name)
    if not colors then return end
    local skin = Settings.data.active_skin
    local design = Editor.read()
    for _, key in ipairs(SKIN_CATALOG.palette_keys) do design[key] = colors[key] end
    Settings.data.styles[skin] = Style.sanitize(skin, design)
    Editor.apply(Settings.data.styles[skin])
    Editor.refresh_palette_combos()
    Settings.mark_dirty()
    Preview.request(1)
    append_log(tr("log.palette_applied", { palette = Style.palette_label(name), skin = Style.skin_label(skin) }))
end

-- ------------------------------------------------------------------------------------------
-- Preset library

local Presets = {}

function Presets.unique_name(list, name)
    local candidate = name
    local counter = 2
    local function taken(value)
        for _, item in ipairs(list) do
            if item.name == value then return true end
        end
        return false
    end
    while taken(candidate) do
        candidate = name .. " (" .. tostring(counter) .. ")"
        counter = counter + 1
    end
    return candidate
end

function Presets.refresh(selected_name)
    local labels = {}
    local index = 0
    for position, preset in ipairs(Settings.data.presets) do
        table.insert(labels, preset.name .. "  ·  " .. Style.skin_label(preset.skin))
        if preset.name == selected_name then index = position - 1 end
    end
    if #labels == 0 then labels = { tr("presets.empty") } end
    local was = Editor.suppress
    Editor.suppress = true
    Editor.fill_combo("PresetList", labels, index)
    local quick = { tr("preset.current_style") }
    local quick_index = 0
    for position, preset in ipairs(Settings.data.presets) do
        table.insert(quick, tr("preset.option", { name = preset.name, skin = Style.skin_label(preset.skin) }))
        if preset.name == Editor.active_preset then quick_index = position end
    end
    Editor.fill_combo("QuickPreset", quick, quick_index)
    Editor.suppress = was
end

function Presets.selected()
    if #Settings.data.presets == 0 then return nil end
    return Settings.data.presets[Editor.combo_index("PresetList") + 1]
end

function Presets.apply(preset)
    if not preset then error(tr("error.preset_not_selected")) end
    Settings.data.styles[preset.skin] = Style.sanitize(preset.skin, preset.design)
    Editor.select_skin(preset.skin)
    Editor.active_preset = preset.name
    Presets.refresh(preset.name)
    Editor.update_preset_summary()
    append_log(tr("log.preset_applied", { name = preset.name }))
end

function Presets.save()
    local name = trim(text_field("PresetName", ""))
    if name == "" then error(tr("error.preset_name_required")) end
    local skin = Settings.data.active_skin
    Settings.data.styles[skin] = Editor.read()
    local existing = nil
    for _, preset in ipairs(Settings.data.presets) do
        if preset.name == name then existing = preset end
    end
    if existing then
        existing.skin = skin
        existing.design = copy_table(Settings.data.styles[skin])
    else
        table.insert(Settings.data.presets, { name = string.sub(name, 1, 60), skin = skin, design = copy_table(Settings.data.styles[skin]) })
    end
    save_current_style()
    Editor.active_preset = name
    Presets.refresh(name)
    Editor.update_preset_summary()
    append_log(tr("log.preset_saved", { name = name }))
end

function Presets.rename()
    local preset = Presets.selected()
    if not preset then error(tr("error.preset_not_selected")) end
    local name = trim(text_field("PresetName", ""))
    if name == "" then error(tr("error.preset_name_required")) end
    local old = preset.name
    preset.name = Presets.unique_name(Settings.data.presets, string.sub(name, 1, 60))
    save_current_style()
    Presets.refresh(preset.name)
    append_log(tr("log.preset_renamed", { old = old, name = preset.name }))
end

function Presets.delete()
    local preset = Presets.selected()
    if not preset then error(tr("error.preset_not_selected")) end
    for index, item in ipairs(Settings.data.presets) do
        if item == preset then table.remove(Settings.data.presets, index) break end
    end
    save_current_style()
    Presets.refresh()
    append_log(tr("log.preset_deleted", { name = preset.name }))
end

function Presets.folder()
    local folder = path_join(install_root(), "presets")
    mkdir_p(folder)
    return folder
end

function Presets.export()
    local preset = Presets.selected()
    if not preset then error(tr("error.preset_not_selected")) end
    local target = path_join(Presets.folder(), safe_stem(preset.name) .. ".tviz-preset.json")
    write_file(target, json_encode({ format = "tviz.preset", version = 1, name = preset.name, skin = preset.skin, design = preset.design }, "  "))
    append_log(tr("log.preset_exported", { path = target }))
    run_runner_config({ mode = "open", path = Presets.folder() }, "open")
end

function Presets.import()
    local selected = fusion:RequestFile(Presets.folder(), "*.json", {})
    local path = Presets.single_file(selected)
    if path == "" then return end
    local ok, data = pcall(function() return json_decode(read_file(path)) end)
    if not ok or type(data) ~= "table" or data == JSON_NULL then error(tr("error.import_invalid", { path = path })) end
    if data.format == "tviz.preset" and Style.is_skin(data.skin) then
        local name = Presets.unique_name(Settings.data.presets, string.sub(trim(tostring(data.name or "Preset")), 1, 60))
        table.insert(Settings.data.presets, { name = name, skin = data.skin, design = Style.sanitize(data.skin, data.design) })
        save_current_style()
        Presets.refresh(name)
        append_log(tr("log.preset_imported", { name = name }))
    elseif data.format == "tviz.palette" then
        local name = Presets.unique_name(Settings.data.palettes, string.sub(trim(tostring(data.name or "Palette")), 1, 60))
        if Style.builtin_palette(name) or name == "Custom" then name = name .. " (2)" end
        table.insert(Settings.data.palettes, { name = name, colors = Settings.sanitize_palette_colors(data.colors) })
        save_current_style()
        Editor.refresh_palette_combos()
        append_log(tr("log.preset_imported", { name = name }))
    else
        error(tr("error.import_invalid", { path = path }))
    end
end

function Presets.save_palette()
    local name = trim(text_field("PaletteName", ""))
    if name == "" then error(tr("error.preset_name_required")) end
    if Style.builtin_palette(name) or name == "Custom" then error(tr("error.palette_builtin")) end
    local design = Editor.read()
    local colors = {}
    for _, key in ipairs(SKIN_CATALOG.palette_keys) do colors[key] = design[key] end
    local existing = nil
    for _, palette in ipairs(Settings.data.palettes) do
        if palette.name == name then existing = palette end
    end
    if existing then existing.colors = colors else table.insert(Settings.data.palettes, { name = string.sub(name, 1, 60), colors = colors }) end
    save_current_style()
    Editor.refresh_palette_combos()
    append_log(tr("log.palette_saved", { name = name }))
    local target = path_join(Presets.folder(), safe_stem(name) .. ".tviz-palette.json")
    pcall(function() write_file(target, json_encode({ format = "tviz.palette", version = 1, name = name, colors = colors }, "  ")) end)
end

function Presets.library_selected()
    local names = Editor.palette_names()
    return names[Editor.combo_index("PaletteLibrary") + 2]
end

function Presets.delete_palette()
    local name = Presets.library_selected()
    if not name then return end
    if Style.builtin_palette(name) then error(tr("error.palette_builtin")) end
    for index, palette in ipairs(Settings.data.palettes) do
        if palette.name == name then table.remove(Settings.data.palettes, index) break end
    end
    save_current_style()
    Editor.refresh_palette_combos()
    append_log(tr("log.palette_deleted", { name = name }))
end

function Presets.single_file(result)
    if result == nil then return "" end
    if type(result) == "string" then return (trim(result):gsub('^"', ''):gsub('"$', '')) end
    if type(result) == "table" then
        local base = tostring(result.Path or "")
        for key, value in pairs(result) do
            if key ~= "Path" and value and tostring(value) ~= "" then
                if base ~= "" then return path_join(base, tostring(value)) end
                return tostring(value)
            end
        end
    end
    return (trim(tostring(result)):gsub('^"', ''):gsub('"$', ''))
end

-- ------------------------------------------------------------------------------------------
-- Actions

local HANDLERS = {}

function HANDLERS.guard(action)
    local ok, err = pcall(action)
    if not ok then report_error(err) end
end

function HANDLERS.pick_color_safely(field_id, fallback)
    if not PLATFORM.windows then
        local notice = tr("notice.color_manual")
        append_log(notice)
        set_progress(0, notice)
        return
    end
    local swatches = {}
    local design = Settings.data.styles[Settings.data.active_skin] or {}
    for _, color in ipairs(Editor.colors) do
        local value = normalize_hex(design[color.key], "")
        if value ~= "" then
            local r, g, b = hex_to_rgb(value)
            swatches[#swatches + 1] = { r, g, b }
        end
    end
    local ok, err = pcall(function() pick_windows_color(field_id, fallback, swatches) end)
    if not ok then
        report_error(err)
        local notice = tr("notice.color_manual")
        append_log(notice)
        set_progress(0, notice)
        return
    end
    Editor.changed()
end

function HANDLERS.on_create()
    HANDLERS.guard(function() Pipeline.start() end)
end

function HANDLERS.on_list_clips()
    HANDLERS.guard(function()
        local _, project, timeline = current_project_and_timeline()
        local scan = collect_jobs(project, timeline, false)
        append_log(tr("log.clips_listed", { tracks = table.concat(scan.audio_tracks, ","), count = #scan.jobs }))
        append_log(tr("log.scope_help"))
        App.go_to_page(3)
    end)
end

function App.disarm_remove()
    App.remove_armed = 0
    local button = win and win:Find("RemovePlayers") or nil
    if button then button.Text = tr("action.remove_players") end
end

function HANDLERS.on_remove_players()
    HANDLERS.guard(function()
        if Pipeline.state then error(tr("error.busy")) end
        if App.remove_armed <= 0 then
            App.remove_armed = 40
            local button = win:Find("RemovePlayers")
            if button then button.Text = tr("action.remove_confirm") end
            Ticker.ensure()
            return
        end
        App.disarm_remove()
        local _, _, timeline = current_project_and_timeline()
        local track = int_field("VideoTrack", 2, 1, 64)
        local removed = Place.remove_previous(timeline, track, {}, true)
        set_progress(100, tr("status.removed", { count = removed, track = track }))
        append_log(tr("status.removed", { count = removed, track = track }))
    end)
end

function HANDLERS.on_cleanup_legacy()
    HANDLERS.guard(function()
        local _, project, timeline = current_project_and_timeline()
        local in_use = Place.legacy_players(timeline)
        if in_use > 0 then
            append_log(tr("log.legacy_in_use", { count = in_use }))
            return
        end
        local helpers = Place.legacy_helpers(project, timeline)
        if #helpers == 0 then
            append_log(tr("log.legacy_none"))
            return
        end
        local ok, result = pcall(function() return project:GetMediaPool():DeleteTimelines(helpers) end)
        if not ok or result == false then error("DeleteTimelines: " .. tostring(result)) end
        append_log(tr("log.legacy_removed", { count = #helpers }))
    end)
end

function HANDLERS.on_reset_style()
    HANDLERS.guard(function()
        local skin = Settings.data.active_skin
        Settings.data.styles[skin] = Style.defaults(skin)
        Editor.apply(Settings.data.styles[skin])
        Editor.refresh_palette_combos()
        Settings.mark_dirty()
        Preview.request(1)
        append_log(tr("log.style_reset", { skin = Style.skin_label(skin) }))
    end)
end

function HANDLERS.on_open_preview()
    HANDLERS.guard(function()
        if Preview.path and file_exists(Preview.path) then
            run_runner_config({ mode = "open", path = Preview.path }, "open")
        end
    end)
end

function HANDLERS.on_open_log()
    HANDLERS.guard(function()
        if not file_exists(log_path()) then write_file(log_path(), "") end
        run_runner_config({ mode = "open", path = log_path() }, "open")
    end)
end

function HANDLERS.on_clear_log()
    HANDLERS.guard(function()
        Log.lines = {}
        write_file(log_path(), "")
        Log.refresh_widget()
    end)
end

function HANDLERS.on_copy_log()
    HANDLERS.guard(function()
        local log = win:Find("Log")
        if log then
            log:SelectAll()
            log:Copy()
        end
    end)
end

function HANDLERS.on_browse_logo()
    HANDLERS.guard(function()
        local path = Presets.single_file(fusion:RequestFile("", "*.png", {}))
        if path == "" then return end
        if not path:lower():match("%.png$") then error(tr("error.choose_png")) end
        set_text("FallbackLogoPath", path)
        Settings.data.fallback_logo_path = path
        Settings.mark_dirty()
        Preview.request(1)
        append_log(tr("log.logo_selected", { path = path }))
    end)
end

function HANDLERS.on_default_logo()
    HANDLERS.guard(function()
        set_text("FallbackLogoPath", default_fallback_logo_path())
        Settings.data.fallback_logo_path = default_fallback_logo_path()
        Settings.mark_dirty()
        Preview.request(1)
        append_log(tr("log.logo_default"))
    end)
end

function HANDLERS.on_language_changed()
    if Editor.suppress then return end
    local next_mode = language_mode_from_ui()
    if next_mode == language_mode then return end
    language_mode = next_mode
    Settings.data.language_mode = next_mode
    HANDLERS.guard(function() save_current_style() end)
    local hint = win:Find("LanguageRestartHint")
    if hint then hint.Text = tr("language.saved_reopen") end
    append_log(tr("language.saved_reopen"))
end

-- ------------------------------------------------------------------------------------------
-- Window

App.pages = { "PageCreate", "PageStyle", "PagePresets", "PageLog" }
App.style_pages = { "StyleLayout", "StyleColors", "StyleText" }

function App.show_page(index)
    for position, element_id in ipairs(App.pages) do
        local page = win:Find(element_id)
        if page then page.Hidden = position - 1 ~= index end
    end
    pcall(function() win:RecalcLayout() end)
end

function App.go_to_page(index)
    Editor.set_combo("MainTabs", index)
    App.show_page(index)
end

function App.show_style_page(index)
    for position, element_id in ipairs(App.style_pages) do
        local page = win:Find(element_id)
        if page then page.Hidden = position - 1 ~= index end
    end
    pcall(function() win:RecalcLayout() end)
end

App.LABEL_WIDTH = 132

function App.row(label, children, label_width, tooltip)
    local items = { ui:Label({ Text = label, MinimumSize = { label_width or App.LABEL_WIDTH, 0 }, Weight = 0, ToolTip = tooltip }) }
    for _, child in ipairs(children) do table.insert(items, child) end
    table.insert(items, ui:HGap(0, 1))
    return ui:HGroup({ Weight = 0, Spacing = 8 }, items)
end

function App.spin(element_id, minimum, maximum, tooltip)
    return ui:SpinBox({ ID = element_id, Minimum = minimum, Maximum = maximum, MinimumSize = { 76, 28 }, MaximumSize = { 90, 28 }, Weight = 0, ToolTip = tooltip })
end

function App.section(text, fonts)
    return ui:Label({ Text = text, Font = fonts.section, Weight = 0, StyleSheet = App.widget_styles.section })
end

function App.hint(text, fonts, element_id)
    return ui:Label({ ID = element_id, Text = text, Font = fonts.hint, WordWrap = true, Weight = 0, StyleSheet = App.widget_styles.muted })
end

function App.divider()
    return ui:Label({ Text = "", MinimumSize = { 0, 1 }, MaximumSize = { 16777215, 1 }, Weight = 0, StyleSheet = App.widget_styles.divider })
end

function App.preview_panel(suffix, fonts, size)
    local width, height = size[1], size[2]
    return ui:VGroup({ Weight = 0, Spacing = 6 }, {
        ui:Button({
            ID = "Preview" .. suffix, Flat = true, IconSize = { width - 12, height - 12 },
            MinimumSize = { width, height }, MaximumSize = { width, height }, Weight = 0,
            ToolTip = tr("preview.idle"), StyleSheet = App.widget_styles.preview(width, height),
        }),
        App.hint(tr("preview.idle"), fonts, "PreviewStatus" .. suffix),
        ui:VGap(0, 1),
    })
end

function App.swatch_style(color)
    return "QPushButton { min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px; padding: 0;"
        .. " border: 1px solid #4a4e57; border-radius: 6px; background: " .. tostring(color or "#000000") .. "; }"
        .. " QPushButton:hover { border-color: #b8bdc6; }"
end

function App.build_create_page(fonts)
    local controls = ui:VGroup({ Weight = 1, Spacing = 8 }, {
        App.section(tr("section.style_summary"), fonts),
        App.row(tr("field.preset"), {
            ui:ComboBox({ ID = "QuickPreset", MinimumSize = { 250, 28 }, Weight = 0, ToolTip = tr("presets.hint") }),
        }, nil, tr("presets.hint")),
        App.row(tr("field.skin"), { ui:ComboBox({ ID = "SkinSelector", MinimumSize = { 250, 28 }, Weight = 0 }) }),
        App.row(tr("field.palette"), { ui:ComboBox({ ID = "PaletteSelector", MinimumSize = { 250, 28 }, Weight = 0 }) }),
        ui:HGroup({ ID = "PresetSummaryRow", Hidden = true, Weight = 0, Spacing = 8 }, {
            ui:Label({ Text = "", MinimumSize = { App.LABEL_WIDTH, 0 }, MaximumSize = { App.LABEL_WIDTH, 16777215 }, Weight = 0 }),
            ui:Label({ ID = "PresetSummary", Text = "", Font = fonts.hint, WordWrap = true, MinimumSize = { 0, 36 }, Weight = 1, StyleSheet = App.widget_styles.muted }),
        }),
        App.row("", {
            ui:Button({ ID = "OpenStyle", Text = tr("action.customize") .. "  >", Flat = true, Weight = 0, StyleSheet = App.widget_styles.link }),
            ui:Button({ ID = "SaveAsPreset", Text = tr("action.save_as_preset") .. "  >", Flat = true, Weight = 0, StyleSheet = App.widget_styles.link }),
        }),
        ui:VGap(4, 0),
        App.divider(),
        ui:VGap(4, 0),
        App.section(tr("section.timeline"), fonts),
        App.row(tr("field.audio_tracks"), {
            ui:LineEdit({ ID = "AudioTracks", PlaceholderText = "1-3", MinimumSize = { 90, 28 }, MaximumSize = { 110, 28 }, Weight = 0, ToolTip = tr("hint.audio_tracks_tip") }),
            ui:HGap(10, 0),
            ui:Label({ Text = tr("field.video_track"), Weight = 0, ToolTip = tr("hint.video_track_tip") }),
            App.spin("VideoTrack", 1, 64, tr("hint.video_track_tip")),
        }, nil, tr("hint.audio_tracks_tip")),
        App.row(tr("field.switch_mode"), {
            ui:ComboBox({ ID = "SwitchMode", MinimumSize = { 300, 28 }, Weight = 0, ToolTip = tr("hint.switch_mode") }),
        }, nil, tr("hint.switch_mode")),
        App.row(tr("field.update_scope"), {
            ui:LineEdit({ ID = "UpdateScope", PlaceholderText = tr("scope.placeholder"), MinimumSize = { 196, 28 }, MaximumSize = { 250, 28 }, Weight = 0, ToolTip = tr("scope.hint") }),
            ui:Button({ ID = "ListClips", Text = tr("action.list_clips"), Weight = 0, ToolTip = tr("log.scope_help") }),
        }, nil, tr("scope.hint")),
        ui:VGap(16, 0),
        ui:Button({ ID = "CreatePlayers", Text = tr("action.create"), MinimumSize = { 0, 44 }, Weight = 0, StyleSheet = App.widget_styles.primary }),
        ui:Label({ ID = "ProgressBar", Text = "", MinimumSize = { 0, 4 }, MaximumSize = { 16777215, 4 }, Weight = 0 }),
        ui:HGroup({ Weight = 0, Spacing = 8 }, {
            ui:Label({ ID = "ProgressStatus", Text = tr("status.ready"), WordWrap = true, Weight = 1, StyleSheet = App.widget_styles.muted }),
            ui:Button({ ID = "CancelRun", Text = tr("action.cancel"), Hidden = true, Weight = 0 }),
            ui:Button({ ID = "RemovePlayers", Text = tr("action.remove_players"), MinimumSize = { 190, 28 }, Weight = 0, StyleSheet = App.widget_styles.quiet }),
        }),
        ui:Label({ ID = "LastError", Text = "", Hidden = true, WordWrap = true, Font = fonts.hint, Weight = 0, StyleSheet = App.widget_styles.error }),
        ui:Label({ ID = "RateWarning", Text = "", Hidden = true, WordWrap = true, MinimumSize = { 0, 72 }, Font = fonts.hint, Weight = 0, StyleSheet = App.widget_styles.warning }),
        ui:VGap(0, 1),
    })
    return ui:HGroup({ ID = "PageCreate", Weight = 1, Spacing = 20 }, {
        controls,
        App.preview_panel("Create", fonts, App.PREVIEW_MAIN),
    })
end

function App.build_style_page(fonts)
    local toggle_rows = {}
    local current = {}
    for index, toggle in ipairs(Editor.toggles) do
        table.insert(current, ui:CheckBox({ ID = toggle.id, Text = tr(toggle.label), MinimumSize = { 170, 0 }, Weight = 0, StyleSheet = "QCheckBox { min-width: 170px; }" }))
        if #current == 3 or index == #Editor.toggles then
            table.insert(current, ui:HGap(0, 1))
            table.insert(toggle_rows, ui:HGroup({ Weight = 0 }, current))
            current = {}
        end
    end

    local layout_children = {
        App.row(tr("field.anchor"), { ui:ComboBox({ ID = "Anchor", MinimumSize = { 200, 28 }, Weight = 0 }) }),
        App.row(tr("field.scale"), { App.spin("Scale", 25, 400) }),
        App.row(tr("field.margin_x"), {
            App.spin("MarginX", 0, 2000),
            ui:Label({ Text = tr("field.margin_y"), Weight = 0 }),
            App.spin("MarginY", 0, 2000),
        }),
        ui:VGap(4, 0),
        App.section(tr("field.elements"), fonts),
    }
    for _, row in ipairs(toggle_rows) do table.insert(layout_children, row) end
    for _, row in ipairs({
        ui:VGap(4, 0),
        App.row(tr("field.progress_style"), { ui:ComboBox({ ID = "ProgressStyle", MinimumSize = { 240, 28 }, Weight = 0 }) }),
        App.row(tr("field.time_mode"), { ui:ComboBox({ ID = "TimeMode", MinimumSize = { 240, 28 }, Weight = 0 }) }),
        App.row(tr("field.progress_basis"), { ui:ComboBox({ ID = "ProgressBasis", MinimumSize = { 240, 28 }, Weight = 0 }) }),
        App.row(tr("field.bar_count"), { App.spin("BarCount", 8, 200) }),
        App.row(tr("field.brand_text"), { ui:LineEdit({ ID = "BrandText", MinimumSize = { 200, 28 }, Weight = 0 }) }),
        App.row(tr("field.fallback_logo"), {
            ui:LineEdit({ ID = "FallbackLogoPath", MinimumSize = { 160, 28 }, Weight = 1, ToolTip = tr("hint.fallback_logo") }),
            ui:Button({ ID = "BrowseFallbackLogo", Text = tr("action.choose_png"), Weight = 0 }),
            ui:Button({ ID = "DefaultFallbackLogo", Text = tr("action.default"), Weight = 0 }),
        }, nil, tr("hint.fallback_logo")),
        ui:VGap(0, 1),
    }) do table.insert(layout_children, row) end

    local color_rows = {}
    for _, color in ipairs(Editor.colors) do
        local children = {
            ui:Button({ ID = "Pick" .. color.id, Text = "", Weight = 0, ToolTip = tr("field.color"), StyleSheet = App.swatch_style("#000000") }),
            ui:LineEdit({ ID = color.id, MinimumSize = { 92, 28 }, MaximumSize = { 100, 28 }, Weight = 0 }),
        }
        if color.alpha then
            table.insert(children, ui:HGap(8, 0))
            table.insert(children, ui:Label({ Text = tr("field.opacity"), Weight = 0 }))
            table.insert(children, App.spin(color.alpha, 0, 255))
        end
        table.insert(color_rows, App.row(tr(color.label), children, 150))
    end
    table.insert(color_rows, ui:VGap(4, 0))
    table.insert(color_rows, App.row(tr("field.glass_strength"), { App.spin("GlassStrength", 0, 100) }, 150))
    table.insert(color_rows, App.row(tr("field.radius"), { App.spin("CornerRadius", 0, 64) }, 150))
    table.insert(color_rows, ui:VGap(0, 1))

    local function font_row(label, font_id, size_id, extra)
        local children = {
            ui:ComboBox({ ID = font_id, Editable = true, MinimumSize = { 210, 28 }, Weight = 0 }),
            ui:Label({ Text = tr("field.size"), Weight = 0 }),
            App.spin(size_id, 8, 96),
        }
        if extra then table.insert(children, extra) end
        return App.row(label, children, 150)
    end
    local text_children = {
        font_row(tr("field.title_font"), "TitleFontFamily", "TitleSize"),
        font_row(tr("field.artist_font"), "ArtistFontFamily", "ArtistSize"),
        font_row(tr("field.time_font"), "TimeFontFamily", "MetaSize", ui:CheckBox({ ID = "TimeBold", Text = tr("field.time_bold"), Weight = 0 })),
        ui:VGap(0, 1),
    }

    return ui:HGroup({ ID = "PageStyle", Hidden = true, Weight = 1, Spacing = 20 }, {
        ui:VGroup({ Weight = 1, Spacing = 8 }, {
            ui:HGroup({ Weight = 0, Spacing = 8 }, {
                ui:Label({ ID = "StyleTitle", Text = "", Font = fonts.section, Weight = 1, StyleSheet = App.widget_styles.section }),
                ui:Button({ ID = "ResetStyle", Text = tr("action.reset_style"), Weight = 0, StyleSheet = App.widget_styles.quiet }),
            }),
            ui:TabBar({ ID = "StyleTabs", Weight = 0 }),
            ui:VGroup({ ID = "StyleLayout", Weight = 1, Spacing = 7 }, layout_children),
            ui:VGroup({ ID = "StyleColors", Hidden = true, Weight = 1, Spacing = 7 }, color_rows),
            ui:VGroup({ ID = "StyleText", Hidden = true, Weight = 1, Spacing = 7 }, text_children),
        }),
        App.preview_panel("Style", fonts, App.PREVIEW_CLOSE),
    })
end

function App.build_library_page(fonts)
    return ui:VGroup({ ID = "PagePresets", Hidden = true, Weight = 1, Spacing = 8 }, {
        App.section(tr("presets.title"), fonts),
        App.hint(tr("presets.hint"), fonts),
        App.row(tr("field.preset_name"), {
            ui:LineEdit({ ID = "PresetName", MinimumSize = { 280, 28 }, Weight = 0 }),
            ui:Button({ ID = "PresetSave", Text = tr("action.preset_save"), Weight = 0, StyleSheet = App.widget_styles.accent }),
            ui:Button({ ID = "PresetRename", Text = tr("action.preset_rename"), Weight = 0 }),
        }),
        App.row(tr("field.preset_list"), {
            ui:ComboBox({ ID = "PresetList", MinimumSize = { 280, 28 }, Weight = 0 }),
            ui:Button({ ID = "PresetApply", Text = tr("action.preset_apply"), Weight = 0 }),
            ui:Button({ ID = "PresetDelete", Text = tr("action.preset_delete"), Weight = 0, StyleSheet = App.widget_styles.quiet }),
        }),
        App.row("", {
            ui:Button({ ID = "PresetExport", Text = tr("action.preset_export"), Weight = 0 }),
            ui:Button({ ID = "PresetImport", Text = tr("action.preset_import"), Weight = 0 }),
            ui:Button({ ID = "PresetFolder", Text = tr("action.open_presets_folder"), Flat = true, Weight = 0, StyleSheet = App.widget_styles.link }),
        }),
        ui:VGap(8, 0),
        App.divider(),
        ui:VGap(8, 0),
        App.section(tr("palettes.title"), fonts),
        App.hint(tr("palettes.hint"), fonts),
        App.row(tr("field.palette_name"), {
            ui:LineEdit({ ID = "PaletteName", MinimumSize = { 280, 28 }, Weight = 0 }),
            ui:Button({ ID = "PaletteSave", Text = tr("action.palette_save"), Weight = 0, StyleSheet = App.widget_styles.accent }),
        }),
        App.row(tr("field.preset_list"), {
            ui:ComboBox({ ID = "PaletteLibrary", MinimumSize = { 280, 28 }, Weight = 0 }),
            ui:Button({ ID = "PaletteLibraryApply", Text = tr("action.apply"), Weight = 0 }),
            ui:Button({ ID = "PaletteDelete", Text = tr("action.palette_delete"), Weight = 0, StyleSheet = App.widget_styles.quiet }),
        }),
        ui:VGap(0, 1),
    })
end

function App.build_service_page(fonts)
    return ui:VGroup({ ID = "PageLog", Hidden = true, Weight = 1, Spacing = 8 }, {
        App.section(tr("section.interface"), fonts),
        App.row(tr("field.language"), {
            ui:ComboBox({ ID = "LanguageMode", MinimumSize = { 200, 28 }, Weight = 0 }),
        }),
        App.hint(tr("language.restart_hint"), fonts, "LanguageRestartHint"),
        ui:VGap(6, 0),
        App.section(tr("section.updates"), fonts),
        ui:HGroup({ Weight = 0, Spacing = 12 }, {
            ui:Label({ ID = "UpdateVersion", Text = "", Weight = 0 }),
            ui:CheckBox({ ID = "AutoUpdate", Text = tr("field.auto_update"), Weight = 0 }),
            ui:HGap(0, 1),
            ui:Button({ ID = "CheckUpdates", Text = tr("action.check_updates"), Weight = 0 }),
        }),
        ui:Label({ ID = "UpdateStatus", Text = "", Weight = 0, WordWrap = true, StyleSheet = App.widget_styles.muted }),
        ui:VGap(6, 0),
        ui:HGroup({ Weight = 0, Spacing = 8 }, {
            App.section(tr("diagnostics.title"), fonts),
            ui:HGap(0, 1),
            ui:Button({ ID = "CopyLog", Text = tr("action.copy_log"), Weight = 0 }),
            ui:Button({ ID = "OpenLog", Text = tr("action.open_log"), Weight = 0 }),
            ui:Button({ ID = "ClearLog", Text = tr("action.clear_log"), Weight = 0, StyleSheet = App.widget_styles.quiet }),
        }),
        ui:TextEdit({ ID = "Log", ReadOnly = true, Font = fonts.mono, Weight = 1 }),
        App.hint(tr("diagnostics.paths", { log = log_path(), dump = clip_dump_path(), error = path_join(install_root(), "last_error.txt") }), fonts),
        ui:HGroup({ Weight = 0, Spacing = 8 }, {
            ui:Button({ ID = "CleanupLegacy", Text = tr("action.cleanup_legacy"), Weight = 0, ToolTip = tr("hint.cleanup_legacy"), StyleSheet = App.widget_styles.quiet }),
            ui:HGap(0, 1),
        }),
    })
end

function App.build(fonts)
    return ui:VGroup({ Spacing = 10 }, {
        ui:HGroup({ Weight = 0, Spacing = 12 }, {
            ui:Label({ Text = tr("window.title"), Font = fonts.header, Weight = 0 }),
            ui:Label({ Text = tr("app.subtitle"), Font = fonts.hint, Weight = 1, StyleSheet = App.widget_styles.muted }),
        }),
        ui:TabBar({ ID = "MainTabs", Weight = 0 }),
        ui:VGap(2, 0),
        App.build_create_page(fonts),
        App.build_style_page(fonts),
        App.build_library_page(fonts),
        App.build_service_page(fonts),
    })
end

App.PREVIEW_MAIN = { 480, 270 }
App.PREVIEW_CLOSE = { 400, 225 }

-- UIManager does not expose element IDs as Qt object names, so per-widget styles are set directly.
App.widget_styles = {
    primary = "QPushButton { min-height: 42px; background: #3b6fd8; border: none; border-radius: 8px; color: #ffffff; font-weight: 600; font-size: 14px; }"
        .. " QPushButton:hover { background: #4a7de6; } QPushButton:pressed { background: #335fba; }"
        .. " QPushButton:disabled { background: #2a3142; color: #7d8696; }",
    accent = "QPushButton { background: #2d3a55; border: 1px solid #3f5585; color: #e3e9f7; }"
        .. " QPushButton:hover { background: #34446a; } QPushButton:disabled { background: #24262c; border-color: #2e3138; color: #62666e; }",
    quiet = "QPushButton { background: transparent; border: 1px solid #34373e; color: #a9aeb7; }"
        .. " QPushButton:hover { border-color: #565b64; color: #e3e5e8; } QPushButton:disabled { color: #5d6168; border-color: #2a2c31; }",
    link = "QPushButton { background: transparent; border: none; padding: 2px 0; color: #7fa6ff; text-align: left; }"
        .. " QPushButton:hover { color: #b3c9ff; } QPushButton:disabled { color: #5d6168; }",
    section = "QLabel { color: #eef0f3; }",
    muted = "QLabel { color: #8b9099; }",
    divider = "QLabel { background: #2c2f36; border: none; }",
    error = "QLabel { padding: 8px 10px; background: #3a2222; color: #f3aaa4; border: 1px solid #6e3c39; border-radius: 6px; }",
    warning = "QLabel { padding: 8px 10px; background: #3a3020; color: #f0d29a; border: 1px solid #6b5630; border-radius: 6px; }",
    preview = function(width, height)
        return string.format("QPushButton { min-width: %dpx; max-width: %dpx; min-height: %dpx; max-height: %dpx; padding: 0;"
            .. " background: #111216; border: 1px solid #2c2f36; border-radius: 8px; }"
            .. " QPushButton:hover { border-color: #4a4f59; }", width, width, height, height)
    end,
}

App.stylesheet = [[
QWidget { background: #1b1c20; color: #d9dbdf; font-family: "Segoe UI"; font-size: 13px; }
QLabel { background: transparent; }
QToolTip { background: #2a2c32; color: #e6e8eb; border: 1px solid #3d4048; padding: 6px; }
QTabBar { background: transparent; }
QTabBar::tab { min-width: 96px; min-height: 30px; padding: 4px 18px; background: transparent; color: #8b9099; border: none; border-bottom: 2px solid #2a2c32; }
QTabBar::tab:hover { color: #d9dbdf; }
QTabBar::tab:selected { color: #f4f5f7; border-bottom: 2px solid #5b8def; }
QLineEdit, QComboBox, QSpinBox { min-height: 26px; padding: 1px 8px; background: #141519; color: #e1e3e6; border: 1px solid #33363d; border-radius: 6px; selection-background-color: #3e5c8a; }
QLineEdit:hover, QComboBox:hover, QSpinBox:hover { border-color: #464a53; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #5b8def; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { color: #5d6168; border-color: #2a2c31; }
QComboBox QAbstractItemView { background: #1f2025; color: #e1e3e6; border: 1px solid #3d4048; selection-background-color: #34446a; outline: none; }
QPushButton { min-height: 26px; padding: 2px 14px; border: 1px solid #3a3d45; border-radius: 6px; background: #26282e; color: #e1e3e6; }
QPushButton:hover { border-color: #565b64; background: #2d3037; }
QPushButton:disabled { color: #62666e; background: #212328; border-color: #2a2c31; }
QCheckBox { spacing: 8px; background: transparent; color: #d9dbdf; }
QCheckBox:disabled { color: #5d6168; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; border: 1px solid #4a4e57; background: #141519; }
QCheckBox::indicator:hover { border-color: #7a808b; }
QCheckBox::indicator:checked { background: #5b8def; border-color: #5b8def; }
QCheckBox::indicator:disabled { background: #202126; border-color: #2c2e34; }
QTextEdit { background: #141519; color: #c5c8cd; border: 1px solid #2c2f36; border-radius: 6px; padding: 4px; }
]]

function App.bind_events()
    win.On[PLUGIN_ID].Close = function(ev)
        if Pipeline.state then Pipeline.state.cancel = true end
        pcall(function() save_current_style() end)
        if Ticker.timer then pcall(function() Ticker.timer:Stop() end) end
        Ticker.running = false
        dispatcher.On.Timeout = nil
        App.closing = true
        dispatcher:ExitLoop()
    end
    dispatcher.On.Timeout = function(ev)
        local ok, err = pcall(Ticker.tick)
        if not ok then report_error(err) end
    end
    win.On.MainTabs.CurrentChanged = function(ev) App.show_page(Editor.combo_index("MainTabs")) end
    win.On.StyleTabs.CurrentChanged = function(ev) App.show_style_page(Editor.combo_index("StyleTabs")) end
    win.On.CreatePlayers.Clicked = function(ev) HANDLERS.on_create() end
    win.On.CancelRun.Clicked = function(ev) Pipeline.cancel() end
    win.On.RemovePlayers.Clicked = function(ev) HANDLERS.on_remove_players() end
    win.On.ListClips.Clicked = function(ev) HANDLERS.on_list_clips() end
    win.On.OpenStyle.Clicked = function(ev) App.go_to_page(1) end
    win.On.SaveAsPreset.Clicked = function(ev) App.go_to_page(2) end
    win.On.SkinSelector.CurrentIndexChanged = function(ev)
        if Editor.suppress then return end
        HANDLERS.guard(function()
            Settings.data.styles[Settings.data.active_skin] = Editor.read()
            local skin = SKIN_CATALOG.skins[Editor.combo_index("SkinSelector") + 1]
            if skin and skin ~= Settings.data.active_skin then
                Editor.select_skin(skin)
                Editor.reset_quick_preset()
                append_log(tr("log.skin_active", { skin = Style.skin_label(skin) }))
            end
        end)
    end
    win.On.PaletteSelector.CurrentIndexChanged = function(ev)
        if Editor.suppress then return end
        HANDLERS.guard(function()
            local name = Editor.palette_names()[Editor.combo_index("PaletteSelector") + 1]
            local current = Editor.detect_palette(Settings.data.styles[Settings.data.active_skin])
            if name and name ~= "Custom" and name ~= current then
                Editor.apply_palette(name)
                Editor.reset_quick_preset()
            end
        end)
    end
    win.On.QuickPreset.CurrentIndexChanged = function(ev)
        if Editor.suppress then return end
        HANDLERS.guard(function()
            local preset = Settings.data.presets[Editor.combo_index("QuickPreset")]
            if preset and preset.name ~= Editor.active_preset then Presets.apply(preset) end
        end)
    end
    win.On.PaletteLibraryApply.Clicked = function(ev)
        HANDLERS.guard(function() Editor.apply_palette(Presets.library_selected()) end)
    end
    win.On.PaletteSave.Clicked = function(ev) HANDLERS.guard(Presets.save_palette) end
    win.On.PaletteDelete.Clicked = function(ev) HANDLERS.guard(Presets.delete_palette) end
    win.On.PresetApply.Clicked = function(ev) HANDLERS.guard(function() Presets.apply(Presets.selected()) end) end
    win.On.PresetSave.Clicked = function(ev) HANDLERS.guard(Presets.save) end
    win.On.PresetRename.Clicked = function(ev) HANDLERS.guard(Presets.rename) end
    win.On.PresetDelete.Clicked = function(ev) HANDLERS.guard(Presets.delete) end
    win.On.PresetExport.Clicked = function(ev) HANDLERS.guard(Presets.export) end
    win.On.PresetImport.Clicked = function(ev) HANDLERS.guard(Presets.import) end
    win.On.PresetFolder.Clicked = function(ev)
        HANDLERS.guard(function() run_runner_config({ mode = "open", path = Presets.folder() }, "open") end)
    end
    win.On.PresetList.CurrentIndexChanged = function(ev)
        if Editor.suppress then return end
        local preset = Presets.selected()
        if preset then set_text("PresetName", preset.name) end
    end
    win.On.ResetStyle.Clicked = function(ev) HANDLERS.on_reset_style() end
    win.On.BrowseFallbackLogo.Clicked = function(ev) HANDLERS.on_browse_logo() end
    win.On.DefaultFallbackLogo.Clicked = function(ev) HANDLERS.on_default_logo() end
    win.On.CopyLog.Clicked = function(ev) HANDLERS.on_copy_log() end
    win.On.OpenLog.Clicked = function(ev) HANDLERS.on_open_log() end
    win.On.ClearLog.Clicked = function(ev) HANDLERS.on_clear_log() end
    win.On.CleanupLegacy.Clicked = function(ev) HANDLERS.on_cleanup_legacy() end
    win.On.LanguageMode.CurrentIndexChanged = function(ev) HANDLERS.on_language_changed() end
    win.On.AutoUpdate.Clicked = function(ev)
        local enabled = check_field("AutoUpdate", true)
        if Settings.data.auto_update == enabled then return end
        Settings.data.auto_update = enabled
        Settings.mark_dirty()
    end
    win.On.CheckUpdates.Clicked = function(ev)
        HANDLERS.guard(function() Updater.check(true) end)
    end
    for _, suffix in ipairs({ "Create", "Style" }) do
        win.On["Preview" .. suffix].Clicked = function(ev) HANDLERS.on_open_preview() end
    end
    for _, color in ipairs(Editor.colors) do
        win.On[color.id].EditingFinished = function(ev) Editor.changed() end
        win.On["Pick" .. color.id].Clicked = function(ev)
            HANDLERS.pick_color_safely(color.id, Settings.data.styles[Settings.data.active_skin][color.key])
        end
    end
    for _, toggle in ipairs(Editor.toggles) do
        win.On[toggle.id].Clicked = function(ev) Editor.changed() end
    end
    win.On.TimeBold.Clicked = function(ev) Editor.changed() end
    for _, number in ipairs(Editor.numbers) do
        win.On[number.id].ValueChanged = function(ev) Editor.changed() end
    end
    for _, font in ipairs(Editor.fonts) do
        win.On[font.id].CurrentIndexChanged = function(ev) Editor.changed() end
        win.On[font.id].EditTextChanged = function(ev) Editor.changed() end
    end
    for _, enum in ipairs(Editor.enums) do
        win.On[enum.id].CurrentIndexChanged = function(ev) Editor.changed() end
    end
    win.On.BrandText.EditingFinished = function(ev) Editor.changed() end
    for _, element_id in ipairs({ "AudioTracks", "UpdateScope" }) do
        win.On[element_id].EditingFinished = function(ev)
            HANDLERS.guard(function() Editor.capture_timeline() Settings.mark_dirty() end)
        end
    end
    win.On.VideoTrack.ValueChanged = function(ev) HANDLERS.guard(function() Editor.capture_timeline() Settings.mark_dirty() end) end
    win.On.SwitchMode.CurrentIndexChanged = function(ev)
        if Editor.suppress then return end
        HANDLERS.guard(function() Editor.capture_timeline() Settings.mark_dirty() end)
    end
end

function App.populate()
    Editor.suppress = true
    local tabs = win:Find("MainTabs")
    for _, key in ipairs({ "tab.create", "tab.style", "tab.presets", "tab.log" }) do tabs:AddTab(tr(key)) end
    local style_tabs = win:Find("StyleTabs")
    for _, key in ipairs({ "style.tab_layout", "style.tab_colors", "style.tab_text" }) do style_tabs:AddTab(tr(key)) end

    local skin_labels = {}
    for _, skin in ipairs(SKIN_CATALOG.skins) do table.insert(skin_labels, Style.skin_label(skin)) end
    Editor.fill_combo("SkinSelector", skin_labels, Editor.index_of(SKIN_CATALOG.skins, Settings.data.active_skin))
    for _, enum in ipairs(Editor.enums) do
        local labels = {}
        for _, value in ipairs(Editor.enum_values(enum.key)) do table.insert(labels, tr(enum.prefix .. value)) end
        Editor.fill_combo(enum.id, labels, 0)
    end
    for _, font in ipairs(Editor.fonts) do Editor.fill_combo(font.id, FONT_FAMILIES, 0) end
    Editor.fill_combo("LanguageMode", { tr("language.auto"), tr("language.en"), tr("language.ru") }, language_mode_index(language_mode))

    -- UIManager may clamp Value to its default range before Maximum is applied.
    configure_spinbox("VideoTrack", 1, 64, Settings.data.timeline.video_track)
    for _, number in ipairs(Editor.numbers) do
        local range = SKIN_CATALOG.int_ranges[number.key]
        if range then configure_spinbox(number.id, range[1], range[2], range[1]) end
    end
    set_text("AudioTracks", Settings.data.timeline.audio_tracks)
    set_text("UpdateScope", Settings.data.timeline.scope)
    local switch_labels = {}
    for _, mode in ipairs(SWITCH_MODES) do table.insert(switch_labels, tr("switch_mode." .. mode)) end
    Editor.fill_combo("SwitchMode", switch_labels, Editor.index_of(SWITCH_MODES, Settings.data.timeline.switch_mode))
    set_text("FallbackLogoPath", Settings.data.fallback_logo_path)
    Editor.suppress = false

    Editor.apply(Settings.data.styles[Settings.data.active_skin])
    Editor.refresh_palette_combos()
    Presets.refresh()
    Editor.update_preset_summary()
    pcall(function()
        local _, project, timeline = current_project_and_timeline()
        App.show_rate_warning(project, timeline)
    end)
    App.show_page(0)
    App.show_style_page(0)
    Log.refresh_widget()
    App.set_busy(false)
    set_checked("AutoUpdate", Settings.data.auto_update ~= false)
    Updater.show_version()
end

function App.run()
    local existing = ui:FindWindow(PLUGIN_ID)
    if existing then
        existing:Show()
        existing:Raise()
        return
    end
    mkdir_p(tmp_dir())
    Settings.data = load_settings()
    language_mode = Settings.data.language_mode or "auto"
    active_language = effective_language(language_mode)
    Log.rotate()
    local fonts = {
        header = ui:Font({ Family = "Segoe UI", PointSize = 15, Bold = true }),
        section = ui:Font({ Family = "Segoe UI", PointSize = 11, Bold = true }),
        hint = ui:Font({ Family = "Segoe UI", PointSize = 9 }),
        mono = ui:Font({ Family = "Consolas", PointSize = 9 }),
    }
    App.busy_controls = {
        "CreatePlayers", "RemovePlayers", "ListClips", "SkinSelector", "PaletteSelector",
        "QuickPreset", "PresetApply", "PaletteLibraryApply", "ResetStyle", "CleanupLegacy", "AudioTracks",
        "VideoTrack", "UpdateScope", "SwitchMode",
    }
    win = dispatcher:AddWindow({
        ID = PLUGIN_ID,
        WindowTitle = tr("window.title"),
        Geometry = { 120, 60, 1100, 700 },
        MinimumSize = { 980, 620 },
        StyleSheet = App.stylesheet,
    }, App.build(fonts))
    -- A unique timer ID per launch keeps a previous window's timer from reaching this one.
    Ticker.timer = ui:Timer({ ID = "TrackVisualizerTick" .. tostring(os.time()) .. tostring(math.random(1000, 9999)), Interval = TICK_MS })
    App.bind_events()
    App.populate()
    win:Show()
    pcall(function()
        local _, project, timeline = current_project_and_timeline()
        local width, height = timeline_resolution(project, timeline)
        if width and height then Preview.frame = { width, height } end
    end)
    Preview.request(0)
    set_progress(0, tr("status.ready"))
    Updater.auto_check()
    -- Resolve can deliver an event left over from a previously closed window; its dispatcher then
    -- fails to look the sender up and throws out of RunLoop. Resume the loop instead of dying.
    App.closing = false
    local stray_events = 0
    while not App.closing do
        local ok, err = pcall(function() dispatcher:RunLoop() end)
        if ok then break end
        stray_events = stray_events + 1
        pcall(function() append_file(path_join(tmp_dir(), "ui_dispatch.txt"), os.date("%H:%M:%S ") .. tostring(err) .. "\n") end)
        if stray_events >= 20 then error(err) end
    end
    if Ticker.timer then pcall(function() Ticker.timer:Stop() end) end
    win:Hide()
end

local launched, launch_error = xpcall(App.run, debug.traceback)
if not launched then
    print("Track Visualizer: " .. tostring(launch_error))
    pcall(function() set_last_error(launch_error) end)
end
