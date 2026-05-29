import Foundation
import UIKit
import UserNotifications

/// Bridges UIKit's APNs callbacks + UNUserNotificationCenter into something
/// the SwiftUI app and `AppViewModel` can drive.
///
/// Why this exists:
/// 1. APNs token delivery only happens through `UIApplicationDelegate`
///    (`didRegisterForRemoteNotificationsWithDeviceToken`), so we still
///    need an adaptor under the SwiftUI App.
/// 2. We do NOT call `registerForRemoteNotifications` at launch — Apple's
///    permission prompt fires from `requestAuthorization`, and Phase B's UX
///    is just-in-time on Substack add. The AppDelegate just *captures* the
///    device token whenever the system happens to deliver one and forwards
///    it to whoever is currently listening (AppViewModel on cold start /
///    after the pre-prompt accepts).
/// 3. Notification taps need to copy the verification code to the clipboard
///    and try to open the publication URL — handled here in
///    `userNotificationCenter(_:didReceive:withCompletionHandler:)`.
final class PushAppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {

    /// Static singleton so `AppViewModel` can register a callback at init
    /// time without the AppDelegate having to know about it. Setting this
    /// from multiple places overwrites — we only ever have one VM.
    static var deviceTokenHandler: ((String) -> Void)?

    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        UNUserNotificationCenter.current().delegate = self
        // If a previously-granted permission survives across launches, iOS
        // will redeliver the device token automatically — no need to call
        // registerForRemoteNotifications here. The system fires
        // didRegisterForRemoteNotifications on every cold start in that case.
        return true
    }

    func application(
        _ application: UIApplication,
        didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data
    ) {
        let hex = deviceToken.map { String(format: "%02x", $0) }.joined()
        Self.deviceTokenHandler?(hex)
    }

    func application(
        _ application: UIApplication,
        didFailToRegisterForRemoteNotificationsWithError error: Error
    ) {
        NSLog("APNs registration failed: %@", error.localizedDescription)
    }

    /// Show the banner + sound while the app is foregrounded — otherwise
    /// iOS silently swallows the notification (the user would never see a
    /// verification code if they happened to be in-app when it arrived).
    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        completionHandler([.banner, .sound, .badge])
    }

    /// Tap handler: for Substack verification pushes, copy the code to the
    /// clipboard and try to open the publication URL so the user can paste
    /// the code straight into the subscribe form.
    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        defer { completionHandler() }
        let userInfo = response.notification.request.content.userInfo
        guard let type = userInfo["type"] as? String, type == "substack_verification" else {
            return
        }
        if let code = userInfo["code"] as? String, !code.isEmpty {
            UIPasteboard.general.string = code
        }
        if let urlString = userInfo["pub_url"] as? String, let url = URL(string: urlString) {
            DispatchQueue.main.async {
                UIApplication.shared.open(url, options: [:], completionHandler: nil)
            }
        }
    }
}

/// Coordinates with iOS to ask for push permission and register for APNs.
/// Methods are intentionally narrow:
///   - `currentAuthorizationStatus()` -> for UI to gate the pre-prompt
///   - `requestAuthorizationAndRegister()` -> after the user taps "Allow" on
///     our own pre-prompt; fires the system prompt + registers if granted.
enum PushAuthorizationOutcome {
    case granted
    case denied
    case alreadyDetermined(UNAuthorizationStatus)
    case error(Error)
}

enum PushAuthorization {
    static func currentStatus() async -> UNAuthorizationStatus {
        await withCheckedContinuation { continuation in
            UNUserNotificationCenter.current().getNotificationSettings { settings in
                continuation.resume(returning: settings.authorizationStatus)
            }
        }
    }

    static func requestAuthorizationAndRegister() async -> PushAuthorizationOutcome {
        let status = await currentStatus()
        if status == .authorized || status == .provisional || status == .ephemeral {
            await MainActor.run { UIApplication.shared.registerForRemoteNotifications() }
            return .alreadyDetermined(status)
        }
        if status == .denied {
            return .alreadyDetermined(status)
        }
        do {
            let granted = try await UNUserNotificationCenter.current().requestAuthorization(
                options: [.alert, .sound, .badge]
            )
            if granted {
                await MainActor.run { UIApplication.shared.registerForRemoteNotifications() }
                return .granted
            }
            return .denied
        } catch {
            return .error(error)
        }
    }
}
