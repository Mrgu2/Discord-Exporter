package main

import (
	"bytes"
	"encoding/binary"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestOrigin(t *testing.T) {
	for _, s := range []string{"http://a.ts.net", "https://example.com", "https://user@a.ts.net", "https://a.ts.net/path", "https://a.ts.net?secret=x", "https://a.ts.net#x", "https://a.ts.net:123"} {
		if _, e := origin(s); e == nil {
			t.Fatal("accepted invalid origin")
		}
	}
	if s, e := origin("https://A.ts.net/"); e != nil || s != "https://a.ts.net" {
		t.Fatal("normalization")
	}
}
func TestIsolatedHTTPSOrigin(t *testing.T) {
	if s, e := origin("https://fixture.ts.net:8443/"); e != nil || s != "https://fixture.ts.net:8443" {
		t.Fatal("isolated HTTPS port")
	}
}
func TestSameOwnerBindAndInputValidation(t *testing.T) {
	count := 0
	owner := true
	var address string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Origin") != address {
			t.Fatal("origin missing")
		}
		if r.URL.Path == "/api/status" {
			json.NewEncoder(w).Encode(map[string]any{"archive_key": "fixture", "remote": map[string]any{"administrator": owner, "https_url": address}, "system": map[string]any{"project_id": strings.Repeat("a", 64)}, "platform": map[string]any{"system": "darwin"}})
			return
		}
		if r.URL.Path != "/api/bind-discord" || r.Method != "POST" || r.Header.Get("X-Archive-Key") != "fixture" {
			t.Fatal("wrong endpoint or csrf")
		}
		var b map[string]string
		json.NewDecoder(r.Body).Decode(&b)
		if b["credential"] != "synthetic_never_real" || b["expected_user_id"] != "9001" {
			t.Fatal("protocol mismatch")
		}
		count++
		json.NewEncoder(w).Encode(map[string]any{"ok": true})
	}))
	defer server.Close()
	address = server.URL
	c := Config{ServerURL: address, ProjectID: strings.Repeat("a", 64)}
	r, e := handle(c, Message{Action: "bind", Credential: "synthetic_never_real", UserID: "9001"})
	if e != nil || r["ok"] != true || count != 1 {
		t.Fatal("bind failed")
	}
	owner = false
	if _, e = handle(c, Message{Action: "bind", Credential: "synthetic_never_real", UserID: "9001"}); e == nil || count != 1 {
		t.Fatal("nonowner bind accepted")
	}
	for _, m := range []Message{{Action: "bind", Credential: "bad", UserID: "9001"}, {Action: "bind", Credential: "synthetic\nneverreal", UserID: "9001"}, {Action: "bind", Credential: "synthetic_never_real", UserID: "other"}, {Action: "execute"}} {
		if _, e = handle(c, m); e == nil {
			t.Fatal("invalid message accepted")
		}
	}
}
func TestNativeFramingAndOrigin(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("LOCALAPPDATA", home)
	if e := writePrivate(filepath.Join(baseDir(), "server.json"), []byte("{\"server_url\":\"https://fixture.test.ts.net\"}"), 0600); e != nil {
		t.Fatal(e)
	}
	for _, caller := range []string{"chrome-extension://" + extensionID + "/", "chrome-extension://other/"} {
		inputR, inputW, _ := os.Pipe()
		outputR, outputW, _ := os.Pipe()
		oldIn, oldOut := os.Stdin, os.Stdout
		data := []byte("{\"action\":\"info\"}")
		header := make([]byte, 4)
		binary.LittleEndian.PutUint32(header, uint32(len(data)))
		inputW.Write(append(header, data...))
		inputW.Close()
		os.Stdin, os.Stdout = inputR, outputW
		native(caller)
		outputW.Close()
		os.Stdin, os.Stdout = oldIn, oldOut
		raw, _ := io.ReadAll(outputR)
		inputR.Close()
		outputR.Close()
		if len(raw) < 4 || int(binary.LittleEndian.Uint32(raw[:4])) != len(raw)-4 {
			t.Fatal("bad framing")
		}
		var r map[string]any
		if json.Unmarshal(raw[4:], &r) != nil {
			t.Fatal("invalid utf8 json")
		}
		if caller == "chrome-extension://"+extensionID+"/" && r["ok"] != true {
			t.Fatal("expected caller denied")
		}
		if strings.Contains(caller, "other") && r["ok"] != false {
			t.Fatal("unexpected caller accepted")
		}
		if bytes.Contains(raw, []byte("credential")) {
			t.Fatal("secret field in info")
		}
	}
}

func TestSetupUsesDownloadedServerAndDailyUsesSavedAddress(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("LOCALAPPDATA", home)
	dir := t.TempDir()
	exe := filepath.Join(dir, "client")
	if e := writePrivate(filepath.Join(baseDir(), "server.json"), []byte(`{"server_url":"https://saved.ts.net"}`), 0600); e != nil {
		t.Fatal(e)
	}
	if e := writePrivate(filepath.Join(dir, "server.json"), []byte(`{"server_url":"https://new-server.ts.net"}`), 0600); e != nil {
		t.Fatal(e)
	}
	daily, e := configFrom(exe, false)
	if e != nil || daily.ServerURL != "https://saved.ts.net" {
		t.Fatal("daily settings ignored")
	}
	setup, e := configFrom(exe, true)
	if e != nil || setup.ServerURL != "https://new-server.ts.net" {
		t.Fatal("setup targeted previous server")
	}
}

func TestLocalOriginIsExactLoopbackOnly(t *testing.T) {
	for _, bad := range []string{"http://localhost:8765", "http://127.0.0.2:8765", "http://192.168.1.1:8765", "http://127.0.0.1:8765/path", "http://127.0.0.1:8765?x=1", "http://user@127.0.0.1:8765", "http://127.0.0.1:70000"} {
		if _, e := origin(bad); e == nil {
			t.Fatal("unsafe local origin", bad)
		}
	}
	if v, e := origin("http://127.0.0.1:18766/"); e != nil || v != "http://127.0.0.1:18766" {
		t.Fatal("local origin")
	}
}

func TestLocalIdentityMismatchNeverBinds(t *testing.T) {
	count := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/status" {
			count++
		}
		json.NewEncoder(w).Encode(map[string]any{"archive_key": "fixture", "remote": map[string]any{"administrator": true}, "platform": map[string]any{"system": "darwin"}, "system": map[string]any{"project_id": strings.Repeat("a", 64)}})
	}))
	defer server.Close()
	for _, project := range []string{"", strings.Repeat("b", 64)} {
		if _, e := handle(Config{ServerURL: server.URL, ProjectID: project}, Message{Action: "bind", Credential: "synthetic_never_real", UserID: "9001"}); e == nil {
			t.Fatal("wrong local database accepted")
		}
	}
	if count != 0 {
		t.Fatal("credential submitted to different database")
	}
}

func TestBindingSetupDoesNotReplaceDailyWorkspace(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("LOCALAPPDATA", home)
	saved := filepath.Join(baseDir(), "server.json")
	daily := []byte(`{"server_url":"https://daily.ts.net"}`)
	if e := writePrivate(saved, daily, 0600); e != nil {
		t.Fatal(e)
	}
	local := Config{ServerURL: "http://127.0.0.1:18766", ProjectID: strings.Repeat("a", 64)}
	if e := install(local); e != nil {
		t.Fatal(e)
	}
	unchanged, _ := os.ReadFile(saved)
	if !bytes.Equal(unchanged, daily) {
		t.Fatal("binding replaced daily access")
	}
	binding, e := loadBindingConfig()
	if e != nil || binding != local {
		t.Fatal("binding target not retained")
	}
}
