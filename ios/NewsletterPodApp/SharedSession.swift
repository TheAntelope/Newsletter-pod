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
    /// Access group string. At RUNTIME the keychain access group is the team
    /// id + period + the group name from entitlements — the
    /// `$(AppIdentifierPrefix)` token only resolves at build time inside the
    /// entitlements plist. Code that calls SecItemAdd/SecItemCopyMatching has
    /// to pass the full prefixed value or iOS returns errSecMissingEntitlement
    /// (-34018) silently and the keychain write/read is a no-op.
    /// Team id `R7HS2T53Z8` matches `DEVELOPMENT_TEAM` in `ios/project.yml`.
    static let accessGroup = "R7HS2T53Z8.com.newsletterpod.shared"
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
            // -34018 (errSecMissingEntitlement): access group doesn't match
            // entitlement. Logged in release too — the failure path is
            // otherwise silent and surfaces only as the Share extension
            // showing "Sign in to ClawCast first."
            NSLog("[SharedSession] SecItemAdd failed for %@: status=%d", account, status)
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
