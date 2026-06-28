//  ShareViewController.swift
//  ClawCast share-sheet extension (self-contained).
//
//  Captures a shared link / selected text / document (pdf · epub · docx) from
//  the iOS share sheet, writes it into the App Group container in the exact shape
//  the host app's `receive_sharing_intent` plugin reads, then reopens ClawCast
//  via the `ShareMedia-<hostbundleid>:share` URL. The Flutter app's
//  ShareIntakeController picks it up and shows ShareIntakeScreen for
//  confirm-and-upload — the upload happens in-app where the session token lives,
//  so this extension needs no auth (hence no keychain-access-groups entitlement,
//  unlike the legacy native extension which uploaded inline).
//
//  WHY self-contained (no `import receive_sharing_intent`):
//  the plugin ships only a CocoaPods podspec (no Swift Package Manager support),
//  and this app integrates Flutter plugins via SPM — so the plugin module cannot
//  be linked into an app-extension target without bolting CocoaPods onto the
//  build just for the extension. Instead we vendor the tiny (MIT-licensed)
//  extension-side logic from RSIShareViewController and match the plugin's
//  App-Group wire format byte-for-byte. The host app still uses the plugin
//  normally to READ the payload.
//
//  ⚠️ Keep the wire format below — kUserDefaultsKey, the SharedMediaFile coding
//  keys, and the SharedMediaType raw values — in lock-step with the pinned
//  `receive_sharing_intent` version (pubspec: ^1.8.0). If you bump the plugin,
//  re-diff RSIShareViewController.swift / SwiftReceiveSharingIntentPlugin.swift.

import Social
import UIKit

// Wire-format constants — must match SwiftReceiveSharingIntentPlugin.
private let kSchemePrefix = "ShareMedia"
private let kUserDefaultsKey = "ShareKey"
private let kUserDefaultsMessageKey = "ShareMessageKey"
private let kAppGroupIdKey = "AppGroupId"

/// Mirrors the subset of the plugin's `SharedMediaType` that ClawCast accepts.
/// Raw values must equal the host enum's (`text` / `file` / `url`) so the host's
/// JSONDecoder resolves them.
private enum SharedMediaType: String, Codable, CaseIterable {
    case text
    case file
    case url

    /// Uniform Type Identifier used to probe/load each attachment. Plain string
    /// UTIs (vs. `UTType`) keep this compiling at the app's iOS 13 floor.
    var utTypeIdentifier: String {
        switch self {
        case .text: return "public.text"
        case .file: return "public.file-url"
        case .url: return "public.url"
        }
    }
}

/// Field-for-field mirror of the plugin's `SharedMediaFile` so the JSON we encode
/// is identical to what the host decodes. Only `path`/`mimeType`/`type` are ever
/// populated here; the rest exist to keep the coding keys aligned.
private final class SharedMediaFile: Codable {
    let path: String
    let mimeType: String?
    let thumbnail: String?
    let duration: Double?
    let message: String?
    let type: SharedMediaType

    init(path: String, mimeType: String? = nil, type: SharedMediaType) {
        self.path = path
        self.mimeType = mimeType
        self.thumbnail = nil
        self.duration = nil
        self.message = nil
        self.type = type
    }
}

class ShareViewController: SLComposeServiceViewController {
    private var hostAppBundleIdentifier = ""
    private var appGroupId = ""
    private var sharedMedia: [SharedMediaFile] = []
    private var processedCount = 0 // attachments handled so far (main-thread only)

    override func isContentValid() -> Bool { true }

    override func viewDidLoad() {
        super.viewDidLoad()
        loadIds()
    }

    // Auto-capture on appear and bounce back to the host — we don't wait for the
    // user to tap "Post" (matches the plugin's shouldAutoRedirect() == true).
    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)

        // contentText is UIKit state: read it on the main thread up front, before
        // any background loadItem callbacks.
        let message = contentText

        guard let item = extensionContext?.inputItems.first as? NSExtensionItem,
              let attachments = item.attachments, !attachments.isEmpty else {
            finish(message: message)
            return
        }

        // Every attachment must call itemProcessed exactly once (even when it
        // matches no type, e.g. a shared photo) so the extension can never stall
        // and always returns control to the OS.
        let total = attachments.count
        for attachment in attachments {
            guard let type = SharedMediaType.allCases.first(where: {
                attachment.hasItemConformingToTypeIdentifier($0.utTypeIdentifier)
            }) else {
                itemProcessed(of: total, message: message)
                continue
            }
            attachment.loadItem(forTypeIdentifier: type.utTypeIdentifier, options: nil) { [weak self] data, _ in
                // loadItem calls back on an arbitrary queue; hop to main before
                // mutating sharedMedia or touching UIKit / the extension context.
                DispatchQueue.main.async {
                    guard let self = self else { return }
                    switch type {
                    case .text:
                        if let text = data as? String { self.appendLiteral(text, type: .text) }
                    case .url:
                        if let url = data as? URL { self.appendLiteral(url.absoluteString, type: .url) }
                    case .file:
                        if let url = data as? URL { self.appendFile(url) }
                    }
                    self.itemProcessed(of: total, message: message)
                }
            }
        }
    }

    override func configurationItems() -> [Any]! { [] }

    // MARK: - Capture

    private func appendLiteral(_ value: String, type: SharedMediaType) {
        sharedMedia.append(SharedMediaFile(
            path: value,
            mimeType: type == .text ? "text/plain" : nil,
            type: type))
    }

    private func appendFile(_ url: URL) {
        guard let container = FileManager.default
            .containerURL(forSecurityApplicationGroupIdentifier: appGroupId) else { return }
        let name = url.lastPathComponent.isEmpty ? UUID().uuidString : url.lastPathComponent
        let dst = container.appendingPathComponent(name)
        guard copyFile(at: url, to: dst),
              let decoded = dst.absoluteString.removingPercentEncoding else { return }
        sharedMedia.append(SharedMediaFile(path: decoded, mimeType: mimeType(for: url), type: .file))
    }

    /// Called once per attachment, always on the main thread. Finishes only after
    /// the last attachment has been handled (order-independent across async loads).
    private func itemProcessed(of total: Int, message: String?) {
        processedCount += 1
        guard processedCount >= total else { return }
        finish(message: message)
    }

    /// Single exit point: bounce to the host if we captured anything, otherwise
    /// just dismiss (don't open ClawCast to an empty screen for an unsupported
    /// share). Either branch calls completeRequest, so the OS always regains
    /// control.
    private func finish(message: String?) {
        guard !sharedMedia.isEmpty else {
            extensionContext?.completeRequest(returningItems: [], completionHandler: nil)
            return
        }
        saveAndRedirect(message: message)
    }

    // MARK: - Persist + redirect (App-Group contract with the host plugin)

    private func saveAndRedirect(message: String?) {
        let defaults = UserDefaults(suiteName: appGroupId)
        defaults?.set(try? JSONEncoder().encode(sharedMedia), forKey: kUserDefaultsKey)
        defaults?.set(message, forKey: kUserDefaultsMessageKey)
        defaults?.synchronize()
        redirectToHostApp()
    }

    private func redirectToHostApp() {
        loadIds() // ids may not be loaded yet on early dismissal
        guard let url = URL(string: "\(kSchemePrefix)-\(hostAppBundleIdentifier):share") else {
            extensionContext?.completeRequest(returningItems: [], completionHandler: nil)
            return
        }
        var responder: UIResponder? = self
        if #available(iOS 18.0, *) {
            while responder != nil {
                (responder as? UIApplication)?.open(url, options: [:], completionHandler: nil)
                responder = responder?.next
            }
        } else {
            let selector = sel_registerName("openURL:")
            while responder != nil {
                if responder?.responds(to: selector) == true {
                    _ = responder?.perform(selector, with: url)
                }
                responder = responder?.next
            }
        }
        extensionContext?.completeRequest(returningItems: [], completionHandler: nil)
    }

    // MARK: - Helpers

    /// Host bundle id is this extension's id minus the trailing `.share`; the
    /// App Group id is read from Info.plist (`AppGroupId`), matching the plugin.
    private func loadIds() {
        let bundleId = Bundle.main.bundleIdentifier ?? ""
        if let dot = bundleId.lastIndex(of: ".") {
            hostAppBundleIdentifier = String(bundleId[..<dot])
        } else {
            hostAppBundleIdentifier = bundleId
        }
        let custom = Bundle.main.object(forInfoDictionaryKey: kAppGroupIdKey) as? String
        appGroupId = custom ?? "group.\(hostAppBundleIdentifier)"
    }

    private func copyFile(at src: URL, to dst: URL) -> Bool {
        do {
            if FileManager.default.fileExists(atPath: dst.path) {
                try FileManager.default.removeItem(at: dst)
            }
            try FileManager.default.copyItem(at: src, to: dst)
            return true
        } catch {
            return false
        }
    }

    private func mimeType(for url: URL) -> String? {
        switch url.pathExtension.lowercased() {
        case "pdf": return "application/pdf"
        case "epub": return "application/epub+zip"
        case "docx": return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        default: return nil
        }
    }
}
