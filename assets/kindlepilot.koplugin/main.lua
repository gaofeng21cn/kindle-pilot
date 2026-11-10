local DataStorage = require("datastorage")
local InfoMessage = require("ui/widget/infomessage")
local UIManager = require("ui/uimanager")
local WidgetContainer = require("ui/widget/container/widgetcontainer")
local _ = require("gettext")

local function exists(file)
    local handle = io.open(file, "r")
    if handle then handle:close(); return true end
    return false
end

local function quote(value)
    return string.format("%q", value)
end

local function run(command)
    return os.execute(command) == 0
end

local function read_line(command)
    local pipe = io.popen(command, "r")
    if not pipe then return nil end
    local value = pipe:read("*l")
    pipe:close()
    return value
end

local function write_file(file, content)
    local handle = io.open(file, "w")
    if not handle then return false end
    handle:write(content)
    handle:close()
    return true
end

local function random_hex(bytes)
    local file = assert(io.open("/dev/urandom", "rb"))
    local raw = assert(file:read(bytes))
    file:close()
    local output = {}
    for i = 1, #raw do output[#output + 1] = string.format("%02X", string.byte(raw, i)) end
    return table.concat(output)
end

local function random_hex_digits(digits)
    return string.sub(random_hex(math.ceil(digits / 2)), 1, digits)
end

local path = DataStorage:getFullDataDir()
local canonical_base = path .. "/KindlePilot"
local legacy_base = path .. "/settings/KindlePilot"
local base = canonical_base
if not exists(canonical_base .. "/config.lua") and not exists(canonical_base .. "/server_hostkey")
        and (exists(legacy_base .. "/config.lua") or exists(legacy_base .. "/server_hostkey")) then
    base = legacy_base
end

local config = {
    pairing_port = 2223,
    ssh_port = 2224,
    pairing_code_digits = 6,
    pairing_code_ttl_seconds = 120,
    pairing_max_attempts = 3,
    session_duration_seconds = 1800,
}
local config_ok, loaded_config = pcall(dofile, base .. "/config.lua")
if config_ok and type(loaded_config) == "table" then
    for key, value in pairs(loaded_config) do config[key] = value end
end

local hostkey = base .. "/server_hostkey"
local auth_path = base .. "/settings/SSH/authorized_keys"
local pid_path = base .. "/dropbear.pid"
local daemon_pid_path = base .. "/pairing-daemon.pid"
local request_path = base .. "/pairing.request.lua"
local daemon_entry = path .. "/plugins/KindlePilot.koplugin/pairing_daemon_entry.lua"
local daemon_script = path .. "/plugins/KindlePilot.koplugin/pairing_daemon.lua"

local KindlePilot = WidgetContainer:extend{
    name = "KindlePilot",
}

function KindlePilot:init()
    self.info = nil
    self.pairing_code = nil
    self.ui.menu:registerToMainMenu(self)
end

function KindlePilot:_show(text, timeout)
    if self.info then UIManager:close(self.info) end
    self.info = InfoMessage:new{text = text, timeout = timeout or 8}
    UIManager:show(self.info)
end

function KindlePilot:_stop_daemon()
    if exists(daemon_pid_path) then
        local pid = read_line("cat " .. quote(daemon_pid_path))
        if pid and pid:match("^%d+$") then run("kill " .. pid .. " 2>/dev/null || :") end
    end
    run("rm -f " .. quote(daemon_pid_path) .. " " .. quote(request_path))
end

function KindlePilot:_stop_ssh()
    if exists(pid_path) then
        local pid = read_line("cat " .. quote(pid_path))
        if pid and pid:match("^%d+$") then run("kill " .. pid .. " 2>/dev/null || :") end
    end
    local source = read_line("awk -F= '/^SOURCE=/ {print $2}' " .. quote(base .. "/status"))
    if source then
        run("iptables -D INPUT -p tcp -s " .. quote(source .. "/32") .. " --dport " .. config.ssh_port .. " -j ACCEPT 2>/dev/null || :")
        run("iptables -D INPUT -p tcp ! -s " .. quote(source .. "/32") .. " --dport " .. config.ssh_port .. " -j DROP 2>/dev/null || :")
        run("iptables -D OUTPUT -p tcp -d " .. quote(source .. "/32") .. " --sport " .. config.ssh_port .. " -j ACCEPT 2>/dev/null || :")
    end
    run("rm -f " .. quote(auth_path) .. " " .. quote(pid_path) .. " " .. quote(base .. "/timer.pid"))
    write_file(base .. "/status", "STATE=stopped\n")
end

function KindlePilot:start_pairing()
    if not exists(hostkey) or not config.host_public_b64 then
        self:_show(_("KindlePilot 尚未与这台电脑配对，请先通过 USB 安装一次配对身份。"), 8)
        return
    end
    if exists(daemon_pid_path) or exists(pid_path) then
        self:_stop_daemon()
        self:_stop_ssh()
    end
    local digits = tonumber(config.pairing_code_digits) or 6
    digits = math.max(5, math.min(6, math.floor(digits)))
    local code = random_hex_digits(digits)
    local expires_at = os.time() + (tonumber(config.pairing_code_ttl_seconds) or 120)
    local request = string.format(
        "return { code = %q, device_nonce = %q, expires_at = %d }\n",
        code, random_hex(16), expires_at)
    if not write_file(request_path, request) then
        self:_show(_("无法写入 KindlePilot 配对请求。"), 8)
        return
    end
    local command = "cd " .. quote(path) .. " && nohup ./luajit " .. quote(daemon_entry)
        .. " " .. quote(daemon_script) .. " " .. quote(base) .. " " .. quote(path)
        .. " > " .. quote(base .. "/daemon.log") .. " 2>&1 </dev/null & echo $! > " .. quote(daemon_pid_path)
    if not run(command) then
        self:_stop_daemon()
        self:_show(_("无法启动 KindlePilot 无线维护服务。"), 8)
        return
    end
    self.pairing_code = code
    self:_show(string.format(
        _("KindlePilot 配对码：\n\n%s\n\n请把此配对码告诉 Agent。\n%d 秒后过期。\n\n服务会在 KOReader 退出后继续运行。"),
        code, tonumber(config.pairing_code_ttl_seconds) or 120), (tonumber(config.pairing_code_ttl_seconds) or 120) + 4)
end

function KindlePilot:stop_maintenance()
    self:_stop_daemon()
    self:_stop_ssh()
    self:_show(_("KindlePilot 无线维护已停止。"), 4)
end

function KindlePilot:addToMainMenu(menu_items)
    menu_items.kindlepilot_wireless = {
        text = _("KindlePilot 无线维护"),
        sub_item_table = {
            {
                text = _("配对此电脑并开始维护"),
                callback = function() self:start_pairing() end,
            },
            {
                text = _("停止无线维护"),
                callback = function() self:stop_maintenance() end,
            },
        },
    }
end

return KindlePilot
