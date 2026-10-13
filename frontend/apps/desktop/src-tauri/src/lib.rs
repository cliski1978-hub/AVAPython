#[cfg_attr(mobile, tauri::mobile_entry_point)]

pub fn run() {
    let builder = tauri::Builder::default().plugin(tauri_plugin_opener::init());

    // The embedded WebDriver server is only enabled by the dedicated desktop
    // E2E build feature. Normal debug and production builds do not include it.
    #[cfg(feature = "wdio")]
    let builder = builder.plugin(tauri_plugin_wdio_webdriver::init());

    builder
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
