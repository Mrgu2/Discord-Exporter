package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode"
)

const extensionID = "imghagiblcldabmfgfgbmjknedmpoodf"
const hostName = "local.discordarchive.connector"

type Config struct {
	ServerURL string `json:"server_url"`
	ProjectID string `json:"project_id,omitempty"`
}
type Message struct {
	Action     string `json:"action"`
	Credential string `json:"credential"`
	UserID     string `json:"user_id"`
}

func baseDir() string {
	if runtime.GOOS == "windows" {
		return filepath.Join(os.Getenv("LOCALAPPDATA"), "DiscordArchiveConnector")
	}
	home, _ := os.UserHomeDir()
	return filepath.Join(home, "Library", "Application Support", "DiscordArchiveConnector")
}
func origin(value string) (string, error) {
	u, e := url.Parse(value)
	if e == nil && u.Scheme == "http" && u.Hostname() == "127.0.0.1" && u.User == nil && u.RawQuery == "" && u.Fragment == "" && (u.Path == "" || u.Path == "/") {
		port, err := strconv.Atoi(u.Port())
		if err == nil && port > 0 && port <= 65535 {
			return "http://127.0.0.1:" + u.Port(), nil
		}
	}
	if e != nil || u.Scheme != "https" || !strings.HasSuffix(u.Hostname(), ".ts.net") || u.User != nil || (u.Port() != "" && u.Port() != "443" && u.Port() != "8443") || (u.Path != "" && u.Path != "/") || u.RawQuery != "" || u.Fragment != "" {
		return "", errors.New("需要服务器的 Tailscale HTTPS 根地址")
	}
	suffix := ""
	if u.Port() == "8443" {
		suffix = ":8443"
	}
	return "https://" + strings.ToLower(u.Hostname()) + suffix, nil
}
func loadConfig() (Config, error) {
	exe, _ := os.Executable()
	return configFrom(exe, false)
}
func loadBindingConfig() (Config, error) {
	data, e := os.ReadFile(filepath.Join(baseDir(), "binding.json"))
	if os.IsNotExist(e) {
		return loadConfig()
	}
	if e != nil {
		return Config{}, e
	}
	var c Config
	if json.Unmarshal(data, &c) != nil {
		return Config{}, errors.New("连接目标配置无效")
	}
	c.ServerURL, e = origin(c.ServerURL)
	return c, e
}
func configFrom(exe string, setup bool) (Config, error) {
	dir := filepath.Dir(exe)
	paths := []string{filepath.Join(dir, "server.json"), filepath.Join(dir, "..", "..", "..", "server.json")}
	saved := filepath.Join(baseDir(), "server.json")
	if setup {
		paths = append(paths, saved)
	} else {
		paths = append([]string{saved}, paths...)
	}
	for _, p := range paths {
		b, e := os.ReadFile(p)
		if e != nil {
			continue
		}
		var c Config
		if json.Unmarshal(b, &c) == nil {
			if c.ServerURL, e = origin(c.ServerURL); e == nil {
				return c, nil
			}
		}
	}
	return Config{}, errors.New("请从自己的 Ubuntu 工作台下载客户端，或将 server.json 与客户端放在一起")
}
func discover() (Config, error) {
	paths := []string{"tailscale"}
	if runtime.GOOS == "darwin" {
		paths = append(paths, "/usr/local/bin/tailscale", "/Applications/Tailscale.app/Contents/MacOS/Tailscale")
	} else {
		paths = append(paths, filepath.Join(os.Getenv("PROGRAMFILES"), "Tailscale", "tailscale.exe"))
	}
	var data []byte
	for _, bin := range paths {
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		b, e := exec.CommandContext(ctx, bin, "status", "--json").Output()
		cancel()
		if e == nil {
			data = b
			break
		}
	}
	var state struct {
		BackendState string
		Peer         map[string]struct {
			HostName string
			DNSName  string
			Online   bool
		}
	}
	if json.Unmarshal(data, &state) != nil || state.BackendState != "Running" {
		return Config{}, errors.New("请先登录 Tailscale")
	}
	var candidates []string
	for _, p := range state.Peer {
		if p.Online && strings.HasPrefix(strings.ToLower(p.HostName), "discordarchive") {
			if u, e := origin("https://" + strings.TrimSuffix(p.DNSName, ".")); e == nil {
				candidates = append(candidates, u)
			}
		}
	}
	sort.Strings(candidates)
	var valid []Config
	for _, u := range candidates {
		c := Config{ServerURL: u}
		if _, e := status(c); e == nil {
			valid = append(valid, c)
		}
	}
	if len(valid) == 1 {
		return valid[0], nil
	}
	return Config{}, errors.New("未找到唯一的工作台，请填写一次 HTTPS 地址")
}
func promptConfig(current string) (Config, error) {
	var cmd *exec.Cmd
	if runtime.GOOS == "darwin" {
		script := "text returned of (display dialog " + strconv.Quote("Ubuntu 工作台 HTTPS 地址（只需设置一次）") + " default answer " + strconv.Quote(current) + " buttons {" + strconv.Quote("取消") + "," + strconv.Quote("保存") + "} default button " + strconv.Quote("保存") + ")"
		cmd = exec.Command("/usr/bin/osascript", "-e", script)
	} else {
		quoted, _ := json.Marshal(current)
		cmd = exec.Command("powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "Add-Type -AssemblyName Microsoft.VisualBasic; [Microsoft.VisualBasic.Interaction]::InputBox('Ubuntu workspace HTTPS address', 'Ubuntu Workspace', "+string(quoted)+")")
	}
	b, e := cmd.Output()
	if e != nil {
		return Config{}, errors.New("已取消设置")
	}
	u, e := origin(strings.TrimSpace(string(b)))
	if e != nil {
		return Config{}, e
	}
	return Config{ServerURL: u}, nil
}
func writePrivate(path string, data []byte, mode os.FileMode) error {
	if e := os.MkdirAll(filepath.Dir(path), 0700); e != nil {
		return e
	}
	f, e := os.CreateTemp(filepath.Dir(path), ".client-")
	if e != nil {
		return e
	}
	tmp := f.Name()
	if e = f.Chmod(mode); e == nil {
		_, e = f.Write(data)
	}
	ce := f.Close()
	if e == nil {
		e = ce
	}
	if e == nil {
		e = os.Rename(tmp, path)
	}
	if e != nil {
		_ = os.Remove(tmp)
	}
	return e
}
func install(c Config) error {
	exe, e := os.Executable()
	if e != nil {
		return e
	}
	data, e := os.ReadFile(exe)
	if e != nil {
		return e
	}
	digest := sha256.Sum256(data)
	name := "native-host-" + hex.EncodeToString(digest[:8])
	if runtime.GOOS == "windows" {
		name += ".exe"
	}
	target := filepath.Join(baseDir(), name)
	if _, e = os.Stat(target); os.IsNotExist(e) {
		if e = writePrivate(target, data, 0700); e != nil {
			return e
		}
	}
	config, _ := json.Marshal(c)
	if e = writePrivate(filepath.Join(baseDir(), "binding.json"), config, 0600); e != nil {
		return e
	}
	manifest, _ := json.Marshal(map[string]any{"name": hostName, "description": "Discord Archive one-click binding", "path": target, "type": "stdio", "allowed_origins": []string{"chrome-extension://" + extensionID + "/"}})
	if runtime.GOOS == "windows" {
		p := filepath.Join(baseDir(), "native-host.json")
		if e = writePrivate(p, manifest, 0600); e != nil {
			return e
		}
		for _, browser := range []string{"Google\\Chrome", "Microsoft\\Edge"} {
			cmd := exec.Command("reg", "ADD", "HKCU\\Software\\"+browser+"\\NativeMessagingHosts\\"+hostName, "/ve", "/t", "REG_SZ", "/d", p, "/f")
			if e = cmd.Run(); e != nil {
				return errors.New("无法注册当前用户的浏览器连接组件")
			}
		}
	} else {
		home, _ := os.UserHomeDir()
		for _, browser := range []string{"Google/Chrome", "Microsoft Edge"} {
			p := filepath.Join(home, "Library", "Application Support", browser, "NativeMessagingHosts", hostName+".json")
			if old, e := os.ReadFile(p); e == nil && !bytes.Equal(old, manifest) {
				_ = writePrivate(p+".previous-"+time.Now().Format("20060102150405"), old, 0600)
			}
			if e = writePrivate(p, manifest, 0600); e != nil {
				return e
			}
		}
	}
	return nil
}
func client() *http.Client {
	return &http.Client{Timeout: 25 * time.Second, Transport: &http.Transport{Proxy: nil, DialContext: (&net.Dialer{Timeout: 12 * time.Second}).DialContext, TLSHandshakeTimeout: 12 * time.Second}, CheckRedirect: func(r *http.Request, v []*http.Request) error { return errors.New("不接受重定向") }}
}
func request(c Config, path, method string, payload any, key string) (map[string]any, error) {
	var body io.Reader
	if payload != nil {
		b, _ := json.Marshal(payload)
		body = bytes.NewReader(b)
	}
	req, e := http.NewRequest(method, c.ServerURL+path, body)
	if e != nil {
		return nil, e
	}
	req.Header.Set("Origin", c.ServerURL)
	if payload != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if key != "" {
		req.Header.Set("X-Archive-Key", key)
	}
	r, e := client().Do(req)
	if e != nil {
		if strings.HasPrefix(c.ServerURL, "http://127.0.0.1:") {
			return nil, errors.New("无法连接Mac本机工作台，请先打开完整项目的Start.command")
		}
		return nil, errors.New("无法直连私网 HTTPS；请确认两端 Tailscale 在线")
	}
	defer r.Body.Close()
	b, e := io.ReadAll(io.LimitReader(r.Body, 1048577))
	if e != nil || len(b) > 1048576 {
		return nil, errors.New("服务器响应异常")
	}
	var result map[string]any
	if json.Unmarshal(b, &result) != nil {
		return nil, errors.New("服务器响应异常")
	}
	if r.StatusCode < 200 || r.StatusCode >= 300 {
		message, _ := result["error"].(string)
		if message == "" {
			message = "服务器拒绝连接"
		}
		return nil, errors.New(message)
	}
	return result, nil
}
func status(c Config) (map[string]any, error) {
	s, e := request(c, "/api/status", "GET", nil, "")
	if e != nil {
		return nil, e
	}
	remote, ok := s["remote"].(map[string]any)
	if strings.HasPrefix(c.ServerURL, "http://127.0.0.1:") {
		system, _ := s["system"].(map[string]any)
		platform, _ := s["platform"].(map[string]any)
		if !ok || remote["administrator"] != true || platform["system"] != "darwin" || !regexp.MustCompile("^[a-f0-9]{64}$").MatchString(c.ProjectID) || system["project_id"] != c.ProjectID {
			return nil, errors.New("本机工作台身份不匹配，请从当前Mac工作台重新下载首次连接包")
		}
		return s, nil
	}
	if !ok || remote["administrator"] != true || remote["https_url"] != c.ServerURL {
		return nil, errors.New("当前 Tailscale 身份不是该服务器的获准管理员")
	}
	return s, nil
}
func handle(c Config, m Message) (map[string]any, error) {
	switch m.Action {
	case "info":
		return map[string]any{"ok": true, "server_url": c.ServerURL}, nil
	case "check":
		_, e := status(c)
		return map[string]any{"ok": e == nil, "server_url": c.ServerURL}, e
	case "bind":
		if len(m.Credential) < 16 || len(m.Credential) > 4096 || strings.IndexFunc(m.Credential, unicode.IsSpace) >= 0 || !regexp.MustCompile("^[0-9]{1,30}$").MatchString(m.UserID) {
			return nil, errors.New("登录连接无效")
		}
		s, e := status(c)
		if e != nil {
			return nil, e
		}
		key, _ := s["archive_key"].(string)
		if key == "" {
			return nil, errors.New("服务器缺少请求校验")
		}
		r, e := request(c, "/api/bind-discord", "POST", map[string]string{"credential": m.Credential, "expected_user_id": m.UserID, "expected_project_id": c.ProjectID}, key)
		m.Credential = ""
		if e != nil {
			return nil, e
		}
		if r["ok"] != true {
			return nil, errors.New("服务器未确认绑定")
		}
		return map[string]any{"ok": true, "automatic_paused": true, "server_url": c.ServerURL}, nil
	default:
		return nil, errors.New("不支持的操作")
	}
}
func send(value map[string]any) {
	b, e := json.Marshal(value)
	if e != nil {
		return
	}
	header := make([]byte, 4)
	binary.LittleEndian.PutUint32(header, uint32(len(b)))
	_, _ = os.Stdout.Write(header)
	_, _ = os.Stdout.Write(b)
}
func native(caller string) {
	if strings.TrimSuffix(caller, "/") != "chrome-extension://"+extensionID {
		send(map[string]any{"ok": false, "error": "扩展身份不匹配"})
		return
	}
	header := make([]byte, 4)
	if _, e := io.ReadFull(os.Stdin, header); e != nil {
		return
	}
	n := binary.LittleEndian.Uint32(header)
	if n < 2 || n > 16384 {
		send(map[string]any{"ok": false, "error": "请求大小无效"})
		return
	}
	b := make([]byte, n)
	if _, e := io.ReadFull(os.Stdin, b); e != nil {
		return
	}
	var m Message
	decoder := json.NewDecoder(bytes.NewReader(b))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&m) != nil {
		send(map[string]any{"ok": false, "error": "请求格式无效"})
		return
	}
	c, e := loadBindingConfig()
	if e != nil {
		send(map[string]any{"ok": false, "error": "请先打开客户端完成首次安装"})
		return
	}
	r, e := handle(c, m)
	for i := range b {
		b[i] = 0
	}
	m.Credential = ""
	if e != nil {
		send(map[string]any{"ok": false, "error": e.Error()})
		return
	}
	send(r)
}
func browserPath() string {
	var paths []string
	if runtime.GOOS == "darwin" {
		paths = []string{"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"}
	} else {
		for _, key := range []string{"PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"} {
			if base := os.Getenv(key); base != "" {
				paths = append(paths, filepath.Join(base, "Microsoft", "Edge", "Application", "msedge.exe"), filepath.Join(base, "Google", "Chrome", "Application", "chrome.exe"))
			}
		}
	}
	for _, p := range paths {
		if _, e := os.Stat(p); e == nil {
			return p
		}
	}
	return ""
}
func workspace(c Config) error {
	browser := browserPath()
	if browser == "" {
		return errors.New("请先安装 Chrome 或 Edge")
	}
	profile, e := os.MkdirTemp("", "discordarchive-workspace-")
	if e != nil {
		return e
	}
	// Only this newly created private workspace profile is removed, after its browser exits.
	defer os.RemoveAll(profile)
	cmd := exec.Command(browser, "--user-data-dir="+profile, "--no-proxy-server", "--no-first-run", "--no-default-browser-check", "--disable-background-mode", "--disable-sync", "--app="+c.ServerURL)
	return cmd.Run()
}
func showError(message string) {
	if runtime.GOOS == "darwin" {
		_ = exec.Command("/usr/bin/osascript", "-e", "display dialog "+strconv.Quote(message)+" buttons {\"好\"} default button \"好\" with title \"Ubuntu 工作台\"").Run()
	} else {
		data, _ := json.Marshal(message)
		_ = exec.Command("powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show("+string(data)+", 'Ubuntu Workspace')").Run()
	}
}
func main() {
	if len(os.Args) > 1 && strings.HasPrefix(os.Args[1], "chrome-extension://") {
		native(os.Args[1])
		return
	}
	c, e := loadConfig()
	if len(os.Args) > 1 && os.Args[1] == "--check-binding" {
		c, e = loadBindingConfig()
	}
	if len(os.Args) > 1 && os.Args[1] == "--install-only" {
		exe, _ := os.Executable()
		c, e = configFrom(exe, true)
	}
	configure := len(os.Args) > 1 && os.Args[1] == "--configure"
	if e != nil && !configure {
		c, e = discover()
	}
	if configure || (e != nil && len(os.Args) == 1) {
		c, e = promptConfig(c.ServerURL)
	}
	if e != nil {
		if len(os.Args) > 1 {
			fmt.Fprintln(os.Stderr, e.Error())
		} else {
			showError(e.Error())
		}
		os.Exit(1)
	}
	if len(os.Args) > 1 && (os.Args[1] == "--check" || os.Args[1] == "--check-binding") {
		_, e = status(c)
		if e != nil {
			fmt.Fprintln(os.Stderr, e.Error())
			os.Exit(1)
		}
		fmt.Println("工作台地址、管理员权限与目标身份检查通过；未读取或更改账号连接。")
		return
	}
	if len(os.Args) > 1 && os.Args[1] == "--install-only" {
		e = install(c)
	} else {
		if _, e = status(c); e == nil {
			b, _ := json.Marshal(c)
			e = writePrivate(filepath.Join(baseDir(), "server.json"), b, 0600)
			if e == nil && !configure {
				e = workspace(c)
			}
		}
	}
	if e != nil {
		showError("工作台未能打开。请确认 Tailscale 在线；也可通过设置工具修改 HTTPS 地址。")
		os.Exit(1)
	}
}
