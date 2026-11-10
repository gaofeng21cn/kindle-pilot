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

local path = DataStorage:getFullDataDir()
local canonical_base = path .. "/KindlePilot"
local legacy_base = path .. "/settings/KindlePilot"

-- Older KindlePilot builds installed the identity below settings/. Keep that
-- path readable so updating the plugin does not rotate the device identity or
-- force another USB pairing. New installs use the KOReader data-root path.
local base = canonical_base
if not exists(canonical_base .. "/config.lua") and not exists(canonical_base .. "/server_hostkey")
        and (exists(legacy_base .. "/config.lua") or exists(legacy_base .. "/server_hostkey")) then
    base = legacy_base
end

local config_path = base .. "/config.lua"
local config = {
    pairing_port = 2223,
    ssh_port = 2224,
    pairing_code_digits = 6,
    pairing_code_ttl_seconds = 120,
    pairing_max_attempts = 3,
    session_duration_seconds = 1800,
}
local config_ok, loaded_config = pcall(dofile, config_path)
if config_ok and type(loaded_config) == "table" then
    for key, value in pairs(loaded_config) do config[key] = value end
end
local hostkey = base .. "/server_hostkey"
local auth_path = base .. "/settings/SSH/authorized_keys"
local pid_path = base .. "/dropbear.pid"
local ffi, socket, ssl
local protocol_eol = "\n"

local KindlePilot = WidgetContainer:extend{
    name = "KindlePilot",
}

function KindlePilot:_ensure_runtime()
    if ffi and socket and ssl then return true end
    local ffi_ok, ffi_value = pcall(require, "ffi")
    local socket_ok, socket_value = pcall(require, "socket")
    if not ffi_ok or not socket_ok then
        self:_show(_("KindlePilot 无法加载 KOReader 网络支持。"), 8)
        return false
    end
    ffi = ffi_value
    socket = socket_value
    local cdef_ok = pcall(function()
        ffi.cdef[[
        typedef void EVP_MD;
        const EVP_MD *EVP_sha1(void);
        unsigned char *HMAC(const EVP_MD *, const void *, int, const unsigned char *, size_t, unsigned char *, unsigned int *);
        ]]
    end)
    local ssl_ok, ssl_value = pcall(ffi.loadlib, "ssl", "60")
    if not cdef_ok or not ssl_ok then
        self:_show(_("KindlePilot 无法加载加密支持。"), 8)
        return false
    end
    ssl = ssl_value
    return true
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

local function random_hex(bytes)
    local file = assert(io.open("/dev/urandom", "rb"))
    local raw = assert(file:read(bytes))
    file:close()
    local output = {}
    for i = 1, #raw do output[#output + 1] = string.format("%02X", string.byte(raw, i)) end
    return table.concat(output)
end

local function random_hex_digits(digits)
    local bytes = math.ceil(digits / 2)
    return string.sub(random_hex(bytes), 1, digits)
end

local function hmac_sha1(key, message)
    local output = ffi.new("unsigned char[20]")
    local length = ffi.new("unsigned int[1]")
    assert(ssl.HMAC(ssl.EVP_sha1(), key, #key, message, #message, output, length) ~= nil)
    local result = {}
    for i = 0, 19 do result[#result + 1] = string.format("%02x", output[i]) end
    return table.concat(result)
end

local function constant_equal(left, right)
    if type(left) ~= "string" or type(right) ~= "string" or #left ~= #right then return false end
    local difference = 0
    for i = 1, #left do
        difference = (difference + math.abs((string.byte(left, i) or 0) - (string.byte(right, i) or 0))) % 256
    end
    return difference == 0
end

local function private_ipv4(value)
    local a, b, c, d = value:match("^(%d+)%.(%d+)%.(%d+)%.(%d+)$")
    a, b, c, d = tonumber(a), tonumber(b), tonumber(c), tonumber(d)
    return a and b and c and d and a <= 255 and b <= 255 and c <= 255 and d <= 255
        and (a == 10 or (a == 192 and b == 168) or (a == 172 and b >= 16 and b <= 31))
end

local function valid_public(value)
    return #value >= 40 and #value <= 180 and value:match("^[A-Za-z0-9+/=]+$") ~= nil
end

function KindlePilot:init()
    self.server = nil
    self.pairing_code = nil
    self.device_nonce = nil
    self.expires_at = nil
    self.attempts = 0
    self.lan = nil
    self.info = nil
    self.ui.menu:registerToMainMenu(self)
end

function KindlePilot:_device_ip()
    return read_line("ip -4 addr show dev wlan0 | awk '/inet / {split($2,a,\"/\"); print a[1]; exit}'")
end

function KindlePilot:_lan()
    return read_line("ip -4 route show dev wlan0 scope link | awk 'NR==1 {print $1; exit}'")
end

function KindlePilot:_pairing_firewall(add)
    local lan = self.lan or self:_lan()
    if not lan then return false end
    self.lan = lan
    local action = add and "-I" or "-D"
    run("iptables " .. action .. " INPUT -p tcp ! -s " .. quote(lan) .. " --dport " .. config.pairing_port .. " -j DROP 2>/dev/null || :")
    run("iptables " .. action .. " INPUT -p tcp -s " .. quote(lan) .. " --dport " .. config.pairing_port .. " -j ACCEPT 2>/dev/null || :")
    return true
end

function KindlePilot:_ssh_firewall(source, add)
    local action = add and "-I" or "-D"
    run("iptables " .. action .. " INPUT -p tcp ! -s " .. quote(source .. "/32") .. " --dport " .. config.ssh_port .. " -j DROP 2>/dev/null || :")
    run("iptables " .. action .. " INPUT -p tcp -s " .. quote(source .. "/32") .. " --dport " .. config.ssh_port .. " -j ACCEPT 2>/dev/null || :")
    run("iptables " .. action .. " OUTPUT -p tcp -d " .. quote(source .. "/32") .. " --sport " .. config.ssh_port .. " -j ACCEPT 2>/dev/null || :")
end

function KindlePilot:_show(text, timeout)
    if self.info then UIManager:close(self.info) end
    self.info = InfoMessage:new{text = text, timeout = timeout or 8}
    UIManager:show(self.info)
end

function KindlePilot:_stop_pairing()
    if self.server then self.server:close(); self.server = nil end
    self:_pairing_firewall(false)
    self.pairing_code = nil
    self.device_nonce = nil
    self.expires_at = nil
end

function KindlePilot:_stop_ssh()
    if exists(pid_path) then
        local pid = read_line("cat " .. quote(pid_path))
        if pid and pid:match("^%d+$") then run("kill " .. pid .. " 2>/dev/null || :") end
    end
    local source = read_line("awk -F= '/^SOURCE=/ {print $2}' " .. quote(base .. "/status"))
    if source and private_ipv4(source) then self:_ssh_firewall(source, false) end
    run("rm -f " .. quote(auth_path) .. " " .. quote(pid_path) .. " " .. quote(base .. "/timer.pid"))
    run("printf 'STATE=stopped\\n' > " .. quote(base .. "/status"))
end

function KindlePilot:_timer()
    local command = "sleep " .. tostring(config.session_duration_seconds) .. "; "
        .. "if [ -r " .. quote(pid_path) .. " ]; then kill $(cat " .. quote(pid_path) .. ") 2>/dev/null || :; fi; "
        .. "rm -f " .. quote(auth_path) .. " " .. quote(pid_path) .. "; "
        .. "printf 'STATE=stopped\\n' > " .. quote(base .. "/status")
    run("nohup sh -c " .. quote(command) .. " >/dev/null 2>&1 </dev/null &")
end

function KindlePilot:_start_ssh(public, source)
    if not private_ipv4(source) or not valid_public(public) or not exists(hostkey) then return false end
    local file = io.open(auth_path, "w")
    if not file then return false end
    file:write("ssh-ed25519 " .. public .. " kindlepilot-pair" .. protocol_eol)
    file:close()
    run("chmod 600 " .. quote(auth_path) .. " " .. quote(hostkey))
    local ip = self:_device_ip()
    if not ip then return false end
    self:_ssh_firewall(source, true)
    local command = "./dropbear -E -s -j -k -r " .. quote(hostkey)
        .. " -p " .. quote(ip .. ":" .. tostring(config.ssh_port))
        .. " -P " .. quote(pid_path)
    if not run(command) then self:_ssh_firewall(source, false); return false end
    run("printf 'STATE=running\\nSOURCE=%s\\nPORT=%s\\n' " .. quote(source) .. " " .. tostring(config.ssh_port) .. " > " .. quote(base .. "/status"))
    self:_timer()
    return true
end

function KindlePilot:_handle_client(client)
    client:settimeout(4)
    local hello = client:receive("*l")
    local op, nonce = hello and hello:match("^(KINDLEPILOT/PAIR1) HELLO ([0-9A-Fa-f]+)$")
    if not op or not nonce or #nonce ~= 32 then client:close(); return end
    client:send("KINDLEPILOT/PAIR1 CHALLENGE " .. self.device_nonce .. protocol_eol)
    local auth = client:receive("*l")
    local aop, received_nonce, public, proof = auth and auth:match("^(KINDLEPILOT/PAIR1) AUTH ([0-9A-Fa-f]+) ([A-Za-z0-9+/=]+) ([0-9a-f]+)$")
    self.attempts = self.attempts + 1
    local valid = aop and received_nonce == nonce and valid_public(public) and #proof == 40
        and constant_equal(hmac_sha1(self.pairing_code, nonce .. "|" .. public .. "|" .. self.device_nonce), proof)
    local source = client:getpeername()
    if valid and source and self:_start_ssh(public, source) then
        client:send("KINDLEPILOT/PAIR1 OK " .. random_hex(16) .. " " .. config.host_public_b64
            .. " " .. tostring(config.ssh_port) .. " " .. tostring(config.session_duration_seconds) .. protocol_eol)
        client:close()
        self:_stop_pairing()
        self:_show(_("KindlePilot 无线维护已就绪，可以返回 Agent。"), 8)
        return
    end
    client:send("KINDLEPILOT/PAIR1 ERROR" .. protocol_eol)
    client:close()
end

function KindlePilot:_poll_pairing()
    if not self.server then return end
    if os.time() >= self.expires_at or self.attempts >= config.pairing_max_attempts then
        self:_stop_pairing()
        self:_show(_("KindlePilot 配对已过期。"), 4)
        return
    end
    local client = self.server:accept()
    if client then
        local ok = pcall(function() self:_handle_client(client) end)
        if not ok then pcall(function() client:close() end) end
    end
    if self.server then UIManager:scheduleIn(0.25, function() self:_poll_pairing() end) end
end

function KindlePilot:start_pairing()
    if self.server then return end
    if not self:_ensure_runtime() then return end
    if not exists(hostkey) or not config.host_public_b64 then
        self:_show(_("KindlePilot 尚未与这台电脑配对，请先通过 USB 安装一次配对身份。"), 8)
        return
    end
    if exists(pid_path) then self:_stop_ssh() end
    local server, err = socket.bind("*", config.pairing_port)
    if not server then self:_show(_("无法启动 KindlePilot 配对：") .. tostring(err), 8); return end
    self.server = server
    self.server:settimeout(0)
    local pairing_digits = tonumber(config.pairing_code_digits) or 6
    pairing_digits = math.max(5, math.min(6, math.floor(pairing_digits)))
    self.pairing_code = random_hex_digits(pairing_digits)
    self.device_nonce = random_hex(16)
    self.expires_at = os.time() + config.pairing_code_ttl_seconds
    self.attempts = 0
    if not self:_pairing_firewall(true) then self:_stop_pairing(); self:_show(_("无法获取 Wi-Fi 地址。"), 6); return end
    self:_show(string.format(_("KindlePilot 配对码：\n\n%s\n\n请把此配对码告诉 Agent。\n%d 秒后过期。"), self.pairing_code, config.pairing_code_ttl_seconds), config.pairing_code_ttl_seconds + 2)
    self:_poll_pairing()
end

function KindlePilot:stop_maintenance()
    self:_stop_pairing()
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
