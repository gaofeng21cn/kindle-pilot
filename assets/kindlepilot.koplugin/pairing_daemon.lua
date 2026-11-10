local ffi = require("ffi")
local socket = require("socket")

local base = arg[2]
local root = arg[3]
local protocol_eol = "\n"

local function quote(value)
    return string.format("%q", value)
end

local function run(command)
    return os.execute(command) == 0
end

local function exists(file)
    local handle = io.open(file, "r")
    if handle then handle:close(); return true end
    return false
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

local function receive_line(client)
    local value, err, partial = client:receive("*l")
    return value or partial, err
end

local function random_hex(bytes)
    local file = assert(io.open("/dev/urandom", "rb"))
    local raw = assert(file:read(bytes))
    file:close()
    local output = {}
    for i = 1, #raw do output[#output + 1] = string.format("%02X", string.byte(raw, i)) end
    return table.concat(output)
end

local function hmac_sha1(key, message)
    pcall(function()
        ffi.cdef[[
        typedef void EVP_MD;
        const EVP_MD *EVP_sha1(void);
        unsigned char *HMAC(const EVP_MD *, const void *, int, const unsigned char *, size_t, unsigned char *, unsigned int *);
        ]]
    end)
    local ssl_ok, ssl = pcall(ffi.loadlib, "ssl", "60")
    if not ssl_ok then return nil end
    local output = ffi.new("unsigned char[20]")
    local length = ffi.new("unsigned int[1]")
    if ssl.HMAC(ssl.EVP_sha1(), key, #key, message, #message, output, length) == nil then return nil end
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

local function valid_public(value)
    return type(value) == "string" and #value >= 40 and #value <= 180 and value:match("^[A-Za-z0-9+/=]+$") ~= nil
end

local function private_ipv4(value)
    local a, b, c, d = value and value:match("^(%d+)%.(%d+)%.(%d+)%.(%d+)$")
    a, b, c, d = tonumber(a), tonumber(b), tonumber(c), tonumber(d)
    return a and b and c and d and a <= 255 and b <= 255 and c <= 255 and d <= 255
        and (a == 10 or (a == 192 and b == 168) or (a == 172 and b >= 16 and b <= 31))
end

local config = dofile(base .. "/config.lua")
local request = dofile(base .. "/pairing.request.lua")
local hostkey = base .. "/server_hostkey"
local auth_path = base .. "/settings/SSH/authorized_keys"
local pid_path = base .. "/dropbear.pid"
local status_path = base .. "/status"
local lan = read_line("ip -4 route show dev wlan0 scope link | awk 'NR==1 {print $1; exit}'")
local device_ip = read_line("ip -4 addr show dev wlan0 | awk '/inet / {split($2,a,\"/\"); print a[1]; exit}'")
if not lan or not device_ip or not exists(hostkey) then os.exit(4) end

local function cleanup_pairing(server)
    if server then server:close() end
    run("iptables -D INPUT -p tcp -s " .. quote(lan) .. " --dport " .. config.pairing_port .. " -j ACCEPT 2>/dev/null || :")
    run("iptables -D INPUT -p tcp ! -s " .. quote(lan) .. " --dport " .. config.pairing_port .. " -j DROP 2>/dev/null || :")
    run("rm -f " .. quote(base .. "/pairing.request.lua") .. " " .. quote(base .. "/pairing-daemon.pid"))
end

local function ssh_firewall(source, add)
    local action = add and "-I" or "-D"
    run("iptables " .. action .. " INPUT -p tcp ! -s " .. quote(source .. "/32") .. " --dport " .. config.ssh_port .. " -j DROP 2>/dev/null || :")
    run("iptables " .. action .. " INPUT -p tcp -s " .. quote(source .. "/32") .. " --dport " .. config.ssh_port .. " -j ACCEPT 2>/dev/null || :")
    run("iptables " .. action .. " OUTPUT -p tcp -d " .. quote(source .. "/32") .. " --sport " .. config.ssh_port .. " -j ACCEPT 2>/dev/null || :")
end

local function start_ssh(public, source)
    if not private_ipv4(source) or not valid_public(public) then return false end
    run("mkdir -p " .. quote(base .. "/settings/SSH"))
    local file = io.open(auth_path, "w")
    if not file then return false end
    file:write("ssh-ed25519 " .. public .. " kindlepilot-pair" .. protocol_eol)
    file:close()
    run("chmod 600 " .. quote(auth_path) .. " " .. quote(hostkey))
    ssh_firewall(source, true)
    local command = "cd " .. quote(root) .. " && ./dropbear -E -s -j -k -r " .. quote(hostkey)
        .. " -p " .. quote(device_ip .. ":" .. tostring(config.ssh_port)) .. " -P " .. quote(pid_path)
    if not run(command) then ssh_firewall(source, false); return false end
    write_file(status_path, "STATE=running\nSOURCE=" .. source .. "\nPORT=" .. tostring(config.ssh_port) .. "\n")
    local timer = "sleep " .. tostring(config.session_duration_seconds) .. "; if [ -r " .. quote(pid_path) .. " ]; then kill $(cat " .. quote(pid_path) .. ") 2>/dev/null || :; fi; rm -f " .. quote(auth_path) .. " " .. quote(pid_path) .. "; printf 'STATE=stopped\\n' > " .. quote(status_path)
    run("nohup sh -c " .. quote(timer) .. " >/dev/null 2>&1 </dev/null &")
    return true
end

local function handle_client(client)
    client:settimeout(4)
    local hello = receive_line(client)
    local op, nonce = hello and hello:match("^%s*(KINDLEPILOT/PAIR1)%s+HELLO%s+([0-9A-Fa-f]+)%s*$")
    if not op or not nonce or #nonce ~= 32 then client:close(); return false end
    client:send("KINDLEPILOT/PAIR1 CHALLENGE " .. request.device_nonce .. protocol_eol)
    local auth = receive_line(client)
    local aop, received_nonce, public, proof = auth and auth:match("^%s*(KINDLEPILOT/PAIR1)%s+AUTH%s+([0-9A-Fa-f]+)%s+([A-Za-z0-9+/=]+)%s+([0-9a-f]+)%s*$")
    local expected = hmac_sha1(request.code, nonce .. "|" .. tostring(public) .. "|" .. request.device_nonce)
    local valid = aop and received_nonce == nonce and valid_public(public) and #proof == 40 and expected and constant_equal(expected, proof)
    local source = client:getpeername()
    if valid and source and start_ssh(public, source) then
        client:send("KINDLEPILOT/PAIR1 OK " .. random_hex(16) .. " " .. config.host_public_b64 .. " " .. tostring(config.ssh_port) .. " " .. tostring(config.session_duration_seconds) .. protocol_eol)
        client:close()
        return true
    end
    client:send("KINDLEPILOT/PAIR1 ERROR" .. protocol_eol)
    client:close()
    return false
end

run("iptables -I INPUT -p tcp ! -s " .. quote(lan) .. " --dport " .. config.pairing_port .. " -j DROP 2>/dev/null || :")
run("iptables -I INPUT -p tcp -s " .. quote(lan) .. " --dport " .. config.pairing_port .. " -j ACCEPT 2>/dev/null || :")
local server = socket.bind("*", config.pairing_port)
if not server then cleanup_pairing(nil); os.exit(4) end
server:settimeout(0.25)
local attempts = 0
local expiry = tonumber(request.expires_at) or (os.time() + (config.pairing_code_ttl_seconds or 120))
local paired = false
while os.time() < expiry and attempts < (config.pairing_max_attempts or 3) do
    local client = server:accept()
    if client then
        local ok, result = pcall(handle_client, client)
        attempts = attempts + 1
        if ok and result then paired = true; break end
        if not ok then pcall(function() client:close() end) end
    end
    socket.sleep(0.25)
end
cleanup_pairing(server)
if not paired then write_file(status_path, "STATE=stopped\n") end
