from __future__ import annotations

import ctypes
import os
import re
import unittest
from pathlib import Path

from luaparser import ast


ROOT = Path(__file__).resolve().parents[1]
LUA_PATH = ROOT / "resolve_scripts" / "Track Visualizer.lua"


class LuaPortabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = LUA_PATH.read_text(encoding="utf-8")

    def test_lua_parses(self) -> None:
        ast.parse(self.source)

    def test_resolve_luajit_compiles_when_runtime_is_available(self) -> None:
        # Hosted Linux CI has no pinned Resolve runtime; local certification supplies this DLL.
        configured = os.environ.get("DAVINCI_RESOLVE_LUA_DLL")
        runtime = Path(configured) if configured else Path(
            r"C:\Program Files\Blackmagic Design\DaVinci Resolve\lua5.1.dll"
        )
        if not runtime.is_file():
            self.skipTest(
                "Resolve LuaJIT is unavailable; set DAVINCI_RESOLVE_LUA_DLL to enable this check"
            )

        lua = ctypes.CDLL(str(runtime))
        lua.luaL_newstate.restype = ctypes.c_void_p
        lua.luaL_loadfile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lua.luaL_loadfile.restype = ctypes.c_int
        lua.lua_tolstring.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        lua.lua_tolstring.restype = ctypes.c_void_p
        lua.lua_close.argtypes = [ctypes.c_void_p]

        state = lua.luaL_newstate()
        self.assertTrue(state)
        try:
            result = lua.luaL_loadfile(state, os.fsencode(LUA_PATH))
            if result != 0:
                length = ctypes.c_size_t()
                pointer = lua.lua_tolstring(state, -1, ctypes.byref(length))
                message = ctypes.string_at(pointer, length.value).decode("utf-8", "replace")
                self.fail(f"Resolve LuaJIT rejected {LUA_PATH}: {message}")
        finally:
            lua.lua_close(state)

    def test_platform_descriptor_and_probe_cover_supported_hosts(self) -> None:
        for fragment in (
            "local PLATFORM = platform_descriptor",
            'name = "windows"',
            'name = "macos"',
            'name = "linux"',
            'separator = windows and "\\\\" or "/"',
            "case_sensitive_paths = not windows",
            "platform_probe_config.platform_only == true",
            "same_case_path = path_identity",
            "posix = is_absolute_path",
            "drive = is_absolute_path",
            "unc = is_absolute_path",
            "file_uri = is_absolute_path",
            'remainder:match("^%a:/")',
            'or from_file_uri and value:match("^\\\\") ~= nil',
            'quoted_posix = quote_posix("runner\'s path")',
        ):
            self.assertIn(fragment, self.source)

    def test_platform_roots_and_native_executable_names_match_python_runtime(self) -> None:
        for fragment in (
            '"DAVINCI_TRACK_VISUALIZER_HOME"',
            '"LOCALAPPDATA"',
            '"AppData"',
            '"Local"',
            '"Library"',
            '"Application Support"',
            '"XDG_DATA_HOME"',
            '".local"',
            '"share"',
            'native_executable_name("TrackVisualizerEngine")',
            'native_executable_name("TrackVisualizerRunner")',
            'native_executable_name("ffmpeg")',
            'native_executable_name("ffprobe")',
        ):
            self.assertIn(fragment, self.source)
        self.assertNotIn('"TrackVisualizerEngine.exe"', self.source)
        self.assertNotIn('"TrackVisualizerRunner.exe"', self.source)
        self.assertNotIn('"ffmpeg.exe"', self.source)
        self.assertNotIn('"ffprobe.exe"', self.source)

    def test_output_paths_and_path_identity_are_platform_aware(self) -> None:
        self.assertNotIn("outputs\\\\resolve", self.source)
        self.assertIn('path_join(path_join(install_root(), "outputs"), "resolve")', self.source)
        self.assertIn("if PLATFORM.windows then return value:gsub", self.source)
        self.assertIn("local wanted = path_identity(carrier_path)", self.source)
        self.assertIn("path_identity(file_path) == wanted", self.source)
        self.assertIn("local target_base = path_identity(basename(clip_name))", self.source)
        self.assertIn("local file_base = path_identity(raw_base)", self.source)

    def test_posix_runner_is_detached_and_windows_uses_only_native_launch(self) -> None:
        self.assertIn('local command = "nohup " .. quote_posix(executable)', self.source)
        self.assertIn('" </dev/null >/dev/null 2>&1 &"', self.source)
        self.assertIn("if PLATFORM.windows then", self.source)
        self.assertIn("launched, launch_error = launch_runner_native(runner)", self.source)
        self.assertIn("launched, launch_error = launch_runner_posix(runner)", self.source)
        self.assertIn("claimed = asynchronous or wait_for_runner_claim(task_path)", self.source)
        self.assertIn("if os.time() > task.claim_deadline then", self.source)
        self.assertIn('tr("error.windows_wide_launch"', self.source)
        self.assertNotIn("wscript", self.source.lower())
        self.assertNotIn('CreateObject("WScript.Shell")', self.source)

    def test_windows_ffi_declarations_and_utf_conversions_are_centralized(self) -> None:
        for declaration in (
            "GetEnvironmentVariableW",
            "CreateFileW",
            "ReadFile",
            "WriteFile",
            "FlushFileBuffers",
            "DeleteFileW",
            "MoveFileExW",
            "ReplaceFileW",
            "CreateDirectoryW",
            "CreateProcessW",
            "MultiByteToWideChar",
            "WideCharToMultiByte",
        ):
            self.assertIn(declaration, self.source)
        self.assertIn("local function win32_api()", self.source)
        self.assertIn("local function win32_utf16(value)", self.source)
        self.assertIn("local function win32_utf8(value, character_count)", self.source)
        self.assertEqual(self.source.count("typedef struct tviz_STARTUPINFOW"), 1)
        self.assertEqual(self.source.count("int __stdcall MultiByteToWideChar("), 1)
        self.assertEqual(self.source.count("int __stdcall CreateProcessW("), 1)

    def test_profile_environment_and_filesystem_use_wide_windows_apis(self) -> None:
        self.assertIn("if PLATFORM.windows then return win32_environment_value(name) end", self.source)
        self.assertIn("GetEnvironmentVariableW(wide_name, nil, 0)", self.source)
        self.assertIn("CreateFileW(wide_path, 0x80000000", self.source)
        self.assertIn("ReadFile(handle, buffer, buffer_size", self.source)
        self.assertIn("WriteFile(handle, source + offset", self.source)
        self.assertIn("FlushFileBuffers(handle)", self.source)
        self.assertIn("DeleteFileW(wide_path)", self.source)
        self.assertIn("ReplaceFileW(wide_destination, wide_source, wide_backup", self.source)
        self.assertIn("local flags = replace_existing and 0x00000009 or 0x00000008", self.source)
        self.assertIn("CreateDirectoryW(wide_path, nil)", self.source)
        self.assertIn('os.execute("mkdir -p -- " .. quote_posix(path))', self.source)

        settings = self.source[
            self.source.index("local function load_settings()") : self.source.index(
                "local function save_settings"
            )
        ]
        self.assertIn("write_file_raw(temporary_path, data, false, true)", settings)
        self.assertIn("local restored = move_file(backup_path, path)", settings)
        self.assertIn("had_original and PLATFORM.windows and backup_path or nil", settings)
        self.assertIn('details = details .. "; rollback failed: "', settings)
        self.assertNotRegex(settings, r"\b(?:io\.open|os\.remove|os\.rename)\(")

        # Narrow Lua I/O remains only inside the non-Windows branches of the wrappers.
        self.assertEqual(self.source.count("io.open("), 3)
        self.assertEqual(self.source.count("os.remove("), 1)
        self.assertEqual(self.source.count("os.rename("), 1)

    def test_windows_color_picker_runs_powershell_through_runner_safely(self) -> None:
        picker = self.source[
            self.source.index("local function windows_powershell_path") : self.source.index(
                "local function frame(value)"
            )
        ]
        self.assertIn('ipairs({ "SystemRoot", "WINDIR" })', picker)
        self.assertIn("is_absolute_path(system_root)", picker)
        self.assertIn('path_join(path_join(system_root, "System32"), "WindowsPowerShell")', picker)
        self.assertIn('path_join(path_join(directory, "v1.0"), "powershell.exe")', picker)
        self.assertIn("if file_exists(candidate) then return candidate end", picker)
        self.assertIn('if powershell_path == "" then', picker)
        self.assertIn(
            """command = {
                powershell_path, "-NoLogo", "-NoProfile", "-NonInteractive",
                "-Sta", "-WindowStyle", "Hidden", "-File", script_path,
                "-ResultPath", result_path,
            },""",
            picker,
        )
        self.assertIn("run_runner_config({", picker)
        self.assertIn('"-File", script_path', picker)
        self.assertIn('"-ResultPath", result_path', picker)
        self.assertIn("param([string]$ResultPath)", picker)
        self.assertIn("Set-Content -LiteralPath $ResultPath", picker)
        self.assertIn('"picked_color_" .. picker_stem .. ".txt"', picker)
        self.assertIn("remove_file(result_path)", picker)
        self.assertIn("remove_file(script_path)", picker)
        self.assertIn("if not picker_ok then error(selected) end", picker)
        self.assertNotIn("os.execute", picker)
        self.assertNotIn('"powershell.exe", "-NoLogo"', picker)
        self.assertNotIn('"-Command"', picker)
        self.assertNotIn('"-EncodedCommand"', picker)

    def test_windows_color_picker_uses_the_native_dialog_first(self) -> None:
        dialog = self.source[
            self.source.index("local function win32_color_api()") : self.source.index(
                "-- Mirror of davinci_track_visualizer.skins.catalog()"
            )
        ]
        self.assertIn("int __stdcall ChooseColorW(tviz_CHOOSECOLORW_V1 *chooseColor);", dialog)
        self.assertIn('ffi.load, "comdlg32"', dialog)
        # fuscript.exe starts minimized; the hook restores the dialog and brings it forward.
        self.assertIn("user32.ShowWindow(dialog, 9)", dialog)
        self.assertIn("user32.SetForegroundWindow(dialog)", dialog)
        self.assertIn("0x00000010", dialog)  # CC_ENABLEHOOK
        self.assertIn('require("jit").off(win32_choose_color)', dialog)
        picker = self.source[
            self.source.index("local function apply_picked_color") : self.source.index(
                "local function frame(value)"
            )
        ]
        self.assertIn("local chosen, dialog_error = win32_choose_color(r, g, b, swatches)", picker)
        self.assertIn("if chosen == false then return end", picker)
        # Saving before Editor.changed() made the change look like a no-op: no swatch or preview update.
        apply = picker[: picker.index("local function pick_windows_color")]
        self.assertNotIn("save_current_style", apply)

    def test_windows_color_picker_does_not_override_execution_policy(self) -> None:
        self.assertNotIn("ExecutionPolicy", self.source)
        self.assertNotRegex(self.source, r'(?i)["\']bypass["\']')

    def test_runner_uses_unique_files_and_strict_completion_json(self) -> None:
        runner = self.source[
            self.source.index("local function queue_runner_task") : self.source.index(
                "local function run_runner_config"
            )
        ]
        self.assertIn('stdout_template .. "." .. task_stem', runner)
        self.assertIn('done_template .. "." .. task_stem', runner)
        self.assertIn("queued_config.stdout_path = stdout_path", runner)
        self.assertIn("queued_config.done_path = done_path", runner)
        self.assertIn("pcall(function() return json_decode(done_text) end)", runner)
        self.assertIn('type(code) ~= "number"', runner)
        self.assertNotIn("json_extract_number", runner)

    def test_non_windows_color_picker_is_manual_and_localized(self) -> None:
        self.assertIn('["notice.color_manual"]', self.source)
        picker = self.source[
            self.source.index("function HANDLERS.pick_color_safely") : self.source.index(
                "function HANDLERS.on_create"
            )
        ]
        self.assertIn("if not PLATFORM.windows then", picker)
        self.assertIn('tr("notice.color_manual")', picker)
        self.assertNotIn("powershell.exe", picker)

    def test_windows_color_picker_failure_falls_back_to_manual_input(self) -> None:
        picker = self.source[
            self.source.index("function HANDLERS.pick_color_safely") : self.source.index(
                "function HANDLERS.on_create"
            )
        ]
        self.assertIn("local ok, err = pcall", picker)
        self.assertRegex(
            picker,
            r'if not ok then\s+report_error\(err\)\s+local notice = tr\("notice\.color_manual"\)',
        )
        self.assertIn("set_progress(0, notice)", picker)

    def test_no_raw_russian_text_exists_outside_ru_catalog(self) -> None:
        start = self.source.index("    ru = {")
        end = self.source.index("\n    },\n}", start) + len("\n    },")
        outside_catalog = self.source[:start] + self.source[end:]
        matches = []
        for line_number, line in enumerate(outside_catalog.splitlines(), 1):
            if re.search(r"[А-Яа-яЁё]", line):
                matches.append(f"{line_number}: {line.strip()}")
        self.assertEqual(matches, [], "\n".join(matches))

    def test_generic_missing_binary_labels_do_not_claim_exe_suffix(self) -> None:
        for key in ("error.runner_missing", "error.engine_missing"):
            entries = re.findall(rf'\["{re.escape(key)}"\]\s*=\s*"([^"]*)"', self.source)
            self.assertEqual(len(entries), 2)
            self.assertTrue(all(".exe" not in entry for entry in entries))

    def test_playback_rate_mismatch_is_reported_without_changing_the_project(self) -> None:
        self.assertIn('read_frame_rate(project, timeline, "timelinePlaybackFrameRate")', self.source)
        self.assertIn('ID = "RateWarning"', self.source)
        self.assertIn("App.show_rate_warning(project, timeline)", self.source)
        # The plugin only warns; project and timeline settings stay the user's.
        self.assertNotRegex(self.source, r"(project|timeline):SetSetting\(")
        for entry in re.findall(r'\["warning\.playback_rate"\]\s*=\s*"([^"]*)"', self.source):
            self.assertIn("{playback}", entry)
            self.assertIn("{timeline}", entry)


if __name__ == "__main__":
    unittest.main()
