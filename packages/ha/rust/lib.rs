//! Build-time companion resources, independent of the app's browser UI.
//!
//! Cargo and Nix vendor one crate at a time. Keep the Python producer and its
//! runtime inside this crate so a consumer's locked dependency contains both.

use std::path::PathBuf;

/// The pinned producer used by a consumer's packaging step with Python 3.14.
pub fn bundler_path() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("bundle.py")
}

/// Runtime resources are also embedded, ensuring crate packaging validates them.
pub const RUNTIME_FILES: &[(&str, &str)] = &[
    ("__init__.py", include_str!("../ha_app_kit/__init__.py")),
    ("versions.py", include_str!("../ha_app_kit/versions.py")),
    ("repairs.py", include_str!("../ha_app_kit/repairs.py")),
];
