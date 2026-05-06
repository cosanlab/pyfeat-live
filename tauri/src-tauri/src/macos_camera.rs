//! macOS-only WKWebView camera/microphone permission delegate.
//!
//! Background. On macOS 14.x the OS-level camera prompt (driven by
//! `NSCameraUsageDescription` + the `device.camera` entitlement) is
//! gate #1; gate #2 is WKWebView's *own* JS-sandbox decision about
//! whether to forward the permission to `navigator.mediaDevices.
//! getUserMedia()`. Without an explicit `WKUIDelegate` implementation
//! of `webView:requestMediaCapturePermissionForOrigin:...` Tauri's
//! WebView often falls through to "prompt", which on the affected
//! macOS versions silently fails inside an embedded WKWebView and
//! the JS call rejects with `NotAllowedError`.
//!
//! Tracking issues:
//!   - https://github.com/tauri-apps/tauri/issues/11951
//!   - https://github.com/tauri-apps/wry/issues/1195
//!
//! Fix. Install our own delegate that auto-grants media permission
//! whenever WKWebView asks. Safe because gate #1 (OS-level) still
//! protects the user — if the user denied camera access to Py-feat
//! Live, the OS will block any AVCaptureSession before the JS layer
//! ever sees a stream.
//!
//! Lifetime. The delegate retains a strong reference; `WKWebView`'s
//! `setUIDelegate:` stores it as a *weak* reference, so we leak
//! ours via `forget()` to keep it alive for the WebView's lifetime.
//! We're a single-window app, no churn here.

use objc2::define_class;
use objc2::rc::Retained;
use objc2::runtime::ProtocolObject;
use objc2::{MainThreadMarker, MainThreadOnly};
use objc2_foundation::NSObjectProtocol;
use objc2_web_kit::{
    WKFrameInfo, WKMediaCaptureType, WKPermissionDecision, WKSecurityOrigin,
    WKUIDelegate, WKWebView,
};

define_class!(
    /// `WKUIDelegate` impl that auto-grants media-capture permission.
    /// Defined as a thin objc class with no Rust-side state — every
    /// callback just invokes the decision handler with `Grant`.
    #[unsafe(super(objc2_foundation::NSObject))]
    #[name = "PyfeatliveMediaPermissionDelegate"]
    #[thread_kind = MainThreadOnly]
    struct MediaPermissionDelegate;

    unsafe impl NSObjectProtocol for MediaPermissionDelegate {}

    unsafe impl WKUIDelegate for MediaPermissionDelegate {
        #[unsafe(method(webView:requestMediaCapturePermissionForOrigin:initiatedByFrame:type:decisionHandler:))]
        fn _request_media_capture_permission(
            &self,
            _web_view: &WKWebView,
            _origin: &WKSecurityOrigin,
            _frame: &WKFrameInfo,
            _capture_type: WKMediaCaptureType,
            decision_handler: &block2::DynBlock<dyn Fn(WKPermissionDecision)>,
        ) {
            // Mirror what a user would do at the WebView prompt.
            // OS-level gating already happened when the .app first
            // requested camera access via the system permission API;
            // re-prompting at the WebView layer is the bug we work
            // around.
            decision_handler.call((WKPermissionDecision::Grant,));
        }
    }
);

impl MediaPermissionDelegate {
    fn new(mtm: MainThreadMarker) -> Retained<Self> {
        let alloc = Self::alloc(mtm);
        // SAFETY: `init` is the standard NSObject initialiser and
        // `define_class!` arranged the inheritance chain.
        unsafe { objc2::msg_send![alloc, init] }
    }
}

/// Install the delegate on the given `WKWebView`. Call once per
/// window, on the main thread, after the webview has been created
/// (i.e. inside Tauri's `with_webview()` callback).
///
/// # Safety
///
/// `webview_ptr` must be a valid `WKWebView` pointer — Tauri's
/// `with_webview()` exposes one via `webview.inner()` on macOS.
pub unsafe fn install_media_delegate(webview_ptr: *mut std::ffi::c_void) {
    if webview_ptr.is_null() {
        log::warn!("install_media_delegate: null webview pointer; skipping");
        return;
    }

    // SAFETY: the caller guarantees this points at a live WKWebView.
    // We must be on the main thread because WKWebView is main-thread-only.
    let mtm = match MainThreadMarker::new() {
        Some(m) => m,
        None => {
            log::error!("install_media_delegate: not on main thread; skipping");
            return;
        }
    };

    let webview: &WKWebView = &*(webview_ptr as *const WKWebView);
    let delegate = MediaPermissionDelegate::new(mtm);
    let proto: &ProtocolObject<dyn WKUIDelegate> =
        ProtocolObject::from_ref(&*delegate);
    webview.setUIDelegate(Some(proto));

    // WKWebView holds the delegate weakly. Leak the strong handle
    // here so the delegate outlives the WebView. One-window app —
    // permanent leak is one allocation, not a real concern.
    std::mem::forget(delegate);

    log::info!("WKWebView media-permission delegate installed");
}
