import UIKit
import Social
import UniformTypeIdentifiers

/// Share extension entry point. iOS instantiates this when the user picks
/// ClawCast from any Share sheet. We read the first attachment, pick the
/// matching kind, upload it to POST /v1/items/shared, and dismiss.
///
/// The extension reads the session token from the keychain access group
/// shared with the main app (see SharedSession.swift in the main target).
/// If no token is found the UI surfaces a "Sign in to ClawCast first"
/// message instead of silently failing.
final class ShareViewController: UIViewController {
    private let progressLabel = UILabel()
    private let titleLabel = UILabel()
    private let activityIndicator = UIActivityIndicatorView(style: .medium)
    private let cancelButton = UIButton(type: .system)

    private let baseURL = ShareViewController.resolveBaseURL()

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .systemBackground
        setupUI()

        Task { @MainActor in
            await processShare()
        }
    }

    // MARK: - UI

    private func setupUI() {
        titleLabel.text = "Send to ClawCast"
        titleLabel.font = .systemFont(ofSize: 17, weight: .semibold)
        titleLabel.textAlignment = .center

        progressLabel.text = "Reading shared content…"
        progressLabel.font = .systemFont(ofSize: 15)
        progressLabel.textColor = .secondaryLabel
        progressLabel.textAlignment = .center
        progressLabel.numberOfLines = 0

        activityIndicator.startAnimating()

        cancelButton.setTitle("Cancel", for: .normal)
        cancelButton.addTarget(self, action: #selector(cancelTapped), for: .touchUpInside)

        let stack = UIStackView(arrangedSubviews: [titleLabel, activityIndicator, progressLabel, cancelButton])
        stack.axis = .vertical
        stack.spacing = 16
        stack.alignment = .center
        stack.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            stack.centerYAnchor.constraint(equalTo: view.centerYAnchor),
            stack.widthAnchor.constraint(lessThanOrEqualTo: view.widthAnchor, multiplier: 0.85),
        ])
    }

    @objc private func cancelTapped() {
        complete(success: false, message: nil)
    }

    private func complete(success: Bool, message: String?) {
        DispatchQueue.main.async {
            self.activityIndicator.stopAnimating()
            if let message {
                self.progressLabel.text = message
            }
            // Give the user 0.8s to read the success/failure message before
            // dismissing the extension. iOS doesn't keep the sheet up once
            // we call completeRequest, so we hold briefly first.
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) {
                if success {
                    self.extensionContext?.completeRequest(returningItems: nil)
                } else {
                    let error = NSError(domain: "ShareViewController", code: 0, userInfo: nil)
                    self.extensionContext?.cancelRequest(withError: error)
                }
            }
        }
    }

    // MARK: - Share processing

    @MainActor
    private func processShare() async {
        guard let token = SharedSession.loadToken() else {
            complete(success: false, message: "Sign in to ClawCast first.")
            return
        }

        guard
            let item = (extensionContext?.inputItems as? [NSExtensionItem])?.first,
            let attachments = item.attachments,
            let attachment = attachments.first
        else {
            complete(success: false, message: "Nothing to share.")
            return
        }

        do {
            let payload = try await extractPayload(from: attachment, fallbackText: item.attributedContentText?.string)
            progressLabel.text = "Pinning to your next pod…"
            try await upload(payload: payload, token: token)
            complete(success: true, message: "Pinned to your next pod.")
        } catch let ShareError.userFacing(message) {
            complete(success: false, message: message)
        } catch {
            complete(success: false, message: "Couldn't share: \(error.localizedDescription)")
        }
    }

    private func extractPayload(from attachment: NSItemProvider, fallbackText: String?) async throws -> SharePayload {
        if attachment.hasItemConformingToTypeIdentifier(UTType.url.identifier) {
            let url = try await loadURL(from: attachment)
            // Local file URLs that point at files in the host app's
            // documents (e.g. PDFs from Files.app) come in as URLs but
            // need to be uploaded as files, not URL fields.
            if url.isFileURL {
                return try await loadFilePayload(at: url)
            }
            return .url(url.absoluteString)
        }
        if attachment.hasItemConformingToTypeIdentifier(UTType.pdf.identifier) {
            let data = try await loadData(from: attachment, type: UTType.pdf)
            return .file(kind: "pdf", filename: "share.pdf", data: data)
        }
        if attachment.hasItemConformingToTypeIdentifier(UTType.epub.identifier) {
            let data = try await loadData(from: attachment, type: UTType.epub)
            return .file(kind: "epub", filename: "share.epub", data: data)
        }
        let docxType = UTType("org.openxmlformats.wordprocessingml.document")
        if let docxType, attachment.hasItemConformingToTypeIdentifier(docxType.identifier) {
            let data = try await loadData(from: attachment, type: docxType)
            return .file(kind: "docx", filename: "share.docx", data: data)
        }
        if attachment.hasItemConformingToTypeIdentifier(UTType.plainText.identifier) {
            let text = try await loadText(from: attachment)
            return .file(kind: "text", filename: "share.txt", data: Data(text.utf8))
        }
        if let fallbackText, !fallbackText.isEmpty {
            return .file(kind: "text", filename: "share.txt", data: Data(fallbackText.utf8))
        }
        throw ShareError.userFacing("ClawCast doesn't know how to handle that yet.")
    }

    private func loadFilePayload(at url: URL) async throws -> SharePayload {
        let data = try Data(contentsOf: url)
        let ext = url.pathExtension.lowercased()
        switch ext {
        case "pdf":
            return .file(kind: "pdf", filename: url.lastPathComponent, data: data)
        case "epub":
            return .file(kind: "epub", filename: url.lastPathComponent, data: data)
        case "docx":
            return .file(kind: "docx", filename: url.lastPathComponent, data: data)
        case "txt", "md", "markdown":
            return .file(kind: "text", filename: url.lastPathComponent, data: data)
        default:
            throw ShareError.userFacing("File type .\(ext) isn't supported yet.")
        }
    }

    // MARK: - Attachment loaders

    private func loadURL(from attachment: NSItemProvider) async throws -> URL {
        return try await withCheckedThrowingContinuation { continuation in
            attachment.loadItem(forTypeIdentifier: UTType.url.identifier, options: nil) { item, error in
                if let error {
                    continuation.resume(throwing: error)
                    return
                }
                if let url = item as? URL {
                    continuation.resume(returning: url)
                } else if let urlString = item as? String, let url = URL(string: urlString) {
                    continuation.resume(returning: url)
                } else {
                    continuation.resume(throwing: ShareError.userFacing("Couldn't read the URL."))
                }
            }
        }
    }

    private func loadData(from attachment: NSItemProvider, type: UTType) async throws -> Data {
        return try await withCheckedThrowingContinuation { continuation in
            attachment.loadItem(forTypeIdentifier: type.identifier, options: nil) { item, error in
                if let error {
                    continuation.resume(throwing: error)
                    return
                }
                if let data = item as? Data {
                    continuation.resume(returning: data)
                } else if let url = item as? URL {
                    do {
                        continuation.resume(returning: try Data(contentsOf: url))
                    } catch {
                        continuation.resume(throwing: error)
                    }
                } else {
                    continuation.resume(throwing: ShareError.userFacing("Couldn't read attachment."))
                }
            }
        }
    }

    private func loadText(from attachment: NSItemProvider) async throws -> String {
        return try await withCheckedThrowingContinuation { continuation in
            attachment.loadItem(forTypeIdentifier: UTType.plainText.identifier, options: nil) { item, error in
                if let error {
                    continuation.resume(throwing: error)
                    return
                }
                if let text = item as? String {
                    continuation.resume(returning: text)
                } else if let data = item as? Data, let text = String(data: data, encoding: .utf8) {
                    continuation.resume(returning: text)
                } else {
                    continuation.resume(throwing: ShareError.userFacing("Couldn't read text."))
                }
            }
        }
    }

    // MARK: - Upload

    private func upload(payload: SharePayload, token: String) async throws {
        let url = baseURL.appendingPathComponent("v1/items/shared")
        let boundary = "Boundary-\(UUID().uuidString)"
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.httpBody = payload.multipartBody(boundary: boundary)

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw ShareError.userFacing("No response from ClawCast.")
        }
        if http.statusCode == 401 {
            throw ShareError.userFacing("Sign in to ClawCast first.")
        }
        if http.statusCode == 413 {
            throw ShareError.userFacing("File too large to share.")
        }
        if !(200..<300).contains(http.statusCode) {
            let detail = ShareViewController.decodeErrorDetail(data) ?? "HTTP \(http.statusCode)"
            throw ShareError.userFacing("ClawCast rejected the share: \(detail)")
        }
    }

    private static func decodeErrorDetail(_ data: Data) -> String? {
        struct ErrorBody: Decodable { let detail: String }
        return (try? JSONDecoder().decode(ErrorBody.self, from: data))?.detail
    }

    // MARK: - Base URL resolution

    /// The Share extension can't import AppConfiguration without dragging the
    /// whole main-target Swift module into the extension. We duplicate the
    /// base URL here intentionally — it's a 1-line config that drifts rarely;
    /// if we ever need to change it, change both.
    private static func resolveBaseURL() -> URL {
        return URL(string: "https://newsletter-pod-497154432194.europe-west1.run.app")!
    }
}

// MARK: - Payload + errors

private enum SharePayload {
    case url(String)
    case file(kind: String, filename: String, data: Data)

    func multipartBody(boundary: String) -> Data {
        var body = Data()
        let crlf = "\r\n"

        func appendField(name: String, value: String) {
            body.append(("--" + boundary + crlf).data(using: .utf8)!)
            body.append("Content-Disposition: form-data; name=\"\(name)\"\(crlf)\(crlf)".data(using: .utf8)!)
            body.append((value + crlf).data(using: .utf8)!)
        }

        func appendFile(name: String, filename: String, data: Data, mime: String) {
            body.append(("--" + boundary + crlf).data(using: .utf8)!)
            body.append("Content-Disposition: form-data; name=\"\(name)\"; filename=\"\(filename)\"\(crlf)".data(using: .utf8)!)
            body.append("Content-Type: \(mime)\(crlf)\(crlf)".data(using: .utf8)!)
            body.append(data)
            body.append(crlf.data(using: .utf8)!)
        }

        switch self {
        case .url(let urlString):
            appendField(name: "kind", value: "url")
            appendField(name: "url", value: urlString)
        case .file(let kind, let filename, let data):
            appendField(name: "kind", value: kind)
            appendFile(name: "file", filename: filename, data: data, mime: mimeType(for: kind))
        }

        body.append(("--" + boundary + "--" + crlf).data(using: .utf8)!)
        return body
    }

    private func mimeType(for kind: String) -> String {
        switch kind {
        case "pdf": return "application/pdf"
        case "epub": return "application/epub+zip"
        case "docx": return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        case "text": return "text/plain; charset=utf-8"
        default: return "application/octet-stream"
        }
    }
}

private enum ShareError: Error {
    case userFacing(String)
}
