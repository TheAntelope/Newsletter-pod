// ClawCast share-sheet extension.
//
// Subclasses the receive_sharing_intent plugin's RSIShareViewController, which
// captures the shared items (URL / text / pdf / epub / docx), writes them into
// the App Group container, and — because shouldAutoRedirect defaults to true —
// reopens the host app via the `ShareMedia-<bundleid>` URL scheme. The Flutter
// app then reads them through ReceiveSharingIntent and shows ShareIntakeScreen
// for confirm-and-upload.
//
// This is the iOS parity for the native NewsletterPodShareExtension: the native
// one uploaded inside the extension (reading the session token from a shared
// Keychain); the Flutter flow instead bounces to the app and uploads there,
// where the session already lives — so the extension itself needs no auth.
//
// If you hit "No such module 'receive_sharing_intent'", move the
// `Embed Foundation Extension` build phase above `Thin Binary` on the Runner
// target (see docs/ios-share-extension-setup.md).
import receive_sharing_intent

class ShareViewController: RSIShareViewController {
    // Default shouldAutoRedirect() == true: capture → store in App Group →
    // reopen ClawCast. We rely on that, so no overrides are needed here.
}
