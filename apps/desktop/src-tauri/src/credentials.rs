use keyring::Entry;
use serde_json::Value;

// Bind each stored key to the exact endpoint. An address edit cannot reuse a key silently.
fn entry(config: &Value) -> Result<Entry, String> {
    let id = config["id"].as_str().ok_or("配置 ID 无效。")?;
    let endpoint = config["base_url"].as_str().ok_or("服务地址无效。")?;
    if id.len() != 32 || !id.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err("配置 ID 无效。".into());
    }
    Entry::new("com.narravo.desktop.providers", &format!("{id}@{endpoint}"))
        .map_err(|_| "系统凭据库不可用，请检查系统权限。".into())
}

pub fn save(config: &Value, secret: &str) -> Result<(), String> {
    if secret.is_empty() || secret.len() > 4096 || secret.contains(['\r', '\n']) {
        return Err("API Key 长度或格式无效，请重新填写。".into());
    }
    entry(config)?
        .set_password(secret)
        .map_err(|_| "无法保存到系统凭据库，请检查权限后重试。".into())
}

pub fn load(config: &Value) -> Result<String, String> {
    match entry(config)?.get_password() {
        Ok(secret) => Ok(secret),
        Err(keyring::Error::NoEntry) => Ok(String::new()),
        Err(_) => Err("无法读取系统凭据库，请检查系统权限。".into()),
    }
}

pub fn remove(config: &Value) -> Result<(), String> {
    match entry(config)?.delete_credential() {
        Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
        Err(_) => Err("无法移除系统凭据，请检查系统权限。".into()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    #[ignore = "requires native system credential store; uses an isolated dummy entry"]
    fn native_roundtrip() {
        let unique = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let config = json!({"id":format!("{unique:032x}"),"base_url":"https://narravo-keychain-test.invalid"});
        save(&config, "narravo-test-only-not-a-real-key").expect("write isolated dummy credential");
        let matched = load(&config).map(|secret| secret == "narravo-test-only-not-a-real-key");
        let removed = remove(&config);
        assert_eq!(matched, Ok(true));
        assert!(removed.is_ok());
        assert_eq!(load(&config), Ok(String::new()));
    }

    #[test]
    fn invalid_id_is_rejected_before_accessing_keychain() {
        let config = json!({"id":"../invalid","base_url":"https://example.com"});
        assert!(load(&config).is_err());
    }
}
