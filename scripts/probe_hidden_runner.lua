local function fail(message)
    error("TVIZ_RUNNER_PROBE_ERROR " .. tostring(message), 0)
end

local function json_escape(value)
    return tostring(value or "")
        :gsub("\\", "\\\\")
        :gsub('"', '\\"')
        :gsub("\r", "\\r")
        :gsub("\n", "\\n")
end

local function file_exists(path)
    local handle = io.open(path, "rb")
    if handle then handle:close() return true end
    return false
end

local function write_file(path, content)
    local handle = assert(io.open(path, "wb"))
    handle:write(content)
    handle:close()
end

local function read_file(path)
    local handle = assert(io.open(path, "rb"))
    local content = handle:read("*a")
    handle:close()
    return content
end

local function wait(seconds)
    if bmd and type(bmd.wait) == "function" then
        bmd.wait(seconds)
        return
    end
    local target = os.clock() + seconds
    while os.clock() < target do end
end

local function dirname(path)
    return tostring(path or ""):match("^(.*)[\\/][^\\/]*$") or "."
end

local function file_uri(path)
    local normalized = tostring(path or ""):gsub("\\", "/")
    normalized = normalized:gsub("([^A-Za-z0-9%-%._~/:])", function(character)
        return string.format("%%%02X", string.byte(character))
    end)
    return "file:///" .. normalized
end

local function launch_native(executable)
    local ffi_ok, ffi = pcall(require, "ffi")
    if not ffi_ok then return false, tostring(ffi) end
    local type_ok = pcall(function() return ffi.typeof("tviz_probe_STARTUPINFOW") end)
    if not type_ok then
        ffi.cdef[[
            typedef struct tviz_probe_STARTUPINFOW {
                uint32_t cb; wchar_t *lpReserved; wchar_t *lpDesktop; wchar_t *lpTitle;
                uint32_t dwX; uint32_t dwY; uint32_t dwXSize; uint32_t dwYSize;
                uint32_t dwXCountChars; uint32_t dwYCountChars; uint32_t dwFillAttribute;
                uint32_t dwFlags; uint16_t wShowWindow; uint16_t cbReserved2;
                uint8_t *lpReserved2; void *hStdInput; void *hStdOutput; void *hStdError;
            } tviz_probe_STARTUPINFOW;
            typedef struct tviz_probe_PROCESS_INFORMATION {
                void *hProcess; void *hThread; uint32_t dwProcessId; uint32_t dwThreadId;
            } tviz_probe_PROCESS_INFORMATION;
            int __stdcall MultiByteToWideChar(unsigned int, uint32_t, const char *, int, wchar_t *, int);
            int __stdcall CreateProcessW(const wchar_t *, wchar_t *, void *, void *, int, uint32_t, void *, const wchar_t *, tviz_probe_STARTUPINFOW *, tviz_probe_PROCESS_INFORMATION *);
            int __stdcall CloseHandle(void *);
            uint32_t __stdcall GetLastError(void);
        ]]
    end
    local kernel32 = ffi.load("kernel32")
    local function utf16(value)
        local count = kernel32.MultiByteToWideChar(65001, 0, value, -1, nil, 0)
        if count == 0 then return nil end
        local result = ffi.new("wchar_t[?]", count)
        if kernel32.MultiByteToWideChar(65001, 0, value, -1, result, count) == 0 then return nil end
        return result
    end
    local application = utf16(executable)
    local working_directory = utf16(dirname(executable))
    if not application or not working_directory then return false, "UTF-16 conversion failed" end
    local startup = ffi.new("tviz_probe_STARTUPINFOW[1]")
    startup[0].cb = ffi.sizeof(startup[0])
    startup[0].dwFlags = 1
    startup[0].wShowWindow = 0
    local process = ffi.new("tviz_probe_PROCESS_INFORMATION[1]")
    local created = kernel32.CreateProcessW(application, nil, nil, nil, 0, 0x08000000, nil, working_directory, startup, process)
    if created == 0 then return false, "CreateProcessW error " .. tostring(tonumber(kernel32.GetLastError())) end
    kernel32.CloseHandle(process[0].hThread)
    kernel32.CloseHandle(process[0].hProcess)
    return true
end

local runner = os.getenv("TVIZ_PROBE_RUNNER")
local task_path = os.getenv("TVIZ_PROBE_TASK")
local done_path = os.getenv("TVIZ_PROBE_DONE")
local stdout_path = os.getenv("TVIZ_PROBE_STDOUT")
local launcher_path = task_path and (task_path .. ".vbs") or nil
if not runner or runner == "" then fail("TVIZ_PROBE_RUNNER is required") end
if not task_path or task_path == "" then fail("TVIZ_PROBE_TASK is required") end
if not done_path or done_path == "" then fail("TVIZ_PROBE_DONE is required") end
if not stdout_path or stdout_path == "" then fail("TVIZ_PROBE_STDOUT is required") end

os.remove(task_path)
os.remove(done_path)
os.remove(stdout_path)
write_file(task_path, table.concat({
    "{",
    '  "mode": "run",',
    '  "cwd": "' .. json_escape(os.getenv("WINDIR") or "C:\\Windows") .. '",',
    '  "command": ["' .. json_escape((os.getenv("WINDIR") or "C:\\Windows") .. "\\System32\\where.exe") .. '", "cmd.exe"],',
    '  "stdout_path": "' .. json_escape(stdout_path) .. '",',
    '  "done_path": "' .. json_escape(done_path) .. '"',
    "}",
}, "\r\n"))
write_file(launcher_path, table.concat({
    'Set shell = CreateObject("WScript.Shell")',
    'shell.Run """' .. runner:gsub('"', '""') .. '""", 0, False',
}, "\r\n"))

local launch_method = "ffi"
local launch_ok, launch_error = launch_native(runner)
if not launch_ok then
    launch_method = "openurl"
    local url_ok, url_result = pcall(function() return bmd.openurl(file_uri(launcher_path)) end)
    if not url_ok or url_result == false then
        fail("hidden launch failed: ffi=" .. tostring(launch_error) .. " openurl=" .. tostring(url_result))
    end
end

for _ = 1, 200 do
    if file_exists(done_path) then break end
    wait(0.05)
end
if not file_exists(done_path) then fail("runner did not publish done file") end
local done = read_file(done_path)
if not done:match('"returncode"%s*:%s*0') then fail("runner returned failure: " .. done) end
if file_exists(task_path) then fail("runner did not claim task") end

os.remove(done_path)
os.remove(stdout_path)
os.remove(launcher_path)
print("TVIZ_RUNNER_PROBE_OK method=" .. launch_method .. " claimed=1 returncode=0")
