import Foundation
import Security

/// Shared session-token storage used by both the main app and the
/// Share extension. Writes go into the keychain with `kSecAttrAccessGroup`
/// set to a shared access group so the extension can read whatever the
/// main app stored at sign-in.
///
/// The previous in-memory-only `@Published var sessionToken` model meant
/// the user got signed out on every cold launch and the Share extension
/// had no way to authenticate. Both problems collapse if the token lives
/// in the shared keychain.
///
/// IMPORTANT: the access group string MUST match the value declared in
/// both targets' entitlements files
/// (`NewsletterPodApp/NewsletterPod.entitlements`,
///  `NewsletterPodShareExtension/NewsletterPodShareExtension.entitlements`)
/// or `SecItemAdd` returns `errSecMissingEntitlement` (-34018).
enum SharedSession {
    /// Access group string. `$(AppIdentifierPrefix)` is filled in at runtime
    /// from the app's keychain-access-groups entitlement, so we use the
    /// literal trailing portion here; the entitlements declarations are
    /// authoritative for the prefix.
    static let accessGroup = "com.newsletterpod.shared"
    static let tokenAccount = "session_token"
    static let userIDAccount = "user_id"
    private static let service = "com.newsletterpod.app"

    static func saveToken(_ token: String, userID: String?) {
        write(account: tokenAccount, value: token)
        if let userID {
            write(account: userIDAccount, value: userID)
        }
    }

    static func loadToken() -> String? {
        return read(account: tokenAccount)
    }

    static func loadUserID() -> String? {
        return read(account: userIDAccount)
    }

    static func clear() {
        delete(account: tokenAccount)
        delete(account: userIDAccount)
    }

    // MARK: - Keychain primitives

    private static func baseQuery(account: String) -> [String: Any] {
        return [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecAttrAccessGroup as String: accessGroup,
        ]
    }

    private static func write(account: String, value: String) {
        guard let data = value.data(using: .utf8) else { return }
        var query = baseQuery(account: account)
        // Delete any existing item first so the add doesn't collide; simpler
        // than branching on update vs. add when both code paths converge.
        SecItemDelete(query as CFDictionary)
        query[kSecValueData as String] = data
        query[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
        let status = SecItemAdd(query as CFDictionary, nil)
        if status != errSecSuccess {
            // The extension is the only consumer that fails loudly here in
            // dev — if the access group string doesn't match the entitlement,
            // SecItemAdd returns -34018 and the share endpoint always 401s.
            #if DEBUG
            print("[SharedSession] SecItemAdd failed for \(account): status=\(status)")
            #endif
        }
    }

    private static func read(account: String) -> String? {
        var query = baseQuery(account: account)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        guard status == errSecSuccess, let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private static func delete(account: String) {
        let query = baseQuery(account: account)
        SecItemDelete(query as CFDictionary)
    }
}
