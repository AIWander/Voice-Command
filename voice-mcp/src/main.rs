use chrono::Utc;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::io::{self, BufRead, Write};
use std::path::PathBuf;
use std::process::Stdio;
use std::sync::Mutex;
use tokio::process::Command;
// NAV: TOC at line 626 | 16 fn | 4 struct | 2026-03-29

// Global transcript buffer for checkpointing
lazy_static::lazy_static! {
    static ref TRANSCRIPT: Mutex<Vec<TranscriptEntry>> = Mutex::new(Vec::new());
    static ref SESSION_ID: Mutex<String> = Mutex::new(String::new());
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct TranscriptEntry {
    timestamp: String,
    role: String, // "user", "assistant", or "system"
    content: String,
}

#[derive(Debug, Deserialize)]
struct JsonRpcRequest {
    jsonrpc: Option<String>,
    #[serde(default)]
    id: Value,
    method: Option<String>,
    #[serde(default)]
    params: Value,
}

#[derive(Debug, Serialize)]
struct JsonRpcResponse {
    jsonrpc: &'static str,
    id: Value,
    #[serde(skip_serializing_if = "Option::is_none")]
    result: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<JsonRpcError>,
}

#[derive(Debug, Serialize)]
struct JsonRpcError {
    code: i32,
    message: String,
}

fn tool_definitions() -> Value {
    json!({
        "tools": [
            {
                "name": "speak",
                "description": "Speak text aloud using edge-tts with high-quality neural voices.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": { "type": "string", "description": "Text to speak" },
                        "voice": { "type": "string", "description": "Voice (default: from config)" },
                        "speed": { "type": "number", "description": "Speech rate multiplier (default: 1.0, range 0.5-2.0)" },
                        "pitch": { "type": "string", "description": "Pitch adjustment, e.g. '+10Hz' or '-5Hz' (default: from config)" },
                        "volume": { "type": "number", "description": "Volume multiplier (default: 1.0, range 0.0-1.0)" }
                    },
                    "required": ["text"]
                }
            },
            {
                "name": "listen_for_speech",
                "description": "Listen for voice input. Returns transcribed speech.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "timeout": { "type": "integer", "description": "Max seconds (default: from config or 120)" },
                        "silence_timeout": { "type": "number", "description": "Seconds of silence before cutoff (default: from config or 4.0)" },
                        "min_speech_duration": { "type": "number", "description": "Min seconds of audio to count as speech (default: from config or 4.0)" },
                        "rms_threshold": { "type": "number", "description": "Loudness floor 20-500 (default: from config or 100)" },
                        "pre_record_enabled": { "type": "boolean", "description": "Capture audio before tool returns (default: from config or true)" },
                        "noise_filter_enabled": { "type": "boolean", "description": "Apply noise filter (default: from config or true)" }
                    }
                }
            },
            {
                "name": "start_voice_mode",
                "description": "Check if voice server is ready.",
                "inputSchema": { "type": "object", "properties": {} }
            },
            {
                "name": "voice_checkpoint",
                "description": "Save current transcript to file for crash recovery.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": { "type": "string", "description": "Path (default: auto-generated in voice_sessions/)" },
                        "note": { "type": "string", "description": "Optional note to add" }
                    }
                }
            },
            {
                "name": "voice_load_checkpoint",
                "description": "Load transcript from previous session checkpoint.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": { "type": "string", "description": "Checkpoint file path" }
                    },
                    "required": ["path"]
                }
            },
            {
                "name": "voice_get_transcript",
                "description": "Get current session transcript.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "last_n": { "type": "integer", "description": "Last N entries (default: all)" }
                    }
                }
            },
            {
                "name": "voice_add_note",
                "description": "Add a note to the transcript (for context that doesn't go through speech).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "note": { "type": "string", "description": "Note content" },
                        "role": { "type": "string", "description": "Role: user, assistant, or system (default: system)" }
                    },
                    "required": ["note"]
                }
            },
            {
                "name": "list_voices",
                "description": "List available edge-tts voices.",
                "inputSchema": { "type": "object", "properties": {} }
            },
            {
                "name": "get_config",
                "description": "Return current voice configuration from voice.config.toml.",
                "inputSchema": { "type": "object", "properties": {} }
            }
        ]
    })
}

fn rolling_log_path() -> Option<PathBuf> {
    if let Ok(path) = std::env::var("VOICE_TRANSCRIPT_LOG_PATH") {
        let trimmed = path.trim();
        if !trimmed.is_empty() {
            return Some(PathBuf::from(trimmed));
        }
    }

    if let Some(base) = std::env::var_os("LOCALAPPDATA") {
        return Some(
            PathBuf::from(base)
                .join("Voice-Command")
                .join("voice_sessions")
                .join("rolling_log.jsonl"),
        );
    }

    std::env::var_os("HOME").map(|home| {
        PathBuf::from(home)
            .join(".voice-command")
            .join("voice_sessions")
            .join("rolling_log.jsonl")
    })
}

fn add_to_transcript(role: &str, content: &str) {
    let entry = TranscriptEntry {
        timestamp: Utc::now().to_rfc3339(),
        role: role.to_string(),
        content: content.to_string(),
    };

    // Append to a local rolling log unless the user overrides the path.
    if let Some(log_path) = rolling_log_path() {
        if let Some(parent) = log_path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        if let Ok(json) = serde_json::to_string(&entry) {
            let _ = std::fs::OpenOptions::new()
                .create(true)
                .append(true)
                .open(log_path)
                .and_then(|mut f| {
                    use std::io::Write;
                    writeln!(f, "{}", json)
                });
        }
    }

    // Also keep in memory
    if let Ok(mut transcript) = TRANSCRIPT.lock() {
        transcript.push(entry);
    }
}

fn get_session_id() -> String {
    let mut id = SESSION_ID.lock().unwrap();
    if id.is_empty() {
        *id = Utc::now().format("%Y%m%d_%H%M%S").to_string();
    }
    id.clone()
}

/// Locate voice.config.toml via a search order so the binary is portable:
///   1. VOICE_CONFIG_PATH env var (explicit override)
///   2. voice.config.toml next to the executable
///   3. ~/.config/voice/voice.config.toml
///   4. legacy C:\CPC\voice\voice.config.toml (back-compat for existing installs)
fn find_config_path() -> Option<String> {
    if let Ok(p) = std::env::var("VOICE_CONFIG_PATH") {
        if !p.is_empty() && std::path::Path::new(&p).exists() {
            return Some(p);
        }
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            let p = dir.join("voice.config.toml");
            if p.exists() {
                return Some(p.to_string_lossy().into_owned());
            }
        }
    }
    if let Some(home) = std::env::var_os("USERPROFILE").or_else(|| std::env::var_os("HOME")) {
        let p = std::path::Path::new(&home)
            .join(".config")
            .join("voice")
            .join("voice.config.toml");
        if p.exists() {
            return Some(p.to_string_lossy().into_owned());
        }
    }
    let legacy = "C:\\CPC\\voice\\voice.config.toml";
    if std::path::Path::new(legacy).exists() {
        return Some(legacy.to_string());
    }
    None
}

fn read_voice_config() -> Value {
    let path = match find_config_path() {
        Some(p) => p,
        None => return json!({}),
    };
    match std::fs::read_to_string(&path) {
        Ok(content) => match content.parse::<toml::Table>() {
            Ok(table) => serde_json::to_value(table).unwrap_or(json!({})),
            Err(_) => json!({}),
        },
        Err(_) => json!({}),
    }
}

struct ListenDefaults {
    silence_timeout_secs: f64,
    min_speech_duration_secs: f64,
    rms_threshold: f64,
    pre_record_enabled: bool,
    noise_filter_enabled: bool,
    listen_timeout_secs: u32,
}

fn get_listen_defaults() -> ListenDefaults {
    let config = read_voice_config();
    ListenDefaults {
        silence_timeout_secs: config["listen"]["silence_timeout_secs"]
            .as_f64()
            .unwrap_or(4.0),
        min_speech_duration_secs: config["listen"]["min_speech_duration_secs"]
            .as_f64()
            .unwrap_or(4.0),
        rms_threshold: config["listen"]["rms_threshold"].as_f64().unwrap_or(100.0),
        pre_record_enabled: config["listen"]["pre_record_enabled"]
            .as_bool()
            .unwrap_or(true),
        noise_filter_enabled: config["listen"]["noise_filter_enabled"]
            .as_bool()
            .unwrap_or(true),
        listen_timeout_secs: config["listen"]["listen_timeout_secs"]
            .as_u64()
            .unwrap_or(120) as u32,
    }
}

fn get_edge_tts_defaults() -> (String, f64, String, f64) {
    let config = read_voice_config();
    let defaults_vol = config["defaults"]["volume"].as_f64().unwrap_or(1.0);
    let voice = config["edge-tts"]["voice"]
        .as_str()
        .unwrap_or("en-US-GuyNeural")
        .to_string();
    let speed = config["edge-tts"]["speed"].as_f64().unwrap_or(1.0);
    let pitch = config["edge-tts"]["pitch"]
        .as_str()
        .unwrap_or("+0Hz")
        .to_string();
    let volume = config["edge-tts"]["volume"]
        .as_f64()
        .unwrap_or(defaults_vol);
    (voice, speed, pitch, volume)
}

async fn play_audio(
    audio_path_str: &str,
    volume: f64,
    wait_for_completion: bool,
) -> Result<(), String> {
    let play_script = format!(
        r#"Add-Type -AssemblyName presentationCore
$player = New-Object System.Windows.Media.MediaPlayer
$player.Open([Uri]::new('{0}'))
Start-Sleep -Milliseconds 200
$t = 0
while (-not $player.NaturalDuration.HasTimeSpan -and $t -lt 30) {{
    Start-Sleep -Milliseconds 100
    $t++
}}
$player.Volume = {1}
$player.Play()
if ($player.NaturalDuration.HasTimeSpan) {{
    $dur = [int]$player.NaturalDuration.TimeSpan.TotalMilliseconds + 200
    Start-Sleep -Milliseconds $dur
}} else {{
    Start-Sleep -Milliseconds 3000
}}
$player.Close()
Remove-Item '{0}' -ErrorAction SilentlyContinue"#,
        audio_path_str.replace('\'', "''"),
        volume
    );

    if wait_for_completion {
        let output = Command::new("powershell")
            .arg("-WindowStyle")
            .arg("Hidden")
            .arg("-Command")
            .arg(&play_script)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .output()
            .await
            .map_err(|e| format!("Failed to play audio: {}", e))?;

        if !output.status.success() {
            return Err(format!(
                "Audio playback failed: {}",
                String::from_utf8_lossy(&output.stderr)
            ));
        }
    } else {
        Command::new("powershell")
            .arg("-WindowStyle")
            .arg("Hidden")
            .arg("-Command")
            .arg(&play_script)
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|e| format!("Failed to start audio playback: {}", e))?;
    }

    Ok(())
}

async fn speak_internal(
    text: &str,
    voice: &str,
    speed: f64,
    pitch: &str,
    volume: f64,
    wait_for_completion: bool,
) -> Result<String, String> {
    // Unique temp file per call to avoid lock conflicts
    let uid = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0);
    let audio_path = std::env::temp_dir().join(format!("tts_{}.mp3", uid));
    let audio_path_str = audio_path.to_string_lossy().to_string();

    // Pre-cleanup
    let _ = std::fs::remove_file(&audio_path);

    let rate_str = if (speed - 1.0).abs() > 0.01 {
        Some(format!("{:+.0}%", (speed - 1.0) * 100.0))
    } else {
        None
    };

    let mut cmd = Command::new("edge-tts");
    cmd.arg("--text")
        .arg(text)
        .arg("--voice")
        .arg(voice)
        .arg("--write-media")
        .arg(&audio_path_str);

    if let Some(ref rate) = rate_str {
        cmd.arg(format!("--rate={}", rate));
    }
    if pitch != "+0Hz" {
        cmd.arg(format!("--pitch={}", pitch));
    }

    let output = cmd
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output()
        .await
        .map_err(|e| format!("Failed to run edge-tts: {}", e))?;

    if !output.status.success() {
        return Err(format!(
            "edge-tts failed: {}",
            String::from_utf8_lossy(&output.stderr)
        ));
    }

    play_audio(&audio_path_str, volume, wait_for_completion).await?;
    add_to_transcript("assistant", text);
    Ok("spoke".to_string())
}

async fn speak(
    text: &str,
    voice: &str,
    speed: f64,
    pitch: &str,
    volume: f64,
) -> Result<String, String> {
    // Keep speak half-duplex safe so a follow-up listen_for_speech
    // call cannot start while TTS audio is still playing.
    speak_internal(text, voice, speed, pitch, volume, true).await
}

async fn listen_for_speech(
    timeout: u32,
    silence_timeout: f64,
    min_speech_duration: f64,
    rms_threshold: f64,
    pre_record_enabled: bool,
    noise_filter_enabled: bool,
) -> Result<Value, String> {
    let client = reqwest::Client::new();

    let skip_filter = if noise_filter_enabled {
        "false"
    } else {
        "true"
    };
    let url = format!(
        "http://localhost:5123/listen?timeout={}&silence_timeout={}&min_speech_duration={}&rms_threshold={}&pre_record_enabled={}&skip_filter={}",
        timeout, silence_timeout, min_speech_duration, rms_threshold, pre_record_enabled, skip_filter
    );
    let response = client.post(&url).send().await.map_err(|e| {
        if e.is_connect() {
            "Voice server not running. Start: python voice_server.py".to_string()
        } else {
            format!("Request failed: {}", e)
        }
    })?;

    let json: Value = response
        .json()
        .await
        .map_err(|e| format!("Failed to parse: {}", e))?;

    if json["success"].as_bool().unwrap_or(false) {
        let text = json["text"].as_str().unwrap_or("");
        // Add to transcript
        add_to_transcript("user", text);
        // Pass through emotion data if present
        let mut result = json!({"text": text});
        if let Some(emotion) = json.get("emotion") {
            result["emotion"] = emotion.clone();
        }
        Ok(result)
    } else {
        Err(json["error"]
            .as_str()
            .unwrap_or("Unknown error")
            .to_string())
    }
}

async fn check_voice_server() -> Result<Value, String> {
    // Load recent history from rolling log
    let mut loaded_count = 0;
    if let Some(log_path) = rolling_log_path() {
        if let Ok(content) = std::fs::read_to_string(log_path) {
            let lines: Vec<&str> = content.lines().collect();
            // Load last 50 entries into memory
            let start = if lines.len() > 50 {
                lines.len() - 50
            } else {
                0
            };
            if let Ok(mut transcript) = TRANSCRIPT.lock() {
                transcript.clear();
                for line in &lines[start..] {
                    if let Ok(entry) = serde_json::from_str::<TranscriptEntry>(line) {
                        transcript.push(entry);
                        loaded_count += 1;
                    }
                }
            }
        }
    }

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(2))
        .build()
        .map_err(|e| format!("Client error: {}", e))?;

    match client.get("http://localhost:5123/status").send().await {
        Ok(response) => {
            let json: Value = response
                .json()
                .await
                .map_err(|e| format!("Parse error: {}", e))?;
            if json["success"].as_bool().unwrap_or(false) {
                Ok(json!({
                    "ready": true,
                    "message": "Voice server ready",
                    "session_id": get_session_id(),
                    "history_loaded": loaded_count
                }))
            } else {
                Ok(json!({"ready": false, "message": "Voice server not ready"}))
            }
        }
        Err(_) => Err("Voice server not running. Start: python voice_server.py".to_string()),
    }
}

fn checkpoint(path: Option<&str>, note: Option<&str>) -> Result<Value, String> {
    let session_id = get_session_id();

    let checkpoint_path = match path {
        Some(p) => p.to_string(),
        None => {
            // Auto-generate path in voice_sessions
            let dir = "C:\\My Drive\\Volumes\\voice_sessions";
            let _ = std::fs::create_dir_all(dir);
            format!("{}/session_{}.md", dir, session_id)
        }
    };

    let transcript = TRANSCRIPT
        .lock()
        .map_err(|e| format!("Lock error: {}", e))?;

    // Format as markdown
    let mut content = format!("# Voice Session Transcript\n\n");
    content.push_str(&format!("**Session ID:** {}\n", session_id));
    content.push_str(&format!("**Saved:** {}\n", Utc::now().to_rfc3339()));
    if let Some(n) = note {
        content.push_str(&format!("**Note:** {}\n", n));
    }
    content.push_str(&format!("**Entries:** {}\n\n", transcript.len()));
    content.push_str("---\n\n");

    for entry in transcript.iter() {
        let role_label = match entry.role.as_str() {
            "user" => "🎤 **User**",
            "assistant" => "🔊 **Claude**",
            "system" => "📝 **System**",
            _ => &entry.role,
        };
        content.push_str(&format!(
            "{} ({})\n\n{}\n\n---\n\n",
            role_label,
            &entry.timestamp[11..19], // Just time portion
            entry.content
        ));
    }

    std::fs::write(&checkpoint_path, &content).map_err(|e| format!("Write error: {}", e))?;

    Ok(json!({
        "success": true,
        "path": checkpoint_path,
        "entries": transcript.len(),
        "session_id": session_id
    }))
}

fn load_checkpoint(path: &str) -> Result<Value, String> {
    let content =
        std::fs::read_to_string(path).map_err(|e| format!("Can't read {}: {}", path, e))?;

    // Parse markdown back to transcript entries
    let mut entries: Vec<TranscriptEntry> = Vec::new();
    let mut current_role = String::new();
    let mut current_time = String::new();
    let mut current_content = String::new();
    let mut in_entry = false;

    for line in content.lines() {
        if line.starts_with("🎤 **User**")
            || line.starts_with("🔊 **Claude**")
            || line.starts_with("📝 **System**")
        {
            // Save previous entry
            if in_entry && !current_content.trim().is_empty() {
                entries.push(TranscriptEntry {
                    timestamp: current_time.clone(),
                    role: current_role.clone(),
                    content: current_content.trim().to_string(),
                });
            }

            // Parse new entry header
            if line.starts_with("🎤") {
                current_role = "user".to_string();
            } else if line.starts_with("🔊") {
                current_role = "assistant".to_string();
            } else if line.starts_with("📝") {
                current_role = "system".to_string();
            }

            // Extract time
            if let Some(start) = line.find('(') {
                if let Some(end) = line.find(')') {
                    current_time = format!("2026-01-01T{}:00Z", &line[start + 1..end]);
                }
            }

            current_content = String::new();
            in_entry = true;
        } else if line == "---" {
            // Skip separators
        } else if in_entry {
            current_content.push_str(line);
            current_content.push('\n');
        }
    }

    // Don't forget last entry
    if in_entry && !current_content.trim().is_empty() {
        entries.push(TranscriptEntry {
            timestamp: current_time,
            role: current_role,
            content: current_content.trim().to_string(),
        });
    }

    // Load into global transcript
    let mut transcript = TRANSCRIPT
        .lock()
        .map_err(|e| format!("Lock error: {}", e))?;
    let loaded_count = entries.len();
    *transcript = entries;

    // Extract session ID from filename if present
    if let Some(filename) = std::path::Path::new(path).file_stem() {
        let fname = filename.to_string_lossy();
        if fname.starts_with("session_") {
            let mut sid = SESSION_ID.lock().unwrap();
            *sid = fname.replace("session_", "");
        }
    }

    Ok(json!({
        "success": true,
        "path": path,
        "entries_loaded": loaded_count,
        "session_id": get_session_id()
    }))
}

fn get_transcript(last_n: Option<usize>) -> Result<Value, String> {
    let transcript = TRANSCRIPT
        .lock()
        .map_err(|e| format!("Lock error: {}", e))?;

    let entries: Vec<&TranscriptEntry> = match last_n {
        Some(n) => transcript
            .iter()
            .rev()
            .take(n)
            .collect::<Vec<_>>()
            .into_iter()
            .rev()
            .collect(),
        None => transcript.iter().collect(),
    };

    Ok(json!({
        "session_id": get_session_id(),
        "total_entries": transcript.len(),
        "returned": entries.len(),
        "entries": entries
    }))
}

fn add_note(note: &str, role: &str) -> Result<Value, String> {
    add_to_transcript(role, note);
    Ok(json!({"success": true, "role": role, "note": note}))
}

async fn handle_tool_call(name: &str, args: &Value) -> Result<Value, String> {
    match name {
        "speak" => {
            let text = args["text"].as_str().ok_or("text required")?;
            let (cfg_voice, cfg_speed, cfg_pitch, cfg_volume) = get_edge_tts_defaults();
            let voice = args["voice"].as_str().unwrap_or(&cfg_voice);
            let speed = args["speed"].as_f64().unwrap_or(cfg_speed);
            let pitch_str = args["pitch"]
                .as_str()
                .map(|s| s.to_string())
                .unwrap_or(cfg_pitch);
            let volume = args["volume"].as_f64().unwrap_or(cfg_volume);
            let result = speak(text, voice, speed, &pitch_str, volume).await?;
            Ok(json!(result))
        }

        "listen_for_speech" => {
            let lcfg = get_listen_defaults();
            let timeout = args["timeout"]
                .as_u64()
                .unwrap_or(lcfg.listen_timeout_secs as u64) as u32;
            let silence_timeout = args["silence_timeout"]
                .as_f64()
                .unwrap_or(lcfg.silence_timeout_secs);
            let min_speech_duration = args["min_speech_duration"]
                .as_f64()
                .unwrap_or(lcfg.min_speech_duration_secs);
            let rms_threshold = args["rms_threshold"].as_f64().unwrap_or(lcfg.rms_threshold);
            let pre_record_enabled = args["pre_record_enabled"]
                .as_bool()
                .unwrap_or(lcfg.pre_record_enabled);
            let noise_filter_enabled = args["noise_filter_enabled"]
                .as_bool()
                .unwrap_or(lcfg.noise_filter_enabled);
            listen_for_speech(
                timeout,
                silence_timeout,
                min_speech_duration,
                rms_threshold,
                pre_record_enabled,
                noise_filter_enabled,
            )
            .await
        }

        "start_voice_mode" => check_voice_server().await,

        "voice_checkpoint" => {
            let path = args["path"].as_str();
            let note = args["note"].as_str();
            checkpoint(path, note)
        }

        "voice_load_checkpoint" => {
            let path = args["path"].as_str().ok_or("path required")?;
            load_checkpoint(path)
        }

        "voice_get_transcript" => {
            let last_n = args["last_n"].as_u64().map(|n| n as usize);
            get_transcript(last_n)
        }

        "voice_add_note" => {
            let note = args["note"].as_str().ok_or("note required")?;
            let role = args["role"].as_str().unwrap_or("system");
            add_note(note, role)
        }

        "list_voices" => {
            let output = Command::new("edge-tts")
                .arg("--list-voices")
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .output()
                .await
                .map_err(|e| format!("Failed to list voices: {}", e))?;
            let voices_text = String::from_utf8_lossy(&output.stdout).to_string();
            Ok(json!({"voices": voices_text}))
        }

        "get_config" => {
            let mut config = read_voice_config();
            if config.get("listen").is_none() {
                config["listen"] = json!({
                    "silence_timeout_secs": 4.0,
                    "min_speech_duration_secs": 4.0,
                    "rms_threshold": 100.0,
                    "pre_record_enabled": true,
                    "noise_filter_enabled": true,
                    "listen_timeout_secs": 120
                });
            }
            Ok(config)
        }

        _ => Err(format!("Unknown tool: {}", name)),
    }
}

fn send_response(
    stdout: &mut io::Stdout,
    id: Value,
    result: Option<Value>,
    error: Option<JsonRpcError>,
) {
    let response = JsonRpcResponse {
        jsonrpc: "2.0",
        id,
        result,
        error,
    };
    let _ = writeln!(stdout, "{}", serde_json::to_string(&response).unwrap());
    let _ = stdout.flush();
}

#[tokio::main]
async fn main() {
    let stdin = io::stdin();
    let mut stdout = io::stdout();

    for line in stdin.lock().lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => continue,
        };
        if line.trim().is_empty() {
            continue;
        }

        let request: JsonRpcRequest = match serde_json::from_str(&line) {
            Ok(r) => r,
            Err(_) => continue,
        };

        // Validate JSON-RPC 2.0 version
        if let Some(ref version) = request.jsonrpc {
            if version != "2.0" {
                send_response(
                    &mut stdout,
                    request.id.clone(),
                    None,
                    Some(JsonRpcError {
                        code: -32600,
                        message: format!(
                            "Invalid JSON-RPC version: expected '2.0', got '{}'",
                            version
                        ),
                    }),
                );
                continue;
            }
        }

        let method = match &request.method {
            Some(m) => m.as_str(),
            None => continue,
        };
        if method.starts_with("notifications/") {
            continue;
        }

        let id = request.id.clone();

        match method {
            "initialize" => {
                send_response(
                    &mut stdout,
                    id,
                    Some(json!({
                        "protocolVersion": "2024-11-05",
                        "serverInfo": { "name": "voice", "version": "0.2.0" },
                        "capabilities": { "tools": {} }
                    })),
                    None,
                );
            }

            "tools/list" => {
                send_response(&mut stdout, id, Some(tool_definitions()), None);
            }

            "tools/call" => {
                let tool_name = request.params["name"].as_str().unwrap_or("");
                let arguments = &request.params["arguments"];

                match handle_tool_call(tool_name, arguments).await {
                    Ok(result) => {
                        send_response(
                            &mut stdout,
                            id,
                            Some(json!({
                                "content": [{"type": "text", "text": serde_json::to_string_pretty(&result).unwrap()}]
                            })),
                            None,
                        );
                    }
                    Err(e) => {
                        send_response(
                            &mut stdout,
                            id,
                            Some(json!({
                                "content": [{"type": "text", "text": e}],
                                "isError": true
                            })),
                            None,
                        );
                    }
                }
            }

            _ => {
                send_response(
                    &mut stdout,
                    id,
                    None,
                    Some(JsonRpcError {
                        code: -32601,
                        message: format!("Method not found: {}", method),
                    }),
                );
            }
        }
    }
}

// === FILE NAVIGATION ===
// Generated: 2026-03-29T16:39:38
// Total: 623 lines | 16 functions | 4 structs | 2 constants
//
// IMPORTS: chrono, serde, serde_json, std, tokio
//
// CONSTANTS:
//   static ref: 11
//   static ref: 12
//
// STRUCTS:
//   TranscriptEntry: 16-20
//   JsonRpcRequest: 23-30
//   JsonRpcResponse: 33-40
//   JsonRpcError: 43-46
//
// FUNCTIONS:
//   tool_definitions: 48-137 [med]
//   add_to_transcript: 139-163
//   get_session_id: 165-171
//   play_audio: 173-225 [med]
//   speak_internal: 227-256
//   speak: 258-262
//   listen_for_speech: 275-306
//   check_voice_server: 308-348
//   checkpoint: 350-398
//   load_checkpoint: 400-473 [med]
//   get_transcript: 475-489
//   add_note: 491-494
//   handle_tool_call: 496-545
//   send_response: 547-551
//   main: 554-623 [med]
//
// === END FILE NAVIGATION ===
