local ffi = require("ffi")
local socket = require("socket")
local bit = require("bit")

local base = arg[2]
local root = arg[3]
local protocol_eol = "\n"
local log_path = base .. "/daemon.log"

local function quote(value)
    return string.format("%q", value)
end

local function run(command)
    local result, kind, code = os.execute(command)
    return result == 0 or (result == true and kind == "exit" and code == 0)
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

local function append_log(message)
    local handle = io.open(log_path, "a")
    if handle then
        handle:write(os.date("!%Y-%m-%dT%H:%M:%SZ"), " ", message, "\n")
        handle:close()
    end
end

local function receive_line(client)
    local chunks = {}
    local started = socket.gettime and socket.gettime() or os.time()
    while #chunks < 512 do
        local value, err = client:receive(1)
        if value then
            if value == "\n" then return table.concat(chunks), nil end
            chunks[#chunks + 1] = value
        elseif err == "timeout" then
            local now = socket.gettime and socket.gettime() or os.time()
            if now - started >= 4 then return table.concat(chunks), err end
            socket.sleep(0.01)
        else
            return table.concat(chunks), err
        end
    end
    return table.concat(chunks), "line-too-long"
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
    local ssl_ok, ssl = pcall(ffi.loadlib, "crypto", "57")
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
        difference = bit.bor(difference, bit.bxor(string.byte(left, i), string.byte(right, i)))
    end
    return difference == 0
end

local function valid_public(value)
    return type(value) == "string" and #value >= 40 and #value <= 180 and value:match("^[A-Za-z0-9+/=]+$") ~= nil
end

local function private_ipv4(value)
    if type(value) ~= "string" then return false end
    local a, b, c, d = value:match("^(%d+)%.(%d+)%.(%d+)%.(%d+)$")
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
if not lan or not device_ip or not exists(hostkey) then
    write_file(status_path, "STATE=error\nERROR=WIFI_OR_IDENTITY_MISSING\n")
    os.exit(4)
end
append_log("START ip=" .. tostring(device_ip) .. " lan=" .. tostring(lan))

local function cleanup_pairing(server)
    if server then server:close() end
    run("iptables -D INPUT -p tcp -s " .. quote(lan) .. " --dport " .. config.pairing_port .. " -j ACCEPT 2>/dev/null || :")
    run("iptables -D INPUT -p tcp ! -s " .. quote(lan) .. " --dport " .. config.pairing_port .. " -j DROP 2>/dev/null || :")
    run("iptables -D OUTPUT -p tcp -d " .. quote(lan) .. " --sport " .. config.pairing_port .. " -j ACCEPT 2>/dev/null || :")
    run("rm -f " .. quote(base .. "/pairing.request.lua") .. " " .. quote(base .. "/pairing-daemon.pid") .. " " .. quote(base .. "/pairing.network"))
end

local function ssh_firewall(source, add)
    local action = add and "-I" or "-D"
    run("iptables " .. action .. " INPUT -p tcp ! -s " .. quote(source .. "/32") .. " --dport " .. config.ssh_port .. " -j DROP 2>/dev/null || :")
    run("iptables " .. action .. " INPUT -p tcp -s " .. quote(source .. "/32") .. " --dport " .. config.ssh_port .. " -j ACCEPT 2>/dev/null || :")
    run("iptables " .. action .. " OUTPUT -p tcp -d " .. quote(source .. "/32") .. " --sport " .. config.ssh_port .. " -j ACCEPT 2>/dev/null || :")
end

local session_id = random_hex(16)
local function start_ssh(public, source)
    if not private_ipv4(source) or not valid_public(public) then return false end
    run("mkdir -p " .. quote(base .. "/settings/SSH"))
    local file = io.open(auth_path, "w")
    if not file then return false end
    file:write("ssh-ed25519 " .. public .. " kindlepilot-pair" .. protocol_eol)
    file:close()
    run("chmod 700 " .. quote(base) .. " " .. quote(base .. "/settings") .. " " .. quote(base .. "/settings/SSH"))
    run("chmod 600 " .. quote(auth_path) .. " " .. quote(hostkey))
    local dropbear = config.dropbear_path or (root .. "/dropbear")
    if not run("chmod 700 " .. quote(dropbear)) then os.remove(auth_path); return false end
    ssh_firewall(source, true)
    -- KOReader's patched Dropbear reads settings/SSH/authorized_keys relative
    -- to its working directory. Isolate our temporary key below this base.
    local command = "cd " .. quote(base) .. " && LD_LIBRARY_PATH=" .. quote(root .. "/libs") .. " " .. quote(dropbear) .. " -E -s -j -k -r " .. quote(hostkey)
        .. " -p " .. quote(device_ip .. ":" .. tostring(config.ssh_port)) .. " -P " .. quote(pid_path)
        .. " > " .. quote(base .. "/dropbear.log") .. " 2>&1"
    if not run(command) then
        ssh_firewall(source, false)
        os.remove(auth_path)
        return false
    end
    write_file(base .. "/session.id", session_id .. "\n")
    write_file(status_path, "STATE=running\nSOURCE=" .. source .. "\nPORT=" .. tostring(config.ssh_port) .. "\n")
    local timer = "nohup sh " .. quote(base .. "/stop.sh") .. " --timer " .. quote(session_id)
        .. " " .. tostring(config.session_duration_seconds) .. " >/dev/null 2>&1 </dev/null & echo $! > " .. quote(base .. "/timer.pid")
    if not run(timer) then run("sh " .. quote(base .. "/stop.sh")); return false end
    return true
end

local function handle_client(client)
    client:settimeout(4)
    local hello, hello_err = receive_line(client)
    append_log("HELLO len=" .. tostring(#hello) .. " err=" .. tostring(hello_err))
    local nonce = hello:match("^KINDLEPILOT/PAIR1 HELLO ([0-9A-Fa-f]+)\r?$")
    if not nonce or #nonce ~= 32 then
        client:send("KINDLEPILOT/PAIR1 ERROR" .. protocol_eol)
        client:close()
        append_log("HELLO_INVALID")
        return false, false
    end
    append_log("HELLO_OK")
    client:send("KINDLEPILOT/PAIR1 CHALLENGE " .. request.device_nonce .. protocol_eol)
    local auth = receive_line(client)
    -- A logical expression collapses a function's multiple return values in
    -- Lua. Call match directly so all three authentication fields survive.
    local received_nonce, public, proof = auth:match("^KINDLEPILOT/PAIR1 AUTH ([0-9A-Fa-f]+) ([A-Za-z0-9+/=]+) ([0-9a-f]+)\r?$")
    local expected = hmac_sha1(request.code, nonce .. "|" .. tostring(public) .. "|" .. request.device_nonce)
    local valid = received_nonce == nonce and valid_public(public) and proof and #proof == 40 and expected and constant_equal(expected, proof)
    local source = client:getpeername()
    if valid and source then
        if not start_ssh(public, source) then
            append_log("SSH_START_FAILED")
            client:send("KINDLEPILOT/PAIR1 ERROR SSH_START_FAILED" .. protocol_eol)
            client:close()
            write_file(status_path, "STATE=error\nERROR=SSH_START_FAILED\n")
            return false, true
        end
        client:send("KINDLEPILOT/PAIR1 OK " .. session_id .. " " .. config.host_public_b64 .. " " .. tostring(config.ssh_port) .. " " .. tostring(config.session_duration_seconds) .. protocol_eol)
        client:close()
        append_log("PAIRED")
        return true, true
    end
    append_log("AUTH_REJECTED")
    client:send("KINDLEPILOT/PAIR1 ERROR AUTH_REJECTED" .. protocol_eol)
    client:close()
    return false, true
end

write_file(base .. "/pairing.network", lan .. "\n")
run("iptables -I INPUT -p tcp ! -s " .. quote(lan) .. " --dport " .. config.pairing_port .. " -j DROP 2>/dev/null || :")
run("iptables -I INPUT -p tcp -s " .. quote(lan) .. " --dport " .. config.pairing_port .. " -j ACCEPT 2>/dev/null || :")
run("iptables -I OUTPUT -p tcp -d " .. quote(lan) .. " --sport " .. config.pairing_port .. " -j ACCEPT 2>/dev/null || :")
local server, bind_err = socket.bind(device_ip, config.pairing_port)
if not server then
    append_log("BIND_FAILED " .. tostring(bind_err))
    cleanup_pairing(nil)
    write_file(status_path, "STATE=error\nERROR=BIND_FAILED\n")
    os.exit(4)
end
server:settimeout(0.25)
write_file(status_path, "STATE=pairing\nIP=" .. device_ip .. "\n")
local attempts = 0
local expiry = tonumber(request.expires_at) or (os.time() + (config.pairing_code_ttl_seconds or 120))
local paired = false
while os.time() < expiry and attempts < (config.pairing_max_attempts or 3) do
    local client = server:accept()
    if client then
        local ok, result, attempted = pcall(handle_client, client)
        if attempted or not ok then attempts = attempts + 1 end
        if ok and result then paired = true; break end
        if not ok then
            append_log("CLIENT_ERROR " .. tostring(result))
            pcall(function()
                client:send("KINDLEPILOT/PAIR1 ERROR INTERNAL" .. protocol_eol)
                client:close()
            end)
        end
    end
    socket.sleep(0.25)
end
cleanup_pairing(server)
if not paired then write_file(status_path, "STATE=stopped\n") end
