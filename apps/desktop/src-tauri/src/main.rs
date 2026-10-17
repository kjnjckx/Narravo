#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod credentials;

use serde_json::{json, Value};
use std::{
    collections::HashMap,
    io::{BufRead, BufReader, Read, Write},
    process::{Child, ChildStdin, Command, Stdio},
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc, Mutex,
    },
    time::{Duration, Instant},
};
use tauri::{Emitter, Manager};
use tokio::sync::oneshot;

type Reply = Result<Value, String>;
type Pending = Arc<Mutex<HashMap<String, oneshot::Sender<Reply>>>>;
const LIMIT: usize = 16 * 1024 * 1024;

struct Bridge {
    input: Mutex<Option<ChildStdin>>,
    child: Mutex<Child>,
    pending: Pending,
    sequence: AtomicU64,
    data_dir: std::path::PathBuf,
}

impl Bridge {
    fn launch(app: &tauri::AppHandle) -> Result<Self, Box<dyn std::error::Error>> {
        let mut data_dir;
        let mut command;
        if cfg!(debug_assertions) {
            let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..");
            let python = root.join(if cfg!(windows) {
                "services/engine/.venv/Scripts/python.exe"
            } else {
                "services/engine/.venv/bin/python"
            });
            command = Command::new(python);
            command.args(["-m", "narravo_engine"]);
            data_dir = root.join(".dev-data");
        } else {
            let executable = std::env::current_exe()?
                .parent()
                .ok_or("missing executable directory")?
                .join(if cfg!(windows) {
                    "narravo-engine.exe"
                } else {
                    "narravo-engine"
                });
            command = Command::new(executable);
            data_dir = app.path().app_data_dir()?;
        }
        if let Some(directory) = std::env::var_os("NARRAVO_DATA_DIR") {
            data_dir = std::path::PathBuf::from(directory);
        }
        // Paths are owned by Rust and never accepted from or returned to the renderer.
        let mut child = command
            .arg("--data-dir")
            .arg(&data_dir)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()?;
        let input = child.stdin.take().ok_or("missing stdin")?;
        let output = child.stdout.take().ok_or("missing stdout")?;
        let pending: Pending = Arc::new(Mutex::new(HashMap::new()));
        let readers = pending.clone();
        let handle = app.clone();
        std::thread::spawn(move || {
            let mut reader = BufReader::new(output);
            loop {
                let mut bytes = Vec::new();
                // Limit each frame even if the child emits malformed output.
                let read = std::io::Read::by_ref(&mut reader)
                    .take((LIMIT + 1) as u64)
                    .read_until(b'\n', &mut bytes);
                if !matches!(read, Ok(n) if n > 0 && n <= LIMIT) {
                    break;
                }
                let Ok(message) = serde_json::from_slice::<Value>(&bytes) else {
                    break;
                };
                if message["schema_version"] != 1 || message["jsonrpc"] != "2.0" {
                    break;
                }
                if let Some(id) = message["id"].as_str() {
                    if let Some(sender) = readers.lock().unwrap().remove(id) {
                        let _ = sender.send(Ok(message));
                    }
                } else if message["method"] == "generation.delta" {
                    let _ = handle.emit("engine:event", message);
                }
            }
            for (_, sender) in readers.lock().unwrap().drain() {
                let _ = sender.send(Err("本地引擎已退出，请保留输入并重新启动应用。".into()));
            }
        });
        Ok(Self {
            input: Mutex::new(Some(input)),
            child: Mutex::new(child),
            pending,
            sequence: AtomicU64::new(1),
            data_dir,
        })
    }

    async fn call(&self, method: &str, params: Value) -> Reply {
        let methods: Value =
            serde_json::from_str(include_str!("../../../../packages/contracts/methods.json"))
                .map_err(|_| "合同加载失败")?;
        if methods.get(method).is_none() || !params.is_object() {
            return Err("请求方法或参数无效。".into());
        }
        let id = self.sequence.fetch_add(1, Ordering::Relaxed).to_string();
        let mut bytes = serde_json::to_vec(
            &json!({"jsonrpc":"2.0", "schema_version":1,"id":id,"method":method,"params":params}),
        )
        .map_err(|_| "请求编码失败")?;
        bytes.push(b'\n');
        if bytes.len() > LIMIT {
            return Err("请求过大，请缩小内容范围。".into());
        }
        let (tx, rx) = oneshot::channel();
        self.pending.lock().unwrap().insert(id.clone(), tx);
        let written = self
            .input
            .lock()
            .unwrap()
            .as_mut()
            .ok_or("本地引擎不可用。")?
            .write_all(&bytes);
        if written.is_err() {
            self.pending.lock().unwrap().remove(&id);
            return Err("无法连接本地引擎，请保留输入并重启应用。".into());
        }
        match tokio::time::timeout(Duration::from_secs(15), rx).await {
            Ok(Ok(result)) => result,
            _ => {
                self.pending.lock().unwrap().remove(&id);
                Err("本地操作超时，结果可能已经保存。请保留输入并重新载入作品。".into())
            }
        }
    }

    fn stop(&self) {
        // Closing stdin asks the engine to commit/close and exit; bounded fallback reaps it.
        self.input.lock().unwrap().take();
        let mut child = self.child.lock().unwrap();
        let deadline = Instant::now() + Duration::from_secs(2);
        while Instant::now() < deadline {
            if matches!(child.try_wait(), Ok(Some(_))) {
                return;
            }
            std::thread::sleep(Duration::from_millis(20));
        }
        let _ = child.kill();
        let _ = child.wait();
    }
}

#[tauri::command]
async fn engine_rpc(bridge: tauri::State<'_, Bridge>, method: String, params: Value) -> Reply {
    if params
        .as_object()
        .is_none_or(|object| object.keys().any(|key| key.starts_with('_')))
        || method == "provider.save"
    {
        return Err("请求不允许包含内部字段；密钥请通过模型设置保存。".into());
    }
    let mut params = params;
    let sensitive = method == "provider.test"
        || method == "narration.synthesize"
        || method == "roleplay.send"
        || method == "roleplay.synthesize"
        || (method == "writing.generate" && params["provider"] == "configured");
    if sensitive {
        let id = params["config_id"].as_str().ok_or("请先选择模型配置。")?;
        let reply = bridge.call("provider.get", json!({"config_id":id})).await?;
        let config = reply
            .get("result")
            .ok_or("模型配置不存在，请重新选择。")?
            .clone();
        let captured = config.clone();
        let secret = tauri::async_runtime::spawn_blocking(move || {
            if captured["requires_key"] == false {
                Ok(String::new())
            } else {
                credentials::load(&captured)
            }
        })
        .await
        .map_err(|_| "凭据读取中断。")??;
        params["_credential"] = Value::String(secret);
        params["_credential_endpoint"] = config["base_url"].clone();
    }
    bridge.call(&method, params).await
}

#[tauri::command]
async fn save_provider(
    bridge: tauri::State<'_, Bridge>,
    config: Value,
    api_key: Option<String>,
) -> Reply {
    let validated = bridge
        .call("provider.validate", json!({"config":config}))
        .await?;
    if validated.get("error").is_some() {
        return Ok(validated);
    }
    let captured = config.clone();
    let present = tauri::async_runtime::spawn_blocking(move || -> Result<bool, String> {
        if let Some(secret) = api_key.filter(|value| !value.is_empty()) {
            credentials::save(&captured, &secret)?;
        }
        Ok(!credentials::load(&captured)?.is_empty())
    })
    .await
    .map_err(|_| "凭据保存中断。")??;
    bridge
        .call(
            "provider.save",
            json!({"config":config,"_credential_present":present}),
        )
        .await
}

#[tauri::command]
async fn clear_provider_key(bridge: tauri::State<'_, Bridge>, config_id: String) -> Reply {
    let reply = bridge
        .call("provider.get", json!({"config_id":config_id}))
        .await?;
    let mut config = reply.get("result").ok_or("模型配置不存在。")?.clone();
    let captured = config.clone();
    tauri::async_runtime::spawn_blocking(move || credentials::remove(&captured))
        .await
        .map_err(|_| "凭据操作中断。")??;
    config
        .as_object_mut()
        .ok_or("配置格式无效。")?
        .remove("has_credential");
    bridge
        .call(
            "provider.save",
            json!({"config":config,"_credential_present":false}),
        )
        .await
}

async fn stage_file(
    bridge: &Bridge,
    file: &rfd::FileHandle,
    maximum: u64,
) -> Result<String, String> {
    let asset_id = format!(
        "{:032x}",
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|_| "系统时钟不可用。")?
            .as_nanos()
    );
    let folder = bridge.data_dir.join("inbox");
    tokio::fs::create_dir_all(&folder)
        .await
        .map_err(|_| "无法准备导入目录。")?;
    if tokio::fs::symlink_metadata(&folder)
        .await
        .map_err(|_| "无法读取导入目录。")?
        .file_type()
        .is_symlink()
    {
        return Err("导入目录不允许符号链接。".into());
    }
    let source = file.path().to_owned();
    let target = folder.join(&asset_id);
    tauri::async_runtime::spawn_blocking(move || {
        let mut input = std::fs::File::open(source)
            .map_err(|_| "文件读取失败。")?
            .take(maximum + 1);
        let mut output = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&target)
            .map_err(|_| "无法暂存文件。")?;
        let copied = std::io::copy(&mut input, &mut output);
        if !matches!(copied, Ok(size) if size <= maximum) {
            drop(output);
            let _ = std::fs::remove_file(&target);
            return Err("文件超过大小限制或读取失败。".to_string());
        }
        output
            .sync_all()
            .map_err(|_| "无法保存暂存文件。".to_string())
    })
    .await
    .map_err(|_| "文件暂存中断。")??;
    Ok(asset_id)
}

#[tauri::command]
async fn choose_import(
    bridge: tauri::State<'_, Bridge>,
    encoding: String,
    password: String,
    remove_pdf_margins: bool,
) -> Result<Option<Value>, String> {
    let Some(file) = rfd::AsyncFileDialog::new()
        .add_filter("小说与电子书", &["txt", "epub", "pdf"])
        .pick_file()
        .await
    else {
        return Ok(None);
    };
    let maximum = if file.file_name().to_lowercase().ends_with(".txt") {
        10 * 1024 * 1024
    } else {
        100 * 1024 * 1024
    };
    let asset_id = stage_file(&bridge, &file, maximum).await?;
    bridge.call("file.start_import", json!({"filename":file.file_name(), "asset_id":asset_id, "encoding":encoding, "password":password, "remove_pdf_margins":remove_pdf_margins})).await.map(Some)
}

#[tauri::command]
async fn choose_restore(bridge: tauri::State<'_, Bridge>) -> Result<Option<Value>, String> {
    let Some(file) = rfd::AsyncFileDialog::new()
        .add_filter("叙声完整备份", &["narravo"])
        .pick_file()
        .await
    else {
        return Ok(None);
    };
    let asset_id = stage_file(&bridge, &file, 1024 * 1024 * 1024).await?;
    bridge
        .call("backup.preview_restore", json!({"asset_id":asset_id}))
        .await
        .map(Some)
}

#[tauri::command]
async fn save_backup(
    bridge: tauri::State<'_, Bridge>,
    operation_id: String,
) -> Result<bool, String> {
    if operation_id.len() != 32
        || !operation_id
            .bytes()
            .all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase())
    {
        return Err("备份标识无效。".into());
    }
    let reply = bridge
        .call("file.get", json!({"operation_id":operation_id}))
        .await?;
    if reply["result"]["kind"] != "backup" || reply["result"]["status"] != "completed" {
        return Err("请先等待备份准备完成。".into());
    }
    let Some(destination) = rfd::AsyncFileDialog::new()
        .add_filter("叙声完整备份", &["narravo"])
        .set_file_name("叙声书库.narravo")
        .save_file()
        .await
    else {
        return Ok(false);
    };
    let source = bridge
        .data_dir
        .join("outbox")
        .join(format!("{operation_id}.narravo"));
    let destination = destination.path().to_owned();
    tauri::async_runtime::spawn_blocking(move || {
        let temporary = destination.with_file_name(format!(".narravo-{operation_id}.tmp"));
        let mut output = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)
            .map_err(|_| "无法创建备份文件，请选择其他位置。")?;
        let result = (|| {
            let mut input =
                std::fs::File::open(source).map_err(|_| "备份文件已失效，请重新创建。")?;
            std::io::copy(&mut input, &mut output).map_err(|_| "备份写入失败，请检查磁盘空间。")?;
            output.sync_all().map_err(|_| "备份写入失败。")?;
            drop(output);
            std::fs::rename(&temporary, destination).map_err(|_| "无法完成备份保存。")?;
            Ok(true)
        })();
        let _ = std::fs::remove_file(temporary);
        result
    })
    .await
    .map_err(|_| "备份保存中断。")?
}

#[tauri::command]
async fn save_export(
    bridge: tauri::State<'_, Bridge>,
    branch_id: String,
    format: String,
) -> Result<bool, String> {
    let reply = bridge
        .call(
            "book.export",
            json!({"branch_id":branch_id,"format":format}),
        )
        .await?;
    let result = reply
        .get("result")
        .ok_or("导出失败，请重新打开作品后重试。")?;
    let filename = result["filename"].as_str().ok_or("文件名无效。")?;
    let Some(destination) = rfd::AsyncFileDialog::new()
        .set_file_name(filename)
        .save_file()
        .await
    else {
        return Ok(false);
    };
    tokio::fs::write(
        destination.path(),
        result["content"].as_str().ok_or("导出内容无效。")?,
    )
    .await
    .map_err(|_| "无法写入此位置，请检查磁盘空间或选择其他文件夹。")?;
    Ok(true)
}

#[tauri::command]
async fn save_chat_export(
    bridge: tauri::State<'_, Bridge>,
    conversation_id: String,
) -> Result<bool, String> {
    let reply = bridge
        .call(
            "roleplay.export",
            json!({"conversation_id": conversation_id}),
        )
        .await?;
    let result = reply.get("result").ok_or("导出失败，请重新打开会话。")?;
    let filename = result["filename"].as_str().ok_or("文件名无效。")?;
    let Some(destination) = rfd::AsyncFileDialog::new()
        .set_file_name(filename)
        .save_file()
        .await
    else {
        return Ok(false);
    };
    tokio::fs::write(
        destination.path(),
        result["content"].as_str().ok_or("导出内容无效。")?,
    )
    .await
    .map_err(|_| "无法保存聊天，请检查磁盘或选择其他位置。")?;
    Ok(true)
}

#[tauri::command]
fn exit_app(app: tauri::AppHandle) {
    app.exit(0);
}

fn main() {
    let app = tauri::Builder::default()
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.emit("app:close-requested", ());
            }
        })
        .setup(|app| {
            let bridge = Bridge::launch(app.handle())?;
            app.manage(bridge);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            engine_rpc,
            save_provider,
            clear_provider_key,
            choose_import,
            choose_restore,
            save_backup,
            save_export,
            save_chat_export,
            exit_app
        ])
        .build(tauri::generate_context!())
        .expect("无法启动叙声，请检查本地引擎安装。");
    app.run(|app, event| match event {
        tauri::RunEvent::Exit => app.state::<Bridge>().stop(),
        tauri::RunEvent::ExitRequested {
            code: None, api, ..
        } => {
            api.prevent_exit();
            let _ = app.emit("app:close-requested", ());
        }
        _ => {}
    });
}
