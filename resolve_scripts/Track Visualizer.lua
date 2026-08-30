local PLUGIN_ID = "com.local.davinci.trackvisualizer.lua"
local VISUALIZER_PREFIX = "TVIZ__"
local STYLE_VERSION = 7
local DEFAULT_RENDERER_MODE = "auto"
local LIVE_HELPER_SHARD_SECONDS = 15 * 60

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

local DEFAULT_DESIGN = {
    brand_text = "aplus.fm",
    show_cover = true,
    show_brand = true,
    show_time = true,
    show_progress = true,
    show_knob = true,
    glass_enabled = true,
    panel_color = "#121619",
    panel_alpha = 154,
    border_color = "#FFFFFF",
    border_alpha = 82,
    primary_text_color = "#F5F7F8",
    secondary_text_color = "#EEF3F5",
    accent_color = "#EBEEF0",
    track_color = "#EBEEF0",
    corner_radius = 14,
    glass_strength = 46,
    title_size = 32,
    artist_size = 18,
    meta_size = 16,
    title_font_family = "Segoe UI",
    artist_font_family = "Segoe UI",
}

local I18N = {
    en = {
        ["window.title"] = "Track Visualizer",
        ["app.subtitle"] = "Creates players for audio clips on the current timeline.",
        ["section.quick_start"] = "Quick start",
        ["field.audio_tracks"] = "Audio tracks",
        ["field.video_track"] = "Video track",
        ["hint.quick_start"] = "You can run it now: all matching clips will be processed.",
        ["action.update"] = "Create / update visualizers",
        ["field.status"] = "Status",
        ["status.ready"] = "Ready to run",
        ["hint.status"] = "The current processing stage is shown here.",
        ["section.appearance"] = "Appearance",
        ["field.theme"] = "Theme",
        ["field.palette"] = "Theme palette",
        ["action.apply"] = "Apply",
        ["section.preview"] = "Preview",
        ["action.create_preview"] = "Generate preview",
        ["action.open_png"] = "Open PNG",
        ["preview.external_hint"] = "The preview will open in an external application.",
        ["advanced.title"] = "Advanced settings",
        ["advanced.subtitle"] = "Timeline, render, and appearance settings. One section opens at a time.",
        ["advanced.timeline"] = "Timeline and clip selection",
        ["field.switch_next"] = "Switch visualizer when the next track starts",
        ["field.update_scope"] = "Process clips",
        ["scope.placeholder"] = "empty, 3,5-7, or @playhead",
        ["scope.alias_all"] = "all",
        ["scope.alias_current"] = "current",
        ["action.list_clips"] = "Show list",
        ["scope.hint"] = "Empty = all clips; 3,5-7 = clip numbers; @playhead = clip under the playhead.",
        ["advanced.render"] = "Output and render",
        ["field.mode"] = "Mode",
        ["render.mode_auto"] = "Fusion live (auto)",
        ["render.mode_legacy"] = "Legacy MOV only",
        ["render.hint"] = "Fusion uses full-frame output; legacy fallback is used when position baking is disabled.",
        ["field.player_size"] = "Player size",
        ["field.frame_rate"] = "Frame rate",
        ["field.render_fps"] = "Render",
        ["field.fallback_fps"] = "Fallback FPS",
        ["hint.fallback_fps"] = "Fallback FPS is used only when the timeline frame rate cannot be read.",
        ["field.margin"] = "Edge margin",
        ["field.bake_position"] = "Bake position into a full-frame overlay",
        ["field.output_dir"] = "Output folder",
        ["advanced.elements"] = "Player elements",
        ["field.brand_text"] = "Brand label",
        ["field.glass"] = "Glass",
        ["field.cover"] = "Cover",
        ["field.brand"] = "Brand",
        ["field.time"] = "Time",
        ["field.progress"] = "Progress",
        ["field.marker"] = "Marker",
        ["field.fallback_logo"] = "Fallback cover",
        ["action.choose_png"] = "Choose PNG",
        ["action.default"] = "Default",
        ["advanced.typography"] = "Typography",
        ["field.title"] = "Title",
        ["field.title_timer"] = "Title + timer block",
        ["field.color"] = "Color",
        ["field.size"] = "Size",
        ["field.title_font"] = "Title font",
        ["field.artist_metadata"] = "Artist and metadata",
        ["field.artist_border"] = "Artist + border",
        ["field.artist_size"] = "Artist size",
        ["field.meta_size"] = "Metadata size",
        ["field.artist_font"] = "Artist font",
        ["advanced.card"] = "Card and colors",
        ["field.panel"] = "Panel",
        ["field.background_timer"] = "Background + timer text",
        ["field.opacity"] = "Opacity",
        ["field.border"] = "Border",
        ["field.border_opacity"] = "Border opacity",
        ["field.shape"] = "Shape",
        ["field.radius"] = "Radius",
        ["field.glass_strength"] = "Glass strength",
        ["field.accent"] = "Accent",
        ["field.progress_line"] = "Progress line",
        ["advanced.actions"] = "Style actions",
        ["hint.style_actions"] = "Save the current style for future runs or restore its default values.",
        ["action.save_style"] = "Save style",
        ["action.reset_style"] = "Reset style",
        ["field.language"] = "Language",
        ["language.auto"] = "Auto (system)",
        ["language.en"] = "English",
        ["language.ru"] = "Russian",
        ["language.restart_hint"] = "Language changes are saved separately. Close and reopen Track Visualizer to update every label; current style values are preserved.",
        ["language.saved_reopen"] = "Language saved. Close and reopen Track Visualizer to update every label.",
        ["diagnostics.title"] = "Diagnostics",
        ["diagnostics.paths"] = "The paths below are for reference. The buttons operate on the main log.\nMain log: {log}\nClip property dump: {dump}\nLast error: {error}",
        ["section.last_preview"] = "Last preview",
        ["preview.not_created"] = "Preview has not been generated yet",
        ["action.copy_log"] = "Copy log",
        ["action.open_log"] = "Open log",
        ["action.clear_log"] = "Clear log",
        ["tab.main"] = "Main",
        ["tab.advanced"] = "Advanced",
        ["tab.diagnostics"] = "Diagnostics",
        ["skin.classic"] = "Classic",
        ["skin.minimal"] = "Minimal",
        ["skin.portrait_glass"] = "Portrait Glass",
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
        ["error.last"] = "Last error: {message}",
        ["error.unknown"] = "Unknown error",
        ["error.log_prefix"] = "ERROR: {message}",
        ["status.error"] = "Error: {message}",
        ["status.processing"] = "Processing {index}/{total}",
        ["status.reading_metadata"] = "Reading tags {index}/{total}",
        ["status.preparing_clip"] = "Preparing clip {index}/{total}",
        ["status.rendering"] = "Render {index}/{total}: {percent}%",
        ["status.preparing"] = "Preparing...",
        ["status.busy"] = "Processing...",
        ["error.runner_missing"] = "Track Visualizer runner was not found: {path}",
        ["error.runner_launch"] = "Could not launch the Track Visualizer runner: {details}",
        ["error.windows_wide_launch"] = "Unicode-safe Windows launch is unavailable for this path: {details}",
        ["error.runner_timeout"] = "Runner did not finish within {seconds} seconds",
        ["error.runner_exit"] = "Runner exited with code {code}: {details}",
        ["error.runner_completion"] = "Runner wrote an invalid completion file: {path}",
        ["error.settings_temp_open"] = "Could not open the temporary settings file: {details}",
        ["error.settings_temp_write"] = "Could not write the temporary settings file: {details}",
        ["error.settings_temp_verify"] = "Temporary settings verification failed",
        ["error.settings_invalid_json"] = "Refusing to replace settings with invalid JSON",
        ["error.settings_backup"] = "Could not back up settings before replacement: {details}",
        ["error.settings_replace"] = "Could not replace settings: {details}",
        ["log.clip_properties_no_path"] = "Clip properties without a path: {details}",
        ["log.overlap_same_start"] = "Same-start overlaps resolved in favor of the higher audio track: {count}",
        ["log.zero_length"] = "Skipped zero-length visualizer: {name}",
        ["log.switch_trimmed"] = "Visualizer switched at the next track start: {name} trimmed {from}f -> {to}f",
        ["log.clip_numbers"] = "Timeline clip numbers:",
        ["log.more_clips"] = "...and {count} more clips",
        ["error.no_clip_at_playhead"] = "No active audio clip under the playhead at {time}",
        ["log.playhead_selected"] = "Clip #{number} selected at the playhead",
        ["error.scope_invalid"] = "Process clips: enter clip numbers such as 3,5-7, leave empty for all clips, or use @playhead",
        ["error.unknown_clip_numbers"] = "Unknown clip numbers: {numbers}",
        ["log.partial_update"] = "Partial update: {clips} (previous clips are included when needed for crossfade boundaries)",
        ["log.track_missing"] = "Skipped A{track}: track does not exist",
        ["summary.track_missing"] = "A{track} missing (count={count})",
        ["log.clip_no_path"] = "Skipped audio clip without a file path: {name}",
        ["log.clip_dump"] = "Clip property dump: {path}",
        ["error.live_resolution"] = "Fusion live: Resolve did not return width/height as a pair from timelineResolution or timelineOutputResolution. Playback/proxy settings are intentionally not used.",
        ["warning.legacy_resolution"] = "Warning: timeline resolution was not determined as a pair; legacy uses 1920x1080",
        ["log.timeline_resolution"] = "Timeline resolution: {width}x{height} ({source})",
        ["error.video_track_index"] = "Invalid video track index: {track}",
        ["error.video_track_add"] = "Resolve did not add the video track: {details}",
        ["error.video_track_count"] = "Resolve did not increase the video track count after AddTrack",
        ["error.video_track_create"] = "Could not create video track V{track}",
        ["error.visualizers_delete"] = "Resolve did not delete old visualizers: {details}",
        ["error.output_dir_legacy"] = "Captured jobs do not contain output_dir for the legacy renderer",
        ["error.output_dir_live"] = "Captured jobs do not contain output_dir for Fusion live",
        ["error.output_dir_insert"] = "Captured jobs do not contain output_dir for legacy insertion",
        ["error.legacy_resolution_missing"] = "Captured jobs do not contain a valid timeline resolution for legacy insertion",
        ["error.overlay_import"] = "Could not import overlay: {path}",
        ["error.legacy_insert"] = "Resolve did not insert the legacy MOV: {details}",
        ["error.legacy_wrong_track"] = "Resolve inserted the legacy MOV on the wrong video track",
        ["error.legacy_incomplete"] = "Not all legacy MOV files were inserted: {inserted} of {total}",
        ["error.project_save"] = "Resolve did not save the project: {details}",
        ["error.engine_missing"] = "Track Visualizer engine was not found: {path}",
        ["log.generator_start"] = "Starting generator...",
        ["status.render_no_console"] = "Rendering without terminal windows...",
        ["error.manifest_missing"] = "Generator did not create manifest.json",
        ["status.render_import"] = "Render complete, importing into Resolve...",
        ["log.fusion_preparing"] = "Preparing Fusion...",
        ["status.fusion_preparing"] = "Preparing Fusion...",
        ["error.live_manifest_missing"] = "Generator did not create live_manifest.json",
        ["preview.pending"] = "Preview for {skin} has not been generated yet",
        ["preview.created"] = "PNG for theme \"{skin}\" was generated.",
        ["preview.generate_prompt"] = "Click Generate preview.",
        ["preview.sample_title"] = "Preview Track Title",
        ["preview.sample_artist"] = "Artist Name",
        ["log.preview_generating"] = "Generating preview...",
        ["error.preview_failed"] = "Preview was not generated: {path}",
        ["status.saving_settings"] = "Saving settings...",
        ["status.checking_project"] = "Checking project and timeline...",
        ["status.scanning_audio"] = "Scanning audio clips...",
        ["status.preparing_jobs"] = "Preparing jobs...",
        ["status.preparing_helper"] = "Preparing fresh helper...",
        ["warning.helper_failed"] = "Warning: fresh Fusion helper was not prepared; old visualizers were preserved: {details}",
        ["warning.live_unavailable"] = "Warning: Fusion live is unavailable; using legacy MOV: {details}",
        ["log.visualizers_deleted"] = "Deleted old visualizers from V{track}: {count}",
        ["status.inserting_fusion"] = "Inserting Fusion...",
        ["warning.fusion"] = "Fusion warning: {details}",
        ["status.legacy_fallback"] = "Legacy fallback...",
        ["status.preparing_legacy"] = "Preparing legacy MOV...",
        ["status.importing_legacy"] = "Importing legacy MOV into Resolve...",
        ["status.saving_project"] = "Saving project...",
        ["status.done"] = "Done",
        ["status.reading_clip_list"] = "Reading clip list...",
        ["status.clip_list_ready"] = "Clip list ready",
        ["status.generating_preview"] = "Generating preview...",
        ["status.preview_ready"] = "Preview ready",
        ["error.project_required"] = "Open or create a DaVinci Resolve project first.",
        ["error.timeline_required"] = "Open a timeline first.",
        ["error.no_audio_clips"] = "No matching audio clips were found on A{tracks}.{hint}{details}",
        ["error.no_audio_path_hint"] = " Resolve sees the clips but does not provide the source audio path. A clip property dump was written to tmp for diagnostics.",
        ["error.details"] = " Details: {details}",
        ["log.audio_found"] = "Audio clips found on A{tracks}: {count}",
        ["log.visualizers_inserted"] = "Visualizers inserted on V{track}: {count}",
        ["log.clips_listed"] = "Clips listed on A{tracks}: {count}",
        ["log.scope_help"] = "In Process clips, enter 3,5-7, leave empty for all, or use @playhead.",
        ["log.style_saved"] = "Style saved: {path}",
        ["log.profile_reset"] = "Profile reset: {skin}",
        ["log.preview_ready"] = "Preview ready: {path}",
        ["error.preview_not_ready"] = "The preview has not been generated yet. Click Generate preview first.",
        ["error.choose_png"] = "Choose a .png file for the fallback cover",
        ["log.logo_selected"] = "Fallback PNG selected: {path}",
        ["log.logo_default"] = "Fallback PNG reset to the default aplus.png",
        ["log.palette_applied"] = "Palette \"{palette}\" applied to theme \"{skin}\"",
        ["log.skin_active"] = "Active theme: {skin}",
        ["notice.color_manual"] = "The native color picker is unavailable on this platform. Enter a #RRGGBB value manually.",
    },
    ru = {
        ["window.title"] = "Визуализатор треков",
        ["app.subtitle"] = "Создает плееры для аудиоклипов текущего таймлайна.",
        ["section.quick_start"] = "Быстрый запуск",
        ["field.audio_tracks"] = "Аудиодорожки",
        ["field.video_track"] = "Видеодорожка",
        ["hint.quick_start"] = "Можно запускать сразу: будут обработаны все подходящие клипы.",
        ["action.update"] = "Создать / обновить визуализаторы",
        ["field.status"] = "Статус",
        ["status.ready"] = "Готово к запуску",
        ["hint.status"] = "Во время обработки здесь отображается текущий этап.",
        ["section.appearance"] = "Оформление",
        ["field.theme"] = "Тема",
        ["field.palette"] = "Палитра темы",
        ["action.apply"] = "Применить",
        ["section.preview"] = "Предпросмотр",
        ["action.create_preview"] = "Создать предпросмотр",
        ["action.open_png"] = "Открыть PNG",
        ["preview.external_hint"] = "Предпросмотр откроется во внешнем приложении.",
        ["advanced.title"] = "Расширенные настройки",
        ["advanced.subtitle"] = "Параметры таймлайна, рендера и внешнего вида. Одновременно открывается одна секция.",
        ["advanced.timeline"] = "Таймлайн и выбор клипов",
        ["field.switch_next"] = "Переключать визуализатор на старте следующего трека",
        ["field.update_scope"] = "Обработать клипы",
        ["scope.placeholder"] = "пусто, 3,5-7 или @playhead",
        ["scope.alias_all"] = "все",
        ["scope.alias_current"] = "текущий",
        ["action.list_clips"] = "Показать список",
        ["scope.hint"] = "Пусто = все клипы; 3,5-7 = номера клипов; @playhead = клип под курсором.",
        ["advanced.render"] = "Вывод и рендер",
        ["field.mode"] = "Режим",
        ["render.mode_auto"] = "Fusion на лету (авто)",
        ["render.mode_legacy"] = "Только legacy MOV",
        ["render.hint"] = "Fusion работает в полноразмерном режиме; при отключенном запекании используется legacy fallback.",
        ["field.player_size"] = "Размер плеера",
        ["field.frame_rate"] = "Частота кадров",
        ["field.render_fps"] = "Рендер",
        ["field.fallback_fps"] = "Запасной FPS",
        ["hint.fallback_fps"] = "Запасной FPS используется только если частоту кадров не удалось получить из таймлайна.",
        ["field.margin"] = "Отступ от края",
        ["field.bake_position"] = "Запекать позицию в полноразмерный оверлей",
        ["field.output_dir"] = "Папка вывода",
        ["advanced.elements"] = "Элементы плеера",
        ["field.brand_text"] = "Подпись бренда",
        ["field.glass"] = "Стекло",
        ["field.cover"] = "Обложка",
        ["field.brand"] = "Бренд",
        ["field.time"] = "Время",
        ["field.progress"] = "Прогресс",
        ["field.marker"] = "Маркер",
        ["field.fallback_logo"] = "Заглушка обложки",
        ["action.choose_png"] = "Выбрать PNG",
        ["action.default"] = "Стандартная",
        ["advanced.typography"] = "Типографика",
        ["field.title"] = "Название",
        ["field.title_timer"] = "Название + блок таймера",
        ["field.color"] = "Цвет",
        ["field.size"] = "Размер",
        ["field.title_font"] = "Шрифт названия",
        ["field.artist_metadata"] = "Артист и метаданные",
        ["field.artist_border"] = "Артист + обводка",
        ["field.artist_size"] = "Размер артиста",
        ["field.meta_size"] = "Размер метаданных",
        ["field.artist_font"] = "Шрифт артиста",
        ["advanced.card"] = "Карточка и цвета",
        ["field.panel"] = "Панель",
        ["field.background_timer"] = "Фон + текст таймера",
        ["field.opacity"] = "Прозрачность",
        ["field.border"] = "Обводка",
        ["field.border_opacity"] = "Прозрачность обводки",
        ["field.shape"] = "Форма",
        ["field.radius"] = "Радиус",
        ["field.glass_strength"] = "Сила стекла",
        ["field.accent"] = "Акцент",
        ["field.progress_line"] = "Линия прогресса",
        ["advanced.actions"] = "Действия со стилем",
        ["hint.style_actions"] = "Сохраните текущий стиль для следующих запусков или верните стандартные значения.",
        ["action.save_style"] = "Сохранить стиль",
        ["action.reset_style"] = "Сбросить стиль",
        ["field.language"] = "Язык",
        ["language.auto"] = "Авто (системный)",
        ["language.en"] = "English",
        ["language.ru"] = "Русский",
        ["language.restart_hint"] = "Язык сохраняется отдельно. Закройте и снова откройте Track Visualizer, чтобы обновить все надписи; значения стиля сохранятся.",
        ["language.saved_reopen"] = "Язык сохранен. Закройте и снова откройте Track Visualizer, чтобы обновить все надписи.",
        ["diagnostics.title"] = "Диагностика",
        ["diagnostics.paths"] = "Пути ниже приведены для справки. Кнопки работают с основным логом.\nОсновной лог: {log}\nDump свойств клипов: {dump}\nПоследняя ошибка: {error}",
        ["section.last_preview"] = "Последний предпросмотр",
        ["preview.not_created"] = "Предпросмотр еще не создан",
        ["action.copy_log"] = "Копировать лог",
        ["action.open_log"] = "Открыть лог",
        ["action.clear_log"] = "Очистить лог",
        ["tab.main"] = "Основное",
        ["tab.advanced"] = "Расширенные",
        ["tab.diagnostics"] = "Диагностика",
        ["skin.classic"] = "Классический",
        ["skin.minimal"] = "Минимал",
        ["skin.portrait_glass"] = "Портретное стекло",
        ["palette.Custom"] = "Пользовательская",
        ["palette.Default"] = "По умолчанию",
        ["palette.Violet"] = "Фиолетовый",
        ["palette.Ice"] = "Лед",
        ["palette.Amber"] = "Янтарный",
        ["palette.Neon"] = "Неон",
        ["palette.Ultraviolet"] = "Ультрафиолет",
        ["palette.Acid"] = "Кислотный",
        ["palette.Crimson"] = "Багровый рок",
        ["palette.Steel"] = "Сталь",
        ["palette.Ember"] = "Уголь и пламя",
        ["palette.GoldSignal"] = "Золотой сигнал",
        ["error.last"] = "Последняя ошибка: {message}",
        ["error.unknown"] = "Неизвестная ошибка",
        ["error.log_prefix"] = "ОШИБКА: {message}",
        ["status.error"] = "Ошибка: {message}",
        ["status.processing"] = "Обработка {index}/{total}",
        ["status.reading_metadata"] = "Чтение тегов {index}/{total}",
        ["status.preparing_clip"] = "Подготовка клипа {index}/{total}",
        ["status.rendering"] = "Рендер {index}/{total}: {percent}%",
        ["status.preparing"] = "Подготовка...",
        ["status.busy"] = "Идет обработка...",
        ["error.runner_missing"] = "Не найден runner Track Visualizer: {path}",
        ["error.runner_launch"] = "Не удалось запустить runner Track Visualizer: {details}",
        ["error.windows_wide_launch"] = "Для этого пути недоступен Unicode-безопасный запуск Windows: {details}",
        ["error.runner_timeout"] = "Runner не завершил задачу за {seconds} сек",
        ["error.runner_exit"] = "Runner завершился с кодом {code}: {details}",
        ["error.runner_completion"] = "Runner записал некорректный файл завершения: {path}",
        ["error.settings_temp_open"] = "Не удалось открыть временный файл настроек: {details}",
        ["error.settings_temp_write"] = "Не удалось записать временный файл настроек: {details}",
        ["error.settings_temp_verify"] = "Проверка временного файла настроек не пройдена",
        ["error.settings_invalid_json"] = "Замена настроек некорректным JSON отменена",
        ["error.settings_backup"] = "Не удалось создать резервную копию настроек перед заменой: {details}",
        ["error.settings_replace"] = "Не удалось заменить настройки: {details}",
        ["log.clip_properties_no_path"] = "Свойства клипа без пути: {details}",
        ["log.overlap_same_start"] = "Наложения с одинаковым стартом решены по верхней аудиодорожке: {count}",
        ["log.zero_length"] = "Пропущен визуализатор нулевой длины: {name}",
        ["log.switch_trimmed"] = "Переключение визуализатора на старте следующего трека: {name} обрезано {from}f -> {to}f",
        ["log.clip_numbers"] = "Номера клипов на таймлайне:",
        ["log.more_clips"] = "...и еще клипов: {count}",
        ["error.no_clip_at_playhead"] = "Под playhead нет активного аудиоклипа на {time}",
        ["log.playhead_selected"] = "По playhead выбран клип #{number}",
        ["error.scope_invalid"] = "Поле обновления: введи номера клипов, например 3,5-7, оставь пустым для всех или используй @playhead",
        ["error.unknown_clip_numbers"] = "Неизвестные номера клипов: {numbers}",
        ["log.partial_update"] = "Частичное обновление: {clips} (предыдущие клипы добавляются при необходимости для границ кроссфейда)",
        ["log.track_missing"] = "Пропущена A{track}: дорожка не существует",
        ["summary.track_missing"] = "A{track} нет дорожки (count={count})",
        ["log.clip_no_path"] = "Пропущен аудиоклип без пути к файлу: {name}",
        ["log.clip_dump"] = "Dump свойств клипа: {path}",
        ["error.live_resolution"] = "Fusion live: Resolve не вернул width/height одной парой из timelineResolution или timelineOutputResolution. Playback/proxy settings намеренно не используются.",
        ["warning.legacy_resolution"] = "Предупреждение: разрешение таймлайна не определено парой; для legacy используется 1920x1080",
        ["log.timeline_resolution"] = "Разрешение таймлайна: {width}x{height} ({source})",
        ["error.video_track_index"] = "Некорректный индекс видеодорожки: {track}",
        ["error.video_track_add"] = "Resolve не добавил видеодорожку: {details}",
        ["error.video_track_count"] = "Resolve не увеличил число видеодорожек после AddTrack",
        ["error.video_track_create"] = "Не удалось создать видеодорожку V{track}",
        ["error.visualizers_delete"] = "Resolve не удалил старые визуализаторы: {details}",
        ["error.output_dir_legacy"] = "В captured jobs отсутствует output_dir для legacy renderer",
        ["error.output_dir_live"] = "В captured jobs отсутствует output_dir для Fusion live",
        ["error.output_dir_insert"] = "В captured jobs отсутствует output_dir для legacy insert",
        ["error.legacy_resolution_missing"] = "В captured jobs отсутствует корректная timeline resolution для legacy insert",
        ["error.overlay_import"] = "Не удалось импортировать оверлей: {path}",
        ["error.legacy_insert"] = "Resolve не вставил legacy MOV: {details}",
        ["error.legacy_wrong_track"] = "Resolve вставил legacy MOV не на запрошенную видеодорожку",
        ["error.legacy_incomplete"] = "Вставлено не все legacy MOV: {inserted} из {total}",
        ["error.project_save"] = "Resolve не сохранил проект: {details}",
        ["error.engine_missing"] = "Не найден engine Track Visualizer: {path}",
        ["log.generator_start"] = "Запуск генератора...",
        ["status.render_no_console"] = "Рендер без терминальных окон...",
        ["error.manifest_missing"] = "Генератор не создал manifest.json",
        ["status.render_import"] = "Рендер готов, импорт в Resolve...",
        ["log.fusion_preparing"] = "Подготовка Fusion...",
        ["status.fusion_preparing"] = "Подготовка Fusion...",
        ["error.live_manifest_missing"] = "Генератор не создал live_manifest.json",
        ["preview.pending"] = "Предпросмотр {skin} еще не создан",
        ["preview.created"] = "PNG для темы «{skin}» создан.",
        ["preview.generate_prompt"] = "Нажми Сгенерировать предпросмотр.",
        ["preview.sample_title"] = "Название трека для предпросмотра",
        ["preview.sample_artist"] = "Имя артиста",
        ["log.preview_generating"] = "Генерация предпросмотра...",
        ["error.preview_failed"] = "Предпросмотр не создан: {path}",
        ["status.saving_settings"] = "Сохранение настроек...",
        ["status.checking_project"] = "Проверка проекта и таймлайна...",
        ["status.scanning_audio"] = "Сканирование аудиоклипов...",
        ["status.preparing_jobs"] = "Подготовка jobs...",
        ["status.preparing_helper"] = "Подготовка fresh helper...",
        ["warning.helper_failed"] = "Предупреждение: fresh Fusion helper не подготовлен; старые визуализаторы сохранены: {details}",
        ["warning.live_unavailable"] = "Предупреждение: Fusion live недоступен, используется legacy MOV: {details}",
        ["log.visualizers_deleted"] = "Удалено старых визуализаторов с V{track}: {count}",
        ["status.inserting_fusion"] = "Вставка Fusion...",
        ["warning.fusion"] = "Предупреждение Fusion: {details}",
        ["status.legacy_fallback"] = "Legacy fallback...",
        ["status.preparing_legacy"] = "Подготовка legacy MOV...",
        ["status.importing_legacy"] = "Импорт legacy MOV в Resolve...",
        ["status.saving_project"] = "Сохранение проекта...",
        ["status.done"] = "Готово",
        ["status.reading_clip_list"] = "Чтение списка клипов...",
        ["status.clip_list_ready"] = "Список клипов готов",
        ["status.generating_preview"] = "Генерация предпросмотра...",
        ["status.preview_ready"] = "Предпросмотр готов",
        ["error.project_required"] = "Сначала открой или создай проект DaVinci Resolve.",
        ["error.timeline_required"] = "Сначала открой таймлайн.",
        ["error.no_audio_clips"] = "Не найдены подходящие аудиоклипы на A{tracks}.{hint}{details}",
        ["error.no_audio_path_hint"] = " Resolve видит клипы, но не отдает путь к исходному аудиофайлу. Dump свойств клипа записан в tmp для диагностики.",
        ["error.details"] = " Детали: {details}",
        ["log.audio_found"] = "Найдено аудиоклипов на A{tracks}: {count}",
        ["log.visualizers_inserted"] = "Вставлено визуализаторов на V{track}: {count}",
        ["log.clips_listed"] = "Клипы перечислены на A{tracks}: {count}",
        ["log.scope_help"] = "В поле обновления можно указать 3,5-7, оставить пустым для всех или использовать @playhead.",
        ["log.style_saved"] = "Стиль сохранен: {path}",
        ["log.profile_reset"] = "Профиль сброшен: {skin}",
        ["log.preview_ready"] = "Предпросмотр готов: {path}",
        ["error.preview_not_ready"] = "Предпросмотр еще не создан. Сначала нажми «Создать предпросмотр».",
        ["error.choose_png"] = "Выбери .png файл для заглушки обложки",
        ["log.logo_selected"] = "Выбрана PNG-заглушка: {path}",
        ["log.logo_default"] = "PNG-заглушка сброшена на стандартный aplus.png",
        ["log.palette_applied"] = "Палитра «{palette}» применена к теме «{skin}»",
        ["log.skin_active"] = "Активная тема: {skin}",
        ["notice.color_manual"] = "Системный выбор цвета недоступен на этой платформе. Введите значение #RRGGBB вручную.",
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

local THEME = {
    default_skin = "classic",
    skins = { "classic", "minimal", "portrait_glass" },
    layouts = {
        classic = { width = 640, height = 160, margin = 48, bake_position = true },
        minimal = { width = 640, height = 176, margin = 48, bake_position = true },
        portrait_glass = { width = 420, height = 640, margin = 48, bake_position = true },
    },
    design_defaults = {
        minimal = {
            panel_color = "#241704", panel_alpha = 224,
            border_color = "#F2A900", border_alpha = 255,
            primary_text_color = "#FFD84A", secondary_text_color = "#F2A900",
            corner_radius = 2, title_size = 32, artist_size = 16, meta_size = 28,
            title_font_family = "Impact", artist_font_family = "Courier New",
        },
        portrait_glass = {
            panel_color = "#171125", panel_alpha = 164,
            border_color = "#C4B5FD", border_alpha = 92,
            primary_text_color = "#FFF8ED", secondary_text_color = "#D8CCF2",
            accent_color = "#A78BFA", track_color = "#D8CCF2",
            corner_radius = 24, glass_strength = 70,
            title_size = 30, artist_size = 17, meta_size = 15,
        },
    },
    default_palettes = { classic = "Default", minimal = "GoldSignal", portrait_glass = "Violet" },
    palettes = {
        Default = {},
        Violet = { panel_color = "#1A1028", panel_alpha = 158, border_color = "#B77CFF", border_alpha = 82, primary_text_color = "#FFF4D6", secondary_text_color = "#DCCBFF", accent_color = "#FFB454", track_color = "#DCCBFF", glass_strength = 68 },
        Ice = { panel_color = "#101C23", panel_alpha = 150, border_color = "#B8F2FF", border_alpha = 74, primary_text_color = "#F7FDFF", secondary_text_color = "#C9F5FF", accent_color = "#70E7FF", track_color = "#D7F9FF", glass_strength = 72 },
        Amber = { panel_color = "#21160D", panel_alpha = 156, border_color = "#FFB86B", border_alpha = 76, primary_text_color = "#FFF2DB", secondary_text_color = "#FFD29A", accent_color = "#FF9D3B", track_color = "#FFD29A", glass_strength = 60 },
        Neon = { panel_color = "#090B16", panel_alpha = 178, border_color = "#00E5FF", border_alpha = 118, primary_text_color = "#FF3DF2", secondary_text_color = "#9AF7FF", accent_color = "#00F5D4", track_color = "#43506B", glass_strength = 72 },
        Ultraviolet = { panel_color = "#10091E", panel_alpha = 176, border_color = "#8D5CFF", border_alpha = 112, primary_text_color = "#F4EEFF", secondary_text_color = "#C4A7FF", accent_color = "#FF4FD8", track_color = "#655089", glass_strength = 76 },
        Acid = { panel_color = "#0D120B", panel_alpha = 184, border_color = "#B8FF3D", border_alpha = 108, primary_text_color = "#E8FF65", secondary_text_color = "#B8FF3D", accent_color = "#F4FF00", track_color = "#52612E", glass_strength = 58 },
        Crimson = { panel_color = "#16090A", panel_alpha = 190, border_color = "#E04444", border_alpha = 116, primary_text_color = "#FFF1E8", secondary_text_color = "#FF7A66", accent_color = "#FF2E2E", track_color = "#692929", glass_strength = 48 },
        Steel = { panel_color = "#111417", panel_alpha = 194, border_color = "#A9B2BC", border_alpha = 104, primary_text_color = "#F1F3F5", secondary_text_color = "#A9B2BC", accent_color = "#D5DADE", track_color = "#4A5158", glass_strength = 42 },
        Ember = { panel_color = "#170D08", panel_alpha = 188, border_color = "#FF6A2A", border_alpha = 110, primary_text_color = "#FFE1C2", secondary_text_color = "#FF9A52", accent_color = "#FF3D00", track_color = "#71321C", glass_strength = 52 },
        GoldSignal = { panel_color = "#241704", panel_alpha = 224, border_color = "#F2A900", border_alpha = 255, primary_text_color = "#FFD84A", secondary_text_color = "#F2A900", accent_color = "#FFD84A", track_color = "#F2A900", glass_strength = 0 },
    },
    palette_orders = {
        classic = { "Custom", "Default", "Violet", "Ice", "Amber" },
        minimal = { "Custom", "GoldSignal", "Neon", "Acid", "Steel", "Crimson" },
        portrait_glass = { "Custom", "Violet", "Ice", "Ultraviolet", "Amber", "Crimson", "Ember" },
    },
    palette_keys = { "panel_color", "panel_alpha", "border_color", "border_alpha", "primary_text_color", "secondary_text_color", "accent_color", "track_color", "glass_strength" },
}

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

local resolve = nil
local fusion = rawget(_G, "fusion")
local ui = nil
local dispatcher = nil
local win = nil
local active_skin = THEME.default_skin
local skin_profiles = nil
local suppress_skin_events = false
local suppress_language_events = false
local apply_active_profile_to_ui
local update_skin_ui_visibility
local refresh_active_preview

local function skin_label(skin)
    return tr("skin." .. tostring(skin))
end

local function palette_label(palette)
    return tr("palette." .. tostring(palette))
end

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
        return
    end
    local target = os.clock() + seconds
    while os.clock() < target do end
end

local function wait_for_file(path, timeout_seconds)
    local timeout = tonumber(timeout_seconds) or 3600
    local started = os.time()
    while not file_exists(path) do
        if os.time() - started > timeout then
            return false
        end
        wait_seconds(0.15)
    end
    return true
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

function THEME.is_supported_skin(value)
    for _, skin in ipairs(THEME.skins) do
        if value == skin then return true end
    end
    return false
end

function THEME.enforce_design(skin, design)
    local result = copy_table(DEFAULT_DESIGN)
    update_table(result, THEME.design_defaults[skin] or {})
    update_table(result, design or {})
    if skin == "minimal" then
        result.show_cover = false
        result.show_brand = false
        result.show_time = true
        result.show_progress = false
        result.show_knob = false
        result.glass_enabled = false
    elseif skin == "portrait_glass" then
        result.show_cover = true
        result.show_brand = false
        result.show_time = true
        result.show_progress = true
        result.show_knob = false
        result.glass_enabled = true
    end
    return result
end

function THEME.sanitize_design(skin, source)
    local design = copy_table(DEFAULT_DESIGN)
    update_table(design, THEME.design_defaults[skin] or {})
    local color_fields = {
        panel_color = true,
        border_color = true,
        primary_text_color = true,
        secondary_text_color = true,
        accent_color = true,
        track_color = true,
    }
    if type(source) == "table" and source ~= JSON_NULL then
        for key, default_value in pairs(DEFAULT_DESIGN) do
            local value = source[key]
            if type(value) == type(default_value) then
                design[key] = color_fields[key] and normalize_hex(value, default_value) or value
            end
        end
    end
    return THEME.enforce_design(skin, design)
end

function THEME.default_profile(skin)
    local layout = THEME.layouts[skin] or THEME.layouts[THEME.default_skin]
    local palette = THEME.default_palettes[skin] or "Default"
    return {
        base_width = layout.width,
        base_height = layout.height,
        margin = layout.margin,
        bake_position = layout.bake_position,
        palette = palette,
        design = THEME.enforce_design(skin, THEME.palette_design(palette, skin)),
    }
end

function THEME.palette_order(skin)
    return THEME.palette_orders[skin] or THEME.palette_orders[THEME.default_skin]
end

function THEME.palette_allowed(skin, palette_name)
    for _, name in ipairs(THEME.palette_order(skin)) do
        if name == palette_name then return true end
    end
    return false
end

function THEME.palette_design(palette_name, skin)
    local design = copy_table(DEFAULT_DESIGN)
    update_table(design, THEME.design_defaults[skin] or {})
    update_table(design, THEME.palettes[palette_name] or {})
    return design
end

function THEME.detect_palette(design, skin)
    for _, palette_name in ipairs(THEME.palette_order(skin)) do
        if palette_name ~= "Custom" then
            local candidate = THEME.palette_design(palette_name, skin)
            local matches = true
            for _, key in ipairs(THEME.palette_keys) do
                if design[key] ~= candidate[key] then matches = false break end
            end
            if matches then return palette_name end
        end
    end
    return "Custom"
end

function THEME.load_profile(skin, source)
    local profile = THEME.default_profile(skin)
    if type(source) ~= "table" or source == JSON_NULL then return profile end
    local width = tonumber(source.base_width or source.width or source.player_width)
    local height = tonumber(source.base_height or source.height or source.player_height)
    local margin = tonumber(source.margin or source.player_margin)
    if width then profile.base_width = math.max(240, math.min(1920, math.floor(width + 0.5))) end
    if height then profile.base_height = math.max(80, math.min(720, math.floor(height + 0.5))) end
    if margin then profile.margin = math.max(0, math.min(400, math.floor(margin + 0.5))) end
    if type(source.bake_position) == "boolean" then profile.bake_position = source.bake_position end
    profile.design = THEME.sanitize_design(skin, source.design)
    profile.palette = type(source.palette) == "string" and THEME.palette_allowed(skin, source.palette)
        and source.palette or THEME.detect_palette(profile.design, skin)
    return profile
end

function THEME.default_profiles()
    local profiles = {}
    for _, skin in ipairs(THEME.skins) do profiles[skin] = THEME.default_profile(skin) end
    return profiles
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
    local settings = {
        active_skin = THEME.default_skin,
        profiles = THEME.default_profiles(),
        fallback_logo_path = default_fallback_logo_path(),
        renderer_mode = DEFAULT_RENDERER_MODE,
        -- Releases before localization were Russian-only, so migrate their settings explicitly to Russian.
        language_mode = existing_settings and "ru" or "auto",
    }
    local text = recovered_text or read_file(path)
    if text == "" then return settings end
    local decode_ok, root = pcall(function() return json_decode(text) end)
    if not decode_ok or type(root) ~= "table" or root == JSON_NULL then return settings end

    if type(root.renderer_mode) == "string" and (root.renderer_mode == "auto" or root.renderer_mode == "legacy_mov") then
        settings.renderer_mode = root.renderer_mode
    end
    if root.language_mode == "auto" or root.language_mode == "en" or root.language_mode == "ru" then
        settings.language_mode = root.language_mode
    end
    if type(root.fallback_logo_path) == "string" and trim(root.fallback_logo_path) ~= "" then
        settings.fallback_logo_path = root.fallback_logo_path
    end
    local has_v7_profiles = type(root.profiles) == "table" and root.profiles ~= JSON_NULL
    if has_v7_profiles then
        for _, skin in ipairs(THEME.skins) do settings.profiles[skin] = THEME.load_profile(skin, root.profiles[skin]) end
        if THEME.is_supported_skin(root.active_skin) then settings.active_skin = root.active_skin end
    else
        -- v6 had one design/layout. It becomes Classic only; new skins retain independent defaults.
        local legacy_layout = nil
        if type(root.classic_layout) == "table" and root.classic_layout ~= JSON_NULL then
            legacy_layout = root.classic_layout
        elseif type(root.layout) == "table" and root.layout ~= JSON_NULL then
            legacy_layout = root.layout
        end
        local legacy_profile = legacy_layout and copy_table(legacy_layout) or {}
        legacy_profile.design = type(root.design) == "table" and root.design or nil
        settings.profiles.classic = THEME.load_profile("classic", legacy_profile)
        settings.profiles.classic.palette = THEME.detect_palette(settings.profiles.classic.design, "classic")
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
    local profiles = {}
    for _, skin in ipairs(THEME.skins) do
        profiles[skin] = THEME.load_profile(skin, type(settings.profiles) == "table" and settings.profiles[skin] or nil)
    end
    local payload = {
        settings_version = 1,
        style_version = STYLE_VERSION,
        active_skin = THEME.is_supported_skin(settings.active_skin) and settings.active_skin or THEME.default_skin,
        profiles = profiles,
        fallback_logo_path = settings.fallback_logo_path,
        renderer_mode = settings.renderer_mode == "legacy_mov" and "legacy_mov" or DEFAULT_RENDERER_MODE,
        language_mode = settings.language_mode == "en" and "en" or settings.language_mode == "ru" and "ru" or "auto",
    }
    write_settings_safely(settings_path(), json_encode(payload, ""))
end

local function append_log(message)
    if not win then return end
    local log = win:Find("Log")
    if not log then return end
    local previous = ""
    pcall(function() previous = log.PlainText or "" end)
    if type(previous) ~= "string" or previous == "" then
        pcall(function() previous = log.Text or "" end)
    end
    if type(previous) ~= "string" then previous = "" end
    local text = trim(previous .. "\n" .. tostring(message or ""))
    pcall(function() log.PlainText = text end)
    pcall(function() log.Text = text end)
    pcall(function() write_file(log_path(), text) end)
    pcall(function()
        log:Update()
        log:Repaint()
        win:Repaint()
    end)
end

local set_progress

local function set_last_error(message)
    local text = tostring(message or "")
    local error_path = path_join(install_root(), "last_error.txt")
    pcall(function() write_file(error_path, text) end)
    local label = win and win:Find("LastError") or nil
    if label then
        local has_error = trim(text) ~= ""
        label.Text = has_error and tr("error.last", { message = short_text(text, 240) }) or ""
        label.Hidden = not has_error
        pcall(function() label:Update() end)
        pcall(function() win:RecalcLayout() end)
    end
end

local function report_error(err)
    local message = tostring(err or tr("error.unknown"))
    append_log(tr("error.log_prefix", { message = message }))
    set_last_error(message)
    set_progress(0, tr("status.error", { message = short_text(message, 90) }))
end

function set_progress(percent, status)
    if not win then return end
    local status_label = win:Find("ProgressStatus")
    if status_label and status then status_label.Text = status end
    pcall(function()
        if status_label then status_label:Update() end
        win:Repaint()
    end)
end

local function progress_from_engine_line(line)
    local index, total = tostring(line or ""):match("^%[(%d+)/(%d+)%]")
    if not index or not total then return end
    index = tonumber(index) or 1
    total = math.max(1, tonumber(total) or 1)
    local per_job = 0.05
    local status = tr("status.processing", { index = index, total = total })

    if line:find("Reading metadata", 1, true) then
        per_job = 0.05
        status = tr("status.reading_metadata", { index = index, total = total })
    elseif line:find("Preparing segment", 1, true) or line:find("Preparing player", 1, true) then
        per_job = 0.15
        status = tr("status.preparing_clip", { index = index, total = total })
    elseif line:find("Rendering frames", 1, true) then
        local render_percent = tonumber(line:match("%((%d+)%%%)")) or 0
        per_job = 0.20 + 0.75 * (render_percent / 100.0)
        status = tr("status.rendering", { index = index, total = total, percent = math.floor(render_percent + 0.5) })
    end

    local overall = ((index - 1) + per_job) / total * 100.0
    set_progress(overall, status)
end

local function process_runner_stdout(stdout_path, processed_len)
    local text = read_file(stdout_path)
    local current_len = string.len(text)
    if current_len <= processed_len then return processed_len end
    local chunk = string.sub(text, processed_len + 1)
    for line in chunk:gmatch("[^\r\n]+") do
        if trim(line) ~= "" then
            append_log(line)
            progress_from_engine_line(line)
        end
    end
    return current_len
end

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

local function run_runner_config(config, name)
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
    if launched then claimed = wait_for_runner_claim(task_path) end
    if not claimed then
        remove_file(task_path)
        if PLATFORM.windows and contains_non_ascii(runner) and not launched then
            launch_error = tr("error.windows_wide_launch", { details = launch_error })
        end
        error(tr("error.runner_launch", { details = launch_error or "runner did not claim the queued task" }))
    end

    if tostring(queued_config.mode or "run") == "open" then
        return
    end

    if done_path == "" then return end
    local timeout = tonumber(config.timeout_seconds) or 21600
    local started = os.time()
    local processed_len = 0
    while not file_exists(done_path) do
        processed_len = process_runner_stdout(stdout_path, processed_len)
        if os.time() - started > timeout then
            error(tr("error.runner_timeout", { seconds = timeout }))
        end
        wait_seconds(0.2)
        pcall(function() win:Repaint() end)
    end
    processed_len = process_runner_stdout(stdout_path, processed_len)

    local done_text = read_file(done_path)
    local completion_ok, completion = pcall(function() return json_decode(done_text) end)
    local code = completion_ok and type(completion) == "table" and completion ~= JSON_NULL
        and completion.returncode or nil
    if type(code) ~= "number" or code ~= code or code % 1 ~= 0 then
        remove_file(done_path)
        if stdout_path ~= "" then remove_file(stdout_path) end
        error(tr("error.runner_completion", { path = done_path }))
    end
    if code ~= 0 then
        local stdout_text = read_file(stdout_path)
        remove_file(done_path)
        if stdout_path ~= "" then remove_file(stdout_path) end
        error(tr("error.runner_exit", { code = code, details = short_text(stdout_text, 500) }))
    end
    remove_file(done_path)
    if stdout_path ~= "" then remove_file(stdout_path) end
    remove_file(task_path)
end

local function set_busy(is_busy)
    local button = win:Find("UpdateFromTimeline")
    if button then
        button.Enabled = not is_busy
        button.Text = is_busy and tr("status.busy") or tr("action.update")
        pcall(function() button:Update() end)
    end
    local list_button = win:Find("ListClips")
    if list_button then
        list_button.Enabled = not is_busy
        pcall(function() list_button:Update() end)
    end
    local preview_button = win:Find("PreviewStyle")
    if preview_button then
        preview_button.Enabled = not is_busy
        pcall(function() preview_button:Update() end)
    end
    local renderer_mode = win:Find("RendererMode")
    if renderer_mode then
        renderer_mode.Enabled = not is_busy
        pcall(function() renderer_mode:Update() end)
    end
    for _, element_id in ipairs({ "SkinSelector", "PaletteSelector", "ApplyPalette" }) do
        local element = win:Find(element_id)
        if element then
            element.Enabled = not is_busy
            pcall(function() element:Update() end)
        end
    end
    if is_busy then
        set_progress(0, tr("status.preparing"))
    end
end

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

local function read_renderer_mode()
    local element = win and win:Find("RendererMode") or nil
    if not element then return DEFAULT_RENDERER_MODE end
    local index = nil
    pcall(function() index = tonumber(element.CurrentIndex) end)
    if index == 1 then return "legacy_mov" end
    local text = ""
    pcall(function() text = tostring(element.CurrentText or "") end)
    if text:lower():find("legacy", 1, true) then return "legacy_mov" end
    return DEFAULT_RENDERER_MODE
end

local function renderer_mode_from_ui()
    return read_renderer_mode()
end

local function apply_renderer_mode_to_ui(mode)
    local element = win and win:Find("RendererMode") or nil
    if not element then return end
    pcall(function() element.CurrentIndex = mode == "legacy_mov" and 1 or 0 end)
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

local function pick_windows_color(field_id, fallback)
    if not PLATFORM.windows then error("Windows color picker called on a non-Windows platform") end
    local powershell_path = windows_powershell_path()
    if powershell_path == "" then
        error("Windows PowerShell was not found under SystemRoot or WINDIR")
    end
    local current = normalize_hex(text_field(field_id, fallback), fallback)
    local r, g, b = hex_to_rgb(current)
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
    selected = normalize_hex(selected, "")
    if selected ~= "" then
        set_text(field_id, selected)
        if save_current_style then save_current_style() end
    end
end

local function read_design_from_ui()
    local design = {
        brand_text = trim(text_field("BrandText", DEFAULT_DESIGN.brand_text)) ~= "" and trim(text_field("BrandText", DEFAULT_DESIGN.brand_text)) or DEFAULT_DESIGN.brand_text,
        title_font_family = trim(text_field("TitleFontFamily", DEFAULT_DESIGN.title_font_family)) ~= "" and trim(text_field("TitleFontFamily", DEFAULT_DESIGN.title_font_family)) or DEFAULT_DESIGN.title_font_family,
        artist_font_family = trim(text_field("ArtistFontFamily", DEFAULT_DESIGN.artist_font_family)) ~= "" and trim(text_field("ArtistFontFamily", DEFAULT_DESIGN.artist_font_family)) or DEFAULT_DESIGN.artist_font_family,
        show_cover = check_field("ShowCover", true),
        show_brand = check_field("ShowBrand", true),
        show_time = check_field("ShowTime", true),
        show_progress = check_field("ShowProgress", true),
        show_knob = check_field("ShowKnob", true),
        glass_enabled = check_field("GlassEnabled", true),
        panel_color = normalize_hex(text_field("PanelColor", DEFAULT_DESIGN.panel_color), DEFAULT_DESIGN.panel_color),
        panel_alpha = int_field("PanelAlpha", DEFAULT_DESIGN.panel_alpha, 0, 255),
        border_color = normalize_hex(text_field("BorderColor", DEFAULT_DESIGN.border_color), DEFAULT_DESIGN.border_color),
        border_alpha = int_field("BorderAlpha", DEFAULT_DESIGN.border_alpha, 0, 255),
        primary_text_color = normalize_hex(text_field("PrimaryTextColor", DEFAULT_DESIGN.primary_text_color), DEFAULT_DESIGN.primary_text_color),
        secondary_text_color = normalize_hex(text_field("SecondaryTextColor", DEFAULT_DESIGN.secondary_text_color), DEFAULT_DESIGN.secondary_text_color),
        accent_color = normalize_hex(text_field("AccentColor", DEFAULT_DESIGN.accent_color), DEFAULT_DESIGN.accent_color),
        track_color = normalize_hex(text_field("TrackColor", DEFAULT_DESIGN.track_color), DEFAULT_DESIGN.track_color),
        corner_radius = int_field("CornerRadius", DEFAULT_DESIGN.corner_radius, 0, 64),
        glass_strength = int_field("GlassStrength", DEFAULT_DESIGN.glass_strength, 0, 100),
        title_size = int_field("TitleSize", DEFAULT_DESIGN.title_size, 10, 48),
        artist_size = int_field("ArtistSize", DEFAULT_DESIGN.artist_size, 8, 36),
        meta_size = int_field("MetaSize", DEFAULT_DESIGN.meta_size, 8, 30),
    }
    return THEME.enforce_design(active_skin, design)
end

local function read_fallback_logo_path()
    local path = trim(text_field("FallbackLogoPath", default_fallback_logo_path())):gsub('^"', ''):gsub('"$', '')
    if path ~= "" then return path end
    return default_fallback_logo_path()
end

local function read_active_layout_from_ui()
    local defaults = THEME.layouts[active_skin] or THEME.layouts[THEME.default_skin]
    return {
        base_width = int_field("Width", defaults.width, 240, 1920),
        base_height = int_field("Height", defaults.height, 80, 720),
        margin = int_field("PlayerMargin", defaults.margin, 0, 400),
        bake_position = check_field("BakePosition", defaults.bake_position),
    }
end

local function capture_active_profile()
    if not skin_profiles then skin_profiles = THEME.default_profiles() end
    local layout = read_active_layout_from_ui()
    local design = read_design_from_ui()
    skin_profiles[active_skin] = {
        base_width = layout.base_width,
        base_height = layout.base_height,
        margin = layout.margin,
        bake_position = layout.bake_position,
        palette = THEME.detect_palette(design, active_skin),
        design = design,
    }
    local palette = win and win:Find("PaletteSelector") or nil
    if palette and THEME.palette_index then
        pcall(function() palette.CurrentIndex = THEME.palette_index(skin_profiles[active_skin].palette) end)
    end
    return skin_profiles[active_skin]
end

function save_current_style()
    capture_active_profile()
    save_settings({
        active_skin = active_skin,
        profiles = skin_profiles,
        fallback_logo_path = read_fallback_logo_path(),
        renderer_mode = renderer_mode_from_ui(),
        language_mode = language_mode_from_ui(),
    })
end

local function apply_design_to_ui(design)
    local merged = THEME.enforce_design(active_skin, design)
    set_text("BrandText", merged.brand_text)
    set_text("TitleFontFamily", merged.title_font_family)
    set_text("ArtistFontFamily", merged.artist_font_family)
    set_checked("ShowCover", merged.show_cover)
    set_checked("ShowBrand", merged.show_brand)
    set_checked("ShowTime", merged.show_time)
    set_checked("ShowProgress", merged.show_progress)
    set_checked("ShowKnob", merged.show_knob)
    set_checked("GlassEnabled", merged.glass_enabled)
    set_text("PanelColor", normalize_hex(merged.panel_color, DEFAULT_DESIGN.panel_color))
    set_text("BorderColor", normalize_hex(merged.border_color, DEFAULT_DESIGN.border_color))
    set_text("PrimaryTextColor", normalize_hex(merged.primary_text_color, DEFAULT_DESIGN.primary_text_color))
    set_text("SecondaryTextColor", normalize_hex(merged.secondary_text_color, DEFAULT_DESIGN.secondary_text_color))
    set_text("AccentColor", normalize_hex(merged.accent_color, DEFAULT_DESIGN.accent_color))
    set_text("TrackColor", normalize_hex(merged.track_color, DEFAULT_DESIGN.track_color))
    set_number("PanelAlpha", merged.panel_alpha)
    set_number("BorderAlpha", merged.border_alpha)
    set_number("CornerRadius", merged.corner_radius)
    set_number("GlassStrength", merged.glass_strength)
    set_number("TitleSize", merged.title_size)
    set_number("ArtistSize", merged.artist_size)
    set_number("MetaSize", merged.meta_size)
end

function THEME.palette_index(palette_name)
    for index, name in ipairs(THEME.palette_order(active_skin)) do
        if name == palette_name then return index - 1 end
    end
    return 0
end

function THEME.skin_index(skin_name)
    for index, name in ipairs(THEME.skins) do
        if name == skin_name then return index - 1 end
    end
    return 0
end

apply_active_profile_to_ui = function()
    if not skin_profiles then skin_profiles = THEME.default_profiles() end
    local profile = THEME.load_profile(active_skin, skin_profiles[active_skin])
    skin_profiles[active_skin] = profile
    set_number("Width", profile.base_width)
    set_number("Height", profile.base_height)
    set_number("PlayerMargin", profile.margin)
    set_checked("BakePosition", profile.bake_position)
    apply_design_to_ui(profile.design)
    local palette = win and win:Find("PaletteSelector") or nil
    if palette then
        pcall(function() palette:Clear() end)
        local labels = {}
        for _, palette_name in ipairs(THEME.palette_order(active_skin)) do
            table.insert(labels, palette_label(palette_name))
        end
        pcall(function() palette:AddItems(labels) end)
        pcall(function() palette.CurrentIndex = THEME.palette_index(profile.palette) end)
    end
    local active_skin_label = win and win:Find("ActiveSkinLabel") or nil
    if active_skin_label then active_skin_label.Text = skin_label(active_skin) end
    if update_skin_ui_visibility then update_skin_ui_visibility() end
    if refresh_active_preview then refresh_active_preview() end
end

local function frame(value)
    return math.floor((tonumber(value) or 0) + 0.5)
end

local function seconds(value)
    local parsed = tonumber(value) or 0
    if parsed < 0 then return 0 end
    return parsed
end

local function timeline_fps(project, timeline)
    local owners = { timeline, project }
    for _, owner in ipairs(owners) do
        local ok, raw = pcall(function() return owner:GetSetting("timelineFrameRate") end)
        if ok and raw and tostring(raw) ~= "" then
            local fps_text = tostring(raw)
            fps_text = fps_text:gsub("DF", ""):gsub("df", ""):gsub(",", ".")
            fps_text = fps_text:match("%d+%.?%d*") or ""
            local value = tonumber(fps_text)
            if value then return value end
        end
    end
    return int_field("Fps", 30, 1, 120)
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

local function resolve_overlap_jobs(jobs, fps)
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
    local dropped_same_start = #jobs - #filtered
    sorted_jobs(filtered)
    if dropped_same_start > 0 then
        append_log(tr("log.overlap_same_start", { count = dropped_same_start }))
    end

    local switch_on_next = check_field("SwitchOnNextStart", true)
    local resolved = {}
    for index, job in ipairs(filtered) do
        local start_frame = tonumber(job.record_frame) or 0
        local end_frame = tonumber(job.end_frame) or 0
        local visible_end = end_frame
        if switch_on_next then
            for next_index = index + 1, #filtered do
                local next_start = tonumber(filtered[next_index].record_frame) or 0
                if next_start > start_frame then
                    if next_start < visible_end then visible_end = next_start end
                    break
                end
            end
        end
        local visible_frames = math.max(0, visible_end - start_frame)
        if visible_frames <= 0 then
            append_log(tr("log.zero_length", { name = job.timeline_item_name or "" }))
        else
            if visible_frames < (tonumber(job.duration_frames) or 0) then
                append_log(tr("log.switch_trimmed", {
                    name = job.timeline_item_name or "", from = job.duration_frames, to = visible_frames,
                }))
            end
            local item = copy_table(job)
            item.visible_end_frame = visible_end
            item.duration_frames = visible_frames
            item.duration = visible_frames / math.max(1.0, fps)
            table.insert(resolved, item)
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

local function collect_audio_jobs(project, timeline, apply_scope, require_live_resolution)
    local audio_tracks = parse_track_list(text_field("AudioTracks", "1"))
    local video_track = int_field("VideoTrack", 2, 1, 64)
    local fps = timeline_fps(project, timeline)
    local jobs = {}
    local scan_summary = {}
    local detected_clip_count = 0
    local missing_path_count = 0

    for _, audio_track in ipairs(audio_tracks) do
        local audio_track_count = get_track_count(timeline, "audio")
        if audio_track > audio_track_count then
            append_log(tr("log.track_missing", { track = audio_track }))
            table.insert(scan_summary, tr("summary.track_missing", { track = audio_track, count = audio_track_count }))
        else
            local raw_items = get_timeline_items(timeline, "audio", audio_track)
            local items = normalize_timeline_items(raw_items, "GetName")
            local summary = "A" .. tostring(audio_track) .. ": raw type " .. type(raw_items) .. ", raw " .. tostring(table_count(raw_items)) .. ", clips " .. tostring(#items)
            append_log(summary)
            table.insert(scan_summary, summary)
            detected_clip_count = detected_clip_count + #items
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
                            duration = duration_frames / math.max(1.0, fps),
                            duration_frames = duration_frames,
                            source_start_time = source_start_time(item, fps),
                            audio_track = audio_track,
                            video_track = video_track,
                            timeline_item_name = name,
                        })
                    end
                end
            end
        end
    end

    jobs = resolve_overlap_jobs(jobs, fps)
    for index, job in ipairs(jobs) do job.display_index = index end
    log_clip_numbers(jobs, fps)

    local partial_update = false
    if apply_scope then
        jobs, partial_update = apply_update_scope(jobs, timeline, fps)
    end

    local timeline_width, timeline_height, resolution_source = timeline_resolution(project, timeline)
    if not timeline_width or not timeline_height then
        if require_live_resolution then
            error(tr("error.live_resolution"))
        end
        timeline_width, timeline_height = 1920, 1080
        resolution_source = "legacy default 1920x1080"
        append_log(tr("warning.legacy_resolution"))
    else
        append_log(tr("log.timeline_resolution", { width = timeline_width, height = timeline_height, source = resolution_source }))
    end
    local profile_layout = read_active_layout_from_ui()
    local active_design = read_design_from_ui()
    local bake_position = profile_layout.bake_position
    local layout_scale = math.min(timeline_width / 1920.0, timeline_height / 1080.0)
    if layout_scale <= 0 or layout_scale ~= layout_scale or layout_scale >= math.huge then
        error("Invalid effective Classic layout scale")
    end
    local player_width = math.max(1, math.floor(profile_layout.base_width * layout_scale + 0.5))
    local player_height = math.max(1, math.floor(profile_layout.base_height * layout_scale + 0.5))
    local margin = math.max(0, math.floor(profile_layout.margin * layout_scale + 0.5))
    append_log(string.format(
        "Skin layout: skin=%s base=%dx%d margin=%d, scale=%.4f, effective=%dx%d margin=%d",
        active_skin, profile_layout.base_width, profile_layout.base_height, profile_layout.margin,
        layout_scale, player_width, player_height, margin
    ))
    local render_fps = int_field("RenderFps", 15, 5, 60)
    local payload = {
        version = 2,
        skin = active_skin,
        timeline_name = timeline:GetName(),
        output_dir = text_field("OutputDir", path_join(path_join(install_root(), "outputs"), "resolve")),
        scan_summary = table.concat(scan_summary, "; "),
        detected_clip_count = detected_clip_count,
        missing_path_count = missing_path_count,
        design = active_design,
        fallback_logo_path = read_fallback_logo_path(),
        settings = {
            width = bake_position and timeline_width or player_width,
            height = bake_position and timeline_height or player_height,
            skin = active_skin,
            design = active_design,
            timeline_width = timeline_width,
            timeline_height = timeline_height,
            timeline_fps = fps,
            player_width = player_width,
            player_height = player_height,
            margin = margin,
            bake_position = bake_position,
            base_width = profile_layout.base_width,
            base_height = profile_layout.base_height,
            base_margin = profile_layout.margin,
            effective_scale = layout_scale,
            fps = render_fps,
            bars = 0,
            codec = "qtrle",
        },
        tracks = jobs,
    }
    return payload, audio_tracks, video_track, partial_update
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

local function delete_existing_visualizers(timeline, video_track, job_ids)
    local items = normalize_timeline_items(get_timeline_items(timeline, "video", video_track), "GetName")
    local to_delete = {}
    for _, item in pairs(items) do
        local name = ""
        pcall(function() name = item:GetName() or "" end)
        if starts_with(name, VISUALIZER_PREFIX) then
            local item_id = string.sub(name, string.len(VISUALIZER_PREFIX) + 1)
            if job_ids == nil or job_ids[item_id] then
                table.insert(to_delete, item)
            end
        end
    end
    if #to_delete > 0 then
        local delete_ok, delete_result = pcall(function() return timeline:DeleteClips(to_delete, false) end)
        if not delete_ok or delete_result == false then
            error(tr("error.visualizers_delete", { details = delete_result }))
        end
    end
    return #to_delete
end

local function safe_stem(value)
    local text = trim(value):gsub("[^A-Za-z0-9%._%-]+", "_"):gsub("^[%._%-]+", ""):gsub("[%._%-]+$", "")
    if text == "" then return "track" end
    return text
end

local function run_engine(jobs)
    local out_dir = trim(type(jobs) == "table" and jobs.output_dir or "")
    if out_dir == "" then error(tr("error.output_dir_legacy")) end
    local jobs_path = path_join(tmp_dir(), "timeline_jobs.json")
    local manifest_path = path_join(out_dir, "manifest.json")
    local stdout_path = path_join(tmp_dir(), "render_stdout.txt")
    local done_path = path_join(tmp_dir(), "render_done.json")
    write_file(jobs_path, json_encode(jobs, ""))
    remove_file(manifest_path)
    remove_file(stdout_path)
    remove_file(done_path)

    local root = install_root()
    local engine = engine_path()
    if not file_exists(engine) then error(tr("error.engine_missing", { path = engine })) end
    local ffmpeg = ffmpeg_path(native_executable_name("ffmpeg"), FFMPEG_EXECUTABLE)
    local ffprobe = ffmpeg_path(native_executable_name("ffprobe"), FFPROBE_EXECUTABLE)
    local logo = trim(type(jobs) == "table" and jobs.fallback_logo_path or "")
    if logo == "" then logo = default_fallback_logo_path() end
    local command = {
        engine,
        "render-jobs",
        "--jobs", jobs_path,
        "--out", out_dir,
        "--manifest", manifest_path,
        "--ffmpeg", ffmpeg,
        "--ffprobe", ffprobe,
    }

    append_log(tr("log.generator_start"))
    append_log("Engine: " .. engine)
    set_progress(10, tr("status.render_no_console"))
    run_runner_config({
        mode = "run",
        cwd = root,
        command = command,
        env = { DAVINCI_TRACK_VISUALIZER_LOGO = logo },
        stdout_path = stdout_path,
        done_path = done_path,
    }, "render")
    if not file_exists(manifest_path) then
        error(tr("error.manifest_missing"))
    end
    set_progress(86, tr("status.render_import"))
    return manifest_path
end

local function validate_live_manifest(manifest, jobs)
    if type(manifest) ~= "table" or manifest == JSON_NULL then error("Live manifest must be a JSON object") end
    if manifest.schema ~= "tviz.live.manifest" then error("Invalid live manifest schema") end
    if manifest.version ~= 3 then error("Unsupported live manifest version") end
    if manifest.mode ~= "live_fusion" then error("Invalid live manifest mode") end
    if type(manifest.settings) ~= "table" or manifest.settings == JSON_NULL then error("Live manifest has no settings") end
    local expected_skin = type(jobs) == "table" and (jobs.skin or (type(jobs.settings) == "table" and jobs.settings.skin)) or nil
    if not THEME.is_supported_skin(expected_skin) then error("Jobs do not specify a supported skin") end
    if manifest.settings.skin ~= expected_skin then error("Live manifest skin does not match jobs") end
    local timeline_fps = manifest.settings.timeline_fps
    if type(timeline_fps) ~= "number" or timeline_fps ~= timeline_fps or timeline_fps <= 0 or timeline_fps >= math.huge then
        error("Live manifest timeline_fps must be positive")
    end

    local expected_tracks = jobs and jobs.tracks or nil
    if type(expected_tracks) ~= "table" or expected_tracks == JSON_NULL then error("Jobs have no tracks") end
    local expected_count = 0
    for key, _ in pairs(expected_tracks) do
        if type(key) ~= "number" or key < 1 or key % 1 ~= 0 then
            error("jobs.tracks must be a contiguous array")
        end
        expected_count = expected_count + 1
    end
    if expected_count == 0 then error("Jobs have no tracks") end
    local expected_by_id = {}
    for index = 1, expected_count do
        local job = expected_tracks[index]
        if type(job) ~= "table" or type(job.id) ~= "string" or trim(job.id) == "" then
            error("Jobs contain an invalid track.id")
        end
        if expected_by_id[job.id] then error("Jobs contain a duplicate track.id: " .. job.id) end
        expected_by_id[job.id] = job
    end

    local tracks = manifest.tracks
    if type(tracks) ~= "table" or tracks == JSON_NULL then error("Live manifest has no tracks") end
    local manifest_count = 0
    for key, _ in pairs(tracks) do
        if type(key) ~= "number" or key < 1 or key % 1 ~= 0 then
            error("Live manifest tracks must be a contiguous array")
        end
        manifest_count = manifest_count + 1
    end
    if manifest_count == 0 or manifest_count ~= expected_count then
        error("Live manifest track count does not match jobs")
    end

    local seen_ids = {}
    local seen_static_paths = {}
    for index = 1, manifest_count do
        local track = tracks[index]
        if type(track) ~= "table" or track == JSON_NULL then error("Invalid track in live manifest") end
        if track.schema ~= "tviz.live.track" then error("Invalid live track schema #" .. tostring(index)) end
        if type(track.id) ~= "string" or trim(track.id) == "" then error("Invalid live track.id #" .. tostring(index)) end
        if seen_ids[track.id] then error("Duplicate live track.id: " .. track.id) end
        seen_ids[track.id] = true
        local original = expected_by_id[track.id]
        if not original then error("Unexpected track in live manifest: " .. track.id) end
        if type(track.static_path) ~= "string" or trim(track.static_path) == "" then error("Invalid static_path for " .. track.id) end
        local static_key = path_identity(track.static_path)
        if seen_static_paths[static_key] then
            error("Duplicate static_path in live manifest: " .. track.static_path)
        end
        seen_static_paths[static_key] = true
        if type(track.dynamic) ~= "table" or track.dynamic == JSON_NULL then error("Invalid dynamic spec for " .. track.id) end
        if track.dynamic.schema ~= "davinci_track_visualizer.live_dynamic" or track.dynamic.version ~= 3 then
            error("Unsupported dynamic spec version for " .. track.id)
        end
        if track.dynamic.skin ~= expected_skin then error("Dynamic spec skin does not match jobs for " .. track.id) end
        local time_spec = track.dynamic.time
        local time_box = type(time_spec) == "table" and time_spec.box or nil
        if type(time_box) ~= "table" then error("Dynamic time has no box for " .. track.id) end
        for _, field in ipairs({ "x", "y", "width", "height" }) do
            local value = tonumber(time_box[field])
            if not value or value ~= value or value < 0 or value >= math.huge or (field == "width" or field == "height") and value <= 0 then
                error("Invalid dynamic time.box." .. field .. " for " .. track.id)
            end
        end
        local canvas = track.dynamic.canvas
        local canvas_width = type(canvas) == "table" and tonumber(canvas.width) or nil
        local canvas_height = type(canvas) == "table" and tonumber(canvas.height) or nil
        if not canvas_width or not canvas_height or canvas_width <= 0 or canvas_height <= 0
            or tonumber(time_box.x) + tonumber(time_box.width) > canvas_width
            or tonumber(time_box.y) + tonumber(time_box.height) > canvas_height then
            error("Dynamic time.box exceeds the canvas for " .. track.id)
        end
        if time_spec.anchor ~= "right_center" then error("Dynamic time anchor must be right_center for " .. track.id) end
        if time_spec.horizontal_alignment ~= "right" or time_spec.vertical_alignment ~= "center" then
            error("Invalid dynamic time alignment for " .. track.id)
        end
        if time_spec.fusion_horizontal_justification ~= "right" or time_spec.fusion_vertical_justification ~= "center" then
            error("Invalid Fusion time alignment for " .. track.id)
        end
        if math.abs((tonumber(time_spec.x) or -1) - (tonumber(time_box.x) + tonumber(time_box.width))) > 0.001
            or math.abs((tonumber(time_spec.y) or -1) - (tonumber(time_box.y) + tonumber(time_box.height) / 2.0)) > 0.001 then
            error("Dynamic time position does not match time.box for " .. track.id)
        end
        if expected_skin == "minimal" then
            if track.dynamic.show_time ~= true or track.dynamic.show_progress ~= false or track.dynamic.show_knob ~= false then
                error("Invalid Minimal structural fields for " .. track.id)
            end
        elseif expected_skin == "portrait_glass" then
            if track.dynamic.show_time ~= true or track.dynamic.show_progress ~= true or track.dynamic.show_knob ~= false then
                error("Invalid Portrait Glass structural fields for " .. track.id)
            end
        end
        local record_frame = track.record_frame
        local duration_frames = track.duration_frames
        if type(record_frame) ~= "number" or record_frame ~= record_frame or record_frame <= -math.huge or record_frame >= math.huge or record_frame % 1 ~= 0 then error("record_frame must be an integer for " .. track.id) end
        if type(duration_frames) ~= "number" or duration_frames ~= duration_frames or duration_frames >= math.huge or duration_frames % 1 ~= 0 or duration_frames <= 0 then error("duration_frames must be a positive integer for " .. track.id) end
        if record_frame ~= original.record_frame or duration_frames ~= original.duration_frames then
            error("record_frame/duration_frames do not match jobs for " .. track.id)
        end
    end
    for id, _ in pairs(expected_by_id) do
        if not seen_ids[id] then error("Live manifest is missing track: " .. id) end
    end
    return true
end

local function run_live_engine(jobs)
    local out_dir = trim(type(jobs) == "table" and jobs.output_dir or "")
    if out_dir == "" then error(tr("error.output_dir_live")) end
    local jobs_path = path_join(tmp_dir(), "timeline_jobs_live.json")
    local manifest_path = path_join(out_dir, "live_manifest.json")
    local stdout_path = path_join(tmp_dir(), "live_prepare_stdout.txt")
    local done_path = path_join(tmp_dir(), "live_prepare_done.json")
    write_file(jobs_path, json_encode(jobs, ""))
    remove_file(manifest_path)
    remove_file(stdout_path)
    remove_file(done_path)

    local root = install_root()
    local engine = engine_path()
    if not file_exists(engine) then error(tr("error.engine_missing", { path = engine })) end
    local ffprobe = ffmpeg_path(native_executable_name("ffprobe"), FFPROBE_EXECUTABLE)
    local command = {
        engine,
        "prepare-live",
        "--jobs", jobs_path,
        "--out", out_dir,
        "--manifest", manifest_path,
        "--ffprobe", ffprobe,
    }

    append_log(tr("log.fusion_preparing"))
    set_progress(10, tr("status.fusion_preparing"))
    run_runner_config({
        mode = "run",
        cwd = root,
        command = command,
        env = { DAVINCI_TRACK_VISUALIZER_LOGO = trim(jobs.fallback_logo_path or "") ~= "" and jobs.fallback_logo_path or default_fallback_logo_path() },
        stdout_path = stdout_path,
        done_path = done_path,
    }, "prepare_live")
    if not file_exists(manifest_path) then
        error(tr("error.live_manifest_missing"))
    end

    local manifest = json_decode(read_file(manifest_path))
    validate_live_manifest(manifest, jobs)
    return manifest
end

local last_preview_paths = {}

local function show_preview_path(path)
    path = path or ""
    local can_open = path ~= "" and file_exists(path)
    local label = win:Find("PreviewPath")
    if label then
        label.Text = path ~= "" and path or tr("preview.pending", { skin = skin_label(active_skin) })
        pcall(function() label:Update() end)
    end
    local status = win:Find("PreviewStatus")
    if status then
        status.Text = path ~= "" and tr("preview.created", { skin = skin_label(active_skin) }) or tr("preview.generate_prompt")
        pcall(function() status:Update() end)
    end
    local open_button = win:Find("OpenPreview")
    if open_button then
        open_button.Enabled = can_open
        pcall(function() open_button:Update() end)
    end
end

local function set_preview_image(path, skin)
    skin = THEME.is_supported_skin(skin) and skin or active_skin
    last_preview_paths[skin] = path or ""
    if skin == active_skin then show_preview_path(last_preview_paths[skin]) end
end

refresh_active_preview = function()
    show_preview_path(last_preview_paths[active_skin] or "")
end

local function open_file(path)
    if path and path ~= "" and file_exists(path) then
        local done_path = path_join(tmp_dir(), "open_done.json")
        remove_file(done_path)
        run_runner_config({
            mode = "open",
            path = path,
            done_path = done_path,
        }, "open")
    end
end

local function run_style_preview()
    local profile = capture_active_profile()
    local preview_skin = active_skin
    local out_dir = text_field("OutputDir", path_join(path_join(install_root(), "outputs"), "resolve"))
    local preview_dir = path_join(out_dir, "preview")
    local design_path = path_join(tmp_dir(), "style_preview_design_" .. preview_skin .. ".json")
    local preview_path = path_join(preview_dir, "style_preview_" .. preview_skin .. "_" .. tostring(os.time()) .. ".png")
    write_file(design_path, json_encode(profile.design, ""))
    remove_file(preview_path)

    local root = install_root()
    local engine = engine_path()
    if not file_exists(engine) then error(tr("error.engine_missing", { path = engine })) end
    local logo = read_fallback_logo_path()
    local stdout_path = path_join(tmp_dir(), "preview_stdout.txt")
    local done_path = path_join(tmp_dir(), "preview_done.json")
    remove_file(stdout_path)
    remove_file(done_path)
    local command = {
        engine,
        "preview-style",
        "--out", preview_path,
        "--design-json", design_path,
        "--width", "1920",
        "--height", "1080",
        "--player-width", tostring(profile.base_width),
        "--player-height", tostring(profile.base_height),
        "--margin", tostring(profile.margin),
        "--bake-position",
        "--skin", preview_skin,
        "--title", tr("preview.sample_title"),
        "--artist", tr("preview.sample_artist"),
        "--progress", "0.36",
    }

    append_log(tr("log.preview_generating"))
    run_runner_config({
        mode = "run",
        cwd = root,
        command = command,
        env = { DAVINCI_TRACK_VISUALIZER_LOGO = logo },
        stdout_path = stdout_path,
        done_path = done_path,
    }, "preview")
    if not file_exists(preview_path) then
        error(tr("error.preview_failed", { path = preview_path }))
    end
    set_preview_image(preview_path, preview_skin)
    return preview_path
end

local function overlay_path_for_job(out_dir, job)
    return path_join(path_join(out_dir, "overlays"), "TVIZ__" .. safe_stem(job.id or "track") .. "_overlay.mov")
end

local function first_item(items)
    if type(items) ~= "table" then return nil end
    if items[1] then return items[1] end
    for _, item in pairs(items) do return item end
    return nil
end

local function timeline_contains_item_on_track(timeline, video_track, target_item)
    if not target_item then return false end
    local target_id = ""
    pcall(function() target_id = tostring(target_item:GetUniqueId() or "") end)
    local items = normalize_timeline_items(get_timeline_items(timeline, "video", video_track), "GetName")
    for _, item in pairs(items) do
        if item == target_item then return true end
        if target_id ~= "" then
            local item_id = ""
            pcall(function() item_id = tostring(item:GetUniqueId() or "") end)
            if item_id ~= "" and item_id == target_id then return true end
        end
    end
    return false
end

local function fusion_point(x, y)
    local ok, value = pcall(function() return Point(x, y) end)
    if ok and value ~= nil then return value end
    return { x, y }
end

local function fusion_set_input(tool, input_id, value, time)
    local ok, result = pcall(function()
        if time ~= nil then return tool:SetInput(input_id, value, time) end
        return tool:SetInput(input_id, value)
    end)
    if not ok or result == false then
        error("Fusion rejected input " .. tostring(input_id) .. ": " .. tostring(ok and result or result))
    end
    return result
end

local function fusion_connect(target, input_id, source)
    local ok, result = pcall(function() return target:ConnectInput(input_id, source) end)
    if not ok or result == false then
        error("Fusion did not connect input " .. tostring(input_id) .. ": " .. tostring(ok and result or result))
    end
    return result
end

local function fusion_add_modifier(tool, input_id, modifier_id)
    local ok, result = pcall(function() return tool:AddModifier(input_id, modifier_id) end)
    if not ok or result ~= true then
        error("Fusion did not create modifier " .. tostring(modifier_id) .. " for " .. tostring(input_id) .. ": " .. tostring(result))
    end
end

local function fusion_add_tool(comp, tool_id, x, y)
    local ok, tool = pcall(function() return comp:AddTool(tool_id, false, x, y) end)
    if not ok or tool == nil then
        error("Fusion did not create tool " .. tostring(tool_id) .. ": " .. tostring(tool))
    end
    return tool
end

local function fusion_color(color, alpha)
    local hex_value = color
    if type(color) == "table" then
        local red = math.max(0, math.min(255, math.floor((tonumber(color[1]) or 255) + 0.5)))
        local green = math.max(0, math.min(255, math.floor((tonumber(color[2]) or 255) + 0.5)))
        local blue = math.max(0, math.min(255, math.floor((tonumber(color[3]) or 255) + 0.5)))
        hex_value = string.format("#%02X%02X%02X", red, green, blue)
    end
    local red, green, blue = hex_to_rgb(hex_value)
    local normalized_alpha = math.max(0, math.min(255, tonumber(alpha) or 255)) / 255.0
    return red / 255.0, green / 255.0, blue / 255.0, normalized_alpha
end

local function fusion_time_label(value)
    local total_seconds = math.max(0, math.floor((tonumber(value) or 0) + 0.0001))
    return string.format("%02d:%02d", math.floor(total_seconds / 60), total_seconds % 60)
end

local function build_live_fusion_comp(timeline_item, track, manifest_settings)
    local comp = timeline_item:AddFusionComp()
    if not comp then error("Resolve did not create a Fusion Composition") end

    local function normalize_found_tool(value)
        if value == nil then return nil end
        local ok = pcall(function() return value:GetAttrs() end)
        if ok then return value end
        return first_item(value)
    end

    local function find_tool(name, tool_id)
        local found = nil
        pcall(function() found = comp:FindTool(name) end)
        found = normalize_found_tool(found)
        if found then return found end
        pcall(function() found = comp:FindToolByID(tool_id) end)
        return normalize_found_tool(found)
    end

    local media_in = find_tool("MediaIn1", "MediaIn")
    local media_out = find_tool("MediaOut1", "MediaOut")
    if not media_in then error("Fusion Composition has no MediaIn1") end
    if not media_out then error("Fusion Composition has no MediaOut1") end

    local duration_frames = tonumber(track.duration_frames) or 0
    if duration_frames <= 0 then error("Invalid Fusion clip duration") end
    local last_frame = math.max(0, math.floor(duration_frames + 0.5) - 1)
    local attrs_ok, attrs_result = pcall(function()
        return comp:SetAttrs({
            COMPN_GlobalStart = 0,
            COMPN_GlobalEnd = last_frame,
            COMPN_RenderStart = 0,
            COMPN_RenderEnd = last_frame,
        })
    end)
    if not attrs_ok or attrs_result == false then
        error("Fusion did not set the composition range: " .. tostring(attrs_result))
    end
    pcall(function() comp:SetData("tviz_schema", "live_fusion") end)
    pcall(function() comp:SetData("tviz_version", 1) end)
    pcall(function() comp:SetData("tviz_job_id", tostring(track.id or "")) end)

    local dynamic = track.dynamic
    if type(dynamic) ~= "table" then error("Live manifest has no dynamic spec") end
    if not THEME.is_supported_skin(dynamic.skin) then error("Dynamic spec has no supported skin") end
    pcall(function() comp:SetData("tviz_skin", dynamic.skin) end)
    local canvas = dynamic.canvas or {}
    local canvas_width = tonumber(canvas.width) or 0
    local canvas_height = tonumber(canvas.height) or 0
    if canvas_width <= 0 or canvas_height <= 0 then error("Invalid canvas size in dynamic spec") end

    local current_base = media_in
    local tool_row = 0

    local function add_masked_layer(mask_tool, color, alpha)
        local background = fusion_add_tool(comp, "Background", 0, tool_row)
        fusion_set_input(background, "UseFrameFormatSettings", 1)
        local red, green, blue, normalized_alpha = fusion_color(color, alpha)
        fusion_set_input(background, "TopLeftRed", red)
        fusion_set_input(background, "TopLeftGreen", green)
        fusion_set_input(background, "TopLeftBlue", blue)
        fusion_set_input(background, "TopLeftAlpha", normalized_alpha)
        fusion_connect(background, "EffectMask", mask_tool)

        local merge = fusion_add_tool(comp, "Merge", 2, tool_row)
        fusion_connect(merge, "Background", current_base)
        fusion_connect(merge, "Foreground", background)
        current_base = merge
        tool_row = tool_row + 1
    end

    if dynamic.show_progress == true then
        local progress = dynamic.progress or {}
        local x1 = tonumber(progress.x1)
        local x2 = tonumber(progress.x2)
        local line_y = tonumber(progress.y)
        local line_width = tonumber(progress.line_width)
        if not x1 or not x2 or not line_y or not line_width or x2 <= x1 or line_width <= 0 then
            error("Invalid progress coordinates in dynamic spec")
        end
        local full_width = (x2 - x1) / canvas_width
        local normalized_height = line_width / canvas_height
        local center_y = 1.0 - line_y / canvas_height
        local midpoint_x = ((x1 + x2) / 2.0) / canvas_width

        local track_mask = fusion_add_tool(comp, "RectangleMask", -2, tool_row)
        fusion_set_input(track_mask, "Width", full_width)
        fusion_set_input(track_mask, "Height", normalized_height)
        fusion_set_input(track_mask, "Center", fusion_point(midpoint_x, center_y))
        add_masked_layer(track_mask, progress.track_color, progress.track_alpha)

        local accent_mask = fusion_add_tool(comp, "RectangleMask", -2, tool_row)
        fusion_set_input(accent_mask, "Height", normalized_height)
        local near_zero_width = math.min(full_width, 1.0 / canvas_width)
        fusion_add_modifier(accent_mask, "Width", "BezierSpline")
        fusion_add_modifier(accent_mask, "Center", "Path")
        fusion_set_input(accent_mask, "Width", near_zero_width, 0)
        fusion_set_input(accent_mask, "Center", fusion_point(x1 / canvas_width, center_y), 0)
        fusion_set_input(accent_mask, "Width", full_width, last_frame)
        fusion_set_input(accent_mask, "Center", fusion_point(midpoint_x, center_y), last_frame)
        add_masked_layer(accent_mask, progress.accent_color, progress.accent_alpha)

        if dynamic.show_knob == true then
            local knob_radius = tonumber(progress.knob_radius) or 0
            if knob_radius <= 0 then error("Invalid knob_radius in dynamic spec") end
            local knob_mask = fusion_add_tool(comp, "EllipseMask", -2, tool_row)
            fusion_set_input(knob_mask, "Width", knob_radius * 2.0 / canvas_width)
            fusion_set_input(knob_mask, "Height", knob_radius * 2.0 / canvas_height)
            fusion_add_modifier(knob_mask, "Center", "Path")
            fusion_set_input(knob_mask, "Center", fusion_point(x1 / canvas_width, center_y), 0)
            fusion_set_input(knob_mask, "Center", fusion_point(x2 / canvas_width, center_y), last_frame)
            add_masked_layer(knob_mask, progress.accent_color, progress.knob_alpha)
        end
    end

    if dynamic.show_time == true then
        local time_spec = dynamic.time or {}
        local time_box = type(time_spec.box) == "table" and time_spec.box or nil
        if not time_box then error("Dynamic time has no box") end
        local box_x = tonumber(time_box.x)
        local box_y = tonumber(time_box.y)
        local box_width = tonumber(time_box.width)
        local box_height = tonumber(time_box.height)
        if not box_x or not box_y or not box_width or not box_height or box_x < 0 or box_y < 0 or box_width <= 0 or box_height <= 0 then
            error("Invalid time.box in dynamic spec")
        end
        if time_spec.anchor ~= "right_center" then error("Dynamic time anchor must be right_center") end
        local time_x = tonumber(time_spec.x) or (box_x + box_width)
        local time_y = tonumber(time_spec.y) or (box_y + box_height / 2.0)
        if math.abs(time_x - (box_x + box_width)) > 0.001 or math.abs(time_y - (box_y + box_height / 2.0)) > 0.001 then
            error("Dynamic time position does not match time.box/right_center")
        end
        local font_size = tonumber(time_spec.font_size)
        if not time_x or not time_y or not font_size or font_size <= 0 then
            error("Invalid time parameters in dynamic spec")
        end
        local text_tool = fusion_add_tool(comp, "TextPlus", 0, tool_row)
        pcall(function() fusion_set_input(text_tool, "UseFrameFormatSettings", 1) end)
        local anchor = time_spec.anchor
        local horizontal_alignment = time_spec.fusion_horizontal_justification or time_spec.horizontal_alignment or time_spec.horizontal_align
        local vertical_alignment = time_spec.fusion_vertical_justification or time_spec.vertical_alignment or time_spec.vertical_align
        if type(anchor) == "table" then
            horizontal_alignment = horizontal_alignment or anchor.horizontal or anchor.x
            vertical_alignment = vertical_alignment or anchor.vertical or anchor.y
        elseif type(anchor) == "string" then
            local lowered_anchor = anchor:lower()
            if lowered_anchor:find("left", 1, true) then horizontal_alignment = horizontal_alignment or "left" end
            if lowered_anchor:find("right", 1, true) then horizontal_alignment = horizontal_alignment or "right" end
            if lowered_anchor:find("top", 1, true) then vertical_alignment = vertical_alignment or "top" end
            if lowered_anchor:find("bottom", 1, true) then vertical_alignment = vertical_alignment or "bottom" end
        end
        horizontal_alignment = horizontal_alignment or "center"
        vertical_alignment = vertical_alignment or "center"
        local horizontal_values = { left = -1, center = 0, right = 1 }
        local vertical_values = { top = -1, center = 0, bottom = 1 }
        local horizontal_value = horizontal_values[tostring(horizontal_alignment):lower()] or tonumber(horizontal_alignment) or 0
        local vertical_value = vertical_values[tostring(vertical_alignment):lower()] or tonumber(vertical_alignment) or 0
        pcall(function() fusion_set_input(text_tool, "HorizontalLeftCenterRight", horizontal_value) end)
        pcall(function() fusion_set_input(text_tool, "VerticalTopCenterBottom", vertical_value) end)
        pcall(function() fusion_set_input(text_tool, "HorizontalJustificationNew", 3) end)
        pcall(function() fusion_set_input(text_tool, "VerticalJustificationNew", 3) end)
        local duration_seconds = tonumber(dynamic.duration_seconds or track.duration) or 0
        local total_label = tostring(dynamic.total_duration_label or fusion_time_label(duration_seconds))
        fusion_add_modifier(text_tool, "StyledText", "BezierSpline")
        local design = type(manifest_settings) == "table" and manifest_settings.design or nil
        local font_family = time_spec.font_family
        if type(font_family) ~= "string" or font_family == "" then
            font_family = type(design) == "table" and (design.meta_font_family or design.artist_font_family) or nil
        end
        pcall(function() fusion_set_input(text_tool, "Font", tostring(font_family or "Segoe UI")) end)
        fusion_set_input(text_tool, "Size", font_size / canvas_height)
        fusion_set_input(text_tool, "Center", fusion_point(time_x / canvas_width, 1.0 - time_y / canvas_height))
        local red, green, blue, alpha = fusion_color(time_spec.color, time_spec.alpha)
        pcall(function() fusion_set_input(text_tool, "Red1", red) end)
        pcall(function() fusion_set_input(text_tool, "Green1", green) end)
        pcall(function() fusion_set_input(text_tool, "Blue1", blue) end)
        pcall(function() fusion_set_input(text_tool, "Alpha1", alpha) end)

        local timeline_fps = tonumber(type(manifest_settings) == "table" and manifest_settings.timeline_fps or nil) or 30
        if timeline_fps <= 0 then timeline_fps = 30 end
        local keyframes_ok, keyframes_error = pcall(function()
            local second = 0
            local last_keyframe = -1
            while second <= math.floor(duration_seconds) do
                local keyframe = math.min(last_frame, math.floor(second * timeline_fps + 0.5))
                if keyframe > last_keyframe then
                    fusion_set_input(text_tool, "StyledText", fusion_time_label(second) .. " / " .. total_label, keyframe)
                    last_keyframe = keyframe
                end
                if keyframe >= last_frame then break end
                second = second + 1
            end
            if last_keyframe ~= last_frame then
                local current_seconds = math.min(duration_seconds, last_frame / timeline_fps)
                fusion_set_input(text_tool, "StyledText", fusion_time_label(current_seconds) .. " / " .. total_label, last_frame)
            end
        end)
        if not keyframes_ok then
            error("Fusion did not create time keyframes: " .. tostring(keyframes_error))
        end

        local merge = fusion_add_tool(comp, "Merge", 2, tool_row)
        fusion_connect(merge, "Background", current_base)
        fusion_connect(merge, "Foreground", text_tool)
        current_base = merge
    end

    fusion_connect(media_out, "Input", current_base)
    return comp
end

local function timelines_match(left, right)
    if not left or not right then return false end
    if left == right then return true end

    local left_id_ok, left_id = pcall(function() return left:GetUniqueId() end)
    local right_id_ok, right_id = pcall(function() return right:GetUniqueId() end)
    left_id = left_id_ok and left_id ~= nil and left_id ~= false and trim(tostring(left_id)) or ""
    right_id = right_id_ok and right_id ~= nil and right_id ~= false and trim(tostring(right_id)) or ""
    if left_id ~= "" and right_id ~= "" then return left_id == right_id end

    local left_name_ok, left_name = pcall(function() return left:GetName() end)
    local right_name_ok, right_name = pcall(function() return right:GetName() end)
    return left_name_ok and right_name_ok and left_name ~= nil and right_name ~= nil
        and tostring(left_name) == tostring(right_name)
end

local function live_helper_target_suffix(project, target_timeline)
    local unique_ok, unique_id = pcall(function() return target_timeline:GetUniqueId() end)
    local suffix = unique_ok and unique_id ~= nil and unique_id ~= false and trim(tostring(unique_id)) or ""
    if suffix ~= "" then
        suffix = safe_stem(suffix)
        if string.len(suffix) > 32 then suffix = string.sub(suffix, 1, 32) end
        return suffix
    end

    local name_ok, target_name = pcall(function() return target_timeline:GetName() end)
    if not name_ok or target_name == nil then error("Resolve did not return the target timeline name") end
    target_name = tostring(target_name)

    local count_ok, timeline_count = pcall(function() return project:GetTimelineCount() end)
    timeline_count = count_ok and tonumber(timeline_count) or nil
    if not timeline_count or timeline_count < 0 or timeline_count % 1 ~= 0 then
        error("Resolve did not return a valid timeline count")
    end

    local target_index = nil
    local name_index = nil
    local name_matches = 0
    for index = 1, timeline_count do
        local item_ok, candidate = pcall(function() return project:GetTimelineByIndex(index) end)
        if not item_ok or not candidate then error("Resolve did not return timeline #" .. tostring(index)) end
        if candidate == target_timeline then
            target_index = index
            break
        end
        local candidate_name_ok, candidate_name = pcall(function() return candidate:GetName() end)
        if candidate_name_ok and candidate_name ~= nil and tostring(candidate_name) == target_name then
            name_matches = name_matches + 1
            name_index = index
        end
    end
    if not target_index and name_matches == 1 then target_index = name_index end
    if not target_index then error("Could not determine the target timeline index") end

    suffix = safe_stem(target_name)
    if string.len(suffix) > 28 then suffix = string.sub(suffix, 1, 28) end
    return suffix .. "_" .. tostring(target_index)
end

local function find_project_timeline_by_name(project, exact_name)
    local count_ok, timeline_count = pcall(function() return project:GetTimelineCount() end)
    timeline_count = count_ok and tonumber(timeline_count) or nil
    if not timeline_count or timeline_count < 0 or timeline_count % 1 ~= 0 then
        error("Resolve did not return a valid timeline count")
    end
    for index = 1, timeline_count do
        local item_ok, candidate = pcall(function() return project:GetTimelineByIndex(index) end)
        if not item_ok or not candidate then error("Resolve did not return timeline #" .. tostring(index)) end
        local name_ok, candidate_name = pcall(function() return candidate:GetName() end)
        if name_ok and candidate_name ~= nil and tostring(candidate_name) == exact_name then
            return candidate
        end
    end
    return nil
end

local helper_generation_counter = 0

local function new_live_helper_generation(project, target_timeline)
    local target_suffix = live_helper_target_suffix(project, target_timeline)
    for _ = 1, 1000 do
        helper_generation_counter = helper_generation_counter + 1
        local timestamp = os.date("!%Y%m%dT%H%M%SZ") or tostring(os.time())
        local clock_part = math.floor((os.clock() % 1000) * 1000)
        local generation = timestamp .. string.format("_%06d_%03d", clock_part, helper_generation_counter % 1000)
        local prefix = "TVIZ__SOURCE__G" .. generation .. "__" .. target_suffix
        if not find_project_timeline_by_name(project, prefix .. "__S001") then
            return generation, prefix
        end
    end
    error("Could not allocate a unique helper generation name")
end

local function timeline_frame_range(timeline)
    local start_ok, start_frame = pcall(function() return timeline:GetStartFrame() end)
    local end_ok, end_frame = pcall(function() return timeline:GetEndFrame() end)
    start_frame = start_ok and tonumber(start_frame) or nil
    end_frame = end_ok and tonumber(end_frame) or nil
    if not start_frame or start_frame ~= start_frame or start_frame <= -math.huge or start_frame >= math.huge or start_frame % 1 ~= 0 then
        error("Resolve did not return a valid helper timeline start frame")
    end
    if not end_frame or end_frame ~= end_frame or end_frame <= -math.huge or end_frame >= math.huge or end_frame % 1 ~= 0 then
        error("Resolve did not return a valid helper timeline end frame")
    end
    if end_frame < start_frame then error("Resolve returned a negative helper timeline range") end
    return start_frame, end_frame
end

local function timeline_frame_length(timeline)
    local start_frame, end_frame = timeline_frame_range(timeline)
    return end_frame - start_frame
end

local function strict_timeline_item_frame(item, method_name, label)
    local ok, value = pcall(function() return item[method_name](item, false) end)
    if not ok or value == nil then ok, value = pcall(function() return item[method_name](item) end) end
    value = ok and tonumber(value) or nil
    if not value or value ~= value or value <= -math.huge or value >= math.huge or value % 1 ~= 0 then
        error(tostring(label) .. " did not return a valid " .. tostring(method_name))
    end
    return value
end

local function strict_timeline_item_range(item, label)
    local start_frame = strict_timeline_item_frame(item, "GetStart", label)
    local end_frame = strict_timeline_item_frame(item, "GetEnd", label)
    local duration = strict_timeline_item_frame(item, "GetDuration", label)
    if duration <= 0 or end_frame - start_frame ~= duration then
        error(tostring(label) .. " returned an inconsistent range " .. tostring(start_frame) .. ".." .. tostring(end_frame) .. " duration=" .. tostring(duration))
    end
    return start_frame, end_frame, duration
end

local function optional_timeline_item_frame(item, method_name)
    local lookup_ok, method = pcall(function() return item[method_name] end)
    if not lookup_ok or type(method) ~= "function" then return nil end
    local ok, value = pcall(function() return method(item, false) end)
    if not ok or value == nil then ok, value = pcall(function() return method(item) end) end
    value = ok and tonumber(value) or nil
    if not value or value ~= value or value <= -math.huge or value >= math.huge then return nil end
    return value
end

local function validated_append_items(result, expected_count, label)
    if result == nil or result == false then error(tostring(label) .. " did not return timeline items") end
    if type(result) ~= "table" then error(tostring(label) .. " returned " .. type(result) .. " instead of a table") end
    local items = normalize_timeline_items(result, "GetName")
    if #items ~= expected_count then
        error(tostring(label) .. " returned " .. tostring(#items) .. " timeline items instead of " .. tostring(expected_count))
    end
    return items
end

local function media_pool_items_match(left, right)
    if not left or not right then return false end
    if left == right then return true end
    local left_ok, left_id = pcall(function() return left:GetUniqueId() end)
    local right_ok, right_id = pcall(function() return right:GetUniqueId() end)
    left_id = left_ok and trim(tostring(left_id or "")) or ""
    right_id = right_ok and trim(tostring(right_id or "")) or ""
    return left_id ~= "" and right_id ~= "" and left_id == right_id
end

local function append_helper_carriers(media_pool, helper_timeline, carrier_item, count, expected_duration, label)
    local helper_start, before_end = timeline_frame_range(helper_timeline)
    local batch = {}
    for index = 1, count do batch[index] = carrier_item end
    local append_ok, append_result = pcall(function() return media_pool:AppendToTimeline(batch) end)
    if not append_ok or append_result == false then
        error(tostring(label) .. " failed: " .. tostring(append_result))
    end
    local items = validated_append_items(append_result, count, label)
    local ranges = {}
    for index, item in ipairs(items) do
        if not timeline_contains_item_on_track(helper_timeline, 1, item) then
            error(tostring(label) .. " item #" .. tostring(index) .. " is missing from helper V1")
        end
        local item_start, item_end, item_duration = strict_timeline_item_range(item, label .. " item #" .. tostring(index))
        local source_ok, source_item = pcall(function() return item:GetMediaPoolItem() end)
        if not source_ok or not media_pool_items_match(source_item, carrier_item) then
            error(tostring(label) .. " item #" .. tostring(index) .. " does not reference the requested PNG MediaPoolItem")
        end
        table.insert(ranges, { start_frame = item_start, end_frame = item_end, duration = item_duration })
    end
    table.sort(ranges, function(left, right) return left.start_frame < right.start_frame end)
    local cursor = before_end
    for index, item_range in ipairs(ranges) do
        if item_range.start_frame ~= cursor then
            error(tostring(label) .. " item #" .. tostring(index) .. " starts at " .. tostring(item_range.start_frame) .. " instead of " .. tostring(cursor))
        end
        if expected_duration and item_range.duration ~= expected_duration then
            error(tostring(label) .. " item #" .. tostring(index) .. " duration=" .. tostring(item_range.duration) .. " instead of " .. tostring(expected_duration))
        end
        cursor = item_range.end_frame
    end
    local after_start, after_end = timeline_frame_range(helper_timeline)
    if after_start ~= helper_start or after_end ~= cursor then
        error(tostring(label) .. " helper range=" .. tostring(after_start) .. ".." .. tostring(after_end) .. " instead of " .. tostring(helper_start) .. ".." .. tostring(cursor))
    end
    return ranges[1].duration, after_end - helper_start
end

local function ensure_live_helper_settings(helper_timeline, manifest_settings)
    local layout = type(manifest_settings) == "table" and manifest_settings.layout or nil
    local expected = {
        { key = "timelineFrameRate", value = tonumber(type(manifest_settings) == "table" and manifest_settings.timeline_fps or nil) },
        { key = "timelineResolutionWidth", value = tonumber(type(layout) == "table" and layout.timeline_width or nil) },
        { key = "timelineResolutionHeight", value = tonumber(type(layout) == "table" and layout.timeline_height or nil) },
    }
    for _, setting in ipairs(expected) do
        if not setting.value or setting.value <= 0 or setting.value >= math.huge then
            error("Invalid helper setting " .. setting.key)
        end
        local read_ok, current = pcall(function() return helper_timeline:GetSetting(setting.key) end)
        local current_number = read_ok and tonumber(tostring(current or ""):gsub(",", "."):match("%d+%.?%d*")) or nil
        if not current_number or math.abs(current_number - setting.value) > 0.0001 then
            local set_ok, set_result = pcall(function()
                return helper_timeline:SetSetting(setting.key, tostring(setting.value))
            end)
            if not set_ok or set_result == false then
                error("Resolve did not set helper setting " .. setting.key .. ": " .. tostring(set_result))
            end
            read_ok, current = pcall(function() return helper_timeline:GetSetting(setting.key) end)
            current_number = read_ok and tonumber(tostring(current or ""):gsub(",", "."):match("%d+%.?%d*")) or nil
            if not current_number or math.abs(current_number - setting.value) > 0.0001 then
                error("Helper timeline rejected setting " .. setting.key)
            end
        end
    end
end

local function ensure_live_helper_track(helper_timeline)
    ensure_video_track(helper_timeline, 1)
    local unlock_ok, unlock_result = pcall(function()
        return helper_timeline:SetTrackLock("video", 1, false)
    end)
    if not unlock_ok or unlock_result == false then
        error("Resolve did not unlock the V1 helper timeline")
    end
    local enable_ok, enable_result = pcall(function()
        return helper_timeline:SetTrackEnable("video", 1, true)
    end)
    if not enable_ok or enable_result == false then
        error("Resolve did not enable the V1 helper timeline")
    end
    local lock_state_ok, is_locked = pcall(function()
        return helper_timeline:GetIsTrackLocked("video", 1)
    end)
    if lock_state_ok and is_locked == true then error("V1 helper timeline remained locked") end
    local enable_state_ok, is_enabled = pcall(function()
        return helper_timeline:GetIsTrackEnabled("video", 1)
    end)
    if enable_state_ok and is_enabled == false then error("V1 helper timeline remained disabled") end
end

local function prepare_live_visualizers(project, timeline, manifest)
    local tracks = type(manifest) == "table" and type(manifest.tracks) == "table" and manifest.tracks or {}
    if #tracks == 0 then error("Live manifest has no tracks for helper generation") end
    local media_pool = project:GetMediaPool()
    if not media_pool then error("Resolve did not return the Media Pool") end

    local generation, helper_prefix = new_live_helper_generation(project, timeline)
    local prepared = {
        generation = generation,
        helper_prefix = helper_prefix,
        manifest_settings = manifest.settings or {},
        entries = {},
        shards = {},
    }
    local static_paths = {}
    for _, track in ipairs(tracks) do
        local static_path = trim(track.static_path or "")
        if static_path ~= "" then static_paths[path_identity(static_path)] = true end
    end
    append_log("Helper generation: " .. generation .. " prefix=" .. helper_prefix)
    append_log("Static PNG paths: unique=" .. tostring(table_count(static_paths)) .. " tracks=" .. tostring(#tracks))

    local timeline_fps = tonumber(prepared.manifest_settings.timeline_fps)
    if not timeline_fps or timeline_fps <= 0 then error("Invalid timeline_fps for helper shards") end
    local shard_limit = math.max(1, math.floor(timeline_fps * LIVE_HELPER_SHARD_SECONDS + 0.5))
    local current_shard = nil

    local function switch_to_helper(helper_timeline)
        local switch_ok, switch_result = pcall(function() return project:SetCurrentTimeline(helper_timeline) end)
        local current_ok, current_timeline = pcall(function() return project:GetCurrentTimeline() end)
        if not switch_ok or not switch_result or not current_ok or not timelines_match(current_timeline, helper_timeline) then
            error("Resolve did not switch to the fresh helper timeline")
        end
    end

    local function create_shard()
        local shard_index = #prepared.shards + 1
        local helper_name = helper_prefix .. string.format("__S%03d", shard_index)
        if find_project_timeline_by_name(project, helper_name) then
            error("Fresh helper name already exists; append is not allowed: " .. helper_name)
        end
        local create_ok, created = pcall(function() return media_pool:CreateEmptyTimeline(helper_name) end)
        if not create_ok or created == false then error("Resolve did not create the fresh helper timeline: " .. tostring(created)) end
        local helper_timeline = created ~= nil and type(created) ~= "boolean" and created or nil
        if not helper_timeline then helper_timeline = find_project_timeline_by_name(project, helper_name) end
        if not helper_timeline then error("Could not retrieve the fresh helper timeline " .. helper_name) end
        if timelines_match(helper_timeline, timeline) then error("Fresh helper timeline matches the target timeline") end
        local name_ok, actual_name = pcall(function() return helper_timeline:GetName() end)
        if not name_ok or tostring(actual_name or "") ~= helper_name then
            error("Resolve created a helper with an unexpected name: " .. tostring(actual_name))
        end
        ensure_live_helper_settings(helper_timeline, prepared.manifest_settings)
        switch_to_helper(helper_timeline)
        ensure_live_helper_track(helper_timeline)
        if timeline_frame_length(helper_timeline) ~= 0 then error("Fresh helper timeline is not empty: " .. helper_name) end
        local existing_items = normalize_timeline_items(get_timeline_items(helper_timeline, "video", 1), "GetName")
        if #existing_items ~= 0 then error("Fresh helper V1 contains clips before preparation: " .. helper_name) end
        local shard = { index = shard_index, name = helper_name, timeline = helper_timeline, length = 0 }
        table.insert(prepared.shards, shard)
        append_log("Helper name: generation=" .. generation .. " shard=" .. tostring(shard_index) .. " name=" .. helper_name)
        return shard
    end

    local build_ok, build_error = pcall(function()
        for index, track in ipairs(tracks) do
            local static_path = trim(track.static_path or "")
            local duration_frames = tonumber(track.duration_frames)
            local record_frame = tonumber(track.record_frame)
            local raw_id = type(track.id) == "string" and trim(track.id) or ""
            if static_path == "" then error("Track #" .. tostring(index) .. ": static_path is missing") end
            if not duration_frames or duration_frames ~= duration_frames or duration_frames >= math.huge or duration_frames % 1 ~= 0 or duration_frames <= 0 then
                error("Track #" .. tostring(index) .. ": duration_frames must be a positive integer")
            end
            if not record_frame or record_frame ~= record_frame or record_frame <= -math.huge or record_frame >= math.huge or record_frame % 1 ~= 0 then
                error("Track #" .. tostring(index) .. ": record_frame must be an integer")
            end
            if raw_id == "" then error("Track #" .. tostring(index) .. ": string track.id is missing") end

            if not current_shard or (current_shard.length > 0 and current_shard.length + duration_frames > shard_limit) then
                current_shard = create_shard()
            else
                switch_to_helper(current_shard.timeline)
            end
            local carrier_items = media_pool:ImportMedia({ static_path })
            local carrier_item = first_item(carrier_items)
            if not carrier_item then error("Could not import PNG carrier: " .. static_path) end

            local source_start = current_shard.length
            local still_duration, helper_length = append_helper_carriers(
                media_pool, current_shard.timeline, carrier_item, 1, nil,
                "Helper first append track #" .. tostring(index)
            )
            if still_duration <= 0 then error("PNG carrier has zero duration") end
            local coverage = helper_length - source_start
            while coverage < duration_frames do
                local repeat_count = math.ceil((duration_frames - coverage) / still_duration)
                local batch_count = math.min(256, repeat_count)
                local _, next_length = append_helper_carriers(
                    media_pool, current_shard.timeline, carrier_item, batch_count, still_duration,
                    "Helper batch append track #" .. tostring(index)
                )
                helper_length = next_length
                coverage = helper_length - source_start
            end
            if coverage < duration_frames then error("PNG segment does not cover the required duration") end
            current_shard.length = helper_length
            local source_end = source_start + duration_frames
            local entry = {
                track = track,
                index = index,
                shard = current_shard,
                source_start = source_start,
                source_end = source_end,
            }
            table.insert(prepared.entries, entry)
            append_log(string.format(
                "Helper source #%03d id=%s shard=%03d interval=[%d,%d) coverage=%d static=%s",
                index, raw_id, current_shard.index, source_start, source_end, coverage, static_path
            ))
        end
    end)

    local function restore_target()
        local restore_ok, restore_result = pcall(function() return project:SetCurrentTimeline(timeline) end)
        local current_ok, current_timeline = pcall(function() return project:GetCurrentTimeline() end)
        return restore_ok and restore_result and current_ok and timelines_match(current_timeline, timeline)
    end
    local target_restored = restore_target()
    if not target_restored then target_restored = restore_target() end
    if not build_ok or not target_restored then
        local messages = {}
        if not build_ok then table.insert(messages, "helper preparation: " .. tostring(build_error)) end
        if not target_restored then table.insert(messages, "target timeline was not restored") end
        error(table.concat(messages, "; "))
    end

    for _, shard in ipairs(prepared.shards) do
        local item_ok, media_item = pcall(function() return shard.timeline:GetMediaPoolItem() end)
        if not item_ok or not media_item then error("Helper did not return a MediaPoolItem: " .. shard.name) end
        shard.media_item = media_item
    end
    if #prepared.entries ~= #tracks then error("Helper generation is incomplete") end
    append_log("Helper generation validated: " .. generation .. " tracks=" .. tostring(#prepared.entries) .. " shards=" .. tostring(#prepared.shards))
    return prepared
end

local function append_live_visualizers(project, timeline, prepared, video_track)
    local media_pool = project:GetMediaPool()
    if not media_pool then error("Resolve did not return the Media Pool") end
    local inserted = 0
    local failed_ids = {}
    local failed_seen = {}
    local errors = {}

    local switch_ok, switch_result = pcall(function() return project:SetCurrentTimeline(timeline) end)
    local current_ok, current_timeline = pcall(function() return project:GetCurrentTimeline() end)
    if not switch_ok or not switch_result or not current_ok or not timelines_match(current_timeline, timeline) then
        error("Resolve did not switch to the target timeline for live insertion")
    end

    local function mark_failure(track, index, message)
        local raw_id = type(track) == "table" and type(track.id) == "string" and trim(track.id) ~= "" and track.id or nil
        if raw_id and not failed_seen[raw_id] then
            failed_seen[raw_id] = true
            table.insert(failed_ids, raw_id)
        end
        table.insert(errors, tostring(raw_id or ("track #" .. tostring(index))) .. ": " .. tostring(message))
    end

    for _, entry in ipairs(prepared.entries or {}) do
        local track = entry.track
        local timeline_item = nil
        local ok, err = pcall(function()
            local duration_frames = entry.source_end - entry.source_start
            local record_frame = tonumber(track.record_frame)
            local raw_id = type(track.id) == "string" and track.id or nil
            if record_frame == nil then error("record_frame is missing") end
            if raw_id == nil or raw_id == "" then error("string track.id is missing") end

            local append_ok, append_result = pcall(function() return media_pool:AppendToTimeline({
                {
                    mediaPoolItem = entry.shard.media_item,
                    startFrame = entry.source_start,
                    endFrame = entry.source_end,
                    recordFrame = record_frame,
                    mediaType = 1,
                    trackIndex = video_track,
                }
            }) end)
            if not append_ok or append_result == false then error("Resolve did not insert the PNG carrier on the target: " .. tostring(append_result)) end
            local timeline_items = validated_append_items(append_result, 1, "Target live append " .. raw_id)
            timeline_item = timeline_items[1]
            if not timeline_contains_item_on_track(timeline, video_track, timeline_item) then
                error("Resolve inserted the PNG carrier on the wrong video track")
            end
            local target_source_ok, target_source_item = pcall(function() return timeline_item:GetMediaPoolItem() end)
            if not target_source_ok or not media_pool_items_match(target_source_item, entry.shard.media_item) then
                error("Target carrier does not reference the requested helper MediaPoolItem")
            end
            local actual_start, actual_end, actual_duration = strict_timeline_item_range(timeline_item, "Target live item " .. raw_id)
            if actual_start ~= record_frame or actual_end ~= record_frame + duration_frames or actual_duration ~= duration_frames then
                error("target carrier range=" .. tostring(actual_start) .. ".." .. tostring(actual_end) .. " duration=" .. tostring(actual_duration)
                    .. " instead of " .. tostring(record_frame) .. ".." .. tostring(record_frame + duration_frames))
            end
            local api_source_start = optional_timeline_item_frame(timeline_item, "GetSourceStartFrame")
            local api_source_end = optional_timeline_item_frame(timeline_item, "GetSourceEndFrame")
            append_log(string.format(
                "Target source #%03d id=%s helper=%s requested=[%d,%d) apiStart=%s apiEnd=%s target=[%d,%d)",
                entry.index, raw_id, entry.shard.name, entry.source_start, entry.source_end,
                tostring(api_source_start), tostring(api_source_end), actual_start, actual_end
            ))

            local item_name = VISUALIZER_PREFIX .. raw_id
            local name_ok, name_result = pcall(function() return timeline_item:SetName(item_name) end)
            if not name_ok or name_result == false then error("Could not set the timeline item name") end
            local color_ok, color_result = pcall(function() return timeline_item:SetClipColor("Orange") end)
            if not color_ok or color_result == false then error("Could not set the timeline item color") end
            build_live_fusion_comp(timeline_item, track, prepared.manifest_settings or {})
        end)

        if ok then
            inserted = inserted + 1
        else
            if timeline_item then
                local delete_ok, delete_result = pcall(function() return timeline:DeleteClips({ timeline_item }, false) end)
                if not delete_ok or delete_result == false then
                    error("Could not delete failed timeline carrier " .. tostring(track.id or "") .. ": " .. tostring(delete_result) .. "; original error: " .. tostring(err))
                end
                if timeline_contains_item_on_track(timeline, video_track, timeline_item) then
                    error("Failed timeline carrier remained on V" .. tostring(video_track) .. ": " .. tostring(track.id or ""))
                end
            end
            mark_failure(track, entry.index, err)
        end
    end
    return inserted, failed_ids, errors
end

local function append_legacy_visualizers(project, timeline, jobs, video_track)
    local media_pool = project:GetMediaPool()
    local switch_ok, switch_result = pcall(function() return project:SetCurrentTimeline(timeline) end)
    local current_ok, current_timeline = pcall(function() return project:GetCurrentTimeline() end)
    if not switch_ok or not switch_result or not current_ok or not timelines_match(current_timeline, timeline) then
        error("Resolve did not switch to the target timeline for legacy fallback")
    end
    local out_dir = trim(jobs.output_dir or "")
    if out_dir == "" then error(tr("error.output_dir_insert")) end
    local settings = jobs.settings or {}
    local timeline_width = tonumber(settings.timeline_width)
    local timeline_height = tonumber(settings.timeline_height)
    if not timeline_width or not timeline_height or timeline_width <= 0 or timeline_height <= 0 then
        error(tr("error.legacy_resolution_missing"))
    end
    local player_width = tonumber(settings.player_width or settings.width or 640) or 640
    local player_height = tonumber(settings.player_height or settings.height or 160) or 160
    local bake_position = settings.bake_position == true
    local margin = tonumber(settings.margin)
    if margin == nil then margin = THEME.layouts.classic.margin end
    local render_fps = tonumber(settings.fps or 15) or 15
    local inserted = 0

    for _, track in ipairs(jobs.tracks or {}) do
        local overlay_path = overlay_path_for_job(out_dir, track)
        local overlay_items = media_pool:ImportMedia({ overlay_path })
        local overlay_item = first_item(overlay_items)
        if not overlay_item then
            error(tr("error.overlay_import", { path = overlay_path }))
        end
        local item_name = VISUALIZER_PREFIX .. tostring(track.id or safe_stem(overlay_path))
        pcall(function() overlay_item:SetName(item_name) end)
        local frame_count = math.max(1, math.ceil((tonumber(track.duration) or 0) * render_fps))
        local record_frame = tonumber(track.record_frame) or 0
        local append_ok, append_result = pcall(function() return media_pool:AppendToTimeline({
            {
                mediaPoolItem = overlay_item,
                startFrame = 0,
                endFrame = frame_count,
                recordFrame = record_frame,
                mediaType = 1,
                trackIndex = video_track,
            }
        }) end)
        if not append_ok or append_result == false then error(tr("error.legacy_insert", { details = append_result })) end
        local timeline_items = validated_append_items(append_result, 1, "Target legacy append " .. item_name)
        local timeline_item = timeline_items[1]
        if not timeline_contains_item_on_track(timeline, video_track, timeline_item) then
            error(tr("error.legacy_wrong_track"))
        end
        local expected_duration = tonumber(track.duration_frames)
        if not expected_duration or expected_duration <= 0 or expected_duration % 1 ~= 0 then
            error("Captured legacy job has no valid duration_frames")
        end
        local actual_start, actual_end, actual_duration = strict_timeline_item_range(timeline_item, "Target legacy item " .. item_name)
        if actual_start ~= record_frame or actual_end ~= record_frame + expected_duration or actual_duration ~= expected_duration then
            error("legacy target range=" .. tostring(actual_start) .. ".." .. tostring(actual_end) .. " duration=" .. tostring(actual_duration)
                .. " instead of " .. tostring(record_frame) .. ".." .. tostring(record_frame + expected_duration))
        end
        append_log(string.format(
            "Legacy target source id=%s requested=[0,%d) apiStart=%s apiEnd=%s target=[%d,%d)",
            tostring(track.id or ""), frame_count,
            tostring(optional_timeline_item_frame(timeline_item, "GetSourceStartFrame")),
            tostring(optional_timeline_item_frame(timeline_item, "GetSourceEndFrame")),
            actual_start, actual_end
        ))
        local name_ok, name_result = pcall(function() return timeline_item:SetName(item_name) end)
        if not name_ok or name_result == false then error("Could not set the legacy timeline item name") end
        pcall(function() timeline_item:SetClipColor("Orange") end)
        pcall(function()
            if bake_position then
                timeline_item:SetProperty("ZoomX", 1.0)
                timeline_item:SetProperty("ZoomY", 1.0)
                timeline_item:SetProperty("Pan", 0.0)
                timeline_item:SetProperty("Tilt", 0.0)
            else
                local zoom = math.max(0.05, math.min(1.0, player_width / math.max(1, timeline_width)))
                timeline_item:SetProperty("ZoomX", zoom)
                timeline_item:SetProperty("ZoomY", zoom)
                timeline_item:SetProperty("Pan", -timeline_width / 2 + margin + player_width / 2)
                timeline_item:SetProperty("Tilt", -timeline_height / 2 + margin + player_height / 2)
            end
        end)
        inserted = inserted + 1
    end
    if inserted ~= #(jobs.tracks or {}) then
        error(tr("error.legacy_incomplete", { inserted = inserted, total = #(jobs.tracks or {}) }))
    end
    return inserted
end

local function current_project_and_timeline()
    local project_manager = resolve:GetProjectManager()
    local project = project_manager:GetCurrentProject()
    if not project then error(tr("error.project_required")) end
    local timeline = project:GetCurrentTimeline()
    if not timeline then error(tr("error.timeline_required")) end
    return project_manager, project, timeline
end

local HANDLERS = {}

function HANDLERS.on_update_from_timeline(ev)
    set_busy(true)
    local ok, err = pcall(function()
        set_last_error("")
        set_progress(1, tr("status.saving_settings"))
        save_current_style()
        set_progress(2, tr("status.checking_project"))
        local project_manager, project, timeline = current_project_and_timeline()
        local mode = renderer_mode_from_ui()
        set_progress(3, tr("status.scanning_audio"))
        local jobs, audio_tracks, video_track, partial_update = collect_audio_jobs(project, timeline, true, mode ~= "legacy_mov")
        if #(jobs.tracks or {}) == 0 then
            local details = tostring(jobs.scan_summary or "")
            if details ~= "" then details = tr("error.details", { details = details }) end
            local hint = ""
            if tonumber(jobs.missing_path_count or 0) > 0 then
                hint = tr("error.no_audio_path_hint")
            end
            error(tr("error.no_audio_clips", { tracks = table.concat(audio_tracks, ","), hint = hint, details = details }))
        end
        ensure_video_track(timeline, video_track)
        set_progress(5, tr("status.preparing_jobs"))
        append_log(tr("log.audio_found", { tracks = table.concat(audio_tracks, ","), count = #jobs.tracks }))
        local original_jobs_by_id = {}
        for _, job in ipairs(jobs.tracks) do
            if type(job.id) ~= "string" or job.id == "" then error("Invalid source job.id") end
            if original_jobs_by_id[job.id] then error("Duplicate source job.id: " .. job.id) end
            original_jobs_by_id[job.id] = job
        end
        local job_ids = nil
        if partial_update then
            job_ids = {}
            for _, job in ipairs(jobs.tracks) do job_ids[tostring(job.id)] = true end
        end

        local live_manifest = nil
        local live_prepared = nil
        local live_prepare_ok = false
        local fallback_reason = nil
        if mode ~= "legacy_mov" then
            local prepare_ok, prepare_result = pcall(function() return run_live_engine(jobs) end)
            if prepare_ok then
                live_manifest = prepare_result
                set_progress(76, tr("status.preparing_helper"))
                local helper_ok, helper_result = pcall(function()
                    return prepare_live_visualizers(project, timeline, live_manifest)
                end)
                if helper_ok then
                    live_prepared = helper_result
                    live_prepare_ok = true
                else
                    fallback_reason = tostring(helper_result)
                    append_log(tr("warning.helper_failed", { details = fallback_reason }))
                end
            else
                fallback_reason = tostring(prepare_result)
                append_log(tr("warning.live_unavailable", { details = fallback_reason }))
            end
        end

        local inserted = 0
        if live_prepare_ok then
            -- Helper generation is complete and immutable before target replacement begins.
            local deleted = delete_existing_visualizers(timeline, video_track, job_ids)
            if deleted > 0 then append_log(tr("log.visualizers_deleted", { track = video_track, count = deleted })) end
            set_progress(82, tr("status.inserting_fusion"))
            local live_inserted, failed_ids, live_errors = append_live_visualizers(project, timeline, live_prepared, video_track)
            inserted = inserted + live_inserted
            append_log("Fusion live: " .. tostring(live_inserted) .. " of " .. tostring(#(live_manifest.tracks or {})))
            for _, live_error in ipairs(live_errors) do
                append_log(tr("warning.fusion", { details = live_error }))
            end

            if #failed_ids > 0 then
                set_progress(88, tr("status.legacy_fallback"))
                local fallback_jobs = {}
                for key, value in pairs(jobs) do fallback_jobs[key] = value end
                fallback_jobs.tracks = {}
                local fallback_seen = {}
                for _, failed_id in ipairs(failed_ids) do
                    if type(failed_id) ~= "string" or failed_id == "" then error("Invalid failed track ID") end
                    if fallback_seen[failed_id] then error("Duplicate failed track ID: " .. failed_id) end
                    local original_job = original_jobs_by_id[failed_id]
                    if not original_job then error("Unknown failed track ID: " .. failed_id) end
                    fallback_seen[failed_id] = true
                    table.insert(fallback_jobs.tracks, original_job)
                end
                run_engine(fallback_jobs)
                local legacy_inserted = append_legacy_visualizers(project, timeline, fallback_jobs, video_track)
                inserted = inserted + legacy_inserted
                append_log("Legacy fallback: " .. tostring(legacy_inserted) .. " of " .. tostring(#failed_ids))
            else
                append_log("Legacy fallback: 0")
            end
        else
            if mode == "legacy_mov" then
                set_progress(10, tr("status.preparing_legacy"))
            else
                set_progress(10, tr("status.legacy_fallback"))
            end
            run_engine(jobs)
            local deleted = delete_existing_visualizers(timeline, video_track, job_ids)
            if deleted > 0 then append_log(tr("log.visualizers_deleted", { track = video_track, count = deleted })) end
            set_progress(90, tr("status.importing_legacy"))
            inserted = append_legacy_visualizers(project, timeline, jobs, video_track)
            if fallback_reason then
                append_log("Legacy fallback: " .. tostring(inserted) .. " of " .. tostring(#jobs.tracks))
            else
                append_log("Legacy MOV: " .. tostring(inserted) .. " of " .. tostring(#jobs.tracks))
            end
        end
        set_progress(98, tr("status.saving_project"))
        local save_ok, save_result = pcall(function() return project_manager:SaveProject() end)
        if not save_ok or save_result == false then error(tr("error.project_save", { details = save_result })) end
        append_log(tr("log.visualizers_inserted", { track = video_track, count = inserted }))
        set_progress(100, tr("status.done"))
    end)
    if not ok then
        report_error(err)
    end
    set_busy(false)
end

function HANDLERS.on_list_clips(ev)
    set_busy(true)
    local ok, err = pcall(function()
        set_last_error("")
        set_progress(5, tr("status.reading_clip_list"))
        local _, project, timeline = current_project_and_timeline()
        local jobs, audio_tracks = collect_audio_jobs(project, timeline, false)
        append_log(tr("log.clips_listed", { tracks = table.concat(audio_tracks, ","), count = #jobs.tracks }))
        append_log(tr("log.scope_help"))
        set_progress(100, tr("status.clip_list_ready"))
    end)
    if not ok then
        report_error(err)
    end
    set_busy(false)
end

function HANDLERS.on_save_style(ev)
    local ok, err = pcall(function()
        save_current_style()
        append_log(tr("log.style_saved", { path = settings_path() }))
    end)
    if not ok then report_error(err) end
end

function HANDLERS.on_reset_style(ev)
    local ok, err = pcall(function()
        skin_profiles[active_skin] = THEME.default_profile(active_skin)
        apply_active_profile_to_ui()
        save_current_style()
        append_log(tr("log.profile_reset", { skin = skin_label(active_skin) }))
    end)
    if not ok then report_error(err) end
end

function HANDLERS.on_preview_style(ev)
    set_busy(true)
    local ok, err = pcall(function()
        save_current_style()
        set_progress(15, tr("status.generating_preview"))
        local preview_path = run_style_preview()
        set_progress(100, tr("status.preview_ready"))
        append_log(tr("log.preview_ready", { path = preview_path }))
        open_file(preview_path)
    end)
    if not ok then
        report_error(err)
    end
    set_busy(false)
end

function HANDLERS.on_open_preview(ev)
    local ok, err = pcall(function()
        local preview_path = last_preview_paths[active_skin] or ""
        if preview_path == "" or not file_exists(preview_path) then
            error(tr("error.preview_not_ready"))
        end
        open_file(preview_path)
    end)
    if not ok then report_error(err) end
end

function HANDLERS.on_copy_log(ev)
    local ok, err = pcall(function()
        local log = win:Find("Log")
        if log then
            log:SelectAll()
            log:Copy()
        end
    end)
    if not ok then report_error(err) end
end

function HANDLERS.on_open_log(ev)
    local path = log_path()
    if not file_exists(path) then write_file(path, "") end
    open_file(path)
end

function HANDLERS.on_clear_log(ev)
    local ok, err = pcall(function()
        local log = win:Find("Log")
        if log then
            pcall(function() log.Text = "" end)
            pcall(function() log.PlainText = "" end)
            pcall(function() log:Clear() end)
        end
        write_file(log_path(), "")
    end)
    if not ok then report_error(err) end
end

function HANDLERS.single_file_from_request(result)
    if result == nil then return "" end
    if type(result) == "string" then return trim(result):gsub('^"', ''):gsub('"$', '') end
    if type(result) == "table" then
        local base = tostring(result.Path or "")
        for key, value in pairs(result) do
            if key ~= "Path" and value and tostring(value) ~= "" then
                if base ~= "" then return path_join(base, tostring(value)) end
                return tostring(value)
            end
        end
    end
    return trim(tostring(result)):gsub('^"', ''):gsub('"$', '')
end

function HANDLERS.on_browse_fallback_logo(ev)
    local ok, err = pcall(function()
        local selected = fusion:RequestFile("", "*.png", {})
        local path = HANDLERS.single_file_from_request(selected)
        if path == "" then return end
        if not path:lower():match("%.png$") then
            error(tr("error.choose_png"))
        end
        set_text("FallbackLogoPath", path)
        save_current_style()
        append_log(tr("log.logo_selected", { path = path }))
    end)
    if not ok then report_error(err) end
end

function HANDLERS.on_default_fallback_logo(ev)
    local ok, err = pcall(function()
        set_text("FallbackLogoPath", default_fallback_logo_path())
        save_current_style()
        append_log(tr("log.logo_default"))
    end)
    if not ok then report_error(err) end
end

function HANDLERS.apply_preset(preset_name)
    local ok, err = pcall(function()
        if preset_name == "Custom" or not THEME.palettes[preset_name] then return end
        local design = read_design_from_ui()
        local skin_defaults = THEME.palette_design("Default", active_skin)
        for _, key in ipairs(THEME.palette_keys) do
            design[key] = skin_defaults[key]
        end
        update_table(design, THEME.palettes[preset_name])
        design = THEME.enforce_design(active_skin, design)
        apply_design_to_ui(design)
        local profile = capture_active_profile()
        profile.palette = preset_name
        save_current_style()
        append_log(tr("log.palette_applied", { palette = palette_label(preset_name), skin = skin_label(active_skin) }))
    end)
    if not ok then report_error(err) end
end

function THEME.on_apply_palette(ev)
    local selector = win:Find("PaletteSelector")
    local index = selector and tonumber(selector.CurrentIndex) or 0
    HANDLERS.apply_preset(THEME.palette_order(active_skin)[(index or 0) + 1] or "Custom")
end

function HANDLERS.pick_color_safely(field_id, fallback)
    if not PLATFORM.windows then
        local notice = tr("notice.color_manual")
        append_log(notice)
        set_progress(0, notice)
        return
    end
    local ok, err = pcall(function() pick_windows_color(field_id, fallback) end)
    if not ok then
        report_error(err)
        local notice = tr("notice.color_manual")
        append_log(notice)
        set_progress(0, notice)
    end
end

-- Keep UI bootstrap locals in a separate LuaJIT function scope.
function HANDLERS.run_plugin()
local internal_probe_config = rawget(_G, "TVIZ_INTERNAL_PROBE")
if type(internal_probe_config) == "table" then
    local project_manager = resolve:GetProjectManager()
    local project = project_manager and project_manager:GetCurrentProject() or nil
    local timeline = project and project:GetCurrentTimeline() or nil
    if not project or not timeline then error("TVIZ internal probe requires an active isolated project/timeline") end
    local jobs = json_decode(read_file(tostring(internal_probe_config.jobs_path or "")))
    local manifest = json_decode(read_file(tostring(internal_probe_config.manifest_path or "")))
    validate_live_manifest(manifest, jobs)
    local video_track = tonumber(internal_probe_config.video_track) or 2
    ensure_video_track(timeline, video_track)
    local prepared = prepare_live_visualizers(project, timeline, manifest)
    local job_ids = {}
    for _, job in ipairs(jobs.tracks or {}) do job_ids[tostring(job.id)] = true end
    local delete_filter = job_ids
    if internal_probe_config.replace_all == true then delete_filter = nil end
    local deleted = delete_existing_visualizers(timeline, video_track, delete_filter)
    local inserted, failed_ids, errors = append_live_visualizers(project, timeline, prepared, video_track)
    if #failed_ids > 0 or #errors > 0 or inserted ~= #(jobs.tracks or {}) then
        error("TVIZ internal probe insert failed: inserted=" .. tostring(inserted)
            .. " failed=" .. tostring(#failed_ids) .. " errors=" .. table.concat(errors, "; "))
    end
    local save_ok, save_result = pcall(function() return project_manager:SaveProject() end)
    if not save_ok or save_result == false then error("TVIZ internal probe did not save project") end
    return {
        generation = prepared.generation,
        helper_prefix = prepared.helper_prefix,
        shard_count = #(prepared.shards or {}),
        inserted = inserted,
        deleted = deleted,
    }
end

local existing = ui:FindWindow(PLUGIN_ID)
if existing then
    existing:Show()
    existing:Raise()
    return
end

local root = install_root()
local default_output = path_join(path_join(root, "outputs"), "resolve")
local saved_settings = load_settings()
language_mode = saved_settings.language_mode or "auto"
active_language = effective_language(language_mode)
active_skin = THEME.is_supported_skin(saved_settings.active_skin) and saved_settings.active_skin or THEME.default_skin
skin_profiles = type(saved_settings.profiles) == "table" and saved_settings.profiles or THEME.default_profiles()
local saved_profile = THEME.load_profile(active_skin, skin_profiles[active_skin])
skin_profiles[active_skin] = saved_profile
local saved_design = saved_profile.design
local saved_fallback_logo = saved_settings.fallback_logo_path or default_fallback_logo_path()
local saved_renderer_mode = saved_settings.renderer_mode or DEFAULT_RENDERER_MODE
local header_font = ui:Font({ Family = "Segoe UI", PointSize = 15, Bold = true })
local section_font = ui:Font({ Family = "Segoe UI", PointSize = 11, Bold = true })
local hint_font = ui:Font({ Family = "Segoe UI", PointSize = 9 })
local compact_style = [[
QWidget { background: #202124; color: #d7d9dc; font-family: "Segoe UI"; }
QLabel { background: transparent; color: #d7d9dc; }
QTabBar { background: #18191c; border-bottom: 1px solid #3b3e45; }
QTabBar::tab { min-width: 130px; min-height: 28px; padding: 4px 16px; background: #24262a; color: #969ba3; border: 1px solid #3b3e45; border-bottom: 2px solid #24262a; }
QTabBar::tab:hover { background: #2a2c31; color: #d7d9dc; }
QTabBar::tab:selected { background: #202124; color: #f0f1f2; border-bottom: 2px solid #e0524d; }
QLineEdit, QComboBox, QSpinBox { min-width: 96px; min-height: 26px; padding: 2px 7px; background: #151619; color: #d7d9dc; border: 1px solid #3b3e45; border-radius: 3px; selection-background-color: #465a73; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #69717d; }
QPushButton { min-height: 24px; padding: 2px 12px; border: 1px solid #3b3e45; border-radius: 3px; background: #2a2c30; color: #d7d9dc; }
QPushButton:hover { border-color: #555a63; background: #303238; }
QPushButton:pressed, QPushButton:checked { background: #34373d; border-color: #666c76; color: #f0f1f2; }
QPushButton:disabled { background: #24262a; color: #6f747c; border-color: #34363b; }
QPushButton#AdvancedTimelineHeader, QPushButton#AdvancedRenderHeader, QPushButton#AdvancedElementsHeader, QPushButton#AdvancedTypographyHeader, QPushButton#AdvancedCardHeader, QPushButton#AdvancedActionsHeader { background: #24262a; padding: 4px 10px; }
QPushButton#UpdateFromTimeline { min-height: 34px; background: #3f566f; border-color: #58728e; color: #f3f5f7; font-weight: 600; }
QPushButton#UpdateFromTimeline:hover { background: #49627d; border-color: #6b87a3; }
QPushButton#UpdateFromTimeline:disabled { background: #303b47; border-color: #46515e; color: #8d969f; }
QCheckBox { spacing: 6px; background: transparent; color: #d7d9dc; }
QTextEdit { background: #18191c; color: #c7cacf; border: 1px solid #3b3e45; border-radius: 3px; padding: 5px; }
QLabel#LastError { padding: 6px 8px; background: #302122; color: #f0a09c; border: 1px solid #71413f; border-radius: 3px; }
]]

win = dispatcher:AddWindow({
    ID = PLUGIN_ID,
    WindowTitle = tr("window.title"),
    Geometry = { 100, 45, 900, 700 },
    MinimumSize = { 720, 560 },
    StyleSheet = compact_style,
}, ui:VGroup({ Spacing = 8 }, {
    ui:TabBar({ ID = "MainTabs", Weight = 0 }),

    ui:VGroup({ ID = "PageMain", Weight = 1, Spacing = 8 }, {
        ui:Label({ Text = "Track Visualizer", Font = header_font, Weight = 0 }),
        ui:Label({ Text = tr("app.subtitle"), Font = hint_font, WordWrap = true, Weight = 0 }),
        ui:VGap(4, 0),
        ui:Label({ Text = tr("section.quick_start"), Font = section_font, Weight = 0 }),
        ui:HGroup({ Weight = 0 }, {
            ui:Label({ Text = tr("field.audio_tracks"), MinimumSize = { 150, 0 }, Weight = 0 }),
            ui:LineEdit({ ID = "AudioTracks", Text = "1,2,3", MinimumSize = { 180, 28 }, MaximumSize = { 240, 28 }, Weight = 0 }),
            ui:HGap(0, 1),
        }),
        ui:HGroup({ Weight = 0 }, {
            ui:Label({ Text = tr("field.video_track"), MinimumSize = { 150, 0 }, Weight = 0 }),
            ui:SpinBox({ ID = "VideoTrack", Value = 2, Minimum = 1, Maximum = 64, MinimumSize = { 100, 28 }, MaximumSize = { 120, 28 }, Weight = 0 }),
            ui:HGap(0, 1),
        }),
        ui:Label({ Text = tr("hint.quick_start"), Font = hint_font, WordWrap = true, Weight = 0 }),
        ui:Button({ ID = "UpdateFromTimeline", Text = tr("action.update"), MinimumSize = { 0, 38 }, Weight = 0 }),
        ui:HGroup({ Weight = 0 }, {
            ui:Label({ Text = tr("field.status"), MinimumSize = { 70, 0 }, Weight = 0 }),
            ui:Label({ ID = "ProgressStatus", Text = tr("status.ready"), Weight = 1 }),
        }),
        ui:Label({ Text = tr("hint.status"), Font = hint_font, WordWrap = true, Weight = 0 }),
        ui:Label({ ID = "LastError", Text = "", Hidden = true, WordWrap = true, Font = hint_font, Weight = 0 }),
        ui:VGap(4, 0),
        ui:Label({ Text = tr("section.appearance"), Font = section_font, Weight = 0 }),
        ui:HGroup({ Weight = 0 }, {
            ui:Label({ Text = tr("field.theme"), MinimumSize = { 150, 0 }, Weight = 0 }),
            ui:ComboBox({ ID = "SkinSelector", MinimumSize = { 260, 28 }, MaximumSize = { 340, 28 }, Weight = 0 }),
            ui:HGap(0, 1),
        }),
        ui:HGroup({ Weight = 0 }, {
            ui:Label({ Text = tr("field.palette"), MinimumSize = { 150, 0 }, Weight = 0 }),
            ui:ComboBox({ ID = "PaletteSelector", MinimumSize = { 260, 28 }, MaximumSize = { 340, 28 }, Weight = 0 }),
            ui:Button({ ID = "ApplyPalette", Text = tr("action.apply"), MaximumSize = { 110, 28 }, Weight = 0 }),
            ui:HGap(0, 1),
        }),
        ui:VGap(4, 0),
        ui:Label({ Text = tr("section.preview"), Font = section_font, Weight = 0 }),
        ui:HGroup({ Weight = 0 }, {
            ui:Button({ ID = "PreviewStyle", Text = tr("action.create_preview"), Weight = 0 }),
            ui:Button({ ID = "OpenPreview", Text = tr("action.open_png"), Enabled = false, Weight = 0 }),
            ui:HGap(0, 1),
        }),
        ui:Label({ ID = "PreviewStatus", Text = tr("preview.external_hint"), Font = hint_font, WordWrap = true, Weight = 0 }),
    }),

    ui:VGroup({ ID = "PageAdvanced", Hidden = true, Weight = 1, Spacing = 6 }, {
        ui:Label({ Text = tr("advanced.title"), Font = header_font, Weight = 0 }),
        ui:Label({ Text = tr("advanced.subtitle"), Font = hint_font, WordWrap = true, Weight = 0 }),

        ui:Button({ ID = "AdvancedTimelineHeader", Text = "▶ " .. tr("advanced.timeline"), Checkable = true, Checked = false, Weight = 0 }),
        ui:VGroup({ ID = "AdvancedTimelineBody", Hidden = true, Weight = 0, Spacing = 5 }, {
            ui:HGroup({ Weight = 0 }, {
                ui:CheckBox({ ID = "SwitchOnNextStart", Text = tr("field.switch_next"), Checked = true, Weight = 0 }),
                ui:HGap(0, 1),
            }),
            ui:HGroup({ Weight = 0 }, {
                ui:Label({ Text = tr("field.update_scope"), MinimumSize = { 170, 0 }, Weight = 0 }),
                ui:LineEdit({ ID = "UpdateScope", Text = "", PlaceholderText = tr("scope.placeholder"), MinimumSize = { 360, 28 }, Weight = 1 }),
                ui:Button({ ID = "ListClips", Text = tr("action.list_clips"), MaximumSize = { 140, 28 }, Weight = 0 }),
            }),
            ui:Label({ Text = tr("scope.hint"), Font = hint_font, WordWrap = true, Weight = 0 }),
        }),

        ui:Button({ ID = "AdvancedRenderHeader", Text = "▶ " .. tr("advanced.render"), Checkable = true, Checked = false, Weight = 0 }),
        ui:VGroup({ ID = "AdvancedRenderBody", Hidden = true, Weight = 0, Spacing = 5 }, {
            ui:HGroup({ Weight = 0 }, {
                ui:Label({ Text = tr("field.mode"), MinimumSize = { 170, 0 }, Weight = 0 }),
                ui:ComboBox({ ID = "RendererMode", MinimumSize = { 260, 28 }, MaximumSize = { 320, 28 }, Weight = 0 }),
                ui:HGap(0, 1),
            }),
            ui:Label({ Text = tr("render.hint"), Font = hint_font, WordWrap = true, Weight = 0 }),
            ui:HGroup({ Weight = 0 }, {
                ui:Label({ Text = tr("field.player_size"), MinimumSize = { 170, 0 }, Weight = 0 }),
                ui:SpinBox({ ID = "Width", Value = saved_profile.base_width, Minimum = 240, Maximum = 1920, MinimumSize = { 100, 28 }, MaximumSize = { 120, 28 }, Weight = 0 }),
                ui:Label({ Text = "x", Weight = 0 }),
                ui:SpinBox({ ID = "Height", Value = saved_profile.base_height, Minimum = 80, Maximum = 720, MinimumSize = { 100, 28 }, MaximumSize = { 120, 28 }, Weight = 0 }),
                ui:HGap(0, 1),
            }),
            ui:HGroup({ Weight = 0 }, {
                ui:Label({ Text = tr("field.frame_rate"), MinimumSize = { 170, 0 }, Weight = 0 }),
                ui:Label({ Text = tr("field.render_fps"), Weight = 0 }),
                ui:SpinBox({ ID = "RenderFps", Value = 15, Minimum = 5, Maximum = 60, MinimumSize = { 90, 28 }, MaximumSize = { 110, 28 }, Weight = 0 }),
                ui:Label({ Text = tr("field.fallback_fps"), Weight = 0 }),
                ui:SpinBox({ ID = "Fps", Value = 30, Minimum = 1, Maximum = 120, MinimumSize = { 90, 28 }, MaximumSize = { 110, 28 }, Weight = 0 }),
                ui:HGap(0, 1),
            }),
            ui:Label({ Text = tr("hint.fallback_fps"), Font = hint_font, WordWrap = true, Weight = 0 }),
            ui:HGroup({ Weight = 0 }, {
                ui:Label({ Text = tr("field.margin"), MinimumSize = { 170, 0 }, Weight = 0 }),
                ui:SpinBox({ ID = "PlayerMargin", Value = saved_profile.margin, Minimum = 0, Maximum = 400, MinimumSize = { 100, 28 }, MaximumSize = { 120, 28 }, Weight = 0 }),
                ui:HGap(0, 1),
            }),
            ui:HGroup({ Weight = 0 }, {
                ui:CheckBox({ ID = "BakePosition", Text = tr("field.bake_position"), Checked = saved_profile.bake_position ~= false, Weight = 0 }),
                ui:HGap(0, 1),
            }),
            ui:HGroup({ Weight = 0 }, {
                ui:Label({ Text = tr("field.output_dir"), MinimumSize = { 170, 0 }, Weight = 0 }),
                ui:LineEdit({ ID = "OutputDir", Text = default_output, MinimumSize = { 480, 28 }, Weight = 1 }),
            }),
        }),

        ui:Button({ ID = "AdvancedElementsHeader", Text = "▶ " .. tr("advanced.elements"), Checkable = true, Checked = false, Weight = 0 }),
        ui:VGroup({ ID = "AdvancedElementsBody", Hidden = true, Weight = 0, Spacing = 5 }, {
            ui:HGroup({ ID = "BrandTextRow", Weight = 0 }, {
                ui:Label({ Text = tr("field.brand_text"), MinimumSize = { 170, 0 }, Weight = 0 }),
                ui:LineEdit({ ID = "BrandText", Text = tostring(saved_design.brand_text or DEFAULT_DESIGN.brand_text), MinimumSize = { 320, 28 }, MaximumSize = { 440, 28 }, Weight = 0 }),
                ui:HGap(0, 1),
            }),
            ui:HGroup({ ID = "ElementFlagsRow", Weight = 0 }, {
                ui:CheckBox({ ID = "GlassEnabled", Text = tr("field.glass"), Checked = saved_design.glass_enabled ~= false, Weight = 0 }),
                ui:CheckBox({ ID = "ShowCover", Text = tr("field.cover"), Checked = saved_design.show_cover ~= false, Weight = 0 }),
                ui:CheckBox({ ID = "ShowBrand", Text = tr("field.brand"), Checked = saved_design.show_brand ~= false, Weight = 0 }),
                ui:HGap(0, 1),
            }),
            ui:HGroup({ ID = "DynamicFlagsRow", Weight = 0 }, {
                ui:CheckBox({ ID = "ShowTime", Text = tr("field.time"), Checked = saved_design.show_time ~= false, Weight = 0 }),
                ui:CheckBox({ ID = "ShowProgress", Text = tr("field.progress"), Checked = saved_design.show_progress ~= false, Weight = 0 }),
                ui:CheckBox({ ID = "ShowKnob", Text = tr("field.marker"), Checked = saved_design.show_knob ~= false, Weight = 0 }),
                ui:HGap(0, 1),
            }),
            ui:HGroup({ ID = "FallbackLogoRow", Weight = 0 }, {
                ui:Label({ Text = tr("field.fallback_logo"), MinimumSize = { 170, 0 }, Weight = 0 }),
                ui:LineEdit({ ID = "FallbackLogoPath", Text = saved_fallback_logo, MinimumSize = { 360, 28 }, Weight = 1 }),
                ui:Button({ ID = "BrowseFallbackLogo", Text = tr("action.choose_png"), MaximumSize = { 120, 28 }, Weight = 0 }),
                ui:Button({ ID = "DefaultFallbackLogo", Text = tr("action.default"), MaximumSize = { 120, 28 }, Weight = 0 }),
            }),
        }),

        ui:Button({ ID = "AdvancedTypographyHeader", Text = "▶ " .. tr("advanced.typography"), Checkable = true, Checked = false, Weight = 0 }),
        ui:VGroup({ ID = "AdvancedTypographyBody", Hidden = true, Weight = 0, Spacing = 5 }, {
            ui:HGroup({ Weight = 0 }, {
                ui:Label({ ID = "PrimaryTextLabel", Text = tr("field.title"), MinimumSize = { 170, 0 }, Weight = 0 }),
                ui:LineEdit({ ID = "PrimaryTextColor", Text = normalize_hex(saved_design.primary_text_color, DEFAULT_DESIGN.primary_text_color), MinimumSize = { 120, 28 }, MaximumSize = { 140, 28 }, Weight = 0 }),
                ui:Button({ ID = "PickPrimary", Text = tr("field.color"), MaximumSize = { 80, 28 }, Weight = 0 }),
                ui:Label({ Text = tr("field.size"), Weight = 0 }),
                ui:SpinBox({ ID = "TitleSize", Value = tonumber(saved_design.title_size) or DEFAULT_DESIGN.title_size, Minimum = 10, Maximum = 48, MinimumSize = { 80, 28 }, MaximumSize = { 100, 28 }, Weight = 0 }),
                ui:HGap(0, 1),
            }),
            ui:HGroup({ Weight = 0 }, {
                ui:Label({ Text = tr("field.title_font"), MinimumSize = { 170, 0 }, Weight = 0 }),
                ui:ComboBox({ ID = "TitleFontFamily", Editable = true, CurrentText = tostring(saved_design.title_font_family or DEFAULT_DESIGN.title_font_family), MinimumSize = { 320, 28 }, MaximumSize = { 440, 28 }, Weight = 0 }),
                ui:HGap(0, 1),
            }),
            ui:HGroup({ Weight = 0 }, {
                ui:Label({ ID = "SecondaryTextLabel", Text = tr("field.artist_metadata"), MinimumSize = { 170, 0 }, Weight = 0 }),
                ui:LineEdit({ ID = "SecondaryTextColor", Text = normalize_hex(saved_design.secondary_text_color, DEFAULT_DESIGN.secondary_text_color), MinimumSize = { 120, 28 }, MaximumSize = { 140, 28 }, Weight = 0 }),
                ui:Button({ ID = "PickSecondary", Text = tr("field.color"), MaximumSize = { 80, 28 }, Weight = 0 }),
                ui:HGap(0, 1),
            }),
            ui:HGroup({ Weight = 0 }, {
                ui:Label({ Text = tr("field.artist_size"), MinimumSize = { 170, 0 }, Weight = 0 }),
                ui:SpinBox({ ID = "ArtistSize", Value = tonumber(saved_design.artist_size) or DEFAULT_DESIGN.artist_size, Minimum = 8, Maximum = 36, MinimumSize = { 80, 28 }, MaximumSize = { 100, 28 }, Weight = 0 }),
                ui:HGap(0, 1),
            }),
            ui:HGroup({ Weight = 0 }, {
                ui:Label({ Text = tr("field.meta_size"), MinimumSize = { 170, 0 }, Weight = 0 }),
                ui:SpinBox({ ID = "MetaSize", Value = tonumber(saved_design.meta_size) or DEFAULT_DESIGN.meta_size, Minimum = 8, Maximum = 30, MinimumSize = { 80, 28 }, MaximumSize = { 100, 28 }, Weight = 0 }),
                ui:HGap(0, 1),
            }),
            ui:HGroup({ Weight = 0 }, {
                ui:Label({ Text = tr("field.artist_font"), MinimumSize = { 170, 0 }, Weight = 0 }),
                ui:ComboBox({ ID = "ArtistFontFamily", Editable = true, CurrentText = tostring(saved_design.artist_font_family or DEFAULT_DESIGN.artist_font_family), MinimumSize = { 320, 28 }, MaximumSize = { 440, 28 }, Weight = 0 }),
                ui:HGap(0, 1),
            }),
        }),

        ui:Button({ ID = "AdvancedCardHeader", Text = "▶ " .. tr("advanced.card"), Checkable = true, Checked = false, Weight = 0 }),
        ui:VGroup({ ID = "AdvancedCardBody", Hidden = true, Weight = 0, Spacing = 5 }, {
            ui:HGroup({ ID = "PanelColorRow", Weight = 0 }, {
                ui:Label({ ID = "PanelColorLabel", Text = tr("field.panel"), MinimumSize = { 170, 0 }, Weight = 0 }),
                ui:LineEdit({ ID = "PanelColor", Text = normalize_hex(saved_design.panel_color, DEFAULT_DESIGN.panel_color), MinimumSize = { 120, 28 }, MaximumSize = { 140, 28 }, Weight = 0 }),
                ui:Button({ ID = "PickPanel", Text = tr("field.color"), MaximumSize = { 80, 28 }, Weight = 0 }),
                ui:Label({ Text = tr("field.opacity"), Weight = 0 }),
                ui:SpinBox({ ID = "PanelAlpha", Value = tonumber(saved_design.panel_alpha) or DEFAULT_DESIGN.panel_alpha, Minimum = 0, Maximum = 255, MinimumSize = { 80, 28 }, MaximumSize = { 100, 28 }, Weight = 0 }),
                ui:HGap(0, 1),
            }),
            ui:HGroup({ ID = "BorderColorRow", Weight = 0 }, {
                ui:Label({ Text = tr("field.border"), MinimumSize = { 170, 0 }, Weight = 0 }),
                ui:LineEdit({ ID = "BorderColor", Text = normalize_hex(saved_design.border_color, DEFAULT_DESIGN.border_color), MinimumSize = { 120, 28 }, MaximumSize = { 140, 28 }, Weight = 0 }),
                ui:Button({ ID = "PickBorder", Text = tr("field.color"), MaximumSize = { 80, 28 }, Weight = 0 }),
                ui:HGap(0, 1),
            }),
            ui:HGroup({ ID = "BorderAlphaRow", Weight = 0 }, {
                ui:Label({ Text = tr("field.border_opacity"), MinimumSize = { 170, 0 }, Weight = 0 }),
                ui:Label({ Text = tr("field.opacity"), Weight = 0 }),
                ui:SpinBox({ ID = "BorderAlpha", Value = tonumber(saved_design.border_alpha) or DEFAULT_DESIGN.border_alpha, Minimum = 0, Maximum = 255, MinimumSize = { 80, 28 }, MaximumSize = { 100, 28 }, Weight = 0 }),
                ui:HGap(0, 1),
            }),
            ui:HGroup({ ID = "CornerRadiusRow", Weight = 0 }, {
                ui:Label({ Text = tr("field.shape"), MinimumSize = { 170, 0 }, Weight = 0 }),
                ui:Label({ Text = tr("field.radius"), Weight = 0 }),
                ui:SpinBox({ ID = "CornerRadius", Value = tonumber(saved_design.corner_radius) or DEFAULT_DESIGN.corner_radius, Minimum = 0, Maximum = 64, MinimumSize = { 80, 28 }, MaximumSize = { 100, 28 }, Weight = 0 }),
                ui:HGap(0, 1),
            }),
            ui:HGroup({ ID = "GlassStrengthRow", Weight = 0 }, {
                ui:Label({ Text = tr("field.glass"), MinimumSize = { 170, 0 }, Weight = 0 }),
                ui:Label({ Text = tr("field.glass_strength"), Weight = 0 }),
                ui:SpinBox({ ID = "GlassStrength", Value = tonumber(saved_design.glass_strength) or DEFAULT_DESIGN.glass_strength, Minimum = 0, Maximum = 100, MinimumSize = { 80, 28 }, MaximumSize = { 100, 28 }, Weight = 0 }),
                ui:HGap(0, 1),
            }),
            ui:HGroup({ ID = "AccentColorRow", Weight = 0 }, {
                ui:Label({ Text = tr("field.accent"), MinimumSize = { 170, 0 }, Weight = 0 }),
                ui:LineEdit({ ID = "AccentColor", Text = normalize_hex(saved_design.accent_color, DEFAULT_DESIGN.accent_color), MinimumSize = { 120, 28 }, MaximumSize = { 140, 28 }, Weight = 0 }),
                ui:Button({ ID = "PickAccent", Text = tr("field.color"), MaximumSize = { 80, 28 }, Weight = 0 }),
                ui:HGap(0, 1),
            }),
            ui:HGroup({ ID = "TrackColorRow", Weight = 0 }, {
                ui:Label({ Text = tr("field.progress_line"), MinimumSize = { 170, 0 }, Weight = 0 }),
                ui:LineEdit({ ID = "TrackColor", Text = normalize_hex(saved_design.track_color, DEFAULT_DESIGN.track_color), MinimumSize = { 120, 28 }, MaximumSize = { 140, 28 }, Weight = 0 }),
                ui:Button({ ID = "PickTrack", Text = tr("field.color"), MaximumSize = { 80, 28 }, Weight = 0 }),
                ui:HGap(0, 1),
            }),
        }),

        ui:Button({ ID = "AdvancedActionsHeader", Text = "▶ " .. tr("advanced.actions"), Checkable = true, Checked = false, Weight = 0 }),
        ui:VGroup({ ID = "AdvancedActionsBody", Hidden = true, Weight = 0, Spacing = 5 }, {
            ui:Label({ Text = tr("hint.style_actions"), Font = hint_font, WordWrap = true, Weight = 0 }),
            ui:HGroup({ Weight = 0 }, {
                ui:Button({ ID = "SaveStyle", Text = tr("action.save_style"), Weight = 0 }),
                ui:Button({ ID = "ResetStyle", Text = tr("action.reset_style"), Weight = 0 }),
                ui:HGap(0, 1),
            }),
            ui:HGroup({ Weight = 0 }, {
                ui:Label({ Text = tr("field.language"), MinimumSize = { 170, 0 }, Weight = 0 }),
                ui:ComboBox({ ID = "LanguageMode", MinimumSize = { 260, 28 }, MaximumSize = { 320, 28 }, Weight = 0 }),
                ui:HGap(0, 1),
            }),
            ui:Label({ ID = "LanguageRestartHint", Text = tr("language.restart_hint"), Font = hint_font, WordWrap = true, Weight = 0 }),
        }),
        ui:VGap(0, 1),
    }),

    ui:VGroup({ ID = "PageDiagnostics", Hidden = true, Weight = 1, Spacing = 8 }, {
        ui:Label({ Text = tr("diagnostics.title"), Font = header_font, Weight = 0 }),
        ui:Label({ Text = tr("diagnostics.paths", { log = log_path(), dump = clip_dump_path(), error = path_join(install_root(), "last_error.txt") }), Font = hint_font, WordWrap = true, Weight = 0 }),
        ui:Label({ Text = tr("section.last_preview"), Font = section_font, Weight = 0 }),
        ui:Label({ ID = "PreviewPath", Text = tr("preview.not_created"), Font = hint_font, WordWrap = true, Weight = 0 }),
        ui:HGroup({ Weight = 0 }, {
            ui:Button({ ID = "CopyLog", Text = tr("action.copy_log"), Weight = 0 }),
            ui:Button({ ID = "OpenLog", Text = tr("action.open_log"), Weight = 0 }),
            ui:Button({ ID = "ClearLog", Text = tr("action.clear_log"), Weight = 0 }),
            ui:HGap(0, 1),
        }),
        ui:TextEdit({ ID = "Log", ReadOnly = true, MinimumSize = { 0, 360 }, Weight = 1 }),
    }),
}))

THEME.main_tabs = win:Find("MainTabs")
THEME.main_tabs:AddTab(tr("tab.main"))
THEME.main_tabs:AddTab(tr("tab.advanced"))
THEME.main_tabs:AddTab(tr("tab.diagnostics"))

function THEME.populate_font_combo(element_id, value)
    local combo = win:Find(element_id)
    if not combo then return end
    pcall(function() combo:Clear() end)
    pcall(function() combo:AddItems(FONT_FAMILIES) end)
    set_text(element_id, value)
end

function THEME.refresh_layout()
    if not win then return end
    pcall(function() win:RecalcLayout() end)
    pcall(function() win:Update() end)
    pcall(function() win:Repaint() end)
end

function THEME.set_element_hidden(element_id, hidden)
    local element = win:Find(element_id)
    if not element then return end
    pcall(function() element.Hidden = hidden and true or false end)
    pcall(function() element:Update() end)
end

update_skin_ui_visibility = function()
    local is_classic = active_skin == "classic"
    local is_minimal = active_skin == "minimal"
    local elements_header = win:Find("AdvancedElementsHeader")
    if is_minimal then
        if elements_header then
            elements_header.Checked = false
            elements_header.Text = "▶ " .. tr("advanced.elements")
        end
        THEME.set_element_hidden("AdvancedElementsHeader", true)
        THEME.set_element_hidden("AdvancedElementsBody", true)
    else
        THEME.set_element_hidden("AdvancedElementsHeader", false)
        local is_open = elements_header and (elements_header.Checked == true or elements_header.Checked == 1)
        THEME.set_element_hidden("AdvancedElementsBody", not is_open)
    end

    THEME.set_element_hidden("BrandTextRow", not is_classic)
    THEME.set_element_hidden("ElementFlagsRow", not is_classic)
    THEME.set_element_hidden("DynamicFlagsRow", not is_classic)
    THEME.set_element_hidden("FallbackLogoRow", is_minimal)
    THEME.set_element_hidden("BorderColorRow", is_minimal)
    THEME.set_element_hidden("GlassStrengthRow", is_minimal)
    THEME.set_element_hidden("AccentColorRow", is_minimal)
    THEME.set_element_hidden("TrackColorRow", is_minimal)

    local primary_label = win:Find("PrimaryTextLabel")
    local secondary_label = win:Find("SecondaryTextLabel")
    local panel_label = win:Find("PanelColorLabel")
    if primary_label then primary_label.Text = is_minimal and tr("field.title_timer") or tr("field.title") end
    if secondary_label then secondary_label.Text = is_minimal and tr("field.artist_border") or tr("field.artist_metadata") end
    if panel_label then panel_label.Text = is_minimal and tr("field.background_timer") or tr("field.panel") end

    local structural = THEME.enforce_design(active_skin, read_design_from_ui())
    set_checked("ShowCover", structural.show_cover)
    set_checked("ShowBrand", structural.show_brand)
    set_checked("ShowTime", structural.show_time)
    set_checked("ShowProgress", structural.show_progress)
    set_checked("ShowKnob", structural.show_knob)
    set_checked("GlassEnabled", structural.glass_enabled)
    THEME.refresh_layout()
end

function THEME.selected_skin_from_ui()
    local selector = win:Find("SkinSelector")
    local index = selector and tonumber(selector.CurrentIndex) or 0
    return THEME.skins[(index or 0) + 1] or THEME.default_skin
end

function THEME.on_skin_changed(ev)
    if suppress_skin_events then return end
    local next_skin = THEME.selected_skin_from_ui()
    if next_skin == active_skin then return end
    capture_active_profile()
    active_skin = next_skin
    apply_active_profile_to_ui()
    save_current_style()
    append_log(tr("log.skin_active", { skin = skin_label(active_skin) }))
end

function THEME.on_language_changed(ev)
    if suppress_language_events then return end
    local next_mode = language_mode_from_ui()
    if next_mode == language_mode then return end
    local previous_mode = language_mode
    language_mode = next_mode
    active_language = effective_language(language_mode)
    local save_ok, save_error = pcall(function() save_current_style() end)
    if not save_ok then
        language_mode = previous_mode
        active_language = effective_language(language_mode)
        suppress_language_events = true
        local selector = win:Find("LanguageMode")
        if selector then pcall(function() selector.CurrentIndex = language_mode_index(language_mode) end) end
        suppress_language_events = false
        report_error(save_error)
        return
    end
    local hint = win:Find("LanguageRestartHint")
    if hint then
        hint.Text = tr("language.saved_reopen")
        pcall(function() hint:Update() end)
    end
    set_progress(0, tr("language.saved_reopen"))
    append_log(tr("language.saved_reopen"))
end

function THEME.show_main_page()
    local current_index = tonumber(THEME.main_tabs.CurrentIndex) or 0
    THEME.set_element_hidden("PageMain", current_index ~= 0)
    THEME.set_element_hidden("PageAdvanced", current_index ~= 1)
    THEME.set_element_hidden("PageDiagnostics", current_index ~= 2)
    THEME.refresh_layout()
end

THEME.advanced_sections = {
    { header = "AdvancedTimelineHeader", body = "AdvancedTimelineBody", title = tr("advanced.timeline") },
    { header = "AdvancedRenderHeader", body = "AdvancedRenderBody", title = tr("advanced.render") },
    { header = "AdvancedElementsHeader", body = "AdvancedElementsBody", title = tr("advanced.elements") },
    { header = "AdvancedTypographyHeader", body = "AdvancedTypographyBody", title = tr("advanced.typography") },
    { header = "AdvancedCardHeader", body = "AdvancedCardBody", title = tr("advanced.card") },
    { header = "AdvancedActionsHeader", body = "AdvancedActionsBody", title = tr("advanced.actions") },
}

function THEME.toggle_advanced_section(header_id)
    local selected_header = win:Find(header_id)
    local should_open = selected_header and (selected_header.Checked == true or selected_header.Checked == 1)
    for _, section in ipairs(THEME.advanced_sections) do
        local is_open = section.header == header_id and should_open
        local header = win:Find(section.header)
        if header then
            header.Checked = is_open
            header.Text = (is_open and "▼ " or "▶ ") .. section.title
            pcall(function() header:Update() end)
        end
        THEME.set_element_hidden(section.body, not is_open)
    end
    THEME.refresh_layout()
end

function THEME.initialize_navigation()
    THEME.main_tabs.CurrentIndex = 0
    THEME.show_main_page()
    for _, section in ipairs(THEME.advanced_sections) do
        local header = win:Find(section.header)
        if header then
            header.Checked = false
            header.Text = "▶ " .. section.title
        end
        THEME.set_element_hidden(section.body, true)
    end
end

function THEME.load_existing_log()
    local log = win:Find("Log")
    if not log then return end
    local text = read_file(log_path())
    pcall(function() log.PlainText = text end)
    pcall(function() log.Text = text end)
    pcall(function() log:Update() end)
end

win.On[PLUGIN_ID].Close = function(ev)
    pcall(function() save_current_style() end)
    dispatcher:ExitLoop()
end
win.On.MainTabs.CurrentChanged = function(ev) THEME.show_main_page() end
win.On.AdvancedTimelineHeader.Clicked = function(ev) THEME.toggle_advanced_section("AdvancedTimelineHeader") end
win.On.AdvancedRenderHeader.Clicked = function(ev) THEME.toggle_advanced_section("AdvancedRenderHeader") end
win.On.AdvancedElementsHeader.Clicked = function(ev) THEME.toggle_advanced_section("AdvancedElementsHeader") end
win.On.AdvancedTypographyHeader.Clicked = function(ev) THEME.toggle_advanced_section("AdvancedTypographyHeader") end
win.On.AdvancedCardHeader.Clicked = function(ev) THEME.toggle_advanced_section("AdvancedCardHeader") end
win.On.AdvancedActionsHeader.Clicked = function(ev) THEME.toggle_advanced_section("AdvancedActionsHeader") end
win.On.SkinSelector.CurrentChanged = THEME.on_skin_changed
win.On.SkinSelector.CurrentIndexChanged = THEME.on_skin_changed
win.On.LanguageMode.CurrentChanged = THEME.on_language_changed
win.On.LanguageMode.CurrentIndexChanged = THEME.on_language_changed
win.On.UpdateFromTimeline.Clicked = HANDLERS.on_update_from_timeline
win.On.ListClips.Clicked = HANDLERS.on_list_clips
win.On.SaveStyle.Clicked = HANDLERS.on_save_style
win.On.ResetStyle.Clicked = HANDLERS.on_reset_style
win.On.PreviewStyle.Clicked = HANDLERS.on_preview_style
win.On.OpenPreview.Clicked = HANDLERS.on_open_preview
win.On.CopyLog.Clicked = HANDLERS.on_copy_log
win.On.OpenLog.Clicked = HANDLERS.on_open_log
win.On.ClearLog.Clicked = HANDLERS.on_clear_log
win.On.BrowseFallbackLogo.Clicked = HANDLERS.on_browse_fallback_logo
win.On.DefaultFallbackLogo.Clicked = HANDLERS.on_default_fallback_logo
win.On.ApplyPalette.Clicked = THEME.on_apply_palette
win.On.PickPanel.Clicked = function(ev) HANDLERS.pick_color_safely("PanelColor", DEFAULT_DESIGN.panel_color) end
win.On.PickBorder.Clicked = function(ev) HANDLERS.pick_color_safely("BorderColor", DEFAULT_DESIGN.border_color) end
win.On.PickPrimary.Clicked = function(ev) HANDLERS.pick_color_safely("PrimaryTextColor", DEFAULT_DESIGN.primary_text_color) end
win.On.PickSecondary.Clicked = function(ev) HANDLERS.pick_color_safely("SecondaryTextColor", DEFAULT_DESIGN.secondary_text_color) end
win.On.PickAccent.Clicked = function(ev) HANDLERS.pick_color_safely("AccentColor", DEFAULT_DESIGN.accent_color) end
win.On.PickTrack.Clicked = function(ev) HANDLERS.pick_color_safely("TrackColor", DEFAULT_DESIGN.track_color) end

win:Show()
local skin_selector = win:Find("SkinSelector")
local palette_selector = win:Find("PaletteSelector")
suppress_skin_events = true
if skin_selector then
    pcall(function() skin_selector:Clear() end)
    local labels = {}
    for _, skin in ipairs(THEME.skins) do table.insert(labels, skin_label(skin)) end
    pcall(function() skin_selector:AddItems(labels) end)
    pcall(function() skin_selector.CurrentIndex = THEME.skin_index(active_skin) end)
end
if palette_selector then
    pcall(function() palette_selector:Clear() end)
    local labels = {}
    for _, palette_name in ipairs(THEME.palette_order(active_skin)) do table.insert(labels, palette_label(palette_name)) end
    pcall(function() palette_selector:AddItems(labels) end)
    pcall(function() palette_selector.CurrentIndex = THEME.palette_index(saved_profile.palette) end)
end
suppress_skin_events = false
local renderer_mode_combo = win:Find("RendererMode")
if renderer_mode_combo then
    pcall(function() renderer_mode_combo:Clear() end)
    pcall(function() renderer_mode_combo:AddItems({ tr("render.mode_auto"), tr("render.mode_legacy") }) end)
end
apply_renderer_mode_to_ui(saved_renderer_mode)
local language_mode_combo = win:Find("LanguageMode")
suppress_language_events = true
if language_mode_combo then
    pcall(function() language_mode_combo:Clear() end)
    pcall(function() language_mode_combo:AddItems({ tr("language.auto"), tr("language.en"), tr("language.ru") }) end)
    pcall(function() language_mode_combo.CurrentIndex = language_mode_index(language_mode) end)
end
suppress_language_events = false
-- UIManager may clamp Value to its default range before Maximum is applied.
configure_spinbox("VideoTrack", 1, 64, 2)
configure_spinbox("Width", 240, 1920, saved_profile.base_width)
configure_spinbox("Height", 80, 720, saved_profile.base_height)
configure_spinbox("RenderFps", 5, 60, 15)
configure_spinbox("Fps", 1, 120, 30)
configure_spinbox("PlayerMargin", 0, 400, saved_profile.margin)
configure_spinbox("TitleSize", 10, 48, 32)
configure_spinbox("ArtistSize", 8, 36, 18)
configure_spinbox("MetaSize", 8, 30, 16)
configure_spinbox("PanelAlpha", 0, 255, 154)
configure_spinbox("BorderAlpha", 0, 255, 82)
configure_spinbox("CornerRadius", 0, 64, 14)
configure_spinbox("GlassStrength", 0, 100, 46)
THEME.load_existing_log()
THEME.populate_font_combo("TitleFontFamily", saved_design.title_font_family or DEFAULT_DESIGN.title_font_family)
THEME.populate_font_combo("ArtistFontFamily", saved_design.artist_font_family or DEFAULT_DESIGN.artist_font_family)
apply_active_profile_to_ui()
THEME.initialize_navigation()
set_progress(0, tr("status.ready"))
dispatcher:RunLoop()
end

return HANDLERS.run_plugin()
